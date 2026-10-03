# Agent Note: 文件字节统一经 ManagedObjectStore 与 PostgreSQL 对象目录管理

Status: implemented

## Problem

上传试卷、派生页图、转换缓存与答案图片由各模块自行拼路径，经多个易漂移的 bind mount 共享；对象的
用途、保留期、删除状态与对账没有统一所有者，宿主绝对路径还会写进数据库。

## Decision

- `ManagedObjectStore` 是 API、Worker 与 GC 唯一的文件接口；后端可为本地目录或 S3 兼容存储
  （Compose `--profile s3` 下的 SeaweedFS）。
- 每个对象在 PostgreSQL 对象目录记录用途、owner、SHA-256、大小、MIME、保留期与删除状态；数据库只存
  对象键，不存宿主绝对路径。
- 写入经临时文件原子替换；本地实现拒绝路径穿越。
- `storage-gc` 按保留期有界批处理删除，失败保留并重试；`storage-migrate` 幂等复制与登记旧文件，不删源。
- owner 表示生命周期归属，不是访问授权。

## Alternatives considered

- **各模块自行管理路径与多个 bind mount** — 无新组件。但保留期、删除和跨进程一致性没有所有者，迁移
  宿主路径时数据库记录失效。

## Consequences

- **收益**：生命周期、校验和与删除可对账；本地与 S3 后端可切换，业务模块不理解 bucket 或路径。
- **代价与已知上限**：多了一张目录表和一个 GC 服务；S3 模式依赖 SeaweedFS 容器。多用户部署时对象目录
  不能替代授权。
