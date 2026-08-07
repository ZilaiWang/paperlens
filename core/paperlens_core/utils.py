"""Small deterministic helpers used across PaperLens."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_space(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00ad", "")
    return re.sub(r"\s+", " ", text).strip()


def normalize_match_text(text: str) -> str:
    text = normalize_space(text).casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", text).strip()


def estimate_tokens(text: str) -> int:
    """Conservative language-agnostic token estimate without a tokenizer dependency."""

    latin_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", text))
    punctuation = len(re.findall(r"[^\w\s]", text))
    return max(1, latin_words + cjk_chars + punctuation // 3)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write a new/replaceable cache artifact without leaving a partial file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(path)
