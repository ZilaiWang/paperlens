# PaperLens 设计文档

## 1. 设计总纲

论文 PDF 不是天然可供检索的纯文本：直接交给大模型会破坏双栏阅读顺序、表格、公式、引用和证据位置。因此 PaperLens 的设计主线是：

> 先通过**确定性解析**恢复论文结构，再通过**自行实现的检索**找到候选证据，最后只允许大模型在**证据边界内**进行理解、翻译和语言生成。

整个系统分为三层：

| 层 | 职责 | 核心模块 |
| --- | --- | --- |
| 文档理解层 | 恢复段落、章节、图表、公式、参考文献与页码位置 | `pymupdf_adapter` / `pdfplumber` / `arxiv_html` / `paragraphs` / `sections` |
| 证据检索层 | 段落感知分片、自研 BM25、证据账本与定位 | `reader`（BM25Index）、`evidence` 账本、字符区间/bbox 定位 |
| 语言分析层 | 翻译、问答、质量评估、受控的多篇比较 | `translation` / Agent 五段式管线 / `quality` / `comparison` |

## 2. 解析链路（文档理解层）

### 2.1 双路径解析

- **PDF 路径**：ParseRouter 统一入口，`PAPERLENS_PDF_PARSER=hybrid` 时 PyMuPDF 优先、pdfplumber 回退；页级质量门（quality gate）对每一页做双引擎融合，低质量页自动换引擎。
- **arXiv HTML 路径**：优先抓取 LaTeXML 结构化 HTML（段落、公式、表格、图表位置天然有序），老论文无 HTML 时回退 PDF 管线。

### 2.2 段落重建与章节识别

- PyMuPDF span 级提取（字体、字号、加粗、基线、方向），旋转文字（页眉水印）过滤出正文流；表格区域（find_tables）作为掩膜：表格内 span 不进入正文段落，同时生成 `⟦TABLE p.x b.y bbox=…⟧` 占位块，图表资产提取据此工作。
- 章节识别：基于字号/加粗的标题候选 + 上下文继承规则（未知编号小节继承父级类型），输出章节树（Section 实体），正文 block 归属到最近前置章节。

### 2.3 公式与图表占位

- LaTeXML display 公式是表格结构（tr/div.ltx_equation > td.ltx_eqn_cell），检测后整体从段落文本排除，生成 FORMULA 块；行内公式用 `$...$` 包裹，前端 KaTeX 渲染。
- 图/表资产：资产块文本含 `⟦FIGURE/⟦TABLE⟧` 标记与 bbox，资产端点按需回源下载（服务器预下载上限 10 张，其余按需代理回源）。

### 2.4 参考文献链路

- 双路径提取：PDF 路径 `parse_references`（按序号切分逐条解析），HTML 路径 `parse_bibliography`（LaTeXML ltx_biblist DOM 结构，双重序号去重）。
- 字段解析：作者、标题、年份、venue、DOI、arXiv 编号（年份正则带 `(?!\d|\.\d)` 防误抓 arXiv 编号）。
- 风格感知格式检查（lint）：数字式（IEEE [n]）/ 作者-年份式 / 混用分别检查；13 种问题码（序号缺失/重复/不连续/非 IEEE、缺作者/标题/年份、年份异常、标题过短、缺句号、疑似 DOI/arXiv 未解析）。
- 在线身份核验：Crossref/arXiv 瀑布式匹配（精确 ID 优先，模糊检索兜底），VERIFIED/AMBIGUOUS/PROBABLE 三级判定，核验结果持久化并回填元数据。

## 3. 证据检索与问答（Agent 五段式管线）

1. **检索**：BM25 索引（段落级分片），支持章节上下文限定（前端开关）与多轮历史改写。
2. **草稿生成**：LLM 生成主张（claim），受确定性守卫约束（引文逐字/数字/否定/比较词规则）。
3. **语义核验**：每个主张独立 LLM 并发核验，只带该主张的引文上下文。
4. **组织**：把通过核验的主张重写为散文；主张数 ≤2 时直接拼接。
5. **流式输出**：SSE 事件流，前端气泡实时显示阶段。

证据账本（evidence ledger）记录每个引文的 block/字符区间/bbox，前端可跳转定位到原文精确位置。

## 4. 质量评估

页级双引擎融合质量门（Active Quality Gate）：每页 verdict（GOOD/MEDIUM/LOW）+ 解析引擎记录（resolved_by），前端论文页横幅展示；质量评估（quality agent）与主张核验共享证据约束。

## 5. 多篇比较

- 主题对齐判定（judge_topic_alignment）：RELATED / DIFFERENT / NOT_COMPARABLE。
- 字段抽取：13 个维度（默认 5 个核心字段：任务/方法/数据集/指标/主要结果），LLM 抽取与 understanding_artifact 字段复用结合；多篇并发抽取（每篇独立 LLM 实例）。
- 结构化结果对比：数据集/指标/条件一致时才宣告"同条件可对比"；自动最佳值判定因不可靠已从前端隐藏。
- 后台线程执行 + 进度持久化 + 前端 2s 轮询；同组合+同维度结果缓存。

## 6. 技术选型

| 选型 | 理由 |
| --- | --- |
| FastAPI + SQLite + SSE | 轻量、单机部署友好（腾讯云 2C2G），SQLite 满足单用户课程场景 |
| 自研 BM25 而非 embedding | 课程要求"自行实现检索"，零依赖、可解释、离线可用 |
| PyMuPDF + pdfplumber 双引擎 | PyMuPDF 快但 AGPL、表格识别粗；pdfplumber 稳定但较慢，页级融合互补 |
| Next.js 16 + Turbopack | 客户端交互密集（SSE、拖拽、PDF 渲染），App Router 服务端渲染首页 |
| 单进程线程并发 + 进程级信号量 | 满足 300 篇/用户配额的单机场景；全局翻译并发受信号量钳制，避免超出 API 承载 |

## 7. 数据与部署

- SQLite 文档表（documents 统一事实源，DocumentGraph），版本化（version_id）。
- systemd（pl-server :8700 / pl-web :3000）+ nginx 反代 + 一年 immutable 静态缓存 + API no-store。
- arXiv 访问经 mihomo 代理（PAPERLENS_ARXIV_PROXY），国内直连挂起问题的根治。
