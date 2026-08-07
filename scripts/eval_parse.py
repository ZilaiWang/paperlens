#!/usr/bin/env python3
"""V3.0A parse evaluation baseline (改进方案2.md §V3.0A).

Runs the current parser + paragraph rebuild over a corpus of CV papers and
reports reproducible metrics: tiny-block ratios, paragraph stats, table-row
detection, formula blocks, section detection against gold (when present).

Usage:
    python scripts/eval_parse.py --corpus /path/to/papers [--gold-dir dir]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from paperlens_core.parser import parse_pdf_bytes
from paperlens_core.paragraphs import rebuild_paragraphs, _is_table_row
from paperlens_core.sections import detect_sections, section_metrics


def tiny_ratio(texts: list[str]) -> dict[str, float]:
    total = len(texts)
    single = sum(1 for t in texts if len(t) <= 1)
    tiny = sum(1 for t in texts if len(t) <= 2)
    return {
        "blocks": total,
        "single_char": single,
        "single_char_ratio": round(single / max(total, 1), 4),
        "len_le_2": tiny,
        "len_le_2_ratio": round(tiny / max(total, 1), 4),
    }


def evaluate_pdf(path: Path, engine: str = "hybrid") -> dict[str, object]:
    raw = path.read_bytes()
    # V4.0-4：统一经 ParseRouter（生产与评测同入口），
    # --engine 仅作回归对比的显式覆盖
    if engine in ("pymupdf", "pdfplumber"):
        from paperlens_core.config import Settings

        from paperlens_core.parse_router import ParseRouter

        settings = Settings(_env_file=None)
        settings.paperlens_pdf_parser = engine
        parsed, _ = ParseRouter(settings).parse_pdf(raw, str(path))
    else:
        from paperlens_core.parse_router import parse_pdf

        parsed, _ = parse_pdf(raw, str(path))
    rebuilt = rebuild_paragraphs(parsed.blocks)
    texts = [b.text for b in rebuilt if b.block_type.value == "TEXT"]
    table_rows = [t for t in texts if _is_table_row(t)]
    formulas = [b for b in rebuilt if b.block_type.value == "FORMULA"]
    sections, _ = detect_sections("eval", rebuilt)
    result: dict[str, object] = {
        "file": path.name,
        "pages": parsed.paper.page_count,
        "raw_blocks": len(parsed.blocks),
        "rebuilt_blocks": len(rebuilt),
        "paragraphs": len(texts),
        **tiny_ratio(texts),
        "table_rows": len(table_rows),
        "formula_blocks": len(formulas),
        "sections": len(sections),
        "section_canonicals": [s.canonical_name for s in sections[:10]],
    }
    # reading-order inversion proxy: sections with start_page going backwards
    inversions = sum(
        1
        for i in range(1, len(sections))
        if sections[i].start_page < sections[i - 1].start_page
    )
    result["section_order_inversions"] = inversions
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True, help="dir of PDFs to evaluate")
    parser.add_argument("--gold-dir", default="", help="dir with gold_sections.json files")
    parser.add_argument("--output", default="tests/results/parse_eval.json")
    parser.add_argument("--engine", default="pdfplumber", choices=["pdfplumber", "pymupdf"])
    args = parser.parse_args()

    corpus = Path(args.corpus)
    pdfs = sorted(corpus.glob("*.pdf"))
    if not pdfs:
        print(f"no PDFs in {corpus}")
        return 1

    rows = [evaluate_pdf(path, args.engine) for path in pdfs]
    aggregate = {
        "papers": len(rows),
        "avg_single_char_ratio": round(
            sum(row["single_char_ratio"] for row in rows) / len(rows), 4
        ),
        "avg_len_le_2_ratio": round(
            sum(row["len_le_2_ratio"] for row in rows) / len(rows), 4
        ),
        "avg_table_rows": round(sum(row["table_rows"] for row in rows) / len(rows), 1),
        "avg_formula_blocks": round(
            sum(row["formula_blocks"] for row in rows) / len(rows), 1
        ),
        "papers_with_order_inversions": sum(
            1 for row in rows if row["section_order_inversions"] > 0
        ),
    }
    if args.engine == "pymupdf":
        args.output = args.output.replace(".json", "_pymupdf.json")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"aggregate": aggregate, "papers": rows}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    for row in rows:
        print(
            f"  {row['file'][:36]:<38} p{row['pages']:<3} 单字符={row['single_char']:>4} "
            f"({row['single_char_ratio']:.1%}) ≤2字={row['len_le_2']:>4} "
            f"表行={row['table_rows']:>3} 公式={row['formula_blocks']:>3} 章节={row['sections']:>3}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
