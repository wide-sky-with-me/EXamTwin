---
kind: issue
title: "发布 9660 版本化核心索引"
type: ff
status: closed
created: 2026-08-06
epic: "001-o-多科目知识生产与难度证据流水线"
---

# 发布 9660 版本化核心索引

## 做了什么

确认“索引待发布”不是 Qdrant 构建失败，而是旧 22,011 点混合索引未进入新版工作区版本账本。按 9640 的来源隔离方式，为 9660 构建并发布只含官方课纲和授权核心教材的 Core Knowledge Base v1。

## 改了哪些

- 运行数据 — 发布 1 份 syllabus 与 3 份 `licensed_core` textbook，生成 4,975 点版本化核心索引。
- `codestable/spec/index.md` — 同步 9660 Core v1 与旧混合 alias 的当前边界。

## 怎么验证的

构建结果为 4/4 文档成功、0 失败；版本与向量构建账本均为 `published`，4 个文档生成 7,760 个层级块。`/api/v1/subjects/status` 返回 9660 `vector_index_ready=true`、Core v1、4,975 点，Qdrant live alias 指向该版本 staging collection。

## 对 codestable/ 的影响

- 已同步 project spec：`codestable/spec/index.md`。
