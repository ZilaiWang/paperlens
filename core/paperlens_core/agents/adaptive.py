"""Adaptive planning for a single Paper Agent entry point."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AnalysisDepth


@dataclass(frozen=True)
class RoutedQuestion:
    depth: AnalysisDepth
    intent: str
    reason: str


class DepthRouter:
    """Deterministic, inspectable routing before any optional model planning."""

    deep_markers = (
        "复现", "审稿", "是否可靠", "完整分析", "深入", "系统分析", "批判",
        "reproduce", "review", "reliable", "deep analysis", "failure mode",
    )
    analytic_markers = (
        "方法", "实验", "局限", "为什么", "如何", "比较", "公式", "消融",
        "method", "experiment", "limitation", "compare", "ablation", "equation",
    )

    def route(self, question: str) -> RoutedQuestion:
        normalized = " ".join(question.lower().split())
        intent = _detect_intent(normalized)
        if any(marker in normalized for marker in self.deep_markers):
            return RoutedQuestion(AnalysisDepth.DEEP, intent, "question requests verification or reproduction")
        if any(marker in normalized for marker in self.analytic_markers) or len(normalized) > 80:
            return RoutedQuestion(AnalysisDepth.ANALYTIC, intent, "question needs cross-section analysis")
        return RoutedQuestion(AnalysisDepth.QUICK, intent, "localized factual question")


def _detect_intent(question: str) -> str:
    if any(token in question for token in ("复现", "reproduce", "代码", "环境")):
        return "REPRODUCTION"
    if any(token in question for token in ("实验", "结果", "消融", "experiment", "ablation")):
        return "EXPERIMENT"
    if any(token in question for token in ("局限", "可靠", "审稿", "limitation", "review")):
        return "CRITICAL"
    if any(token in question for token in ("公式", "equation", "推导")):
        return "FORMULA"
    if any(token in question for token in ("方法", "method", "模型", "architecture")):
        return "METHOD"
    return "GENERAL"
