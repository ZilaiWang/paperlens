"""Background job execution with real per-stage progress events.

One thread per job for now (SQLite-safe, single process); the cloud milestone
moves this to a worker process with PostgreSQL-backed queues (P6).
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime

from paperlens_core.adapter import derive_assets, to_blocks, to_chunks, to_sections
from paperlens_core.documents import Paper, PaperVersion
from paperlens_core.jobs import Job, JobStatus, JobType

from .events import bus
from .logging_config import get_logger
from .repository import Repository, now_iso

PARSE_STAGE_ORDER = [
    "file_validation",
    "metadata_and_pages",
    "layout_and_text",
    "sections",
    "assets",
    "references",
    "index",
    "initial_translation",
]


class JobExecutor:
    def __init__(self, repository: Repository, data_dir: str):
        self.repository = repository
        self.data_dir = data_dir
        self._threads: dict[str, threading.Thread] = {}

    def submit(self, job: Job, fn) -> str:
        job.status = JobStatus.QUEUED
        self.repository.create_job(job)
        thread = threading.Thread(target=self._run, args=(job.job_id, fn), daemon=True)
        self._threads[job.job_id] = thread
        thread.start()
        return job.job_id

    def _run(self, job_id: str, fn) -> None:
        from datetime import datetime, timezone

        from .logging_config import get_logger

        logger = get_logger()
        job = self.repository.get_job(job_id)
        if job is None:
            return
        started = datetime.now(timezone.utc)
        job.status = JobStatus.RUNNING
        job.updated_at = now_iso()
        self.repository.update_job(job)
        bus.publish(job_id, {"event": "job_started", "job_id": job_id, "progress": 0.0})
        logger.info("job %s started (%s)", job_id, job.job_type.value)
        try:
            fn(job)
        except Exception as exc:  # noqa: BLE001 - record and surface as job_failed
            import traceback
            traceback.print_exc()
            job.status = JobStatus.FAILED
            job.error_code = type(exc).__name__
            job.error_message = str(exc)
            job.updated_at = now_iso()
            self.repository.update_job(job)
            logger.error(
                "job %s FAILED after %.1fs: %s: %s",
                job_id,
                (datetime.now(timezone.utc) - started).total_seconds(),
                job.error_code,
                job.error_message,
                exc_info=True,
            )
            bus.publish(
                job_id,
                {
                    "event": "job_failed",
                    "job_id": job_id,
                    "error_code": job.error_code,
                    "error_message": job.error_message,
                },
            )
        finally:
            self._threads.pop(job_id, None)

    def log_stage_times(self, job: Job) -> None:
        """One line with every stage's wall time (日志系统 V3.6)."""
        from .logging_config import get_logger

        durations = ", ".join(
            f"{key}={stage.duration_seconds}s"
            for key, stage in job.stages.items()
            if stage.duration_seconds > 0
        )
        get_logger().info("job %s stage timings: %s", job.job_id, durations or "(none finished)")

    def complete(self, job: Job, result_uri: str = "") -> None:
        job.status = JobStatus.SUCCEEDED
        job.result_uri = result_uri
        job.updated_at = now_iso()
        self.repository.update_job(job)
        bus.publish(
            job_id=job.job_id,
            event={"event": "job_succeeded", "job_id": job.job_id, "progress": 1.0, "result_uri": result_uri},
        )


def translate_initial_pages(
    repository: Repository, version: PaperVersion, job: Job, pages: list[int] | None = None
) -> int:
    """initial_translation stage: really translate the first pages inside the
    parse job (改进方案2.md §18.2). The home progress bar shows this stage
    with real work, and the workbench opens with pages 1-5 already readable;
    the workbench then keeps translating the rest automatically.
    """
    import json

    from paperlens_core.config import Settings
    from paperlens_core.documents import Block as BlockIR
    from paperlens_core.documents import BlockType, TranslationUnit
    from paperlens_core.documents import Section as SectionIR
    from paperlens_core.llm import OpenAICompatibleModel
    from paperlens_core.translation import (
        GlossaryEntry,
        PaperTranslationProfile,
        batch_translate,
        build_glossary,
        build_profile,
        make_units,
    )

    pages = pages or [1, 2, 3]
    blocks = [
        BlockIR.model_validate(item)
        for item in repository.load_document(version.version_id, "blocks")
    ]
    # 预翻译统一前 15 段（V3.12）：HTML 论文无物理页按段落序，
    # PDF 论文同样按正文顺序取前 15 段（不再按 3 页）
    # V3.22：HTML 公式块（block_type=TEXT，角色在 metadata）不参与翻译
    text_blocks = sorted(
        (
            block for block in blocks
            if block.block_type == BlockType.TEXT
            and block.text.strip()
            and len(block.text) > 40
            and (block.metadata or {}).get("html_role") != "FORMULA"
        ),
        key=lambda block: (block.page, block.paragraph_index),
    )[:15]
    if not text_blocks:
        return 0

    thread_id = f"translate-{version.version_id}"
    settings = Settings()
    model = OpenAICompatibleModel(settings)

    # glossary: reuse the same per-version cache as the translate endpoint
    glossary: list[dict[str, object]] = []
    glossary_cache = repository.load_document(version.version_id, "glossary")
    if glossary_cache:
        glossary = (
            [json.loads(item) for item in glossary_cache]
            if isinstance(glossary_cache[0], str)
            else glossary_cache
        )
    else:
        abstract_texts = [
            block.text for block in blocks if block.page <= 2 and block.text.strip()
        ][:6]
        entries = build_glossary(model, abstract_texts, thread_id=thread_id)
        glossary = [entry.model_dump(mode="json") for entry in entries]
        repository.store_document(version.version_id, "glossary", glossary)
    glossary_entries = [GlossaryEntry.model_validate(entry) for entry in glossary]

    # paper profile: cached like the endpoint does
    sections = [
        SectionIR.model_validate(item)
        for item in repository.load_document(version.version_id, "sections")
    ]
    profile: PaperTranslationProfile | None = None
    profile_cache = repository.load_document(version.version_id, "translation_profile")
    if profile_cache and isinstance(profile_cache[0], dict):
        profile = PaperTranslationProfile.model_validate(profile_cache[0])
    else:
        captions = [
            block.text for block in blocks
            if block.block_type == BlockType.CAPTION and block.text.strip()
        ]
        abstract = "\n".join(
            block.text for block in blocks if block.page <= 1 and block.text.strip()
        )[:2000]
        try:
            profile = build_profile(
                model,
                title=version.file_name,
                abstract=abstract,
                section_titles=[section.title for section in sections if section.title],
                captions=captions,
                thread_id=thread_id,
            )
            repository.store_document(
                version.version_id,
                "translation_profile",
                [profile.model_dump(mode="json")],
            )
        except Exception:  # noqa: BLE001 - profile is an enhancement
            profile = None

    from concurrent.futures import ThreadPoolExecutor

    def translate_group(start: int) -> list[object]:
        group = text_blocks[start : start + 6]
        section = next(
            (s for s in sections if s.section_id == group[0].section_id), None
        ) if sections else None
        worker_model = OpenAICompatibleModel(Settings())
        targets, issues = batch_translate(
            worker_model,
            paragraphs=[block.text for block in group],
            section_title=section.title if section else "",
            previous_summary="",
            glossary=glossary_entries,
            thread_id=thread_id,
            profile=profile,
        )
        return make_units(
            paper_version_id=version.version_id,
            section_id=group[0].section_id,
            source_blocks=[block.model_dump(mode="json") for block in group],
            targets=targets,
            issues=issues,
            model_name=settings.paperlens_model,
            thread_id=thread_id,
        )

    batches = list(range(0, len(text_blocks), 6))
    # 进度随批次推进（首页进度条据此估算剩余时间，V3.7）
    from concurrent.futures import as_completed

    new_units = []
    with ThreadPoolExecutor(max_workers=min(4, len(batches) or 1)) as pool:
        futures = [pool.submit(translate_group, start) for start in batches]
        for done, future in enumerate(as_completed(futures), start=1):
            new_units.extend(future.result())
            job.mark_stage(
                "initial_translation",
                status=JobStatus.RUNNING,
                ratio=round(done / len(batches), 3),
                detail="正在翻译…",
            )
            repository.update_job(job)
    # V3.22：保留的旧单元按内容校验——block_id 是索引型，重解析后同 id
    # 内容可能已变（错位根因），内容不匹配的旧单元作废（前端按需重译）
    from paperlens_core.translation import unit_matches_block

    block_texts = {block.block_id: block.text for block in blocks}
    existing = [
        unit
        for unit in [
            TranslationUnit.model_validate(item)
            for item in repository.load_document(version.version_id, "translations")
        ]
        if unit.source_block_ids
        and unit_matches_block(
            unit.source_text, block_texts.get(unit.source_block_ids[0], "")
        )
    ]
    merged = [unit.model_dump(mode="json") for unit in existing]
    merged.extend(unit.model_dump(mode="json") for unit in new_units)
    repository.store_document(version.version_id, "translations", merged)
    return len(new_units)


def _download_asset_to_disk(url: str, asset_dir: str, asset_id: str) -> str:
    """预下载 HTML 论文图到服务器（V3.9b）；返回本地路径，失败返回空串。"""
    from paperlens_core.net import make_arxiv_httpx_client

    try:
        os.makedirs(asset_dir, exist_ok=True)
        path = os.path.join(asset_dir, f"{asset_id}.png")
        if os.path.exists(path):
            return path
        with make_arxiv_httpx_client(timeout=40) as client:
            response = client.get(url)
            response.raise_for_status()
        with open(path, "wb") as handle:
            handle.write(response.content)
        return path
    except Exception as exc:  # noqa: BLE001 - asset download is best-effort
        get_logger().warning("asset %s pre-download failed: %s", asset_id, exc)
        return ""


def new_job(job_type: JobType, *, paper_id: str = "", paper_version_id: str = "", owner_id: str = "") -> Job:
    return Job(
        job_id=f"job-{uuid.uuid4().hex[:12]}",
        job_type=job_type,
        paper_id=paper_id,
        paper_version_id=paper_version_id,
        owner_id=owner_id,
        created_at=now_iso(),
        updated_at=now_iso(),
    )


def create_arxiv_html_job(
    executor: JobExecutor,
    repository: Repository,
    *,
    arxiv_id: str,
    job: Job | None = None,
    user_id: str = "guest",
    pdf_path: str = "",
) -> Job:
    """Source-first import: parse the arXiv HTML (semantic structure intact)
    instead of the fragmented PDF. Sections, paragraphs, figures, tables and
    citations come from the LaTeXML DOM directly.

    ``pdf_path`` (the user's uploaded PDF) is attached to the version so the
    原版 viewer still shows the real PDF; without it (arXiv-link import) the
    PDF is downloaded through the proxy. Failure to attach never fails the
    parse (V3.9).
    """

    from paperlens_core.adapter import to_blocks, to_chunks
    from paperlens_core.arxiv_html import fetch_arxiv_html, parse_arxiv_html
    from paperlens_core.chunking import chunk_blocks
    from paperlens_core.documents import Paper, PaperVersion

    job = job or new_job(JobType.PARSE)
    # 预注册全部计划阶段（QUEUED）：首页进度条预先显示后续步骤
    #（V3.10），执行时逐个 RUNNING → SUCCEEDED
    for stage_key in ("file_validation", "layout_and_text", "sections", "assets", "index", "initial_translation"):
        job.mark_stage(stage_key, status=JobStatus.QUEUED, ratio=0.0)
    repository.update_job(job)
    # file_validation 包住 fetch：耗时归属到本阶段（日志系统 V3.6）
    job.mark_stage("file_validation", status=JobStatus.RUNNING, ratio=0.5, detail="获取 arXiv HTML…")
    repository.update_job(job)
    html_text = fetch_arxiv_html(arxiv_id)
    job.mark_stage("file_validation", status=JobStatus.SUCCEEDED, ratio=1.0, detail="arXiv HTML")
    repository.update_job(job)

    import hashlib

    sha = hashlib.sha256(html_text.encode("utf-8")).hexdigest()
    paper_id = sha[:16]
    version_id = f"ver-html-{sha[:16]}"
    repository.create_paper(
        Paper(
            paper_id=paper_id,
            canonical_title=f"arxiv-{arxiv_id}",
            user_id=user_id,
            created_at=now_iso(),
        )
    )
    version = PaperVersion(
        version_id=version_id,
        paper_id=paper_id,
        version_label=f"arxiv-html-{arxiv_id}",
        source="ARXIV",
        file_name=f"arxiv-{arxiv_id}",
        file_sha256=sha,
        page_count=0,
        created_at=now_iso(),
    )
    # V4.6-2（改进方案3 §14.1）：用户库登记（论文全局，收藏/归属按用户）
    repository.add_user_paper(user_id, paper_id)
    repository.create_version(version)
    job.paper_id = paper_id
    job.paper_version_id = version_id
    job.mark_stage("layout_and_text", status=JobStatus.RUNNING, ratio=0.3, detail="解析与资源准备…")
    repository.update_job(job)
    blocks = parse_arxiv_html(html_text, arxiv_id=arxiv_id)
    # 原版模式（V3.9）：HTML 论文也要有对应 PDF。上传路径直接复用用户 PDF；
    # arXiv 链接导入路径在此下载（走代理，约几秒）。失败不阻塞解析。
    try:
        from pathlib import Path as _Path

        from .logging_config import get_logger

        if pdf_path and _Path(pdf_path).exists():
            # 上传路径：复用用户 PDF，无下载
            repository.update_version_file_path(version_id, pdf_path)
        else:
            # V4.7e（2026-08-05）：原版 PDF 与 HTML 解析并行后台下载。
            # 此前预下载要等翻译完成才启动（约 20s 后），用户首次打开
            # 原版模式仍要现场下载 15MB；现在 attach 阶段即启动线程，
            # 解析/翻译期间下载已完成。目标文件幂等，重复导入不重复下。
            def _prefetch_pdf() -> None:
                try:
                    from .arxiv import download_pdf

                    target = _Path(executor.data_dir) / f"arxiv-{arxiv_id}.pdf"
                    if target.exists():
                        repository.update_version_file_path(version_id, str(target))
                        return
                    downloaded = download_pdf(
                        arxiv_id,
                        executor.data_dir,
                        contact_email="paperlens@example.com",
                    )
                    repository.update_version_file_path(version_id, downloaded)
                    get_logger().info("arxiv %s PDF 后台预下载完成", arxiv_id)
                except Exception as exc:  # noqa: BLE001 - prefetch is best-effort
                    get_logger().warning(
                        "arxiv %s PDF 预下载失败（get_pdf 懒下载兜底）: %s",
                        arxiv_id,
                        exc,
                    )

            import threading

            threading.Thread(target=_prefetch_pdf, daemon=True).start()
    except Exception as exc:  # noqa: BLE001 - PDF is a display nicety
        get_logger().warning("arxiv %s PDF attach failed: %s", arxiv_id, exc)


    job.mark_stage("layout_and_text", status=JobStatus.SUCCEEDED, ratio=1.0, detail="HTML 语义解析")
    job.mark_stage("sections", status=JobStatus.SUCCEEDED, ratio=1.0)
    repository.update_job(job)

    from paperlens_core.arxiv_html import parse_bibliography
    from paperlens_core.assets import extract_callouts_html
    from paperlens_core.documents import Section as SectionIR

    references = parse_bibliography(html_text, version_id=version_id)
    repository.store_document(version_id, "references", references)

    # 元信息 + 图/表资产（改进方案2.md §18.2 / V3.6）：arXiv HTML 直接提供
    # 标题/作者/摘要与真实图 URL，展示页按 arXiv 风格渲染。
    # V4.0-5：此处曾与 PDF attach 后的同名块重复（重复下载 + 重复存储），
    # 已删除前一份，本份为唯一事实源
    from paperlens_core.arxiv_html import extract_assets, extract_metadata

    meta = extract_metadata(html_text)
    meta["arxiv_id"] = arxiv_id
    repository.store_document(version_id, "paper_meta", [meta])
    from paperlens_core.documents import Asset as AssetIR
    from paperlens_core.documents import AssetKind as AssetKindIR

    # 图片服务器内组织（V3.9b）：导入时预下载落盘，之后的显示/下载走本地
    # 不再回源 arXiv（一次拉取，浏览器和下载端点都用本地缓存）。
    # V4.6-5（检查 2）：同步下载上限 10 张（实测一篇论文 172 张图全量同步
    # 下载耗时 180s）——其余图 local_file 留空，首次查看时由下载端点
    # 按需回源并落盘缓存（与翻译的后台补全同思路）；进度条只显示阶段
    # 不显示图片计数
    MAX_SYNC_FIGURES = int(os.environ.get("PAPERLENS_MAX_SYNC_FIGURES", "10"))
    job.mark_stage("assets", status=JobStatus.RUNNING, ratio=0.3, detail="准备图表资产…")
    repository.update_job(job)
    html_assets = []
    asset_dir = os.path.join(executor.data_dir, "assets", version_id)
    asset_items = extract_assets(html_text, arxiv_id=arxiv_id)
    figure_downloaded = 0
    for item in asset_items:
        asset = AssetIR.model_validate({**item, "paper_version_id": version_id})
        # asset_id 加 version 前缀：fig-html-01 曾是全局相同的（下载端点会
        # 匹配到最新论文的图），fix 2026-08-04
        asset = asset.model_copy(
            update={"asset_id": f"{asset.asset_id}-{version_id[:10]}"}
        )
        if (
            asset.asset_kind == AssetKindIR.FIGURE
            and asset.content_uri
            and figure_downloaded < MAX_SYNC_FIGURES
        ):
            local = _download_asset_to_disk(asset.content_uri, asset_dir, asset.asset_id)
            if local:
                asset.local_file = local
                figure_downloaded += 1
        html_assets.append(asset.model_dump(mode="json"))
    repository.store_document(version_id, "assets", html_assets)
    job.mark_stage("assets", status=JobStatus.SUCCEEDED, ratio=1.0, detail="图表资产就绪")
    repository.update_job(job)

    # bind in-text [n] citations to the ReferenceEntry records (改进方案2.md §11.2)
    callouts = extract_callouts_html(version_id, blocks, len(references))
    repository.store_document(
        version_id,
        "callouts",
        [callout.model_dump(mode="json") for callout in callouts],
    )

    sections_ir = []
    current_section_id: str | None = None
    for index, block in enumerate(blocks):
        if block.metadata.get("html_role") == "HEADING":
            current_section_id = f"sec-html-{index:03d}"
            sections_ir.append(
                SectionIR(
                    section_id=current_section_id,
                    paper_version_id=version_id,
                    title=block.text,
                    raw_title=block.text,
                    canonical_name="other",
                    level=1,
                    start_page=1,
                    confidence=0.99,
                )
            )
        # 写回 section_id：前端据此加粗标题、目录跳转（fix 2026-08-04，
        # HTML blocks 此前 section_id 全为 None → 标题不粗、目录点不动）
        block.section_id = current_section_id
    blocks_ir = to_blocks(blocks, version)
    job.mark_stage("index", status=JobStatus.RUNNING, ratio=0.4, detail="建立检索分片…")
    repository.update_job(job)
    chunks, _ = chunk_blocks(paper_id, blocks)
    chunks_ir = to_chunks(chunks, version)
    repository.store_document(version_id, "blocks", [b.model_dump(mode="json") for b in blocks_ir])
    repository.store_document(version_id, "sections", [s.model_dump(mode="json") for s in sections_ir])
    repository.store_document(version_id, "chunks", [c.model_dump(mode="json") for c in chunks_ir])
    job.mark_stage("index", status=JobStatus.SUCCEEDED, ratio=1.0, detail=f"{len(chunks)} 个分片")
    job.mark_stage("initial_translation", status=JobStatus.RUNNING, ratio=0.0, detail="正在翻译…")
    repository.update_job(job)
    try:
        translated = translate_initial_pages(repository, version, job)
        detail = f"翻译完成（{translated} 段）" if translated else "无待翻译段落"
    except Exception:  # noqa: BLE001 - translation failure never fails the parse
        detail = "翻译暂不可用，进入后自动重试"
    job.mark_stage("initial_translation", status=JobStatus.SUCCEEDED, ratio=1.0, detail=detail)
    repository.update_job(job)
    # 2026-08-07（教师优化 1）：解析时用摘要生成示例问题（Agent 输入框
    # placeholder 动态化）。一次轻量 LLM 调用，失败降级不阻塞导入。
    try:
        from paperlens_core.config import Settings
        from paperlens_core.llm import OpenAICompatibleModel
        from paperlens_core.metadata import generate_sample_questions

        meta = repository.load_document(version.version_id, "paper_meta")
        abstract = (meta[0].get("abstract") or "") if meta else ""
        if abstract:
            questions = generate_sample_questions(
                OpenAICompatibleModel(Settings()), abstract
            )
            if questions:
                repository.store_document(
                    version.version_id, "sample_questions", questions
                )
                get_logger().info(
                    "paper %s 示例问题生成: %s", version.paper_id, questions[0][:30]
                )
    except Exception as exc:  # noqa: BLE001 - placeholder is a nicety
        get_logger().warning("sample questions failed: %s", exc)
    # 预下载已提前到 attach 阶段并行启动（V4.7e，见上）；get_pdf 端点懒下载兜底
    executor.log_stage_times(job)
    executor.complete(job)
    return job


def create_parse_job(
    executor: JobExecutor,
    repository: Repository,
    *,
    pdf_path: str,
    file_name: str,
    job: Job | None = None,
    user_id: str = "guest",
) -> Job:
    """Build the PARSE job: validate file, parse, section, index, persist DocumentIR.

    Uses the caller's submitted job (so stage updates and completion land on
    the row the client is polling); completes it at the end.
    """

    from paperlens_core.sections import detect_sections

    job = job or new_job(JobType.PARSE)
    # 预注册全部计划阶段（QUEUED，V3.10）：进度条预先显示后续步骤
    for stage_key in PARSE_STAGE_ORDER:
        job.mark_stage(stage_key, status=JobStatus.QUEUED, ratio=0.0)
    repository.update_job(job)
    job.mark_stage("file_validation", status=JobStatus.RUNNING, ratio=1.0, detail="校验通过")
    repository.update_job(job)
    bus.publish(job.job_id, {"event": "stage_started", "job_id": job.job_id, "stage": "file_validation"})

    import hashlib
    from pathlib import Path

    raw = Path(pdf_path).read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise ValueError("not a PDF file")
    job.mark_stage("file_validation", status=JobStatus.SUCCEEDED, ratio=1.0, detail="校验通过")
    repository.update_job(job)
    sha = hashlib.sha256(raw).hexdigest()
    paper_id = sha[:16]
    version_id = f"ver-{sha[:20]}"
    paper = Paper(paper_id=paper_id, canonical_title=file_name, user_id=user_id, created_at=now_iso())
    repository.create_paper(paper)
    version = PaperVersion(
        version_id=version_id,
        paper_id=paper_id,
        version_label=f"upload-{datetime.now().strftime('%Y%m%d')}",
        file_name=file_name,
        file_sha256=sha,
        file_path=pdf_path,
        created_at=now_iso(),
    )
    repository.create_version(version)
    job.paper_id = paper_id
    job.paper_version_id = version_id
    repository.update_job(job)
    # V4.6-2（改进方案3 §14.1）：用户库登记（论文全局，收藏/归属按用户）
    repository.add_user_paper(user_id, paper_id)
    bus.publish(job.job_id, {"event": "stage_started", "job_id": job.job_id, "stage": "metadata_and_pages"})

    # layout + text (real page ratio); metadata_and_pages 包住 PDF 解析（耗时归属）
    job.mark_stage("metadata_and_pages", status=JobStatus.RUNNING, ratio=0.2, detail="解析 PDF 页面…")
    repository.update_job(job)
    from paperlens_core.paragraphs import rebuild_paragraphs
    from paperlens_core.parse_router import parse_pdf  # V4.0-4：统一入口

    parsed, parse_engine = parse_pdf(raw, pdf_path)
    # rebuild full paragraphs from line-level blocks (two-column aware);
    # template fingerprints pin column boundaries and typography when matched
    from paperlens_core.templates import (
        extract_fingerprint,
        load_registry,
        match_template,
    )

    metadata = next(
        (block.metadata for block in parsed.blocks if block.metadata.get("page_width")), {}
    )
    template = None
    try:
        fingerprint = extract_fingerprint(
            parsed.blocks,
            page_width=float(metadata.get("page_width", 612.0)),
            page_height=float(metadata.get("page_height", 792.0)),
        )
        template = match_template(fingerprint, load_registry())
    except Exception:  # noqa: BLE001 - fingerprinting is best-effort
        template = None
    parsed.blocks = rebuild_paragraphs(parsed.blocks, template=template)
    job.mark_stage("metadata_and_pages", status=JobStatus.SUCCEEDED)
    job.mark_stage(
        "layout_and_text",
        status=JobStatus.RUNNING,
        ratio=1.0,
        detail=f"{parsed.paper.page_count} 页",
    )
    repository.update_job(job)
    bus.publish(
        job.job_id,
        {"event": "stage_progress", "job_id": job.job_id, "stage": "layout_and_text", "progress": 0.25},
    )

    # V4.2 Active Quality Gate（改进方案3 §6.4）：先评估，LOW/SUSPECT 页
    # 用另一引擎重解析并页级融合，再评估——章节识别基于融合后的 blocks
    from paperlens_core.quality_gate import assess_pages, fuse_page_candidates

    page_width = float(metadata.get("page_width", 612.0))
    page_quality = assess_pages(
        parsed.blocks, page_width=page_width, page_count=parsed.paper.page_count
    )
    flagged_pages = [q.page for q in page_quality if q.verdict in ("LOW", "SUSPECT")]
    fused_pages: dict[str, str] = {}
    if flagged_pages:
        alternate_engine = "pdfplumber" if parse_engine == "pymupdf" else "pymupdf"
        try:
            from paperlens_core.parse_router import ParseRouter

            alternate = ParseRouter().parse_with_engine(raw, pdf_path, alternate_engine)
            alternate_blocks = rebuild_paragraphs(alternate.blocks, template=template)
            fused_blocks, fused_pages = fuse_page_candidates(
                parsed.blocks,
                alternate_blocks,
                flagged_pages,
                page_width=page_width,
                primary_engine=parse_engine,
                alternate_engine=alternate_engine,
            )
            if fused_pages:
                parsed.blocks = fused_blocks
                get_logger().info(
                    "active quality gate: %d 页融合（%s）",
                    len(fused_pages),
                    fused_pages,
                )
        except Exception as exc:  # noqa: BLE001 - quality gate is best-effort
            get_logger().warning("active quality gate failed: %s", exc)
    page_quality = assess_pages(
        parsed.blocks, page_width=page_width, page_count=parsed.paper.page_count
    )
    for quality in page_quality:
        quality.resolved_by = fused_pages.get(quality.page, "")
    # fused_pages 键是 int 页码，ParseRun 用 str 键（JSON 序列化稳定）
    fused_pages_str = {str(page): engine for page, engine in fused_pages.items()}
    repository.store_document(
        version_id,
        "page_quality",
        [quality.model_dump(mode="json") for quality in page_quality],
    )
    # ParseRun（V4.2）：解析运行可追溯记录
    from paperlens_core.models import ParseRun

    quality_summary: dict[str, int] = {}
    for quality in page_quality:
        quality_summary[quality.verdict] = quality_summary.get(quality.verdict, 0) + 1
    repository.store_document(
        version_id,
        "parse_run",
        [
            ParseRun(
                parse_run_id=f"pr-{version_id[:12]}-{uuid.uuid4().hex[:8]}",
                paper_version_id=version_id,
                parser_pipeline=f"hybrid:{parse_engine}",
                engine=parse_engine,
                page_count=parsed.paper.page_count,
                quality_summary=quality_summary,
                fused_pages=fused_pages_str,
            ).model_dump(mode="json")
        ],
    )

    # sections
    job.mark_stage("layout_and_text", status=JobStatus.SUCCEEDED)
    job.mark_stage("sections", status=JobStatus.RUNNING, ratio=0.4, detail="识别章节结构…")
    repository.update_job(job)
    sections, assigned = detect_sections(paper_id, parsed.blocks)
    job.mark_stage("sections", status=JobStatus.SUCCEEDED, ratio=1.0, detail=f"{len(sections)} 个章节")
    # 论文级元信息（V3.6）：首页排版提取标题/作者，展示页 arXiv 风格 header
    from paperlens_core.metadata import extract_pdf_metadata

    pdf_meta = extract_pdf_metadata(pdf_path)
    repository.store_document(version_id, "paper_meta", [pdf_meta])
    # index: chunking 归属 index 阶段（此前落在 assets 区间，index 显示 0.0s）
    job.mark_stage("index", status=JobStatus.RUNNING, ratio=0.4, detail="建立检索分片…")
    repository.update_job(job)
    from paperlens_core.chunking import chunk_blocks

    chunks, _ = chunk_blocks(paper_id, assigned)
    job.mark_stage("index", status=JobStatus.SUCCEEDED, ratio=1.0, detail=f"{len(chunks)} 个分片")

    # assets: 图/表候选提取 + caption 关联
    job.mark_stage("assets", status=JobStatus.RUNNING, ratio=0.5, detail="提取图/表候选")
    repository.update_job(job)
    blocks = to_blocks(assigned, version)
    from paperlens_core.documents import BlockType as BlockTypeIR

    # 公式兜底（V3.12 / 改进方案2.md §10.4）：编号 + 上下文段落写入
    # metadata，前端标注；最差情况公式以区域图片保留而非碎片化
    import re as _re

    for index, block in enumerate(blocks):
        if block.block_type != BlockTypeIR.FORMULA:
            continue
        formula_meta = dict(block.metadata)
        number_match = _re.search(r"\((\d+(?:\.\d+)?)\)\s*$", block.text)
        formula_meta["formula_number"] = number_match.group(1) if number_match else ""
        context: list[str] = []
        for offset in (1, -1):
            neighbor = blocks[index + offset] if 0 <= index + offset < len(blocks) else None
            if neighbor and neighbor.block_type == BlockTypeIR.TEXT and neighbor.text.strip():
                context.append(neighbor.text[:150])
        formula_meta["context"] = context
        block.metadata = formula_meta
    assets = derive_assets(blocks)
    from paperlens_core.assets import associate_captions

    assets = associate_captions(assets, blocks)
    # 表格结构化（V3.12 / 改进方案2.md §10.3）：有线框表格用 PyMuPDF
    # 矢量线重建网格 → cell matrix + CSV；失败保持 PARTIAL（前端显示原图）
    try:
        import fitz

        from paperlens_core.documents import (
            AssetExtractionStatus as AssetExtractionStatusIR,
            AssetKind as AssetKindIR,
            AssetSourceKind as AssetSourceKindIR,
        )
        from paperlens_core.table_grid import build_table_grid
        from paperlens_core.tables import grid_to_html, rows_to_csv

        with fitz.open(pdf_path) as document:
            for asset in assets:
                if asset.asset_kind != AssetKindIR.TABLE or asset.page < 1:
                    continue
                page = document[asset.page - 1]
                x0, y0, x1, y1 = asset.bbox
                grid = build_table_grid(page, x0=x0, y0=y0, x1=x1, y1=y1)
                if not grid:
                    continue
                asset.structured_data = {
                    "rows": grid,
                    "csv": rows_to_csv(grid),
                    "html": grid_to_html(grid),
                }
                asset.source_kind = AssetSourceKindIR.STRUCTURED_TABLE
                asset.extraction_status = AssetExtractionStatusIR.EXTRACTED
                asset.confidence = 0.85
    except Exception as exc:  # noqa: BLE001 - structured tables are best-effort
        get_logger().warning("pdf table grid failed: %s", exc)
    job.mark_stage("assets", status=JobStatus.SUCCEEDED)

    # persist DocumentIR
    sections_ir = to_sections(sections, version)
    chunks_ir = to_chunks(chunks, version)
    repository.store_document(version_id, "blocks", [b.model_dump(mode="json") for b in blocks])
    repository.store_document(version_id, "sections", [s.model_dump(mode="json") for s in sections_ir])
    repository.store_document(version_id, "chunks", [c.model_dump(mode="json") for c in chunks_ir])
    repository.store_document(version_id, "assets", [a.model_dump(mode="json") for a in assets])

    # references: 引用条目解析 + callout 绑定
    job.mark_stage("references", status=JobStatus.RUNNING, ratio=0.4, detail="解析引用…")
    repository.update_job(job)
    from paperlens_core.assets import extract_callouts
    from paperlens_core.references import (
        parse_references,
        serialize_reference_records,
    )

    references_text = "\n".join(
        block.text
        for block in blocks
        if block.page >= (next((s.start_page for s in sections_ir if s.canonical_name == "references"), 999))
    )
    reference_records = parse_references(references_text)
    # V4.2（改进方案3 §7.1）：引用记录导入期持久化——此前只取计数供
    # callout，访问时临时重解析，结果不稳定
    repository.store_document(
        version_id,
        "references",
        serialize_reference_records(reference_records, version_id),
    )
    reference_count = len(reference_records)
    callouts = extract_callouts(version_id, blocks, sections_ir, reference_count)
    repository.store_document(
        version_id,
        "callouts",
        [callout.model_dump(mode="json") for callout in callouts],
    )
    job.mark_stage("references", status=JobStatus.SUCCEEDED, ratio=1.0, detail="引用条目解析")
    job.mark_stage("initial_translation", status=JobStatus.RUNNING, ratio=0.0, detail="正在翻译…")
    repository.update_job(job)
    try:
        translated = translate_initial_pages(repository, version, job)
        detail = f"翻译完成（{translated} 段）" if translated else "无待翻译段落"
    except Exception:  # noqa: BLE001 - translation failure never fails the parse
        detail = "翻译暂不可用，进入后自动重试"
    job.mark_stage("initial_translation", status=JobStatus.SUCCEEDED, ratio=1.0, detail=detail)
    repository.update_job(job)
    executor.log_stage_times(job)
    executor.complete(job)
    return job
