"""Parser v2 真实 PDF 集成测试（改进方案1 §三-五 / 改进方案2 Phase C）。

使用测试临时目录生成结构有效的 PDF，绝不读取用户 `.paperlens/uploads`。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

try:
    import fitz  # noqa: F401
    HAS_PYMUPDF = True
except ImportError:  # pragma: no cover
    HAS_PYMUPDF = False


@pytest.mark.skipif(not HAS_PYMUPDF, reason="PyMuPDF not installed")
class TestParserV2OnRealPdf:
    @pytest.fixture
    def pdf_path(self, tmp_path: Path) -> Path:
        import fitz

        path = tmp_path / "integration.pdf"
        document = fitz.open()
        for page_number in range(2):
            page = document.new_page()
            page.insert_text(
                (72, 90),
                f"Section {page_number + 1}\nA complete research paragraph with metric 73.2.",
            )
        document.save(path)
        document.close()
        return path

    def test_full_pipeline_on_real_pdf(self, pdf_path: Path) -> None:
        from paperlens_core.parsing.backends import PyMuPDFBackend
        from paperlens_core.parsing.pipeline import ParsePipeline

        raw = pdf_path.read_bytes()
        pipeline = ParsePipeline([PyMuPDFBackend()])
        result = pipeline.run(
            document_path=str(pdf_path),
            raw_bytes=raw,
            source_version_id="ver-real-1",
        )
        # probe 应报告真实页数（>=1）且管线产出节点
        assert result.probe.page_count >= 1
        assert len(result.document.nodes) > 0
        # 每个节点都带 provenance 与稳定 node_id/revision_id
        first = result.document.nodes[0]
        assert first.node_id.startswith("n-")
        assert first.revision_id.startswith("r-")
        assert first.provenance
        assert first.parse_run_ids

    def test_benchmark_on_real_pdf(self, pdf_path: Path) -> None:
        from paperlens_core.parsing.backends import PyMuPDFBackend
        from paperlens_core.parsing.benchmark import (
            BenchmarkDocument,
            run_benchmark,
        )
        from paperlens_core.parsing.pipeline import ParsePipeline

        pipeline = ParsePipeline([PyMuPDFBackend()])
        report = run_benchmark(
            [BenchmarkDocument(path=str(pdf_path), label="real")],
            pipeline,
        )
        assert report.documents
        entry = report.documents[0]
        assert entry.node_count > 0
        assert entry.duration_ms >= 0
        assert "aggregate" in report.model_dump(mode="json")
