# PaperLens 测试报告

## 1. 测试总览

- 自动化测试：**72 项全部通过**（无网络/LLM 依赖，可离线运行）。
- 运行方式：`cd core && .venv/bin/python -m pytest tests/`（或项目根 `pytest tests/`）。
- 覆盖范围：参考文献链路（提取/格式检查/核验/端点契约）、arXiv HTML 解析、资产/调用绑定、解析修复回归、比较端点、Job 状态机等。

## 2. 核心测试用例（样例）

### 2.1 参考文献格式检查（lint）

| 用例 | 输入 | 预期 | 实际 |
| --- | --- | --- | --- |
| 干净 IEEE 条目 | `[1] John Smith. A great paper. Journal of Science, 2016.`(含作者/标题/年份) | 无格式问题 | ✅ 零问题 |
| 非 IEEE 序号 | `1. John Smith. …`（无方括号） | REF_NON_IEEE_NUMBER | ✅ |
| 年份误抓 arXiv 编号 | `…arXiv:1904.04232, 2019.` | year=2019（非 1904） | ✅ |
| 长作者列表标题 | `Chen, W.-Y., …, and Huang, J.-B. A closer look…` | 标题完整解析 | ✅ |
| HTML 路径无误报 | LaTeXML biblist 条目（无序号前缀） | 不报 REF_NON_IEEE_NUMBER | ✅ |
| 风格混用 | 数字式 + 作者-年份式混排 | REF_MIXED_STYLE | ✅ |
| 年份异常 | year=9999 | REF_IMPLAUSIBLE_YEAR | ✅ |

### 2.2 参考文献在线核验

| 用例 | 输入 | 预期 | 实际 |
| --- | --- | --- | --- |
| arXiv 精确命中 | raw 内 arXiv:1607.06450，本地字段齐全 | VERIFIED + 证据记录 | ✅ |
| 精确命中但字段不全 | arXiv 命中但本地标题空 | PROBABLE + 元数据回填 | ✅ |
| 未知引用 | 不存在的 reference_id | 404 | ✅ |
| 核验结果持久化 | resolve 后查库 | identity_status 已更新 | ✅ |

### 2.3 解析与章节

| 用例 | 输入 | 预期 | 实际 |
| --- | --- | --- | --- |
| arXiv HTML 参考文献提取 | LaTeXML LATEXML_HTML 样本 | 3 条 entry、id 约定、年份/标题/作者正确 | ✅ |
| 引用编号范围展开 | `[3-5]` | 3,4,5 | ✅ |
| 目录排除参考文献段 | 正文块流 | 参考文献块不进正文 | ✅ |
| PyMuPDF 表格占位 | 含表格 PDF（1703.06870） | 21 个 TABLE 占位块、表格 cell 不混入正文 | ✅ |

## 3. 线上端到端验证记录（2026-08-05）

| 场景 | 结果 |
| --- | --- |
| 批量核验 244 条参考文献（含大量无 ID 条目） | 4 并发约 4 分钟；VERIFIED 43 / PROBABLE 112 / AMBIGUOUS 9 / UNRESOLVED 80 |
| 多篇比较（2 篇，V-JEPA 2 vs I-JEPA） | 主题对齐 SAME_TASK、26 格对比矩阵、结构化结果分组 |
| 多篇比较并发抽取（1706.03762 vs 2604.13565） | 90 秒完成、26 格完整 |
| 问答证据定位 | "Adam 优化器"问答 SSE 流式 + 定位到 block/字符区间 |
| 页级质量门 | wang2020 页 1 LOW → pdfplumber 融合后 GOOD |
| PDF 后台预下载 | 导入期并行下载，首次打开原版模式无需等待 |

## 4. 已知边界说明

- 72 项离线测试不含真实 LLM 调用（模型调用在线上端到端验证中覆盖）。
- 解析评测语料（tests/eval_corpus）manifest 化（arXiv ID + SHA256），版权 PDF 不入提交包，通过 `scripts/fetch_eval_corpus.py` 下载。
