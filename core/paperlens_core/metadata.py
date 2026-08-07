"""Paper metadata extraction for the workbench header (V3.6, arXiv-style).

HTML papers get title/authors/abstract straight from the LaTeXML header;
PDF papers get best-effort title and author line from page 1 typography
(largest font = title, next tier = authors). Abstract for PDFs comes from
the Abstract section block at display time.
"""

from __future__ import annotations

import re
from typing import Any


def _spans_from_pdf(pdf_path: str) -> list[tuple[float, str]]:
    """(font_size, text) spans of page 1, arXiv header lines filtered."""
    spans: list[tuple[float, str]] = []
    try:
        import fitz  # PyMuPDF (optional; pdfplumber fallback below)

        document = fitz.open(pdf_path)
        page = document[0]
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if len(text) > 8 and not re.match(
                        r"(?i)arXiv\s*:\s*\d{4}\.\d{4,5}", text
                    ):
                        spans.append((float(span.get("size", 0.0)), text))
        document.close()
        if spans:
            return spans
    except Exception:  # noqa: BLE001 - try pdfplumber below
        pass
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as document:
            for line in document.pages[0].extract_text_lines():
                text = line["text"].strip()
                if len(text) > 8 and not re.match(
                    r"(?i)arXiv\s*:\s*\d{4}\.\d{4,5}", text
                ):
                    spans.append((float(line.get("size", 0.0)), text))
    except Exception:  # noqa: BLE001 - best-effort by design
        return []
    return spans


def extract_pdf_metadata(pdf_path: str) -> dict[str, str]:
    """Title and author line from page-1 typography; empty strings on failure."""
    spans = _spans_from_pdf(pdf_path)
    if not spans:
        return {"title": "", "authors": ""}
    spans.sort(key=lambda item: item[0], reverse=True)
    best_size = spans[0][0]
    title_lines = [
        text for size, text in spans if size >= best_size - 1.5
    ]
    title = " ".join(title_lines)
    # authors: the next size tier below the title (usually one line)
    author_tier = next(
        (size for size, _ in sorted(spans, key=lambda item: item[0], reverse=True)
         if size < best_size - 1.5),
        0.0,
    )
    author_lines = [
        text for size, text in spans
        if author_tier and abs(size - author_tier) <= 1.0 and size < best_size - 1.5
    ]
    authors = " ".join(author_lines)
    return {
        "title": title if len(title) <= 300 else title[:300],
        "authors": authors if len(authors) <= 300 else authors[:300],
    }


def meta_with_abstract(meta: dict[str, Any], blocks: list[Any]) -> dict[str, Any]:
    """Attach the Abstract-section text for PDF papers (HTML already has it)."""
    if meta.get("abstract"):
        return meta
    abstract = ""
    for block in blocks:
        text = (getattr(block, "text", "") or "").strip()
        if re.match(r"^(abstract)\b", text, re.IGNORECASE) and len(text) < 60:
            continue  # the section heading itself
        section = getattr(block, "section_path", "") or ""
        if "abstract" in section.casefold() and len(text) > 60:
            abstract = text
            break
    return {**meta, "abstract": abstract}


# ---------------------------------------------------------------------------
# 2026-08-07（教师优化 1）：解析时用论文摘要生成示例问题——前端 Agent
# 输入框 placeholder 动态化。一次 LLM 调用生成 3 个读者视角的具体问题，
# 取第一个展示；失败降级为空列表（前端回退默认文案）。
# ---------------------------------------------------------------------------

SAMPLE_QUESTIONS_SYSTEM = """你是论文阅读助手。基于给定的论文摘要，生成 3 个
读者最可能问的、针对这篇论文的具体问题（中文，每个 12-25 字）。要求具体
（提及论文的关键方法/任务/数据），不要泛泛而问（如"这篇论文讲了什么"）。
输出严格 JSON：{"questions": ["问题1", "问题2", "问题3"]}"""


def generate_sample_questions(model: Any, abstract: str, count: int = 3) -> list[str]:
    """用摘要生成示例问题（best-effort；失败返回空列表）。"""
    from pydantic import BaseModel, Field

    class SampleQuestionsDraft(BaseModel):
        questions: list[str] = Field(default_factory=list)

    if not abstract or len(abstract.strip()) < 40:
        return []
    try:
        draft = model.invoke_json(
            system=SAMPLE_QUESTIONS_SYSTEM,
            user=abstract[:1200],
            schema=SampleQuestionsDraft,
            stage="sample_questions",
            thread_id="sample-questions",
        )
        questions = [q.strip() for q in (draft.questions or []) if q.strip()]
        return questions[:count]
    except Exception:  # noqa: BLE001 - placeholder is a nicety
        return []
