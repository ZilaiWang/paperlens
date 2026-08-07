# PaperLens 进度与当前状态

> 更新日期：2026-08-03 · 本文档如实记录已完成、已验证与待提升项。

## 1. 已完成（按里程碑）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| **P0** | 章节检测重构（删除语料适配、通用模式+上下文继承、重复/顺序诊断）；质量 Profile 枚举化 | ✅ |
| **P1a** | DocumentIR 实体（15 个）、稳定 block_id、Job 真实进度模型 | ✅ |
| **P1b** | FastAPI 后端全接口：上传/arXiv 导入（白名单+SSRF 防护）、Job+SSE、文档/大纲/PDF/资产、会话问答、质量、CV 档案、引用、标注 | ✅ |
| **P1c** | Next.js 前端：首页（拖拽/arXiv/真实进度条）、三栏工作台、PDF.js 原版模式、Agent 面板 | ✅ |
| **P3** | 沉浸式翻译：术语表、保护符号、批量并发翻译、首页预翻译 5 页、后台持续翻译全文 | ✅（质量待打磨） |
| **P4** | 图表资源（caption 关联、PDF.js 客户端裁剪下载）、参考文献网络（callout 绑定、一键导入） | ✅ |
| **P5** | CVPaperProfile（9 字段证据化档案）、质量证据审计 | ✅ |
| **P6** | 腾讯云部署（systemd + nginx）、Python 3.10 兼容、模板指纹匹配 | ✅（多用户/独立 worker 待做） |
| **V3.0A** | 解析评测基线：`scripts/eval_parse.py` + 7 篇真实 CV 论文语料（`tests/eval_corpus`），单字符块比例/表行/顺序逆序等指标 | ✅ |
| **V3.0B** | PyMuPDF 几何适配器（`pymupdf_adapter.py`）：span 级抽取、旋转文本过滤（竖排 arXiv 水印）、表格区域 mask、y 重叠行合并（上下标同带合并）；语料单字符比 9.95%→9.02%（YOLO 16.0%→10.1%） | ✅ |
| **V3.1** | Source-first arXiv HTML 导入：LaTeXML DOM 语义解析（章节/段落/图表/公式序）、同 job 贯穿 download→parse→store；biblist 排除出正文流；服务器验证 1706.03762→8 章 83 块零碎片 | ✅ |
| **V3.2a** | 参考文献链路：`parse_bibliography`（ltx_bibblock DOM 分段：作者/标题/venue，IEEE 引号回退）、解析时持久化 ReferenceEntry + callout 绑定、`[3-5]`→3,4,5 区间展开、`POST /references/{id}/resolve` 在线身份核验（DOI/arXiv 精确→Crossref 多字段瀑布，结果持久化）；1706.03762 实测 [1] Layer normalization→VERIFIED（arXiv 1607.06450）、[2] Bahdanau→VERIFIED（abs/1409.0473） | ✅ |
| **V3.2b** | 前端参考文献 rail：身份核验按钮、VERIFIED/PROBABLE/AMBIGUOUS 徽标、引用点击滚动+闪烁高亮 ref 条目 | ✅ |
| **V3.1b** | 解析质量门 `quality_gate.py`（§8）：每页 tiny-block 比例/表格污染/阅读顺序逆序/字符覆盖率，LOW/SUSPECT/GOOD 判定 + fallback_reasons，解析时持久化、`/page-quality` 接口、前端横幅如实展示低可信页；YOLO 论文 16/26 页被正确标记 | ✅ |
| **V3.4a** | 证据反向定位（§16）：ChunkSegment 字符映射（连字符修复偏移感知）、EvidenceGuard 填充 `EvidenceLink.locators`（block+字符区间+页+bbox）、SSE `/messages/stream` 逐条推送已验证 claim；线上实测 "Adam 优化器" 回答定位到原文 block/字符区间 | ✅ |
| **V3.3a** | 翻译分层体系（§12/13/15，不含 CV 术语库——用户另行设计）：PaperTranslationProfile 每版本构建一次并缓存、确定性 SectionBrief、批次前后文 context-only 窗口、术语 WARNING 级校验（不降级）、concordance + 选择性修复（只重译漂移单元） | ✅ |
| **V3.2c** | 资产语义序渲染（§10.1）：caption 内联回正文流 + 图缩略图（视口懒裁剪）、媒体占位、HTML 路径 chunking 修复（LaTeXML 段落即段落边界 + 许可证过滤：1 chunk→11 chunks 全带 segments） | ✅ |
| **V3.4b** | 前端精修（§18/19）：job.paper_id 跳转（不再 rows[0]）、content-visibility 虚拟化、Agent claim SSE 逐条出现 + 定位 p.X 按钮、沉浸模式字符高亮、PdfViewer（pdfjs canvas + bbox overlay 替换 iframe）、motion token/焦点环/prefers-reduced-motion | ✅ |
| **V3.5a** | 预翻译前 5 页 = job 真实阶段：`translate_initial_pages` 在 initial_translation stage 真实翻译前 5 页（glossary/profile 缓存复用、并发批次、翻译失败不阻塞解析），进度条显示"翻译前 5 页"，翻完 SUCCEEDED 才跳转；工作台进入后自动从第 6 页持续翻译全文（无需按钮）；线上实测 YOLO PDF："前 5 页已翻译（84 段）" | ✅ |
| **V3.5b** | 上传 PDF 自动匹配 arXiv（§4.1 Source-first）：文件名即 arXiv ID 直接走 HTML；否则按文件名/首页最大字号标题（多行合并、滤 arXiv 页眉、NFKC 归一化）搜 arXiv（ti: 查询 + 前缀感知 SequenceMatcher≥0.7）；命中且有 HTML → 语义解析，HTML 不可用（老论文）→ 同一 job 回退 PDF 管线；线上实测随机文件名上传 YOLO PDF → 命中 1506.02640v5 → HTML 缺失自动回退 PDF 解析成功 | ✅ |
| **V3.6a 日志系统** | JobStage started_at/finished_at（mark_stage 自动计时，RUNNING→SUCCEEDED 归属耗时）；`data/logs/paperlens.log`（10MB 轮转×5）+ 控制台双写；job 起止/失败（含耗时与堆栈）、上传 arXiv 匹配决策与 HTML 回退原因、翻译批次状态汇总、每 job 一行 stage timings；前端进度条显示每步耗时 | ✅ |
| **V3.6b 翻译空缺修复** | 根因：verify_translation 的 CIT 校验只认 19xx/20xx 年份 → HTML 论文的纯数字 `[12]` 引用全被误判丢失（用户论文 65 段中 34 段 NEEDS_RETRY）；改为引用组内所有数字必须存活；NEEDS_RETRY 单位重新进入 pending（此前永不重试）。修复后同论文：TRANSLATED 31→50，NEEDS_RETRY 34→15 | ✅ |
| **V3.6c 元信息 arXiv header** | HTML：extract_metadata（h1.ltx_title/ltx_authors/ltx_abstract）；PDF：extract_pdf_metadata（首页字号分层：标题+作者行，fitz/pdfplumber 双后端）；`GET /api/papers/{id}/meta`；工作台顶部 arXiv 风格展示区（居中标题、作者行、Abstract 卡片）；线上实测 PETDet 标题/作者/摘要全对 | ✅ |
| **V3.6d 图/表资产** | HTML 论文此前完全无资产：extract_assets 从 DOM 提取 figure 图 URL 直链（相对路径解析）+ caption、table caption（2312.10515：6 图 22 表）；PDF 论文 caption 样式 TEXT 块内联图；AssetThumb 优先 content_uri 直链，无则客户端 PDF 裁剪 | ✅ |
| **耗时实测（2026-08-04）** | HTML 路径：file_validation(fetch HTML) 24-54s ⚠ 瓶颈、翻译前 5 页 24-26s；PDF 路径：解析 3s、翻译 9s、其余 <1s。总时长主要由 arXiv HTML 下载与首 5 页翻译构成 | 📊 |
| **V3.7a arXiv 加速代理** | 服务器部署 mihomo（systemd + /etc/clash，订阅配置 + Country.mmdb，mixed 7890）；`net.py`：PAPERLENS_ARXIV_PROXY → httpx mounts（0.28 兼容），仅 fetch_arxiv_html/scholarly arxiv provider/download_pdf 走代理，其余直连；实测 arxiv.org HTML 20.8s → **1.1s**，job fetch 阶段 54s → **2s** | ✅ |
| **V3.7b 预翻译 3 页** | translate_initial_pages 默认 [1,2,3]，进度条"翻译前 3 页"，工作台从第 4 页自动续翻 | ✅ |
| **V3.7c 每用户 300 篇配额** | Paper.user_id（默认 guest）+ papers 表 user_id 列（ALTER 迁移）+ 显式列名 INSERT（修了迁移库列错位：位置绑定把 user_id/created_at 写反）；upload/import 读 X-User-Id，count≥300 拒绝 403；实测 testuser01/02 归属正确 | ✅ |
| **V3.7d 翻译 JSON 容错** | 根因：模型在 JSON 字符串输出 LaTeX 裸反斜杠（\beta）→ extract_json 抛 Invalid \escape → 前 3 页翻译整批失败（"翻译暂不可用"）；修复：容错二次解析只把非法转义加倍（\\n/\\t/\\uXXXX/\\\\ 不动）；translate_initial_pages 异常带堆栈进日志 | ✅ |
| **V3.7e 展示修复** | ① HTML blocks section_id 全 None → 标题不加粗、目录点不动：构建 sections 时写回 block.section_id；② 跳转后一句翻译不显示：Workbench 进入即加载 job 已翻译译文（此前只有 translate 请求后才拉取）；③ HTML 论文（无物理页）改翻译前 8 段（PDF 前 3 页），进度条文案"正在翻译…"；④ 进度条只显示 job 实际存在的 stage（HTML 路径隐藏无用条目），右侧"预计剩余 Xs"（批次 ratio 推进 × 已耗时估算） | ✅ |
| **V3.7f 两个隐藏 bug** | ① mark_stage 对 RUNNING 进度更新重置 started_at → 阶段耗时归零：保留首次 start；② make_units 的 unit_id 用组内 index → 同 section 多组重复：改 block_id 派生（唯一且重译幂等） | ✅ |
| **V3.7g 译文不显示终修** | ① Workbench 初始加载 effect 竞态：blocks 异步到达前 pages 为空，首次 effect 置 ref → 之后永不加载：加 pages.length===0 守卫；② HTML blocks 的 to_blocks 按 (page,bbox,text) 重算 stable id，bbox 全 0 导致同文本段落 block_id 撞车（80 块 1 id 重复 10 次）→ 译文 map key 覆盖：HTML 逻辑块保留 legacy 唯一 id。验证：80 blocks 零重复、8 段译文全部映射 | ✅ |
| **V3.8** | ① 预计剩余时间从导入（job created_at）起算、按总进度估算（旧算法从翻译阶段起算且 ratio 粒度粗 → 出现 5→7 递增假象）；② 进度条文案统一"正在翻译"；③ HTML 论文预翻译 8→**15 段**；④ Workbench 自动续翻补上 HTML 论文分支（pageCount=1 → translate([1]) 补翻全部剩余段落，此前只在 PDF 的 pageCount>3 时触发，HTML 论文进入后停在 15 段）；进度文案"正在翻译全文…" | ✅ |
| **V3.9** | ① 代理节点优化：mihomo URLTest/fallback 健康检查目标 cp.cloudflare.com → **arxiv.org/robots.txt**（选出的节点即对 arXiv 最优），interval 1800→600s；自动选中美国旧金山，实测 2.6-8.6s → **0.6-1.6s**；② **摘要进正文流**：ltx_abstract 此前被 walk 跳过（摘要只在展示 header，不翻译不进检索）→ 作为第一个 PARAGRAPH 块进入正文流，自然落入预翻译前 15 段并被翻译（实测摘要译文生成） | ✅ |
| **V3.9b 六项体验优化** | ① 原版模式：HTML 论文挂载 PDF（上传复用用户 PDF / arXiv 链接导入时 job 内下载），PdfViewer 用 PDF 实际页数；② 图片下载：`/api/assets/{id}/download` 服务器代理端点（实测 921KB PNG 200），pdfCrop 文档级缓存；③ 参考文献 raw_text 去双重序号；④ caption 块与资产统一空格 join（此前匹配全失败，图不插入），6/6 匹配；⑤ Agent 删 Insights 标签 → Ask 豆包式功能气泡（4 预设 + CV 档案 + 证据审计）；⑥ 回答组织化：正文由模型基于已验证主张组织连贯段落（证据逐条展示，失败降级拼接）——DeepSeek 503 期间部署，待 API 恢复实测 | ✅ |
| **V3.9c 图片服务器内组织** | 导入时预下载 HTML 图落盘（data/uploads/assets/{version}/，走 arXiv 代理一次拉取），Asset.local_file；下载端点本地 FileResponse 秒回（实测 0.15s，不再回源）；旧数据无本地文件时回源+落盘缓存。期间修两个真 bug：① jobs.py 缺 `import os` → HTML job 每次 NameError 被回退逻辑吞掉（PDF 挂载/预下载全失效）；② asset_id `fig-html-01` 全局相同 → 下载端点匹配到最新论文的图：加 version 前缀唯一化 | ✅ |
| **V3.10 进度条完善** | ① 预显示全部计划步骤：create_arxiv_html_job/create_parse_job 预注册 QUEUED stage（HTML 5 个 / PDF 8 个），前端"待开始"灰显、当前 ● 高亮、完成 ✓（实测 6s 时 1✓+4 待开始）；② ETA 改滑动窗口斜率估算（最近 8 个进度点，阶段完成瞬间 progress 跳变不再导致倒计时乱跳，进度卡住时不显示） | ✅ |
| **V3.12 公式与表格识别**（改进方案2.md §10.3/§10.4） | **P1 HTML 表格结构化**：LaTeXML tr/td → cell matrix + CSV + html 渲染串（tables.py：rowspan 延续展开、csv、html）；实测 22 表 22 结构化 · **P2 PDF 表格网格**：table_grid.py PyMuPDF 矢量线（line/rect 路径、坐标合并容差、**竖线阈值 5pt 支持每行 12pt 短线段**、全空列清理）→ 网格 → span 锚点分配 cell；derive_assets 合并连续 TABLE_ROW 为整表（bbox union）；实测 1812.01187 7/7 结构化（6×7 两组合并表头）· **P3 HTML 公式**：inline math 用 alttext LaTeX 替换 MathML 渲染文本（消除 "subscript/roman" 泄漏），display 公式提取 FORMULA 块（尾部编号保留）· **P4 PDF 公式兜底**：FORMULA 块 metadata 记编号 + 上下文段落。前端：表格内联真实渲染（点击展开）+ 下载 CSV、FORMULA 显示编号、detail 模态表格 + CSV。**生效修复**：parse_table caption join、PyMuPDF 1.28 ("re",Rect,extra)、BlockTypeIR 导入位置、**图 URL 带版本目录前缀时取文件名拼 base**（2608.02589 8 图 404→8/8 预下载）。测试论文 CAPEval 2608.02589：12/12 表结构化 + 8/8 图落盘 | ✅ |
| **V3.13 性能与下载** | ① attribute 并发（4 路线程池，6 条主张 16s→5s）；② 高清下载：PDF 嵌入源图 vs arXiv 位图对比取大（`/api/assets/{id}/download`）；③ SSE completed 透传 stage_timings | ✅ |
| **V3.14–V3.23 集中补记（2026-08-04）** | ① Agent 面板实时阶段反馈（stage_started 文案 + 弹跳圆点）；② 性能：draft 会话缓存（重复问题 5.3s→1.1s）、compact JSON 输出（draft 25.3s→14.4s）、证据截断护栏、organize 跳过（claims≤2）；③ UI：等待提示去重、左右栏拖拽调宽、主张句整句可点+原文软黄高亮、历史主张折叠；④ **公式排版**：LaTeXML display 公式表格结构识别（1706.03762 0→7 块）+ 编号入库 + KaTeX 渲染（行内 `$...$` + display 居中右编号，arXiv 风格）；⑤ **翻译错位修复**（block_id 索引型重解析移位 → `unit_matches_block` 内容校验）、MATH 占位符校验补全、方向性数字校验移除；⑥ **图片加载**：前端改走服务器代理端点 + arXiv 图 URL 版本目录修复（ModalNet 等 5/5 图本地化） | ✅ |
| **V4.0-1 打包守卫** | `scripts/package_release.py`：rsync 过滤暂存 → 对暂存包检查（真实 .env/API key 特征/依赖/缓存/数据库/版权 PDF）→ 通过才打包；曾发生真实 .env 随包外发，已重打包剔除并提示轮换 Key | ✅ |
| **V4.0-2 流式用户消息持久化** | SSE 路径流开始时即落库 user 消息（此前只存 assistant，刷新丢历史） | ✅ |
| **V4.0-3 Session 恢复** | `GET /api/sessions/latest` + AgentPanel 挂载恢复最近会话并加载历史消息（无则新建） | ✅ |
| **V4.0-4 ParseRouter** | `core/parse_router.py` 统一 PDF 解析入口：`PAPERLENS_PDF_PARSER=hybrid`（PyMuPDF 优先，异常回退 pdfplumber）；jobs.py 与 eval_parse.py 同入口，不再直接 import 具体 parser | ✅ |
| **V4.0-5 重复逻辑清理** | create_arxiv_html_job 的 paper_meta/assets 曾重复存储两遍（重复下载），删除前一份 | ✅ |
| **V4.0-6 版本号统一** | `core/paperlens_core/version.py`（4.0.0 / V4.0），`/api/health` 返回；pyproject 同步 4.0.0 | ✅ |
| **V4.3** | 上下文检索（reader context_scope/context_block_ids + Workbench 滚动跟踪章节 + AgentPanel 上下文条）、UnderstandingArtifact 版本化持久化（字段带 evidence_locators）、TaskDefinition 注册表（core/tasks.py + /api/tasks + task_id 侧重词）、多轮指代消解（history_rewrite，历史只重写意图不作证据） | ✅ |
| **V4.4** | 单篇旗舰 4 端点：method_graph（LLM 结构化抽取+确定性过滤，持久化）、experiments（表格确定性提取 ResultRecord）、reproduction（artifact 复用）、claim-map（会话主张+参考文献）；前端 AnalyticsPanel 左栏"分析"tab；线上实测 method-graph 11 节点 13 边全带证据、experiments 88 条 | ✅ |
| **V4.5** | 多篇比较：judge_topic_alignment（基于 artifact 摘要，确定性兜底）+ add_comparability_warnings + /api/v1/comparisons（独立抽取→确定性组装→可比性判定→comparisons 表持久化）+ /compare 页矩阵；线上实测正确判定 Transformer vs TFA 为 DIFFERENT | ✅ |
| **V4.6-0 自查修复** | ① /compare 页误发 paper_id（后端 _require_version 404）→ list_papers 附带 version_id；② 流式路径 history 含刚追加的当前问题（buffered 路径不含）→ 追加前读取；③ 比较存储由 documents 表 hack 改为独立 comparisons 表（脏行已清理）；④ 死代码清理 | ✅ |
| **V4.6-1 会话管理** | GET /api/sessions（列表）+ rename + delete 端点（sessions 表补 updated_at + 迁移）；AgentPanel 会话菜单（恢复/切换/新建/重命名/删除） | ✅ |
| **V4.6-2 所有权分离** | §14.1：user_papers 表（论文全局去重，收藏按用户），导入/上传时登记；Lite Mode 落地，云端认证/租户隔离待环境改造 | ✅ |
| **V4.0-7 评测 manifest** | `tests/eval_corpus/manifest.json`（7 篇 arXiv ID + SHA256）+ `scripts/fetch_eval_corpus.py` 下载校验脚本 | ✅ |

## 2. 当前架构

```text
浏览器 → nginx :80
           ├─ /          → Next.js :3000（pl-web.service；HTML no-cache，静态资源 immutable）
           └─ /api/*     → FastAPI :8700（pl-server.service；SQLite JSON 文档存储）
                              └─ DeepSeek API（deepseek-v4-flash，thinking 关闭）
```

- **任务执行**：进程内线程队列（每 job 一线程），SSE 推送阶段事件；云端化（独立 worker/PostgreSQL）为后续里程碑。
- **数据**：SQLite `data/paperlens.db`——papers（SHA 去重）、paper_versions、documents（JSON：blocks/sections/chunks/translations/assets/callouts）。

## 3. 解析管线（当前实现细节）

```text
pdfplumber 文本层
  → 行碎片（bbox/字号/粗体；图/表对象标记）
  → 按 y 粗分组（0.6 行高容差）
  → 栏检测（碎片 x0 簇最大间隙；模板指纹命中时直接用已知栏边界）
  → 按栏分簇 → 按基线（y0 差 ≤ 1/4 行高）合并成"视觉行"（数学碎片同基线合并，无视 x 间隔）
  → 表格行检测（连续 ≥3 个纯数字 token）→ 独立，不并入段落
  → 标题/图注/页码独立（加粗需配合窄行，防正文加粗误判）
  → 栏内按 y 合并成"段落"（gap/句尾/缩进规则；保持左栏→右栏阅读顺序）
  → 分片 → DocumentIR 持久化
```

**模板指纹**（`core/paperlens_core/templates.py` + `template_registry.json`）：页宽/栏边界/正文字号/行距/标题字号/缩进/caption 前缀/引用风格。当前 4 个模板：`pmlr`、`arxiv`、`neurips`、`iclr`。匹配按栏数/页宽/字号/栏边界加权打分。`scripts/extract_template.py` 用样张 PDF 扩展。

## 4. 翻译流程（当前实现）

```text
首页导入 → 解析 job（真实阶段进度）→ "预翻译前 5 页…"（约 1 分钟）→ 自动进入论文页
论文页 → 后台持续翻译剩余页（5 页一批，显示"后台翻译中：第 X-Y 页 / 共 N 页…"）→ 全文翻译完成
```

- **术语表**：从摘要/方法区一次构建（严格 JSON），翻译批次共用。
- **保护符号**：引用（[n] / 作者-年份）、图表/公式引用、年份、行内公式替换为占位符，翻译后还原。
- **校验**：2026-08-03 按产品决策**暂时关闭**（数字存活/引用保留检查此前误杀过多合理译文）；仅空译文（模型漏译段）不展示。代码注释保留恢复开关。
- **并发**：4 worker × 每批 3 段；TFA 前 4 页 27 秒，NTTT 全文 29 页 ~5 分钟。

## 5. 已知问题与待提升

1. **段落匹配**：极端版面（复杂公式混排、嵌套表格、跨页段落）仍可能拆错；当前"表格行"检测是启发式（连续数字流），对含公式的表格行可能误判。
2. **翻译质量**：未专门打磨——术语一致性、长句、数学符号周边语义、参考文献保留策略都需要评测迭代。
3. **公式处理**：行内公式已随行合并恢复；独立公式占位（FORMULA 块）存在但未做 LaTeX 识别（候选：UniMERNet 等，见调研）。
4. **模板库**：仅 4 个模板；匹配算法朴素（加权打分），无误匹配/漏匹配测试集；指纹提取对数学多的论文可能测偏栏边界。
5. **云端化**：单进程线程队列 → 独立 worker + PostgreSQL + 多用户隔离（RLS）未做；HITL 审批、限流、Guest 过期等云治理未做。
6. **多篇对比页**：占位页（Beta），未实现。

## 6. 生产环境

- 服务器：<server-ip>（腾讯云 2C2G），代码 `/home/ubuntu/paperlens`。
- systemd：`pl-server`（uvicorn :8700）、`pl-web`（next start :3000）。
- nginx：`docs/nginx/paperlens.conf`——HTML no-cache（关键：Next 静态页默认一年缓存曾导致更新不可见）、静态资源 immutable、API no-store。
- 安全：仅放行 80/22；3000/8700 内网；API key 在服务器 `.env`，`.gitignore` 排除。

## 7. Git 历史（按时间）

`208e05a` P1b 后端 → `8fa1233` P1c 前端 → `fdb2fb8` P3 翻译 → `2eada33` P4 资源 → `a240f5e` P5 CV 档案 → `946e201` P6 部署 → `3c80e74` 双栏段落重建+翻译并发 → `7e46645` 模板指纹 → `88d4ba1` 模板脚本 → `03928aa` editable 修复 → `52615a9` 标题消歧+顺序 → `ad13802` 翻译校验 40%→97% → `0b921e9` 校验关闭 → `44b3696` 预翻译 → `8515b5e` nginx 缓存 → `2377bba` 后台持续翻译 → `3b91d35` 渲染修复 → `4fa3e8a` 段落匹配改进 → `8ae207f` V3 P0 修复（翻译批次/arXiv job 线程/版本号/校验分级）→ `5685058` V3.0A 解析评测基线 → `e5a20c7` V3.0B PyMuPDF 几何适配器 → `c661e56` V3.1 Source-first arXiv HTML 导入 → `f97cd5a` V3.2 参考文献链路+resolve 接口 → `a59a465` Python 3.10 兼容（timezone.utc）→ `e2d868f` resolve contact_email 回退 → `0a5b1d7` parse_bibliography DOM ltx_bibblock 分段 → `bd62fdf` resolve arXiv-id-in-text 精确路径 → `44ac569` extract_arxiv_id 支持 abs/ 记法
