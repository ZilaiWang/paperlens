# Third-party notices

PaperLens source code is licensed under MIT, but its dependencies and imported
documents retain their own licenses. The dependency metadata and upstream
license texts are authoritative; this file highlights a material optional
boundary and is not legal advice.

## PyMuPDF / MuPDF

PyMuPDF is an **optional** parser backend. Upstream describes PyMuPDF and MuPDF
as dual-licensed under GNU AGPL v3 and a commercial Artifex license. The default
PaperLens installation does not install PyMuPDF; `ParseRouter` falls back to
pdfplumber. Install the `pymupdf` extra only after deciding how you will comply
with the applicable upstream license.

- [PyMuPDF repository and licensing summary](https://github.com/pymupdf/PyMuPDF)
- [PyMuPDF documentation](https://pymupdf.readthedocs.io/)
- [GNU AGPL v3](https://www.gnu.org/licenses/agpl-3.0.html)

## Other dependencies

Python and JavaScript packages installed from `core/pyproject.toml` and
`web/package.json` are not relicensed by PaperLens. Preserve their notices and
review their licenses for binary redistribution, hosted services, or commercial
products.

## Papers and metadata

PaperLens does not grant rights to papers, figures, tables, or metadata imported
through uploads, arXiv, or scholarly services. Users and operators are
responsible for access, processing, display, retention, and redistribution under
the source material's terms.
