#!/usr/bin/env python3
"""下载评测语料（改进方案3 §十六 / V4.0-7）。

评测 PDF 有版权约束不入发布包——manifest.json 记录 arXiv ID 与 SHA256，
本脚本按 manifest 下载并校验完整性：

    python scripts/fetch_eval_corpus.py [--dir tests/eval_corpus]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx

MANIFEST = Path(__file__).resolve().parents[1] / "tests/eval_corpus" / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(MANIFEST.parent), help="语料目录")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    target = Path(args.dir)
    target.mkdir(parents=True, exist_ok=True)
    ok = 0
    with httpx.Client(
        timeout=120, follow_redirects=True,
        headers={"User-Agent": "PaperLens-eval-corpus/4.0 (mailto:paperlens@example.invalid)"},
    ) as client:
        for entry in manifest["papers"]:
            path = target / entry["file"]
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]:
                print(f"  skip {entry['file']} (already valid)")
                ok += 1
                continue
            print(f"  fetch {entry['arxiv_id']} ...")
            response = client.get(entry["source"])
            response.raise_for_status()
            sha = hashlib.sha256(response.content).hexdigest()
            if sha != entry["sha256"]:
                print(f"  ✗ SHA256 mismatch for {entry['file']} (got {sha[:16]}...)")
                continue
            path.write_bytes(response.content)
            ok += 1
    print(f"✅ {ok}/{len(manifest['papers'])} 篇就绪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
