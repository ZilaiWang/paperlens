# paperlens-core

`paperlens-core` is the document-understanding and evidence engine used by
[PaperLens](https://github.com/ZilaiWang/paperlens). It provides canonical
document IR, multi-backend PDF parsing, selective repair, retrieval, grounded
claims, adaptive paper-agent planning, comparison models, and translation
terminology support.

```bash
pip install -e "core[pymupdf,dev]"
```

The default package is lightweight. Docling and PaddleOCR-VL are optional:

```bash
pip install -e "core[docling]"
pip install -e "core[paddleocr-vl]"
```

See the repository [README](https://github.com/ZilaiWang/paperlens#readme) and
[architecture guide](https://github.com/ZilaiWang/paperlens/blob/main/docs/architecture.md)
for the complete application and provider configuration.
