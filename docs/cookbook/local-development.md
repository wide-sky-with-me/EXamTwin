# 本地开发与运行

## 前置

- `uv`（Python 由 `.python-version` 固定）、Docker Compose、`pnpm 11.1.1`。
- 私有 `.env` 从 `.env.example` 复制并手工填写密钥；`.env` 不入库，权限 600。

## 标准启动（Linux 原生 Docker）

1. 校验配置契约：`uv run examtwin config-check`（Settings、Compose-only 字段、`.env`、`.env.example` 四方一致）。
2. 启动全部服务：`docker compose up -d --build`，`docker compose ps` 中 `api` 必须为 `healthy`。
3. 初始化与清点：`uv run examtwin init`、`uv run examtwin inventory`。
4. 前端：`cd frontend && pnpm install && pnpm dev`，页面 `http://localhost:5173`，API 文档 `http://localhost:8000/docs`。

健康检查要求 HTTP 200、当前 API 契约版本与全部能力同时存在。代码变化后执行
`docker compose up -d --build api paper-worker storage-gc`，保证 API、Worker 与 GC 同版本。

## Docker Desktop / WSL

Docker Desktop 的 `host` 网络可能只在 Docker VM 内可达。此时叠加 `compose.local.yaml`：数据库、向量库与
S3 在 Compose 网络互联，API 仍只监听容器 loopback，同网络命名空间的 Nginx 代理只发布到宿主
`127.0.0.1`。代理内部使用 18001 端口，`API_PORT` 不能设为 18001。

1. 在 `.env` 选择空闲 `API_PORT`（如 `18000`）；使用 S3 时设置非默认 `OBJECT_STORE_ACCESS_KEY` 与随机
   `OBJECT_STORE_SECRET_KEY`。
2. 容器需要代理访问模型服务时设置 `CONTAINER_PROXY_URL`（如 `http://host.docker.internal:7897`）；
   覆盖文件不继承宿主 shell 的 `HTTP_PROXY`，因为容器内的 `127.0.0.1` 不是宿主机。
3. 启动：

```bash
uv sync --frozen --group dev
uv run examtwin config-check
docker compose -f compose.yaml -f compose.local.yaml --profile s3 up -d --build --wait
cd frontend
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1 --strictPort
```

页面 `http://127.0.0.1:5173`，API 文档 `http://127.0.0.1:18000/docs`。后续重建必须使用相同的两个
Compose 文件；只用主文件会切回 `host` 网络。Docker Desktop 重启后若容器以 bind mount 错误退出，
加 `--force-recreate` 重建。

## 访问边界

API 默认 `API_BIND_HOST=127.0.0.1`，ASGI 边界拒绝非 loopback 客户端，并校验 Host 与浏览器 Origin；
自定义前端域名需加入 `CORS_ORIGINS`，无 Origin 的本机 CLI 请求可用。不要同时把 `LOCAL_ACCESS_ONLY=false`
与非 loopback 绑定用于 LAN 或公网。

## 上传容量

默认试卷 25 MiB、配套材料 256 MiB（`KNOWLEDGE_UPLOAD_MAX_BYTES`）；本地 Nginx 代理按两者之和加 multipart
开销放行。提高上限时同步调整 `scripts/local-proxy.conf.template`。
