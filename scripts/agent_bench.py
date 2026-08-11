"""Run the deterministic Paper Agent routing benchmark."""

from __future__ import annotations

import json

from paperlens_core.agents.benchmark import AgentBenchCase, run_agent_bench
from paperlens_core.agents.models import AnalysisDepth

CASES = [
    AgentBenchCase(question="作者使用了什么数据集？", expected_depth=AnalysisDepth.QUICK),
    AgentBenchCase(question="请梳理这篇论文的方法结构。", expected_depth=AnalysisDepth.ANALYTIC, expected_intent="METHOD"),
    AgentBenchCase(question="如果要完整复现，还缺少哪些环境和超参数？", expected_depth=AnalysisDepth.DEEP, expected_intent="REPRODUCTION"),
    AgentBenchCase(question="实验是否充分支持结论？", expected_depth=AnalysisDepth.ANALYTIC, expected_intent="EXPERIMENT"),
]


def main() -> None:
    print(json.dumps(run_agent_bench(CASES).model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
