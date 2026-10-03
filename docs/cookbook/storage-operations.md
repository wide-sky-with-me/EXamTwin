# 对象存储运维

## 启用 S3 后端

```bash
OBJECT_STORE_BACKEND=s3 docker compose --profile s3 up -d --build
```

SeaweedFS 4.27 按官方 `weed mini` 方式创建带凭据的 bucket，只监听 loopback。

## 迁移本地文件到 S3

1. 预演：`OBJECT_STORE_BACKEND=s3 uv run examtwin storage-migrate --dry-run`
2. 执行：`OBJECT_STORE_BACKEND=s3 uv run examtwin storage-migrate --execute`

迁移是幂等复制与登记，不删除源文件。

## 回收与对账

- 手工执行一批过期对象回收：`uv run examtwin storage-gc`
- 查看按生命周期状态汇总的数量与字节：`uv run examtwin storage-stats`
- 往返验证当前后端：`uv run examtwin storage-smoke`

`storage-gc` 服务持续按保留期有界批处理；删除失败保留在 `stored_objects` 中并重试。

## 数据卷

PostgreSQL、Qdrant 与 SeaweedFS 使用 `compose.yaml` 声明的命名卷（项目前缀 `examtwin_examtwin_*`）。
删除任何卷前先确认挂载它的容器与卷内数据，并核对 `docs/postmortem/` 中的相关记录。
