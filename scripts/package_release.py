#!/usr/bin/env python3
"""Build a source archive after checking for local or sensitive data.

The script copies the repository into an isolated staging directory, excludes
development/runtime data, checks the staged tree, and creates a zip next to the
repository. It never modifies the source tree.

Usage:
    python scripts/package_release.py
    python scripts/package_release.py --check
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "paperlens-source"

EXCLUDES = [
    ".env",
    ".git",
    ".venv",
    ".paperlens",
    ".obsidian",
    "data",
    "node_modules",
    ".next",
    "tsconfig.tsbuildinfo",
    "__pycache__",
    "*.pyc",
    "*.log",
    ".pytest_cache",
    ".ruff_cache",
    "tests/eval_corpus/*.pdf",
    "tests/results",
    "改进方案*.md",
]

# 禁止出现在包里的目录/文件（对暂存目录检查）
FORBIDDEN_DIRS = {
    ".git", ".venv", ".paperlens", ".obsidian", "data", "node_modules", ".next",
    "__pycache__", ".pytest_cache", ".ruff_cache",
}
FORBIDDEN_FILES = {".env"}
KEY_PATTERNS = [
    re.compile(r"(?i)^\s*(OPENAI_API_KEY|DEEPSEEK_API_KEY|API_KEY)\s*=\s*\S+"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})\b"),
]


def check_stage(stage: Path) -> list[str]:
    """Return paths that must not appear in a public source archive."""
    violations: list[str] = []

    for child in sorted(stage.rglob("*")):
        rel = child.relative_to(stage)
        if child.is_dir():
            if child.name in FORBIDDEN_DIRS:
                violations.append(str(rel) + "/")
            continue
        if child.name in FORBIDDEN_FILES:
            violations.append(str(rel))
        if child.suffix == ".pdf":
            violations.append(str(rel))
        if child.suffix in {".pyc", ".log"}:
            violations.append(str(rel))
        if child.suffix == ".py" or child.name.endswith(".example"):
            try:
                text = child.read_text(encoding="utf-8", errors="ignore")[:200000]
            except OSError:
                continue
            for pattern in KEY_PATTERNS:
                if pattern.search(text) and "example" not in child.name:
                    violations.append(f"{rel} (疑似 API Key)")
                    break
    return sorted(set(violations))


def build_stage() -> Path:
    stage = Path(tempfile.mkdtemp(prefix="paperlens-release-")) / PACKAGE_NAME
    stage.mkdir(parents=True)
    cmd = ["rsync", "-az"] + [f"--exclude={item}" for item in EXCLUDES] + [
        f"{ROOT}/", f"{stage}/"
    ]
    subprocess.run(cmd, check=True)
    return stage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check without creating a zip")
    args = parser.parse_args()

    stage = build_stage()
    violations = check_stage(stage)
    if violations:
        print("Release check failed:")
        for item in violations:
            print(f"   - {item}")
        return 1
    print(f"Release check passed: {stage}")

    if args.check:
        shutil.rmtree(stage.parent)
        return 0

    target = ROOT.parent / f"{PACKAGE_NAME}.zip"
    if target.exists():
        target.unlink()  # zip -qr 不删除已消失条目，必须重打
    subprocess.run(
        ["zip", "-qr", str(target), stage.name],
        cwd=stage.parent,
        check=True,
    )
    shutil.rmtree(stage.parent)
    print(f"Created {target} ({target.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
