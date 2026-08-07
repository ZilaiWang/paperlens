# PaperLens

> 证据可追溯的学术论文阅读工作台：上传 PDF 或 arXiv 链接，获得结构化解析、双语阅读、证据定位问答、质量评估与多篇对比。

[![CI](https://github.com/ZilaiWang/paperlens/actions/workflows/ci.yml/badge.svg)](https://github.com/ZilaiWang/paperlens/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

PaperLens 把论文 PDF 当作**文档对象**处理，而不是直接丢给大模型。系统先通过确定性解析恢复论文结构（段落、章节、图表、公式、参考文献），再基于结构做检索与语言分析——回答的每条主张都能跳回原文精确位置。

## 核心特性

| 特性 | 说明 |
|---|---|
| **双路径解析** | PyMuPDF span 级几何提取 + pdfplumber 兜底，页级质量门双引擎融合；arXiv LaTeXML HTML Source-first（老论文自动回退 PDF） |
| **文档原生阅读** | 三栏工作台：资源轨（目录/图/表/参考文献）、沉浸式双语正文、Agent 问答面板 |
| **章节与媒体** | 章节识别（字号/加粗候选 + 上下文继承）；表格掩膜 + 占位块；公式 KaTeX 渲染 |
| **渐进式翻译** | 术语表一致性（漂移检测选择性修复）、公式/引用占位保护、批次并发、逐批持久化 |
| **证据问答** | 自研 BM25 段落级检索 → 原子主张 → 确定性证据门 + 逐主张语义核验 → 证据账本定位跳转 |
| **质量评估** | 独立子 Agent 按 7 维度打分，正分必须附证据 ID，总分程序计算 |
| **多篇比较** | 主题对齐 → 13 维度字段抽取（默认 5 核心）→ 结构化结果对比，多篇并发 |
| **参考文献链路** | 自动提取 → 风格感知格式检查（13 种问题）→ Crossref/arXiv 在线核验 → 一键导入 |

## 架构

```text
core/     evidence kernel（paperlens_core）
  ├── documents.py     DocumentIR 实体（Block/Section/Asset/TranslationUnit/...）
  ├── paragraphs.py     双栏感知段落重建
  ├── sections.py       章节识别
  ├── retrieval.py      BM25 段落级索引
  ├── reader.py         证据问答主工作流（检索→主张→核验→组织）
  ├── translation.py    渐进式翻译
  ├── quality.py        质量评估子 Agent
  ├── comparison.py     多篇比较
  └── references.py     参考文献提取/格式检查/核验
server/   FastAPI 后端（上传/arXiv 导入/Job+SSE/文档/翻译/问答/质量/比较/引用）
web/      Next.js 16 前端（首页 + 三栏工作台 + PDF.js 原版模式）
scripts/  评测与工具脚本
docs/     部署、里程碑、nginx/systemd 配置
```

## 快速开始

### 后端

```bash
python3 -m venv .venv
.venv/bin/pip install -e core fastapi "uvicorn[standard]" python-multipart
cp .env.example .env    # 配置 OpenAI 兼容端点（DeepSeek / Ollama 等）
.venv/bin/uvicorn server.app.main:app --port 8700
```

### 前端（需要 bun）

```bash
cd web
bun install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8700 bun run dev
```

打开 http://127.0.0.1:3000 上传 PDF 或粘贴 arXiv 链接即可。

### 测试

```bash
.venv/bin/python -m pytest tests/ -q     # 72 项离线测试（无网络/LLM 依赖）
.venv/bin/python scripts/eval_parse.py --corpus tests/eval_corpus
```

评测语料通过 `scripts/fetch_eval_corpus.py` 按 manifest 下载（arXiv ID + SHA256 校验）。

## 文档

- `DESIGN.md` — 架构设计（三层：文档理解/证据检索/语言分析）
- `REQUIREMENTS.md` — 功能需求与非功能需求
- `ANALYSIS.md` — 方案选型与已知边界
- `DEPLOY.md` — 服务器部署（systemd + nginx）
- `SUMMARY.md` — 迭代历程与性能优化
- `CHANGELOG.md` — 版本记录

## 技术栈

Python 3.10+ · FastAPI · SQLite · PyMuPDF / pdfplumber · Next.js 16 · pdf.js · DeepSeek API（OpenAI 兼容）

## License

MIT — 详见 [LICENSE](LICENSE)。
