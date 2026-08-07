# PaperLens 服务器部署

> 已部署：<server-ip>（腾讯云 2C2G）· /home/ubuntu/paperlens
> 外网入口：http://<server-ip>/（nginx :80 → web :3000 + api :8700）

## 架构

```text
浏览器 → nginx :80
           ├─ /        → Next.js web  :3000（pl-web.service）
           └─ /api/*   → FastAPI      :8700（pl-server.service）
                              ├─ SQLite（/home/ubuntu/paperlens/data）
                              └─ DeepSeek API（.env 配置）
```

## 部署步骤（从零）

```bash
# 1. 同步代码（本地构建 web，服务器只跑）
rsync -az --delete --exclude '.venv' --exclude 'node_modules' --exclude '.next' \
  --exclude '.paperlens' --exclude '.env' --exclude '.git' --exclude '__pycache__' \
  ./ ubuntu@<服务器>:/home/ubuntu/paperlens/

# 2. 服务器后端
ssh ubuntu@<服务器>
cd /home/ubuntu/paperlens
python3 -m venv .venv
# editable_mode=compat: new core modules (e.g. templates.py) become visible
# without reinstalling; the default static finder caches the module list.
.venv/bin/pip install -e core fastapi "uvicorn[standard]" python-multipart
.venv/bin/pip install -e core --no-deps --force-reinstall --config-settings editable_mode=compat
# .env：OpenAI 兼容端点配置（见 .env.example），PAPERLENS_DATA_DIR=/home/ubuntu/paperlens/data

# 3. 前端（本地构建产物直接同步，服务器无需 npm/bun）
cd web && NEXT_PUBLIC_API_BASE=http://<服务器IP> bun run build
rsync -az --delete .next/ ubuntu@<服务器>:/home/ubuntu/paperlens/web/.next/

# 4. systemd（文件在仓库 docs/systemd/）
sudo cp docs/systemd/*.service /etc/systemd/system/
sudo systemctl enable --now pl-server pl-web

# 5. nginx（docs/nginx/paperlens.conf）
sudo apt install nginx
sudo cp docs/nginx/paperlens.conf /etc/nginx/sites-available/paperlens
sudo ln -sf /etc/nginx/sites-available/paperlens /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

## 缓存策略（重要）

Next.js 静态页默认 `Cache-Control: s-maxage=31536000`（一年）——首页 HTML 被浏览器缓存后，前端更新永远不可见。nginx 已修正（见 `docs/nginx/paperlens.conf`）：HTML no-cache、`/_next/static/` 一年 immutable、API no-store。改前端后无需强制刷新。

## 安全组

只需放行 **80**（和 22）。3000/8700 只在内网，由 nginx 转发。

## 运维

```bash
sudo systemctl status pl-server pl-web     # 状态
sudo journalctl -u pl-server -f            # 后端日志
sudo journalctl -u pl-web -f               # 前端日志
sudo systemctl restart pl-server pl-web    # 重启
curl http://127.0.0.1:8700/api/health      # 健康检查
```

## 已知边界

- 任务队列为进程内线程（单进程）；云端多用户/PostgreSQL/独立 Worker 为后续里程碑。
- arXiv 导入下载受 arXiv API 礼貌限流（≥3s/请求）；服务器到 arxiv.org 偶发超时会重试或报错。
- 首次外部模型调用即用 .env 的端点（DeepSeek），无额外审批；多用户 HITL 待 P6 云端化。
