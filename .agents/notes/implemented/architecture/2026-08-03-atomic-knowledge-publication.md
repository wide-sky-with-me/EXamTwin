# Agent Note: 知识图谱单事务发布，向量索引 staging 后原子切换 alias

Status: implemented

## Problem

图谱与索引曾被就地重建：删除正式数据后再写新数据，任何中途失败都会留下半套或空数据，并直接影响
正在进行的作答。

## Decision

- 课程图谱、难度与题目观测都以 run 为单位在单个 PostgreSQL 事务内发布；候选校验失败时正式数据不变。
- 向量索引写入带 build id 的不可变 staging collection，记录输入哈希与检查点；点数门禁通过后原子切换
  该科 live alias，失败只保留 staging 与错误。
- 点数门禁使用 `count(exact=true)`。
- 部分索引（`index --limit`）禁止发布到 live alias。
- 中断恢复按节点 ID 补缺，不把 collection 点数当成写入偏移。
- 节点带稳定内容指纹；embedding 服务、模型、索引 schema 与内容都一致时才复用旧稠密向量。

## Alternatives considered

- **删除正式 collection 后就地重建** — 实现简单、不需要 alias。失败窗口内检索不可用，且失败会留下空索引。
- **以 `get_collection().points_count` 做门禁** — 调用便宜。实测 Qdrant 后台 segment 合并期间该值从精确
  的 18,307 短暂偏高为 18,502，门禁因此拒绝了正确的构建。
- **跨 schema 复用全部旧向量** — 节省 embedding 费用。旧 prose 节点把运行期导航 ID 写进了 embedding
  内容，与新内容不等价，只能复用指纹一致的节点。

## Consequences

- **收益**：失败时上一版本始终在线；发布可审计、可恢复；未变节点不重复付费。
- **代价与已知上限**：发布期间新旧 collection 同时占用存储；staging 需要人工或后续流程清理。
