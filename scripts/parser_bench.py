"""Run ParserBench against an explicit local manifest (PDFs stay uncommitted)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from paperlens_core.parsing import BenchmarkDocument, ParsePipeline, run_benchmark
from paperlens_core.parsing.backends import PDFPlumberBackend, PyMuPDFBackend


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="JSON list of {path,label,expected_page_count}")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    rows = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    documents = [BenchmarkDocument.model_validate(row) for row in rows]
    report = run_benchmark(documents, ParsePipeline([PyMuPDFBackend(), PDFPlumberBackend()]))
    payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
