# 数据清洗说明

## 1. 为什么需要数据清洗

项目涉及两类敏感/体积数据：**版权 PDF**（评测语料与用户上传）与**运行数据**（数据库、日志、缓存）。提交包必须不包含这些内容。

## 2. 评测语料（tests/eval_corpus）

- 语料通过 `scripts/fetch_eval_corpus.py` 从 arXiv 下载（manifest.json 记录 arXiv ID + SHA256）。
- **版权 PDF 不入包**：发布包守卫（package_release.py）显式排除 `tests/eval_corpus/*.pdf`，检查阶段对任何 .pdf 文件报违规。
- 换机器后运行 `python scripts/fetch_eval_corpus.py` 即可重建语料（manifest 校验 SHA256）。

## 3. 运行数据（不入包）

| 类型 | 位置 | 说明 |
| --- | --- | --- |
| SQLite 数据库 | `.paperlens/paperlens.db`（含 WAL） | 生产/开发库，含用户上传元数据与解析结果 |
| 上传目录 | `.paperlens/uploads/` | 用户上传的 PDF 与预下载 PDF |
| 日志 | `.paperlens/logs/` | 轮转日志 |
| 缓存 | `__pycache__/ .pytest_cache/ .ruff_cache/ tsconfig.tsbuildinfo` | 编译与测试缓存 |

## 4. 发布包守卫（package_release.py）

打包流程：rsync 过滤暂存 → 违规检查 → zip。

排除规则（锚定根目录）：

```
.env（真实密钥，只保留 .env.example）
.git  .venv  .paperlens  data  node_modules  .next
__pycache__  *.pyc  *.log  .pytest_cache  .ruff_cache
tests/eval_corpus/*.pdf  tests/results  tsconfig.tsbuildinfo
```

违规检查（任何一项命中即中止打包）：
- 目录：.git / .venv / .paperlens / data / node_modules / .next / 各类缓存目录
- 文件：.env（真实）、*.pdf（版权）、*.pyc、*.log
- 内容特征：`OPENAI_API_KEY=…` / `DEEPSEEK_API_KEY=…` / `sk-[16+字符]` 密钥模式（含 .example 的文件除外）

## 5. 使用方式

```bash
python scripts/package_release.py            # 暂存 → 检查 → 打包
python scripts/package_release.py --check    # 只检查不打包
```

通过后输出：`✅ 检查通过：暂存 … 无 .env / 密钥 / 依赖 / 缓存 / 数据库 / PDF。`
