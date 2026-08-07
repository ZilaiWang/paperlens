"""V3 feature tests (改进方案2.md): quality gate, chunk segments, evidence
locators and the translation layered system. No network or LLM required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from paperlens_core.chunking import chunk_blocks
from paperlens_core.documents import TranslationUnit
from paperlens_core.evidence import locate_chunk_spans
from paperlens_core.models import Block, BlockType, SupportStatus
from paperlens_core.quality_gate import assess_page_quality
from paperlens_core.translation import (
    GlossaryEntry,
    PaperTranslationProfile,
    terminology_concordance,
    terminology_violations,
    unit_matches_block,
)


def _block(block_id: str, text: str, index: int, y0: float = 100.0, block_type: BlockType = BlockType.TEXT) -> Block:
    return Block(
        block_id=block_id,
        paper_id="p",
        paper_version_id="v",
        page=1,
        block_index=index,
        bbox=(50.0, y0, 450.0, y0 + 15.0),
        block_type=block_type,
        text=text,
        content_sha256="sha",
    )


# ---------------------------------------------------------------------------
# 质量门（改进方案2.md §8）
# ---------------------------------------------------------------------------


class TestQualityGate:
    def test_clean_page_is_good(self) -> None:
        blocks = [_block(f"b{i}", f"paragraph {i} with enough words to parse.", i) for i in range(6)]
        quality = assess_page_quality(1, blocks)
        assert quality.verdict == "GOOD"
        assert quality.fallback_reasons == []

    def test_tiny_block_ratio_flags_page(self) -> None:
        blocks = [
            _block("b0", "a normal sized paragraph here.", 0),
            _block("b1", "M", 1),
            _block("b2", "V", 2),
            _block("b3", "C", 3),
            _block("b4", "n", 4),
        ]
        quality = assess_page_quality(1, blocks)
        assert quality.verdict == "LOW"
        assert "TOO_MANY_TINY_BLOCKS" in quality.fallback_reasons

    def test_table_text_contamination(self) -> None:
        blocks = [
            _block("b0", "method paragraphs read normally here.", 0),
            _block("b1", "AP 50 75.3 10 shot 44.2", 1),
            _block("b2", "another normal paragraph for good measure.", 2),
        ]
        quality = assess_page_quality(1, blocks)
        assert quality.verdict == "LOW"
        assert "TABLE_TEXT_IN_BODY" in quality.fallback_reasons

    def test_reading_order_inversion(self) -> None:
        blocks = [
            _block("b0", "first paragraph in the column.", 0, y0=100.0),
            _block("b1", "second paragraph moves upward.", 1, y0=60.0),
            _block("b2", "third paragraph moves upward too.", 2, y0=30.0),
        ]
        quality = assess_page_quality(1, blocks, page_width=612.0)
        assert quality.reading_order_inversions == 2
        assert "READING_ORDER_UNCERTAIN" in quality.fallback_reasons

    def test_empty_page_passes(self) -> None:
        quality = assess_page_quality(1, [])
        assert quality.verdict == "GOOD"


# ---------------------------------------------------------------------------
# ChunkSegment 字符映射（改进方案2.md §16.1）
# ---------------------------------------------------------------------------


class TestChunkSegments:
    def test_segments_map_through_hyphen_repair(self) -> None:
        blocks = [
            _block("b0", "We freeze the back-", 0),
            _block("b1", "bone in stage one and the", 1),
            _block("b2", "model stays frozen.", 2),
        ]
        chunks, _ = chunk_blocks("p", blocks, target_tokens=1000, max_tokens=2000)
        chunk = chunks[0]
        assert "backbone" in chunk.text
        # the repaired "backbone" spans b0 (without hyphen) + b1
        segments = {segment.block_id: segment for segment in chunk.segments}
        assert segments["b0"].chunk_char_end == 18
        assert segments["b1"].chunk_char_start == 18
        locators = locate_chunk_spans(
            [segment.model_dump(mode="json") for segment in chunk.segments],
            chunk.text.find("backbone"),
            chunk.text.find("backbone") + 8,
        )
        reconstructed = []
        for locator in locators:
            source = next(block.text for block in blocks if block.block_id == locator["block_id"])
            reconstructed.append(
                source[locator["block_char_start"] : locator["block_char_end"]]
            )
        assert "".join(reconstructed) == "backbone"

    def test_locator_clips_to_overlap(self) -> None:
        blocks = [
            _block("b0", "the quick brown fox jumps over the lazy dog", 0),
        ]
        chunks, _ = chunk_blocks("p", blocks, target_tokens=1000, max_tokens=2000)
        segment = chunks[0].segments[0]
        locators = locate_chunk_spans(
            [segment.model_dump(mode="json") for segment in chunks[0].segments],
            segment.chunk_char_start + 4,
            segment.chunk_char_end - 3,
        )
        assert len(locators) == 1
        assert locators[0]["block_char_start"] == 4
        assert locators[0]["block_char_end"] == len(blocks[0].text) - 3

    def test_chunk_text_roundtrip(self) -> None:
        blocks = [
            _block("b0", "first paragraph with several words.", 0),
            _block("b1", "second paragraph continues the story.", 1),
        ]
        chunks, _ = chunk_blocks("p", blocks, target_tokens=1000, max_tokens=2000)
        chunk = chunks[0]
        text = ""
        for segment in chunk.segments:
            text += chunk.text[segment.chunk_char_start : segment.chunk_char_end] + " "
        assert "first paragraph" in text and "second paragraph" in text

    def test_document_graph_chunk_direct_roundtrip(self) -> None:
        # V4.1：_legacy_chunks 桥已删除——documents.Chunk 直接进 reader 路径，
        # 存储 payload（含 segments）必须能直接 model_validate 且段信息无损
        from paperlens_core.documents import Chunk as IRChunk
        from paperlens_core.documents import ChunkSegment as IRCS

        stored = {
            "chunk_id": "c1",
            "paper_version_id": "v",
            "text": "freeze the backbone",
            "content_sha256": "s",
            "segments": [
                {
                    "chunk_char_start": 0,
                    "chunk_char_end": 20,
                    "block_id": "b0",
                    "block_char_start": 0,
                    "block_char_end": 20,
                    "page": 1,
                    "bboxes": [[50.0, 100.0, 450.0, 115.0]],
                }
            ],
        }
        chunk = IRChunk.model_validate(stored)
        assert chunk.segments[0].block_id == "b0"
        assert chunk.segments[0].bboxes == [(50.0, 100.0, 450.0, 115.0)]
        # 直接供检索使用（reader 路径与 _legacy_chunks 时代的字段一致）
        assert chunk.chunk_id == "c1" and chunk.paper_version_id == "v"


# ---------------------------------------------------------------------------
# 翻译分层体系（改进方案2.md §12/13/15）
# ---------------------------------------------------------------------------


class TestTerminology:
    def test_preferred_translation_passes(self) -> None:
        glossary = [GlossaryEntry(source="feature extractor", translation="特征提取器")]
        assert terminology_violations("we use a feature extractor", "我们使用特征提取器", glossary) == []

    def test_drift_is_flagged_as_warning(self) -> None:
        glossary = [GlossaryEntry(source="feature extractor", translation="特征提取器")]
        violations = terminology_violations("we use a feature extractor", "我们使用特征抽取器", glossary)
        assert violations and "特征提取器" in violations[0]

    def test_plain_number_citation_passes_verification(self) -> None:
        # fix 2026-08-04: "[12]" citations were always rejected because the
        # old check only accepted 19xx/20xx years inside the citation token
        from paperlens_core.translation import (
            protect_tokens,
            restore_tokens,
            verify_translation,
        )

        source = "We freeze the backbone [12] and the head [3, 7]."
        protected, tokens = protect_tokens(source, [])
        # model keeps the numbers but drops the brackets: "…主干网络 12 …"
        target = restore_tokens("我们冻结主干网络 12 以及头部 3 7", tokens)
        assert verify_translation(source, target, tokens) == []
        # numbers genuinely missing still fail
        target_missing = restore_tokens("我们冻结主干网络以及头部", tokens)
        assert verify_translation(source, target_missing, tokens) != []

    def test_keep_english_violation(self) -> None:
        glossary = [GlossaryEntry(source="Grounding DINO", translation="x", keep_english=True)]
        violations = terminology_violations("we use Grounding DINO", "我们使用接地DINO", glossary)
        assert violations and "保持英文" in violations[0]

    def test_inline_math_restored_passes_verification(self) -> None:
        # V3.23b：行内公式 $...$ 保护激活后，恢复原文的单元必须通过——
        # 此前 _restored_acceptably 没有 MATH 分支，含公式单元全被判失败
        from paperlens_core.translation import (
            protect_tokens,
            restore_tokens,
            verify_translation,
        )

        source = "The encoder has $N=6$ identical layers with $d_{k}$ heads."
        protected, tokens = protect_tokens(source, [])
        target = restore_tokens("编码器由 $N=6$ 个相同层组成，含 $d_{k}$ 个头。", tokens)
        assert verify_translation(source, target, tokens) == []
        # 公式真的被丢弃仍要失败
        target_missing = restore_tokens("编码器由 6 个相同层组成。", tokens)
        assert verify_translation(source, target_missing, tokens) != []

    def test_concordance_finds_drifting_units(self) -> None:
        glossary = [GlossaryEntry(source="proposal", translation="候选框")]
        ok_unit = TranslationUnit(
            unit_id="u-ok",
            paper_version_id="v",
            source_text="our proposal generator",
            target_text="我们的候选框生成器",
        )
        bad_unit = TranslationUnit(
            unit_id="u-bad",
            paper_version_id="v",
            source_text="our proposal generator",
            target_text="我们的提议生成器",
        )
        findings = terminology_concordance([ok_unit, bad_unit], glossary)
        assert len(findings) == 1
        assert findings[0]["unit_id"] == "u-bad"

# ---------------------------------------------------------------------------
# 上传 PDF 自动匹配 arXiv（改进方案2.md §4.1 Source-first）
# ---------------------------------------------------------------------------


class TestArxivMatch:
    def test_title_candidates_from_filename(self) -> None:
        from server.app.main import _title_candidates_from_filename

        assert _title_candidates_from_filename("1706.03762.pdf") == ["1706.03762"]
        assert _title_candidates_from_filename("arXiv_1607.06450v2.pdf") == ["1607.06450v2"]
        assert _title_candidates_from_filename("Attention_Is_All_You_Need_final.pdf") == [
            "Attention Is All You Need"
        ]
        # too short / generic names fall back to the PDF pipeline
        assert _title_candidates_from_filename("yolov7 final draft.pdf") == []

    def test_match_arxiv_by_title_threshold(self) -> None:
        from server.app.main import _match_arxiv_by_title

        class FakeClient:
            def search_arxiv_by_title(self, title: str):
                return [
                    _metadata("1607.06450", "Layer Normalization"),
                    _metadata("1706.03762", "Attention Is All You Need"),
                ]

        client = FakeClient()
        assert _match_arxiv_by_title(client, "Layer Normalization") == "1607.06450"
        assert _match_arxiv_by_title(client, "Attention is all you need") == "1706.03762"
        # unrelated title stays below the 0.70 threshold
        assert _match_arxiv_by_title(client, "A Completely Different Paper") is None

    def test_search_arxiv_by_title_parses_atom(self) -> None:
        from paperlens_core.scholarly import ScholarlyClient

        atom = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1607.06450v1</id>
    <published>2016-07-21T00:00:00Z</published>
    <title>Layer Normalization</title>
    <author><name>Jimmy Lei Ba</name></author>
    <author><name>Jamie Ryan Kiros</name></author>
  </entry>
</feed>"""
        client = object.__new__(ScholarlyClient)
        client.last_errors = {}
        entries = client._parse_arxiv_entries(atom)
        assert len(entries) == 1
        assert entries[0].arxiv_id == "1607.06450v1"
        assert entries[0].title == "Layer Normalization"
        assert entries[0].year == 2016
        assert entries[0].authors == ("Jimmy Lei Ba", "Jamie Ryan Kiros")


def _metadata(arxiv_id: str, title: str):
    from paperlens_core.scholarly import ScholarlyMetadata

    return ScholarlyMetadata(
        provider="arxiv",
        identifier=arxiv_id,
        title=title,
        authors=(),
        year=2020,
        arxiv_id=arxiv_id,
        url=f"http://arxiv.org/abs/{arxiv_id}",
    )


class TestUserQuota:
    def test_quota_rejects_over_limit(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from server.app.main import _enforce_paper_quota

        class FakeRepo:
            def count_papers_by_user(self, user_id: str) -> int:
                return 300

        monkeypatch.setattr("server.app.main.repository", FakeRepo())
        with pytest.raises(HTTPException) as exc_info:
            _enforce_paper_quota("alice")
        assert exc_info.value.status_code == 403

    def test_quota_allows_under_limit(self, monkeypatch) -> None:
        from server.app.main import _enforce_paper_quota

        class FakeRepo:
            def count_papers_by_user(self, user_id: str) -> int:
                return 299

        monkeypatch.setattr("server.app.main.repository", FakeRepo())
        _enforce_paper_quota("alice")  # must not raise

    def test_user_id_from_header(self) -> None:
        from server.app.main import _request_user_id

        class FakeRequest:
            headers = {"X-User-Id": "alice"}

        class FakeRequestEmpty:
            headers = {}

        assert _request_user_id(FakeRequest()) == "alice"
        assert _request_user_id(FakeRequestEmpty()) == "guest"


class TestTranslationProfile:
        profile = PaperTranslationProfile(
            paper_title="Frozen Backbones",
            domain=["computer vision", "few-shot detection"],
            entities=[{"source": "Grounding DINO", "type": "MODEL", "policy": "KEEP_ENGLISH"}],
            abbreviations=[{"short": "FSOD", "long": "few-shot object detection", "preferred_zh": "少样本目标检测"}],
            ambiguous_terms=[{"source": "proposal", "preferred_zh": "候选框", "context": "object detection"}],
        )
        text = profile.render_instructions()
        assert "Grounding DINO" in text
        assert "FSOD -> 少样本目标检测" in text
        assert "proposal -> 候选框" in text
        assert "PAPER: Frozen Backbones" in text


class TestJsonRepair:
    def test_invalid_escape_repaired(self) -> None:
        from paperlens_core.llm import extract_json

        raw = '{"paragraphs": [{"paragraph_index": 0, "translation": "L = \\\\lambda L_{cls}"}]}'
        out = extract_json(raw)
        assert out["paragraphs"][0]["translation"] == "L = \\lambda L_{cls}"

    def test_legal_escapes_untouched(self) -> None:
        from paperlens_core.llm import _repair_invalid_escapes

        assert _repair_invalid_escapes('{"a": "x\\\\ny"}') == '{"a": "x\\\\ny"}'
        assert _repair_invalid_escapes('{"a": "\\\\u4e2d"}') == '{"a": "\\\\u4e2d"}'


class TestTranslateEndpoint:
    def test_pending_uses_translation_status(self, monkeypatch, tmp_path) -> None:
        # regression (fix 2026-08-04): missing TranslationStatus import made
        # every translate request 500 with NameError before touching the model
        from fastapi.testclient import TestClient

        from paperlens_core.documents import (
            Block as IRBlock,
            Paper,
            PaperVersion,
            TranslationStatus,
            TranslationUnit,
        )

        from server.app.main import app
        from server.app.repository import Repository

        repo = Repository(str(tmp_path / "t.db"))
        monkeypatch.setattr("server.app.main.repository", repo)
        repo.create_paper(Paper(paper_id="p1", canonical_title="t", created_at="2026-08-04T00:00:00Z"))
        repo.create_version(
            PaperVersion(
                version_id="ver-abc1234567",
                paper_id="p1",
                version_label="v1",
                source="UPLOAD",
                file_name="t.pdf",
                file_sha256="sha",
                page_count=1,
                created_at="2026-08-04T00:00:00Z",
            )
        )
        block = IRBlock(
            block_id="blk-1",
            paper_version_id="ver-abc1234567",
            page=1,
            block_type="TEXT",
            bbox=(50.0, 100.0, 450.0, 115.0),
            text="This is a long enough paragraph to be translated by the pipeline.",
            content_sha256="s",
        )
        repo.store_document("ver-abc1234567", "blocks", [block.model_dump(mode="json")])
        repo.store_document(
            "ver-abc1234567",
            "translations",
            [
                TranslationUnit(
                    unit_id="tu-1",
                    paper_version_id="ver-abc1234567",
                    source_block_ids=["blk-1"],
                    source_text=block.text,
                    target_text="译文",
                    status=TranslationStatus.TRANSLATED,
                ).model_dump(mode="json")
            ],
        )
        response = TestClient(app).post(
            "/api/papers/p1/translations", json={"pages": [1]}
        )
        assert response.status_code == 200
        assert response.json()["cached"] == 1


class TestFormulaExtraction:
    def test_display_math_becomes_formula_block(self) -> None:
        from paperlens_core.arxiv_html import parse_arxiv_html

        html = """<html><body><section class="ltx_section"><h2 class="ltx_title">Method</h2>
        <div class="ltx_para"><p class="ltx_p">
          <math alttext="L = \\mathcal{L}_{cls} + \\lambda \\mathcal{L}_{reg}"><mtext>MML</mtext></math>(1)
        </p></div>
        <div class="ltx_para"><p class="ltx_p">We use <math alttext="h_{t}">MML</math> inline here.</p></div>
        </section></body></html>"""
        blocks = parse_arxiv_html(html, arxiv_id="9999.99999")
        formulas = [b for b in blocks if b.metadata.get("html_role") == "FORMULA"]
        assert len(formulas) == 1, [b.text for b in blocks]
        assert "mathcal{L}_{cls}" in formulas[0].text
        # V3.21：display 公式编号入库（"(1)" 尾部）
        assert formulas[0].metadata.get("formula_number") == "1"
        paras = [b for b in blocks if b.metadata.get("html_role") == "PARAGRAPH"]
        assert "h_{t}" in paras[-1].text  # inline math latex survives
        # V3.21：行内公式 $ 包裹（翻译保护 + 前端 KaTeX 渲染）
        assert "$h_{t}$" in paras[-1].text
        assert "MML" not in paras[-1].text  # MathML markup does not leak

    def test_equation_table_structure_becomes_formula_block(self) -> None:
        # V3.21b：LaTeXML 表格结构的 display 公式（Attention Is All You Need
        # 的真实形态），此前检测只认 p 的直接 math 子节点，这类全部漏掉
        from paperlens_core.arxiv_html import parse_arxiv_html

        html = """<html><body><section class="ltx_section"><h2 class="ltx_title">Method</h2>
        <div class="ltx_para"><p class="ltx_p">Attention is computed as</p>
        <table class="ltx_equation"><tr class="ltx_equation ltx_eqn_row">
          <td class="ltx_eqn_cell ltx_align_center"><math alttext="\\mathrm{Attention}(Q,K,V)=\\mathrm{softmax}(\\frac{QK^{T}}{\\sqrt{d_{k}}})"><mtext>MML</mtext></math></td>
          <td class="ltx_eqn_cell ltx_align_right ltx_eqn_number"><span class="ltx_tag">(1)</span></td>
        </tr></table>
        </div></section></body></html>"""
        blocks = parse_arxiv_html(html, arxiv_id="9999.99998")
        formulas = [b for b in blocks if b.metadata.get("html_role") == "FORMULA"]
        assert len(formulas) == 1, [b.text for b in blocks]
        assert "softmax" in formulas[0].text
        assert formulas[0].metadata.get("formula_number") == "1"
        paras = [b for b in blocks if b.metadata.get("html_role") == "PARAGRAPH"]
        # 表格结构公式不出现在段落文本里（已排除）
        assert "softmax" not in paras[0].text

    def test_figure_url_keeps_version_dir(self) -> None:
        # V3.23：img src 带版本目录（"1706.03762v7/Figures/..."），
        # 只取文件名拼根路径会 404
        from paperlens_core.arxiv_html import extract_assets

        html = """<html><body>
        <figure class="ltx_figure"><img src="1706.03762v7/Figures/ModalNet-21.png"/><figcaption>Fig 1</figcaption></figure>
        <figure class="ltx_figure"><img src="x1.png"/><figcaption>Fig 2</figcaption></figure>
        </body></html>"""
        assets = extract_assets(html, arxiv_id="1706.03762")
        uris = [a["content_uri"] for a in assets if a["asset_kind"] == "FIGURE"]
        assert "https://arxiv.org/html/1706.03762v7/Figures/ModalNet-21.png" in uris
        assert "https://arxiv.org/html/1706.03762/x1.png" in uris

    def test_inline_math_replaces_mathml_text(self) -> None:
        from paperlens_core.arxiv_html import _node_text_with_math

        from lxml import html as lxml_html

        html = '<div class="ltx_para"><p>score <math alttext="P_{i}">MML</math> is best</p></div>'
        tree = lxml_html.fromstring(html)
        para = tree.xpath("//div")[0]
        text = _node_text_with_math(para)
        assert "$P_{i}$" in text  # V3.21：$ 包裹供前端 KaTeX 行内渲染
        assert "MML" not in text
        assert "score" in text and "is best" in text  # tail preserved


# ---------------------------------------------------------------------------
# 翻译单元内容校验（V3.22）
# ---------------------------------------------------------------------------


class TestUnitMatchesBlock:
    def test_identical_content_passes(self) -> None:
        assert unit_matches_block(
            "We call our particular attention Scaled Dot-Product",
            "We call our particular attention Scaled Dot-Product",
        )

    def test_dollar_wrap_differs_but_content_same(self) -> None:
        # 重解析后行内公式多了 $ 包裹：视为同一内容
        assert unit_matches_block(
            "While for small values of d_{k}",
            "While for small values of $d_{k}$",
        )

    def test_shifted_content_rejected(self) -> None:
        # block_id 索引型：重解析后同 id 指向不同内容 → 旧单元作废
        assert not unit_matches_block(
            "In this work we employ h=8 parallel attention layers",
            "Where the projections are parameter matrices W^{Q}_{i}",
        )

    def test_empty_source_rejected(self) -> None:
        assert not unit_matches_block("", "some text")


# ---------------------------------------------------------------------------
# V4.2 Active Quality Gate（页级候选融合）
# ---------------------------------------------------------------------------


class TestFusePageCandidates:
    def _blocks(self, page: int, texts: list[str], prefix: str) -> list[Block]:
        return [
            Block(
                block_id=f"{prefix}-p{page}-b{i}",
                paper_id="p",
                paper_version_id="v",
                page=page,
                block_index=i,
                bbox=(50.0, float(100 + i * 15), 450.0, float(115 + i * 15)),
                block_type=BlockType.TEXT,
                text=text,
                content_sha256="s",
            )
            for i, text in enumerate(texts)
        ]

    def test_low_page_switches_to_better_candidate(self) -> None:
        from paperlens_core.quality_gate import assess_pages, fuse_page_candidates

        # 主引擎第 1 页碎片化（LOW），备选引擎同页是完整段落（GOOD）
        primary = self._blocks(1, ["M", "V", "C", "n", "a normal paragraph here."], "pm")
        alternate = self._blocks(
            1,
            [
                "a normal paragraph with several words.",
                "another complete paragraph with enough words to read.",
                "a third full paragraph for good measure.",
            ],
            "alt",
        )
        primary[0].bbox = (50.0, 100.0, 450.0, 115.0)
        # 覆盖度阈值对合成文本保守，断言"严格更优"即可（碎片页多一条原因）
        primary_quality = assess_pages(primary, page_width=612.0)[0]
        alternate_quality = assess_pages(alternate, page_width=612.0)[0]
        assert "TOO_MANY_TINY_BLOCKS" in primary_quality.fallback_reasons
        assert "TOO_MANY_TINY_BLOCKS" not in alternate_quality.fallback_reasons

        fused, chosen = fuse_page_candidates(
            primary, alternate, [1], page_width=612.0,
            primary_engine="pymupdf", alternate_engine="pdfplumber",
        )
        assert chosen == {1: "pdfplumber"}
        assert all(block.block_id.startswith("alt-") for block in fused)

    def test_good_page_keeps_primary(self) -> None:
        from paperlens_core.quality_gate import fuse_page_candidates

        primary = self._blocks(1, ["a normal paragraph with several words."], "pm")
        alternate = self._blocks(1, ["M", "V", "C", "n", "junk"], "alt")
        fused, chosen = fuse_page_candidates(
            primary, alternate, [1], page_width=612.0,
            primary_engine="pymupdf", alternate_engine="pdfplumber",
        )
        assert chosen == {1: "pymupdf"}
        assert all(block.block_id.startswith("pm-") for block in fused)

    def test_alternate_without_content_keeps_primary(self) -> None:
        from paperlens_core.quality_gate import fuse_page_candidates

        primary = self._blocks(1, ["fragmented M V C junk text here."], "pm")
        fused, chosen = fuse_page_candidates(
            primary, [], [1], page_width=612.0,
            primary_engine="pymupdf", alternate_engine="pdfplumber",
        )
        assert chosen == {1: "pymupdf"}
        assert len(fused) == 1


class TestSerializeReferences:
    def test_record_shape_matches_endpoint_contract(self) -> None:
        from paperlens_core.references import (
            parse_references,
            serialize_reference_records,
        )

        records = parse_references(
            "[1] K. He, X. Zhang, S. Ren, J. Sun. Deep Residual Learning. CVPR 2016."
        )
        assert records
        items = serialize_reference_records(records, "ver-test12345678")
        assert items[0]["reference_id"].startswith("ref-ver-test12-1")
        assert items[0]["sequence_number"] == 1
        assert items[0]["identity_status"] in {"VERIFIED", "PROBABLE", "AMBIGUOUS", "UNRESOLVED"}
        assert "parsed_title" in items[0] and "authors" in items[0]


# ---------------------------------------------------------------------------
# draft 会话缓存（V3.17）
# ---------------------------------------------------------------------------


class TestDraftCache:
    QUESTION = "论文用的什么优化器？"

    def _chunks(self):
        from paperlens_core import models as legacy

        return [
            legacy.Chunk(
                chunk_id="ch-a", paper_id="p1", paper_version_id="p1", section_id="s1", section_path="Intro",
                page_start=1, page_end=1, block_ids=["b1"],
                text="The model uses the Adam optimizer for training.",
                token_estimate=10, content_sha256="sha1", segments=[],
            ),
            legacy.Chunk(
                chunk_id="ch-b", paper_id="p1", paper_version_id="p1", section_id="s2", section_path="Training",
                page_start=2, page_end=2, block_ids=["b2"],
                text="We trained the Transformer for 100000 steps.",
                token_estimate=10, content_sha256="sha2", segments=[],
            ),
        ]

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        # 模块级缓存跨测试残留会串扰（前一个用例的命中污染下一个）
        from paperlens_core import reader as reader_module

        reader_module._DRAFT_CACHE.clear()
        yield

    def _chain(self, draft: AnswerDraft) -> list[object]:
        """一轮 run_events 所需的静态模型响应序列（1 条主张 → organize 跳过）。

        顺序必须与管线调用一致：plan → draft → 核验。
        """
        plan, verdict = self._plan_verdict(draft)
        return [plan, draft, verdict]

    def _plan_verdict(self, draft: AnswerDraft) -> list[object]:
        """缓存命中轮的响应序列：draft 不调用，只有 plan + 核验。"""
        from paperlens_core.reader import AttributionVerdict, QueryPlan

        plan = QueryPlan(
            intent="method", original_query=self.QUESTION,
            english_query="optimizer", keywords=["optimizer"],
            section_hints=["Training"],
        )
        verdict = AttributionVerdict(
            claim_id=draft.claims[0].claim_id,
            verdict=SupportStatus.SUPPORTED,
            rationale="ok",
        )
        return [plan, verdict]

    def test_repeat_question_skips_second_draft_call(self) -> None:
        from paperlens_core.evidence import sha256_text
        from paperlens_core.llm import StaticJSONModel
        from paperlens_core.reader import PaperReader
        from paperlens_core.models import AnswerClaim, AnswerDraft, EvidenceLink, SupportStatus

        chunks = self._chunks()
        excerpt = chunks[0].text
        evidence_id = f"ev-p1-{sha256_text(chunks[0].chunk_id + excerpt)[:12]}"
        draft = AnswerDraft(
            claims=[
                AnswerClaim(
                    claim_id="cl-1",
                    text="The model uses the Adam optimizer.",
                    evidence_links=[
                        EvidenceLink(
                            evidence_id=evidence_id,
                            verbatim_quote="The model uses the Adam optimizer",
                            char_start=0,
                            char_end=33,
                        )
                    ],
                )
            ],
            answer_summary_claim_ids=["cl-1"],
        )
        model = StaticJSONModel(self._chain(draft) + self._plan_verdict(draft))
        reader = PaperReader(model)

        events1 = list(
            reader.run_events(question=self.QUESTION, chunks=chunks, cache_namespace="ver-1")
        )
        events2 = list(
            reader.run_events(question=self.QUESTION, chunks=chunks, cache_namespace="ver-1")
        )
        # 两次运行只应有 1 次 scientific_reader 调用（第二次命中缓存）
        draft_calls = [c for c in model.calls if c["stage"] == "scientific_reader"]
        assert len(draft_calls) == 1
        # 两轮都正常产出了核验通过的完整回答
        for events in (events1, events2):
            assert any(e.event == "claim_validated" for e in events)
            completed = [e for e in events if e.event == "completed"][0]
            answer = completed.payload["answer"]
            assert answer["claims"][0]["text"] == "The model uses the Adam optimizer."

    def test_different_namespace_misses_cache(self) -> None:
        from paperlens_core.llm import StaticJSONModel
        from paperlens_core.reader import PaperReader
        from paperlens_core.models import AnswerClaim, AnswerDraft, EvidenceLink, SupportStatus

        chunks = self._chunks()
        excerpt = chunks[0].text
        from paperlens_core.evidence import sha256_text

        evidence_id = f"ev-p1-{sha256_text(chunks[0].chunk_id + excerpt)[:12]}"
        draft = AnswerDraft(
            claims=[
                AnswerClaim(
                    claim_id="cl-1",
                    text="The model uses the Adam optimizer.",
                    evidence_links=[
                        EvidenceLink(
                            evidence_id=evidence_id,
                            verbatim_quote="The model uses the Adam optimizer",
                            char_start=0,
                            char_end=33,
                        )
                    ],
                )
            ],
            answer_summary_claim_ids=["cl-1"],
        )
        model = StaticJSONModel(self._chain(draft) + self._chain(draft))
        reader = PaperReader(model)
        list(reader.run_events(question=self.QUESTION, chunks=chunks, cache_namespace="ver-1"))
        list(reader.run_events(question=self.QUESTION, chunks=chunks, cache_namespace="ver-2"))
        draft_calls = [c for c in model.calls if c["stage"] == "scientific_reader"]
        assert len(draft_calls) == 2  # 不同论文版本 → 缓存不命中
