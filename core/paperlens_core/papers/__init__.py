"""Paper Intelligence: PaperProfile (改进方案1 §二十三-二十四 / 改进方案2 Phase E).

A PaperProfile is the structured digest used by Comparison v2 and Research:

    Problem (研究问题/动机/难点)
    Method (方法模块/设计选择)
    Experiment (实验设计/关键结果/失败/限制)
"""

from .models import (
    ExperimentRecord,
    ExperimentResult,
    MethodBlock,
    PaperProfile,
    ProblemStatement,
)
from .profile_builder import PaperProfileBuilder

__all__ = [
    "ExperimentRecord",
    "ExperimentResult",
    "MethodBlock",
    "PaperProfile",
    "ProblemStatement",
    "PaperProfileBuilder",
]
