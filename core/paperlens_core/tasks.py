"""任务定义注册表（改进方案3 §九，V4.3-3）。

预设问题不再是"更好看的 Prompt"——服务端维护版本化任务定义：
retrieval 侧重词（并入检索查询）与 section 侧重（并入检索提示）。
结构化输出与独立核验策略随各旗舰功能（V4.4）演进。
"""

from __future__ import annotations

TASK_DEFINITIONS: dict[str, dict[str, object]] = {
    "paper.overview.v1": {
        "label": "一句话讲清楚",
        "version": "v1",
        "retrieval_emphasis": ["abstract", "introduction", "contribution", "summary"],
        "section_hints": ["Abstract", "Introduction", "Conclusion"],
        "applicable_contexts": ["whole_paper"],
    },
    "method.pipeline.v1": {
        "label": "核心思路",
        "version": "v1",
        "retrieval_emphasis": ["method", "pipeline", "architecture", "module", "overall framework"],
        "section_hints": ["Method", "Approach", "Architecture"],
        "applicable_contexts": ["whole_paper", "section"],
    },
    "method.compare.v1": {
        "label": "与现有方法对比",
        "version": "v1",
        "retrieval_emphasis": ["comparison", "related work", "baseline", "difference", "advantage"],
        "section_hints": ["Related Work", "Method", "Experiments"],
        "applicable_contexts": ["whole_paper"],
    },
    "experiment.details.v1": {
        "label": "关键细节",
        "version": "v1",
        "retrieval_emphasis": ["loss", "hyperparameter", "learning rate", "optimizer", "data augmentation", "detail"],
        "section_hints": ["Method", "Training", "Implementation", "Experiments"],
        "applicable_contexts": ["whole_paper", "section"],
    },
    "experiment.results.v1": {
        "label": "结果解读",
        "version": "v1",
        "retrieval_emphasis": ["results", "performance", "state of the art", "improvement", "table"],
        "section_hints": ["Experiments", "Results", "Evaluation"],
        "applicable_contexts": ["whole_paper", "section"],
    },
    "paper.limitations.v1": {
        "label": "局限与疑点",
        "version": "v1",
        "retrieval_emphasis": ["limitation", "failure", "future work", "drawback", "weakness"],
        "section_hints": ["Limitations", "Discussion", "Conclusion", "Future Work"],
        "applicable_contexts": ["whole_paper", "section"],
    },
    "paper.argument.v1": {
        "label": "论证质量",
        "version": "v1",
        "retrieval_emphasis": ["evaluation", "ablation", "validity", "claim", "evidence", "comparison"],
        "section_hints": ["Method", "Experiments", "Ablation"],
        "applicable_contexts": ["whole_paper", "section"],
    },
}


def get_task(task_id: str) -> dict[str, object] | None:
    return TASK_DEFINITIONS.get(task_id)
