"""Reference chain tests (改进方案2.md §11.5).

Covers citation number range expansion, arXiv HTML bibliography extraction,
bibliography exclusion from body blocks, callout binding, and the online
identity resolve endpoint (with a stubbed ScholarlyClient — no network).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from paperlens_core.arxiv_html import parse_arxiv_html, parse_bibliography
from paperlens_core.assets import (
    expand_citation_numbers,
    extract_callouts_html,
)
from paperlens_core.models import Block, BlockType, ReferenceIdentity

LATEXML_HTML = """<!DOCTYPE html>
<html>
<head><title>Frozen Backbones</title></head>
<body>
<header class="ltx_title">Frozen Backbones and Few-Shot Detection</header>
<section class="ltx_section" id="S1">
  <h2 class="ltx_title">1&nbsp;Introduction</h2>
  <div class="ltx_para"><p>We freeze the backbone in stage one [1]. Recent work improves this [2-3] and also [1, 3].</p></div>
</section>
<section class="ltx_section" id="S2">
  <h2 class="ltx_title">2&nbsp;Method</h2>
  <div class="ltx_para"><p>Our model reuses region proposals <cite class="ltx_cite">[2]</cite>.</p></div>
</section>
<section class="ltx_section ltx_bibliography" id="S3">
  <h2 class="ltx_title">References</h2>
  <ul class="ltx_biblist">
    <li class="ltx_bibitem" id="bib.bib1"><a id="CITEbib1"></a>1 W. Zhang. "Frozen Backbones for Detection." arXiv preprint arXiv:2411.00001, 2024.</li>
    <li class="ltx_bibitem" id="bib.bib2"><a id="CITEbib2"></a>2 J. Doe and A. Smith. "Few-shot Object Detection Revisited." In CVPR, 2023.</li>
    <li class="ltx_bibitem" id="bib.bib3"><a id="CITEbib3"></a>3 M. Wang et al. "Region Proposals Are Enough." arXiv preprint arXiv:2202.00002, 2022.</li>
  </ul>
</section>
</body>
</html>
"""


class TestCitationNumbers:
    def test_single(self) -> None:
        assert expand_citation_numbers("3") == [3]

    def test_list(self) -> None:
        assert expand_citation_numbers("3,5,8") == [3, 5, 8]

    def test_range_expands_to_all_members(self) -> None:
        # 改进方案2.md §11.3: [3-5] -> 3,4,5 (not just the two endpoints)
        assert expand_citation_numbers("3-5") == [3, 4, 5]

    def test_mixed_range_and_list(self) -> None:
        assert expand_citation_numbers("3-5, 8") == [3, 4, 5, 8]

    def test_descending_range_dropped(self) -> None:
        assert expand_citation_numbers("5-3") == []

    def test_noise_dropped(self) -> None:
        assert expand_citation_numbers("3, x, 7") == [3, 7]


class TestBibliographyHtml:
    def test_parse_bibliography_extracts_entries(self) -> None:
        refs = parse_bibliography(LATEXML_HTML, version_id="ver-abc1234567")
        assert len(refs) == 3
        # app-wide id convention: ref-{version_id[:10]}-{n} (matches callouts)
        assert refs[0]["reference_id"] == "ref-ver-abc123-1"
        assert refs[1]["reference_id"] == "ref-ver-abc123-2"
        assert refs[0]["sequence_number"] == 1
        assert refs[0]["year"] == 2024
        assert "Frozen Backbones" in refs[0]["parsed_title"]
        assert refs[0]["authors"] == ["W. Zhang"]

    def test_parse_bibliography_dom_blocks(self) -> None:
        # LaTeXML emits one ltx_bibblock per semantic field; authors, title
        # and venue must separate, and a folded "title, 2001." stays a title
        html = """
        <html><body><ul class="ltx_biblist">
          <li class="ltx_bibitem"><a id="CITEbib1"></a>
            <span class="ltx_tag ltx_role_refnum ltx_tag_bibitem">[1]</span>
            <span class="ltx_bibblock">Sepp Hochreiter, Yoshua Bengio, Paolo Frasconi, and
              Jürgen Schmidhuber.</span>
            <span class="ltx_bibblock">Gradient flow in recurrent nets: the difficulty of
              learning long-term dependencies, 2001.</span>
          </li>
          <li class="ltx_bibitem"><a id="CITEbib2"></a>
            <span class="ltx_tag ltx_role_refnum ltx_tag_bibitem">[2]</span>
            <span class="ltx_bibblock">Denny Britz, Anna Goldie, and Quoc V. Le.</span>
            <span class="ltx_bibblock">Massive exploration of neural machine translation architectures.</span>
            <span class="ltx_bibblock">CoRR, abs/1703.03906, 2017.</span>
          </li>
        </ul></body></html>
        """
        refs = parse_bibliography(html, version_id="ver-abc1234567")
        assert len(refs) == 2
        first, second = refs
        assert first["parsed_title"] == (
            "Gradient flow in recurrent nets: the difficulty of learning long-term dependencies"
        )
        assert first["authors"] == ["Sepp Hochreiter", "Yoshua Bengio", "Paolo Frasconi", "Jürgen Schmidhuber"]
        assert first["year"] == 2001
        assert second["parsed_title"] == "Massive exploration of neural machine translation architectures."
        assert second["authors"] == ["Denny Britz", "Anna Goldie", "Quoc V. Le"]
        assert second["venue"].startswith("CoRR")

    def test_bibliography_excluded_from_body_blocks(self) -> None:
        # the ltx_bibliography section must not pollute the reading view
        blocks = parse_arxiv_html(LATEXML_HTML, arxiv_id="9999.99999")
        texts = " ".join(block.text for block in blocks)
        assert "Frozen Backbones for Detection" not in texts
        assert "Few-shot Object Detection Revisited" not in texts

    def test_blocks_keep_sections_and_native_citations(self) -> None:
        blocks = parse_arxiv_html(LATEXML_HTML, arxiv_id="9999.99999")
        headings = [
            block.text for block in blocks if block.metadata.get("html_role") == "HEADING"
        ]
        assert "1 Introduction" in headings
        assert "2 Method" in headings
        body = next(block.text for block in blocks if "freeze the backbone" in block.text)
        assert "[1]" in body  # citation numbers survive natively (V3.1 commit)


class TestCalloutsHtml:
    def test_callouts_bind_to_references_with_version_prefix(self) -> None:
        blocks = parse_arxiv_html(LATEXML_HTML, arxiv_id="9999.99999")
        refs = parse_bibliography(LATEXML_HTML, version_id="ver-abc1234567")
        callouts = extract_callouts_html("ver-abc1234567", blocks, len(refs))
        raws = sorted(callout.raw for callout in callouts)
        assert raws == ["[1, 3]", "[1]", "[2-3]", "[2]"]
        by_raw = {callout.raw: callout for callout in callouts}
        assert by_raw["[1]"].reference_id == "ref-ver-abc123-1"
        # a range binds to the group's first member and stays within the list
        assert by_raw["[2-3]"].reference_id == "ref-ver-abc123-2"
        assert by_raw["[1, 3]"].reference_id == "ref-ver-abc123-1"

    def test_callouts_skip_out_of_range_numbers(self) -> None:
        blocks = [
            Block(
                block_id="blk-0",
                paper_id="p",
                paper_version_id="v",
                page=1,
                block_index=0,
                bbox=(0.0, 0.0, 0.0, 0.0),
                block_type=BlockType.TEXT,
                content_sha256="sha",
                text="cites [99] but only [1] is real",
            )
        ]
        callouts = extract_callouts_html("ver-abc1234567", blocks, reference_count=2)
        assert [c.raw for c in callouts] == ["[1]"]

    def test_ids_are_unique_across_repeated_markers(self) -> None:
        blocks = [
            Block(
                block_id=f"blk-{i}",
                paper_id="p",
                paper_version_id="v",
                page=1,
                block_index=i,
                bbox=(0.0, 0.0, 0.0, 0.0),
                block_type=BlockType.TEXT,
                content_sha256="sha",
                text="same marker [1] in two places",
            )
            for i in range(2)
        ]
        callouts = extract_callouts_html("ver-abc1234567", blocks, reference_count=5)
        assert len({callout.callout_id for callout in callouts}) == 2


class TestResolveWaterfall:
    def test_arxiv_id_in_raw_text_takes_exact_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # §11.4: arXiv preprints are absent from Crossref (DataCite DOIs), so an
        # arXiv id inside the raw text must hit the exact arXiv path and VERIFY.
        from paperlens_core.models import ReferenceIdentity, ReferenceRecord
        from paperlens_core.scholarly import ScholarlyClient, ScholarlyMetadata

        reference = ReferenceRecord(
            reference_id="r1",
            raw_text=(
                "[1] Jimmy Lei Ba, Jamie Ryan Kiros, and Geoffrey E Hinton. "
                "Layer normalization. arXiv preprint arXiv:1607.06450, 2016."
            ),
            parsed_title="Layer normalization.",
            authors=["Jimmy Lei Ba", "Jamie Ryan Kiros", "Geoffrey E Hinton"],
            year=2016,
        )
        metadata = ScholarlyMetadata(
            provider="arxiv",
            identifier="1607.06450v1",
            title="Layer Normalization",
            authors=("Jimmy Lei Ba", "Jamie Ryan Kiros", "Geoffrey E Hinton"),
            year=2016,
            arxiv_id="1607.06450v1",
        )
        monkeypatch.setattr(ScholarlyClient, "lookup_arxiv", lambda self, aid: metadata)
        with ScholarlyClient(contact_email="paperlens-demo@example.com") as client:
            resolved = client.resolve_reference(reference)
        assert resolved.identity_status == ReferenceIdentity.VERIFIED
        assert resolved.arxiv_id == "1607.06450"

    def test_arxiv_core_strips_version(self) -> None:
        from paperlens_core.scholarly import _arxiv_core

        assert _arxiv_core("1607.06450v3") == "1607.06450"
        assert _arxiv_core("1607.06450") == "1607.06450"


class TestResolveEndpoint:
    @pytest.fixture(autouse=True)
    def _isolated_data_dir(self, tmp_path: Path) -> None:
        from server.app.main import app, repository

        self.app = app
        self.repository = repository
        self.data_dir = tmp_path

    def test_resolve_verifies_and_persists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperlens_core.documents import Paper, PaperVersion
        from paperlens_core.models import ReferenceRecord

        from server.app.repository import Repository

        repo = Repository(str(self.data_dir / "test.db"))
        monkeypatch.setattr("server.app.main.repository", repo)
        repo.create_paper(Paper(paper_id="p1", canonical_title="t", created_at="2026-08-03T00:00:00Z"))
        repo.create_version(
            PaperVersion(
                version_id="ver-abc1234567",
                paper_id="p1",
                version_label="v1",
                source="ARXIV",
                file_name="arxiv-9999.99999",
                file_sha256="sha",
                page_count=0,
                created_at="2026-08-03T00:00:00Z",
            )
        )
        repo.store_document(
            "ver-abc1234567",
            "references",
            [
                ReferenceRecord(
                    reference_id="ref-ver-abc123-1",
                    raw_text='W. Zhang. "Frozen Backbones for Detection." arXiv preprint arXiv:2411.00001, 2024.',
                    sequence_number=1,
                    parsed_title="Frozen Backbones for Detection",
                    authors=["W. Zhang"],
                    year=2024,
                    arxiv_id="2411.00001",
                ).model_dump(mode="json")
            ],
        )

        class FakeScholarlyClient:
            def __init__(self, **kwargs) -> None:
                self.last_errors: dict[str, str] = {}
                assert kwargs["contact_email"], "contact_email must never be empty"

            def __enter__(self) -> FakeScholarlyClient:  # noqa: PYI034
                return self

            def __exit__(self, *args) -> None:
                return None

            def resolve_reference(self, record: ReferenceRecord) -> ReferenceRecord:
                return record.model_copy(
                    update={
                        "identity_status": ReferenceIdentity.VERIFIED,
                        "doi": "10.48550/arXiv.2411.00001",
                        "record_match": "EXACT",
                        "identifier_resolution": "RESOLVES",
                    }
                )

        monkeypatch.setattr("paperlens_core.scholarly.ScholarlyClient", FakeScholarlyClient)

        from fastapi.testclient import TestClient

        response = TestClient(self.app).post("/api/references/ref-ver-abc123-1/resolve")
        assert response.status_code == 200
        payload = response.json()
        assert payload["identity_status"] == "VERIFIED"
        assert payload["doi"] == "10.48550/arXiv.2411.00001"

        # the resolved record is persisted next to the stored references
        persisted = repo.load_document("ver-abc1234567", "references")
        assert persisted[0]["identity_status"] == "VERIFIED"
        assert persisted[0]["doi"] == "10.48550/arXiv.2411.00001"

    def test_resolve_unknown_reference_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from paperlens_core.documents import Paper

        from server.app.repository import Repository

        repo = Repository(str(self.data_dir / "test.db"))
        monkeypatch.setattr("server.app.main.repository", repo)
        repo.create_paper(Paper(paper_id="p1", canonical_title="t", created_at="2026-08-03T00:00:00Z"))

        from fastapi.testclient import TestClient

        response = TestClient(self.app).post("/api/references/ref-missing-1/resolve")
        assert response.status_code == 404


class TestLintReferences:
    """V4.8（题目要求③）：风格感知格式检查器。

    数字式（IEEE [n]）与作者-年份式分别检查；公共检查覆盖
    作者/标题/年份合理性/DOI/arXiv/末尾句号。HTML 路径（raw 剥离
    序号前缀）不得误报 REF_NON_IEEE_NUMBER。
    """

    def _record(self, raw: str, *, number: int | None = None, **kw) -> "ReferenceRecord":
        from paperlens_core.models import ReferenceRecord

        return ReferenceRecord(
            reference_id=kw.pop("reference_id", f"r-{raw[:12]}"),
            raw_text=raw,
            sequence_number=number,
            **kw,
        )

    def test_clean_numeric_entry_has_no_issues(self) -> None:
        from paperlens_core.references import lint_references

        records = [
            self._record(
                "[1] John Smith. A great paper. Journal of Science, 2016.",
                number=1,
                parsed_title="A great paper.",
                authors=["John Smith"],
                year=2016,
            ),
            self._record(
                "[2] Jane Doe. Another fine article. ACM Press, 2017.",
                number=2,
                parsed_title="Another fine article.",
                authors=["Jane Doe"],
                year=2017,
            ),
        ]
        assert lint_references(records)[0].format_issues == []
        assert lint_references(records)[1].format_issues == []

    def test_plain_number_label_flagged_non_ieee(self) -> None:
        # PDF 路径：raw 保留 "1." 前缀，可见标签非 [n] 形式 → 违规
        from paperlens_core.references import lint_references

        record = self._record(
            "1. John Smith. A great paper. Journal of Science, 2016.",
            number=1,
            parsed_title="A great paper.",
            authors=["John Smith"],
            year=2016,
        )
        assert "REF_NON_IEEE_NUMBER" in lint_references([record])[0].format_issues

    def test_numberless_raw_not_flagged_non_ieee(self) -> None:
        # HTML 路径回归：parse_bibliography 有意剥离双重序号前缀，
        # raw 无前缀是正常状态，不得误报
        from paperlens_core.references import lint_references

        record = self._record(
            "W. Zhang. \"Frozen Backbones for Detection.\" "
            "arXiv preprint arXiv:2411.00001, 2024.",
            number=1,
            parsed_title="Frozen Backbones for Detection.",
            authors=["W. Zhang"],
            year=2024,
        )
        issues = lint_references([record])[0].format_issues
        assert "REF_NON_IEEE_NUMBER" not in issues

    def test_duplicate_and_non_sequential_numbers(self) -> None:
        from paperlens_core.references import lint_references

        records = [
            self._record("[1] A. One. Title one. Press, 2016.", number=1,
                         parsed_title="Title one.", authors=["A. One"], year=2016),
            self._record("[1] B. Two. Title two. Press, 2016.", number=1,
                         parsed_title="Title two.", authors=["B. Two"], year=2016),
            self._record("[4] C. Three. Title three. Press, 2016.", number=4,
                         parsed_title="Title three.", authors=["C. Three"], year=2016),
        ]
        out = lint_references(records)
        assert "REF_DUPLICATE_NUMBER" in out[1].format_issues
        assert "REF_NON_SEQUENTIAL_NUMBER" in out[2].format_issues

    def test_mixed_style_flags_all_records(self) -> None:
        from paperlens_core.references import lint_references

        records = [
            self._record("[1] John Smith. A paper. Press, 2016.", number=1,
                         parsed_title="A paper.", authors=["John Smith"], year=2016),
            self._record("Smith, John. A paper. Press, 2016.",
                         parsed_title="A paper.", authors=["John Smith"], year=2016),
        ]
        out = lint_references(records)
        assert all("REF_MIXED_STYLE" in r.format_issues for r in out)

    def test_author_year_style_skips_numeric_checks(self) -> None:
        from paperlens_core.references import lint_references

        records = [
            self._record("Smith, John. A paper. Press, 2016.",
                         parsed_title="A paper.", authors=["John Smith"], year=2016),
            self._record("Doe, Jane. Another paper. Press, 2017.",
                         parsed_title="Another paper.", authors=["Jane Doe"], year=2017),
        ]
        issues = [r.format_issues for r in lint_references(records)]
        assert all("REF_MISSING_NUMBER" not in i for i in issues)

    def test_implausible_year_flagged(self) -> None:
        from paperlens_core.references import lint_references

        record = self._record(
            "[1] John Smith. A paper. Press, 9999.", number=1,
            parsed_title="A paper.", authors=["John Smith"], year=9999,
        )
        issues = lint_references([record])[0].format_issues
        assert any(i.startswith("REF_IMPLAUSIBLE_YEAR") for i in issues)

    def test_title_too_short_flagged(self) -> None:
        from paperlens_core.references import lint_references

        record = self._record(
            "[1] John Smith. A paper. Press, 2016.", number=1,
            parsed_title="A.", authors=["John Smith"], year=2016,
        )
        assert "REF_TITLE_TOO_SHORT" in lint_references([record])[0].format_issues

    def test_missing_final_period_flagged(self) -> None:
        from paperlens_core.references import lint_references

        record = self._record(
            "[1] John Smith. A paper. Press, 2016", number=1,
            parsed_title="A paper.", authors=["John Smith"], year=2016,
        )
        assert "REF_MISSING_FINAL_PERIOD" in lint_references([record])[0].format_issues

    def test_html_bibliography_entries_lint_clean(self) -> None:
        # 题目要求③ 端到端：HTML 路径经 lint 后无格式问题，
        # 且 arXiv 编号被提取（此前会误报 REF_NON_IEEE_NUMBER /
        # REF_BAD_ARXIV_ID）
        refs = parse_bibliography(LATEXML_HTML, version_id="ver-abc1234567")
        assert all(r["format_issues"] == [] for r in refs)
        assert refs[0]["arxiv_id"] == "2411.00001"
        assert refs[2]["arxiv_id"] == "2202.00002"


class TestReferenceParsingFixes:
    """2026-08-05 解析修复：年份误抓 arXiv 编号、长作者列表标题、et al.。"""

    def _entry(self, raw: str) -> "ReferenceRecord":
        from paperlens_core.references import parse_reference_entry

        return parse_reference_entry(raw, fallback_index=1)

    def test_year_not_stolen_from_arxiv_id(self) -> None:
        # "arXiv:1904.04232" 的 1904 不得当年份；DOI 里的 4 位数字同理
        r = self._entry(
            "Chen, W.-Y. A closer look at few-shot classification. "
            "preprint arXiv:1904.04232, 2019."
        )
        assert r.year == 2019
        assert r.arxiv_id == "1904.04232"

    def test_year_not_stolen_from_doi(self) -> None:
        r = self._entry(
            "[1] Jane Doe. A paper. doi:10.48550/arXiv.2411.00001, 2024."
        )
        assert r.year == 2024

    def test_title_after_and_author_list(self) -> None:
        r = self._entry(
            "J. Redmon, S. Divvala, R. Girshick, and A. Farhadi. "
            "You only look once: unified, real-time object detection. CVPR, 2016."
        )
        assert r.parsed_title == "You only look once: unified, real-time object detection"
        assert r.authors[:2] == ["J. Redmon", "S. Divvala"]

    def test_title_after_long_comma_authors(self) -> None:
        # wang2020 真实形态：姓, 名缩写 长列表
        r = self._entry(
            "Chen, W.-Y., Liu, Y.-C., Kira, Z., Wang, Y.-C. F., and Huang, J.-B. "
            "A closer look at few-shot classification. preprint arXiv:1904.04232, 2019."
        )
        assert r.parsed_title == "A closer look at few-shot classification"
        assert r.year == 2019

    def test_title_after_et_al(self) -> None:
        r = self._entry(
            "M. Wang et al. Region Proposals Are Enough. "
            "arXiv preprint arXiv:2202.00002, 2022."
        )
        assert r.parsed_title == "Region Proposals Are Enough"
        assert "arXiv" not in r.parsed_title

    def test_venue_not_swallowed_into_authors(self) -> None:
        # 无逗号条目：作者段截止于标题开始处
        r = self._entry(
            "M. Wang et al. Region Proposals Are Enough. "
            "arXiv preprint arXiv:2202.00002, 2022."
        )
        assert r.authors == ["M. Wang et al"]

    def test_plain_author_title_format(self) -> None:
        r = self._entry("John Smith. A great paper. Journal of Science, 2016.")
        assert r.parsed_title == "A great paper"
        assert r.authors == ["John Smith"]
