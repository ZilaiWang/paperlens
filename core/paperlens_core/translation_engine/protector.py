"""Token Protector: shield citations, formulas, numbers, placeholders.

The protected tokens are extracted from the source before translation and
restored after; the verifier then checks none was lost (改进方案2 §24 [2][4]).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict


class ProtectedToken(BaseModel):
    model_config = ConfigDict(extra="allow")

    token: str          # the replacement placeholder
    original: str
    kind: str           # citation | formula | number | placeholder
    index: int


_CITATION_RE = re.compile(r"\[[\d,\s\-]+\]")
_FORMULA_RE = re.compile(r"\$[^$\n]+\$|\\\([^)]*\\\)")
_NUMBER_RE = re.compile(r"(?<![\w])(\d+(?:\.\d+)?)(?![\w])")


class Protector:
    """Extract and restore protected tokens in a deterministic order."""

    def __init__(self):
        self._tokens: list[ProtectedToken] = []

    def protect(self, text: str, *, protect_numbers: bool = True) -> tuple[str, list[ProtectedToken]]:
        self._tokens = []
        def replace(pattern: re.Pattern[str], kind: str) -> str:
            def _sub(match: re.Match[str]) -> str:
                original = match.group(0)
                index = len(self._tokens)
                token = f"\u200b{{{{P{index}}}}}\u200b"
                self._tokens.append(
                    ProtectedToken(token=token, original=original, kind=kind, index=index)
                )
                return token
            return pattern.sub(_sub, text)

        text = replace(_CITATION_RE, "citation")
        text = replace(_FORMULA_RE, "formula")
        if protect_numbers:
            text = replace(_NUMBER_RE, "number")
        return text, list(self._tokens)

    def all_tokens(self) -> list[ProtectedToken]:
        return list(self._tokens)


_PLACEHOLDER_RE = re.compile(r"\u200b?\{\{P(\d+)\}\}\u200b?")


def restore_tokens(text: str, tokens: list[ProtectedToken]) -> str:
    """Replace placeholders back with originals.

    Handles both the exact zero-width-spaced token the Protector produced and
    the "degraded" form the model may emit after it strips zero-width spaces
    (``{{P0}}`` without ``\u200b``).  Both are restored deterministically.
    """
    result = text
    # 1) exact restore (fast path)
    for token in sorted(tokens, key=lambda t: -len(t.token)):
        result = result.replace(token.token, token.original)
    # 2) degraded restore: bare {{P<n>}} left behind by the model
    if "{{P" in result:
        token_by_index = {token.index: token for token in tokens}

        def _sub(match: re.Match[str]) -> str:
            index = int(match.group(1))
            token = token_by_index.get(index)
            return token.original if token else match.group(0)

        result = _PLACEHOLDER_RE.sub(_sub, result)
    return result
