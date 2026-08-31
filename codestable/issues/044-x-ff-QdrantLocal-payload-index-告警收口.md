---
kind: issue
title: "QdrantLocal payload index 告警收口"
type: ff
status: closed
created: 2026-08-31
---

# QdrantLocal payload index 告警收口

## 做了什么

确认全量测试中的 payload index 告警不是 Linux 或 Qdrant 容器故障，而是
`QdrantClient(":memory:")` 使用的 `QdrantLocal` 明确不实现 payload 索引。
本地后端仍执行 payload 过滤，只是无法获得服务器索引的性能加速。

## 改了哪些

- 向量存储工厂识别 `QdrantLocal`，对其禁用无效的 `doc_id` 与自定义
  payload index 创建请求。
- 服务器型 Qdrant 无论使用 hybrid 还是 dense-compatible 集合，都创建
  `doc_id` 和全部检索过滤字段索引，修复旧集合只有 `doc_id` 的性能缺口。
- 新增回归测试，将警告升级为异常，证明内存混合检索不再发出该告警。

## 怎么验证

- 原始告警用例可稳定复现；修复后同一内存混合检索路径无警告。
- 真实 Qdrant 容器的数学、经济活动 Core collection 均读到 12 个
  payload schema 索引，包含 `doc_id` 和 11 个检索过滤字段。
- 对旧 `examtwin_9640_live` 和 `examtwin_9660_live` 在线补齐索引，两者现均为
  12 个 payload schema；未重建向量或切换 alias。
- 全量后端在 `-W error::UserWarning` 下运行为 566 passed、1 skipped，
  原 QdrantLocal 警告不再出现。

## 对 `codestable/` 的影响

不改变项目规格或检索语义；只对测试/开发用的内嵌后端做能力适配。
