# 对象存储

所有可写文件字节经 `platform/storage.py` 的 `ManagedObjectStore` 读写。API、Worker 与 GC 只依赖这一
接口，不自行拼接路径或 bucket 键。

## 后端

| `OBJECT_STORE_BACKEND` | 实现 | 用途 |
|---|---|---|
| `local` | `LocalObjectStore`，根目录 `EXAMTWIN_STORAGE_ROOT`（默认 `./var`） | 测试与无额外镜像的本地运行 |
| `s3` | `S3ObjectStore`，Compose `--profile s3` 下的 SeaweedFS 4.27 | 本机 Docker 部署 |

S3 后端带本地物化缓存 `OBJECT_STORE_CACHE_DIR`；缓存可随时删除，`materialize` 会重新下载。远程 S3
配置拒绝默认开发凭据。

## 对象目录

每个对象在 PostgreSQL 记录用途（purpose）、owner（type 与 id）、SHA-256、大小、MIME、保留期与删除状态。
owner 表示生命周期归属，不是访问授权。

| 分区 | 内容 | 默认保留 |
|---|---|---|
| `corpus-sources/` | 科目资料原件 | 随资料生命周期 |
| `corpus/md` | 转换后的 Markdown 缓存 | 不自动过期 |
| `paper-jobs/` | 上传试卷与派生页图 | 30 天（`PAPER_OBJECT_RETENTION_DAYS`） |
| `answer-artifacts/` | 答案 PNG | 30 天（`ANSWER_ARTIFACT_RETENTION_DAYS`） |

写入采用临时文件原子替换；本地实现拒绝路径穿越。

## 回收

`storage-gc` 服务按 `STORAGE_GC_INTERVAL_SECONDS` 有界批处理过期对象（`STORAGE_GC_BATCH_SIZE`）；删除失败
在目录中保留并重试。永久删除作答等业务动作把对象标为立即回收。手工命令见
[storage-operations](../cookbook/storage-operations.md)。
