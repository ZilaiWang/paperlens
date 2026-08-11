"""Bundled v1 term-pack catalog.

The catalog is deliberately small and reviewable.  It establishes the pack
contract used by a future standalone ``paperlens-termbases`` repository
without coupling the reader to a terminology SaaS.
"""

from __future__ import annotations

from .models import TermEntry, TermPack, TermPackManifest, TermPolicy, TermScope


def _pack(pack_id: str, name: str, domain: str, description: str, rows: list[tuple[str, str]]) -> TermPack:
    terms = [
        TermEntry(
            source=source,
            target=target,
            domain=domain,
            scope=TermScope.DOMAIN,
            policy=TermPolicy.TRANSLATE,
            confidence=0.96,
        )
        for source, target in rows
    ]
    return TermPack(
        manifest=TermPackManifest(
            pack_id=pack_id,
            name=name,
            domain=domain,
            description=description,
            recommended=True,
            term_count=len(terms),
        ),
        terms=terms,
    )


_PACKS = [
    _pack("machine-learning-zh", "机器学习", "machine_learning", "训练、评测与优化的通用译法。", [
        ("fine-tuning", "微调"), ("few-shot", "少样本"), ("ground truth", "真值"),
        ("learning rate", "学习率"), ("loss function", "损失函数"),
        ("overfitting", "过拟合"), ("validation set", "验证集"), ("ablation study", "消融实验"),
    ]),
    _pack("computer-vision-zh", "计算机视觉", "computer_vision", "检测、分割与视觉表征术语。", [
        ("backbone", "骨干网络"), ("feature extractor", "特征提取器"),
        ("object detection", "目标检测"), ("region proposal", "候选区域"),
        ("semantic segmentation", "语义分割"), ("instance segmentation", "实例分割"),
        ("intersection over union", "交并比"), ("non-maximum suppression", "非极大值抑制"),
    ]),
    _pack("natural-language-processing-zh", "自然语言处理", "nlp", "语言模型、生成与检索术语。", [
        ("language model", "语言模型"), ("tokenization", "分词"),
        ("retrieval-augmented generation", "检索增强生成"), ("in-context learning", "上下文学习"),
        ("chain of thought", "思维链"), ("named entity recognition", "命名实体识别"),
        ("machine translation", "机器翻译"), ("hallucination", "幻觉"),
    ]),
    _pack("remote-sensing-zh", "遥感", "remote_sensing", "遥感影像、传感器与地学任务术语。", [
        ("remote sensing", "遥感"), ("multispectral image", "多光谱影像"),
        ("hyperspectral image", "高光谱影像"), ("spatial resolution", "空间分辨率"),
        ("change detection", "变化检测"), ("land cover", "土地覆盖"),
        ("synthetic aperture radar", "合成孔径雷达"), ("orthorectification", "正射校正"),
    ]),
]


class TermPackCatalog:
    def __init__(self, packs: list[TermPack] | None = None) -> None:
        self._packs = {pack.manifest.pack_id: pack for pack in (packs or _PACKS)}

    def list(self) -> list[TermPackManifest]:
        return [pack.manifest for pack in self._packs.values()]

    def get(self, pack_id: str) -> TermPack | None:
        return self._packs.get(pack_id)

    def entries(self, pack_ids: list[str]) -> list[TermEntry]:
        entries: list[TermEntry] = []
        for pack_id in pack_ids:
            pack = self.get(pack_id)
            if pack:
                entries.extend(entry.model_copy(deep=True) for entry in pack.terms)
        return entries
