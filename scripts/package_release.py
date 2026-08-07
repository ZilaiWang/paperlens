#!/usr/bin/env python3
"""PaperLens 发布包守卫（改进方案3 §一 / V4.0-1）。

生成提交给外部评审/讨论的压缩包前运行本脚本：
1. rsync 过滤暂存（排除 .env、依赖、缓存、数据库、版权 PDF）；
2. 对暂存目录做违规检查（真实 .env、API key 特征、缓存、依赖、PDF），
   发现任何一项立即中止；
3. 通过后打包 zip 到上一级目录（含设计文档）。

用法：
    python scripts/package_release.py            # 暂存 → 检查 → 打包
    python scripts/package_release.py --check    # 只做暂存+检查，不打包
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
PACKAGE_NAME = "PaperLens-GPT讨论3"

# rsync 排除规则（锚定根目录；docs/DEPLOY.md 的规范命令为基准）
EXCLUDES = [
    ".env",                 # 真实密钥（只允许 .env.example）
    ".git",
    ".venv",
    ".paperlens",           # 本地数据库 + 上传 PDF
    "data",                 # 生产/开发数据库
    "node_modules",
    ".next",
    "tsconfig.tsbuildinfo",   # tsc 增量缓存
    "__pycache__",
    "*.pyc",
    "*.log",
    ".pytest_cache",
    ".ruff_cache",
    "tests/eval_corpus/*.pdf",  # 版权 PDF（manifest 提供 ID 与下载脚本）
    "tests/results",            # 本地评测产物
]

# 禁止出现在包里的目录/文件（对暂存目录检查）
FORBIDDEN_DIRS = {
    ".git", ".venv", ".paperlens", "data", "node_modules", ".next",
    "__pycache__", ".pytest_cache", ".ruff_cache",
}
FORBIDDEN_FILES = {".env"}
KEY_PATTERNS = [
    re.compile(r"(?i)^\s*(OPENAI_API_KEY|DEEPSEEK_API_KEY|API_KEY)\s*=\s*\S+"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})\b"),
]


def check_stage(stage: Path) -> list[str]:
    """对暂存目录检查违规项；返回违规列表（空 = 通过）。"""
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
    stage = ROOT.parent / "_package_stage" / PACKAGE_NAME
    if stage.exists():
        shutil.rmtree(stage.parent)
    stage.mkdir(parents=True)
    cmd = ["rsync", "-az"] + [f"--exclude={item}" for item in EXCLUDES] + [
        f"{ROOT}/", f"{stage}/"
    ]
    subprocess.run(cmd, check=True)
    for doc in ("改进方案1.md", "改进方案2.md", "改进方案3.md"):
        src = ROOT.parent / doc
        if src.exists():
            shutil.copy2(src, stage / doc)
    return stage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只做暂存+检查，不打包")
    args = parser.parse_args()

    stage = build_stage()
    violations = check_stage(stage)
    if violations:
        print("❌ 暂存包存在违规项，已中止：")
        for item in violations:
            print(f"   - {item}")
        return 1
    print(f"✅ 检查通过：暂存 {stage} 无 .env / 密钥 / 依赖 / 缓存 / 数据库 / PDF。")

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
    print(f"📦 已生成 {target}（{target.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
