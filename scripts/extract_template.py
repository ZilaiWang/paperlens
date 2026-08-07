#!/usr/bin/env python3
"""Measure a layout fingerprint from a known-template PDF and add it to the
registry. Run once per template (CVPR/ICCV/ECCV/NeurIPS/ICML/PMLR/AAAI/arXiv...)
with a representative sample paper of that template.

Usage:
    python scripts/extract_template.py --pdf path/to/sample.pdf --name cvpr
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from paperlens_core.parser import parse_pdf_bytes
from paperlens_core.templates import (
    extract_fingerprint,
    load_registry,
    save_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="sample paper PDF of the template")
    parser.add_argument("--name", required=True, help="template name, e.g. cvpr")
    parser.add_argument("--print-only", action="store_true", help="print the fingerprint without saving")
    args = parser.parse_args()

    raw = Path(args.pdf).read_bytes()
    parsed = parse_pdf_bytes(raw, args.pdf)
    metadata = next(
        (block.metadata for block in parsed.blocks if block.metadata.get("page_width")), {}
    )
    fingerprint = extract_fingerprint(
        parsed.blocks,
        page_width=float(metadata.get("page_width", 612.0)),
        page_height=float(metadata.get("page_height", 792.0)),
    )
    fingerprint.name = args.name

    import json

    print(json.dumps(fingerprint.to_json(), ensure_ascii=False, indent=2))
    if args.print_only:
        return 0
    registry = load_registry()
    registry[args.name] = fingerprint
    save_registry(registry)
    print(f"registered template '{args.name}' (registry now: {sorted(registry)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
