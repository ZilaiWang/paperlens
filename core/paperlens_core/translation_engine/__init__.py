"""Translation Engine v2 — six explicit stages (改进方案1 §七 / 改进方案2 §24).

    ContextCompiler → TermResolver → Protector → Translator → Verifier → Repairer

V1 ``translation.py`` stays as the compatibility layer used by the server;
this package is the structured successor that composes the six stages into a
real, testable engine.
"""

from .context import ContextCompiler, ContextPack
from .engine import (
    TranslationEngine,
    TranslationJobResult,
    TranslationStage,
)
from .protector import (
    ProtectedToken,
    Protector,
    restore_tokens,
)
from .repair import RepairPlanner as TranslationRepairPlanner
from .verifier import (
    DeterministicVerifier,
    VerificationIssue,
    VerifyReport,
)

__all__ = [
    "ContextCompiler",
    "ContextPack",
    "TranslationEngine",
    "TranslationJobResult",
    "TranslationStage",
    "ProtectedToken",
    "Protector",
    "restore_tokens",
    "TranslationRepairPlanner",
    "DeterministicVerifier",
    "VerificationIssue",
    "VerifyReport",
]
