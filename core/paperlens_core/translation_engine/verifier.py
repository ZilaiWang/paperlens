"""Deterministic + semantic verification of a translation (改进方案2 §24 [4][5]).

Stage [4] is deterministic: citation, formula, figure/table ref, numbers and
placeholders must survive.  Stage [5] is semantic (omission / added meaning /
negation / comparison / terminology) and is delegated to the model; the
verifier's job is to *drive* it and normalize the output.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .protector import ProtectedToken, restore_tokens


class SemanticIssue(BaseModel):
    kind: str = ""
    detail: str = ""
    severity: str = "WARNING"


class SemanticReview(BaseModel):
    issues: list[SemanticIssue] = Field(default_factory=list)


class VerificationIssue(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str          # CITATION_LOST | FORMULA_LOST | NUMBER_LOST | PLACEHOLDER_LOST | SEMANTIC
    detail: str = ""
    severity: str = "WARNING"  # WARNING | ERROR


class VerifyReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    passed: bool = True
    issues: list[VerificationIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[VerificationIssue]:
        return [i for i in self.issues if i.severity == "ERROR"]


class DeterministicVerifier:
    """Check that protected tokens survived the round-trip."""

    def __init__(self, *, strict_numbers: bool = True):
        self.strict_numbers = strict_numbers

    def verify(
        self,
        source: str,
        target: str,
        tokens: list[ProtectedToken],
    ) -> VerifyReport:
        issues: list[VerificationIssue] = []
        restored = restore_tokens(target, tokens)

        for token in tokens:
            present = token.token in target or token.original in target or token.original in restored
            if not present:
                kind_map = {
                    "citation": "CITATION_LOST",
                    "formula": "FORMULA_LOST",
                    "number": "NUMBER_LOST",
                    "placeholder": "PLACEHOLDER_LOST",
                }
                issues.append(
                    VerificationIssue(
                        kind=kind_map.get(token.kind, "PLACEHOLDER_LOST"),
                        detail=f"{token.kind} 原文未在译文中出现: {token.original[:40]}",
                        severity="ERROR",
                    )
                )

        return VerifyReport(passed=not issues, issues=issues)


def semantic_verify(
    source: str,
    target: str,
    *,
    model: object,
    stage: str,
    thread_id: str,
) -> VerifyReport:
    """Drive the model to review semantic fidelity (omission/negation/terms)."""
    result = model.invoke_json(
        system=(
            "You review an English→Chinese scientific translation. "
            "Check ONLY: omission, added meaning, negation flip, comparison "
            "flip, and terminology drift vs the glossary. Return JSON with "
            "issues[].  Empty issues means the translation is faithful."
        ),
        user=f"SOURCE:\n{source}\n\nTARGET:\n{target}\n",
        schema=SemanticReview,
        stage=stage,
        thread_id=thread_id,
    )
    issues = [
        VerificationIssue(
            kind="SEMANTIC",
            detail=item.detail,
            severity="ERROR" if item.severity == "ERROR" else "WARNING",
        )
        for item in result.issues
    ]
    return VerifyReport(passed=not [i for i in issues if i.severity == "ERROR"], issues=issues)
