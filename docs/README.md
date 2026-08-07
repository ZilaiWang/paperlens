# docs 索引

| 文档 | 内容 |
|---|---|
| [DEPLOY.md](DEPLOY.md) | 服务器部署：rsync 同步、systemd、nginx、代理配置 |
| [PROGRESS.md](PROGRESS.md) | 里程碑与状态记录（V3.0A → V4.x） |
| [AUDIT_COMPARISON.md](AUDIT_COMPARISON.md) | 多篇比较专项审计 |
| [systemd/](systemd/) | pl-server / pl-web 服务单元文件 |
| [nginx/](nginx/) | nginx 站点配置（含缓存策略与 PDF 缓存例外） |

## 部署

```bash
# 同步代码（从仓库根目录执行，排除本地数据与依赖）
rsync -az --delete --exclude '.venv' --exclude 'node_modules' --exclude '.next' \
  --exclude '.paperlens' --exclude '.env' --exclude '.git' --exclude 'data' \
  ./ ubuntu@<server>:/home/ubuntu/paperlens/
```

完整步骤见 [DEPLOY.md](DEPLOY.md)。
