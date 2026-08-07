# 多篇比较功能审计（2026-08-05）

> 自查范围：前端设计（`web/app/compare/page.tsx`）、内容质量（`core/paperlens_core/comparison.py`）、后端（`server/app/main.py` 的 `/api/v1/comparisons`）。对照基准：单篇体验（流式主张、证据定位、分析面板、上下文条）。
>
> 实测样本：DINOv3 vs UHR-BAT 对比（2026-08-05 线上运行，20s，全字段 FOUND）。

## 总体结论

**当前多篇比较是一个"能跑通但不可用"的演示壳**：数据链路（独立抽取 → 确定性组装）方向正确，但三个层面的实用性都未闭环。最严重的是**对齐判定在真实运行中输出错误结论**（见 2.1）和**全链路无任何交互**（无流式、无跳转、无追问、无历史）。与单篇相比，单篇已经做到"每条事实可点击跳原文 + 全程可见进度 + 可追问"，多篇全部缺失。

**可复用资产**：抽取链路（BM25 证据包 → LLM 结构化 → 跨论文证据边界校验）是好的，`assemble_comparison` 的跨论文证据防污染检查值得保留。修复应在其上补全体验，而非推倒。

---

## 一、前端设计问题

### 1.1 运行期间零反馈（阻断式等待）
- 现状：点击"比较所选"后按钮文案变为"比较中（各篇独立抽取，约 1 分钟）…"，期间页面完全静止，后端阻塞 20-60s。
- 单篇对照：问答有 SSE 流式（阶段文案 + 逐条主张 + 核验计数），全程可见推进。
- 影响：用户无法判断是"在跑"还是"卡死"；长论文（3 篇全量 13 字段）可超过 2 分钟。
- 建议：比较改为 SSE 事件流（`比较创建 → 每篇抽取完成 → 对齐判定 → 组装完成`），前端显示与单篇一致的阶段推进（"抽取 DINOv3…✓ → 抽取 UHR-BAT… → 判定可比性 → 组装矩阵"）。

### 1.2 单元格无任何证据入口
- 现状：单元格只有一段文本，无"跳原文"、无证据引文、无定位。
- 单篇对照：每条主张可点击 → 阅读区滚动 + 黄色高亮；档案字段带 evidence_locators。
- 影响：用户无法核实"mAP 66.1"出自论文哪里——比较结论成了不可验证的黑盒，违背项目"证据可追溯"核心。
- 建议：ComparisonCell 增加 `evidence_locators`（page/section/block_ids，复用 UnderstandingArtifact 的定位方式），前端单元格渲染证据徽标 + 点击跳转对应论文阅读页（带高亮）。跨论文跳转需定义 URL 约定（`/paper/{id}?locate=block&evidence=...`）。

### 1.3 矩阵渲染是"文本堆砌"
- 现状：每个格子渲染整段 value 文本（可达 200+ 字），无状态图例、无条件标记、无最佳值。
- 影响：同字段不同指标直接并排（"COCO mAP 66.1" vs "XLRS w.Avg 44.0"），读者会误以为可比；空单元格统一显示"未找到"，无法区分"搜索未覆盖 / 确认未报告 / 不适用"。
- 建议：
  - 单元格状态图例（FOUND 实色 / NOT_FOUND 灰 / NOT_REPORTED_CONFIRMED 划线 / PARSE_GAP 虚线）；
  - 数值单元格从 ResultRecord 渲染（dataset/metric/条件列拆分），**指标/数据集不一致时单元格标"Not directly comparable"**（§13.3）；
  - 同任务同条件时高亮最佳值（绿色）。

### 1.4 与单篇体验完全割裂
- 现状：/compare 是独立页面，和阅读工作台零连接——不能从单篇"加入比较"，比较结果不能回到论文。
- 影响：多篇比较无法利用单篇已有的精读能力（图、表、主张、定位），使用者必须在新页面从零理解。
- 建议：单篇工作台增加"加入比较"入口（当前论文 → 比较栏）；比较结果矩阵的每个字段可展开为该论文的相关主张/图表。

### 1.5 无历史、无追问、无导出
- 现状：后端有 GET /comparisons/{id}，但前端从不展示历史；方案 §13.5 的跨论文问答、§13.6 的 export 均未实现。
- 影响：比较是一次性消耗品；"A 和 B 的核心创新区别？"这类最有价值的追问无法进行。
- 建议：比较历史列表（复用最近会话模式）；比较页内嵌"比较 Agent"（基于已抽取的 cells + 各篇证据包作答，输出 CrossPaperClaim 结构）；导出 Markdown/JSON。

### 1.6 选论文交互粗糙
- 现状：卡片只有标题 + source + 版本数；不显示版本、解析状态；选了 3 篇后第 4 篇点击静默截断（slice(0,3)），无提示。
- 影响：用户不知道选的是哪个版本；超选无反馈。
- 建议：显示当前版本 + 解析质量摘要（GOOD/LOW 页数）；超选时 toast 提示。

---

## 二、内容质量问题

### 2.1 【真 Bug】对齐判定在空输入上运行，输出事实错误结论
- 现状：`create_comparison` 给 `judge_topic_alignment` 喂的 summaries 来自 UnderstandingArtifact——**两篇论文都没有构建 artifact（`understanding_artifact` 文档不存在）→ 三个字段全是空串 → LLM 兜底输出 DIFFERENT，rationale 声称"task、method、metrics 均为空"**。
- 实测证据（DINOv3 vs UHR-BAT 运行）：
  ```
  alignment: DIFFERENT
  rationale: 两篇论文的task、method、metrics字段均为空，无法判断…
  但同一响应里 cells 全部 FOUND 且带具体值（task/method/main_results 都有内容）
  ```
- 影响：**对齐判定与展示内容自相矛盾**——这是当前功能最不可信的地方。即便 DINOv3 与 UHR-BAT 确实不同任务，理由也是错的；同任务论文也会被误判。
- 修复：summaries 优先取本次已抽取的 cells（task/method/metrics 的 value），artifact 只是补充；且对齐 rationale 必须引用实际内容（"DINOv3 做自监督视觉表征，UHR-BAT 做遥感图 token 压缩"）。

### 2.2 没有结构化结果记录，数值比较无从谈起
- 现状：main_results/metrics 单元格是散文文本（"COCO detection mAP 66.1; ADE20k mIoU 63.0…"）。
- 影响：无法做 §13.3 的 ComparabilityKey（dataset/metric/条件一致才允许比较）；无法标记最佳值；跨论文数值污染检查（方案核心诉求之一）实际未发生。
- 修复：复用 `experiments.py` 的 ResultRecord 提取（表格结构化数据 → dataset/metric/condition/value），比较时按 ComparabilityKey 对齐；同 key 才高亮最佳值，否则"Not directly comparable"。

### 2.3 证据只有 id，没有引文与定位
- 现状：cell.evidence_ids 存在且通过跨论文边界校验（这是亮点），但前端拿不到引文文本和 locator。
- 影响：无法核实；无法定位；对齐 rationale 也无法引用证据。
- 修复：extract_one 返回时把 evidence_ids → 引文（verbatim_excerpt 截断）+ locator 一并带回 cell。

### 2.4 全字段默认值导致低价值
- 现状：前端不传 dimensions 时后端用 13 个默认字段（含 version_status、code_and_data 等），抽取成本高且多数单元格价值低。
- 建议：默认 5 字段（task_definition / method_core / datasets_and_samples / metrics / main_results），其余按需。

---

## 三、后端问题

### 3.1 阻塞式同步执行
- 现状：POST 在请求线程里串行执行"每篇抽取（BM25+LLM）→ 对齐（LLM）→ 组装"，20-60s+；单篇已有 SSE 基础设施却未复用。
- 影响：请求超时风险（前端 jsonFetch 超时 180s，3 篇全量字段可达上限）；无法取消；服务线程被占。
- 修复：比较任务改 job 模式（复用 JobExecutor/bus），SSE `/comparisons/{id}/events` 推事件；前端显示阶段进度。

### 3.2 抽取未复用 UnderstandingArtifact
- 现状：每次比较都重新 BM25+LLM 抽取全部字段（成本高、结果不稳定）；artifact 只在对齐处（错误地）使用。
- 影响：与方案"概览/质量/问答/比较共享同一理解产物"（§四/§11）背道而驰；同论文多次比较结果漂移。
- 修复：优先读 artifact 的 task/method/metrics/main_results 字段（已有证据定位），缺失字段才触发补充抽取；artifact 抽取结果缓存进 comparison 结果。

### 3.3 无事件/进度/取消接口
- 方案 §13.6 定义了 events、questions、export；现状只有 create + get。
- 建议：补齐 `GET /comparisons/{id}/events`（SSE）、`POST /comparisons/{id}/questions`（跨论文问答）、`GET /comparisons/{id}/export`。

### 3.4 无错误隔离
- 现状：任何一篇抽取失败（LLM 超时/JSON 解析失败）→ 整个请求 500，前端只显示"比较失败"。
- 建议：单篇失败降级为该篇单元格全 NOT_FOUND + 警告行（与单篇"翻译失败不影响解析"同思路）。

### 3.5 id 语义混乱
- 现状：请求收 paper_version_ids，但 `assemble_comparison` 的 paper_ids 用 `version.paper_id`（内容哈希），前端标题映射用 paper_id，结果持久化用 version id——同一实体三种标识在代码里混用。
- 影响：历史比较恢复时难以反查；多版本论文（同一 paper 两个 version）会撞 paper_id。
- 建议：统一以 version_id 为比较实体键，展示层再映射标题。

### 3.6 对齐判定无置信度
- 现状：alignment 只有三档 + rationale，无置信度/依据字段；DIFFERENT 时也不提示"可做方法对照"。
- 建议：增加 confidence 与"判定依据字段列表"（哪些字段参与了判定）。

---

## 四、与单篇体验差距对照

| 能力 | 单篇 | 多篇 |
|---|---|---|
| 运行反馈 | SSE 阶段文案 + 弹跳圆点 + 核验计数 | 静态"比较中…约 1 分钟" |
| 证据可追溯 | 主张句点击 → 原文滚动 + 黄色高亮 | 无 |
| 结构化产物 | UnderstandingArtifact（字段+定位+版本） | 散文文本单元格 |
| 分析深化 | 方法图谱/实验记录/复现清单/主张图 | 无 |
| 上下文 | 上下文条（当前章节限定检索） | 无 |
| 会话 | 恢复/切换/重命名/删除 | 无历史 |
| 失败处理 | 单条主张失败降级，流不中断 | 任一论文失败全挂 |
| 可交互性 | 追问、预设任务定义 | 无 |

---

## 五、修复路线（建议顺序）

| 阶段 | 内容 | 优先级 |
|---|---|---|
| P0 正确性 | 2.1 对齐输入用本次抽取 cells（顺带修 rationale 引实据）；3.5 统一 version_id 键 | 立即 |
| P1 可信 | 2.3 单元格带引文 + locator + 前端跳转高亮；1.2 图例与"Not directly comparable"标记；2.2 ResultRecord 化 main_results | 高 |
| P2 交互 | 1.1 SSE 进度事件；3.1 job 模式；3.3 questions/export 端点；比较历史列表 | 中 |
| P3 深化 | 3.2 artifact 复用；1.4 与单篇打通（加入比较/返回论文）；1.6 选论文增强 | 中 |
| P4 收尾 | 3.6 confidence；3.4 错误隔离；1.5 比较 Agent 问答 | 低 |

**P0+P1 完成后即可达到"可信比较"的实用性底线；P2 之后具备日常可用性。**

---

## 修复状态（2026-08-05 完成，提交见 git log）

| 审计项 | 状态 | 实现 |
|---|---|---|
| 2.1 对齐空输入真 Bug | ✅ | 对齐输入改为本次抽取 cells，空摘要显式拒绝；rationale 引实据（线上：RELATED·置信度 0.5·依据"视觉表示学习与评估 vs 遥感 token 压缩"） |
| 3.5 id 语义混乱 | ✅ | 全链路统一 version_id 为实体键 |
| 2.3 证据无引文定位 | ✅ | ComparisonCell 增 quotes/locators，extract_one 随单元格返回；前端展开引文 + 跳转论文页 |
| 2.2 无结构化结果 | ✅ | build_result_comparisons 按 (dataset, metric, condition) 对齐，same_key 标记最佳值 ★，不一致标 Not directly comparable |
| 1.1/3.1 阻断等待 | ✅ | 比较改后台线程 + 进度逐步持久化，前端 2s 轮询显示阶段与进度条；SSE /events 端点已备 |
| 3.3 无 events/questions/export | ✅ | GET /comparisons（历史）、POST /questions（跨论文问答，CrossPaperAnswer）、GET /export（Markdown）、GET /events（SSE） |
| 3.2 未复用 artifact | ✅ | artifact 的 task/method/datasets/metrics/main_results/ablations/limitations 有值即直接成格，仅缺失字段走 LLM |
| 3.4 无错误隔离 | ✅ | 单篇抽取失败 → 该篇全字段 UNASSESSABLE_PARSE_GAP 降级 + 日志，不阻塞整体 |
| 3.6 无置信度 | ✅ | TopicAlignment 增 confidence/evidence_fields；无抽取可用时保守 RELATED·0.1 |
| 1.3 文本堆砌 | ✅ | 状态图例（有证据/未找到/确认未报告/解析缺口）、单元格展开/收起、最佳值高亮、Not directly comparable 列 |
| 1.5 无历史/导出/追问 | ✅ | 历史列表可恢复；导出 Markdown；比较问答输入框 |
| 1.6 选论文粗糙 | ✅ | 显示版本 id、超选提示、运行中禁用 |
| 3.6 附加 | ✅ | extract_one 截断单格证据/引文至上限（防旧数据超限；端点防御性截断兜底） |
