---
kind: issue
title: "原始证据回退的 pair_key 闭合验证"
type: bug
status: open
created: 2026-08-07
epic: ""
---

# 原始证据回退的 pair_key 闭合验证

## 目标

整卷作答在 `pair_key` 存在时，检索结果既不能带回其他场次的 Mark Scheme 等评分资料，
也不能把跨卷的原始证据 chunk 泄漏进当前题的答案上下文。修复后 raw fallback 与知识卡片
在来源边界上闭合一致。

## 范围

- 包含：`RagService._raw_fallbacks` / `_filter_cards_to_scope` 与 `_in_scope` 之间
  `pair_key` 边界的一致性核对与修复。
- 不包含：改变知识卡片构建规则、改检索的 dense/sparse 融合或 rerank 参数。

## 归属

- 独立 issue（不隶属现有 epic）。
- 相关 spec：`codestable/spec/index.md` “配对键先于语义相似”“整卷证据作答”边界。

## 当前证据

- 预期行为：`pair_key` 存在时，返回给 Agent 的节点（含 raw fallback）都必须属于该场次
  的 `pair_key`，评分资料（Mark Scheme / Examiner Report / question_paper）绝不进入作答。
- 实际行为：需要核对。`_in_scope` 在 retrieve 阶段已按 `pair_key` 与 `source_role` 过滤原始
  节点；`_filter_cards_to_scope` 对知识卡片按 `pair_key` 过滤；但 `_raw_fallbacks`
  （`rag.py:388-419`）在构建 raw fallback 时**只按 `(document_id, page, section)` 去重**，
  没有再次核对 `pair_key`——它依赖上游 reranked 节点“已过 scope”这一前提。
- 最小场景：`pair_key` 非空、某场次 rerank 结果混入非同场次但同文档/同页的原始节点时，
  raw fallback 可能带上不属于当前场次的证据。
- 原始证据：`backend/src/examtwin/assessment/rag.py` 的 `_raw_fallbacks` 与
  `_filter_cards_to_scope` 实现；`_in_scope` 仅出现在 retrieve 主路径。

## 根因定位

- 最可能根因：`_raw_fallbacks` 未在下游独立重申 `pair_key` / `authority_tier` / `source_type`
  边界，把“上游已过滤”当作不变前提；一旦上游 `_in_scope` 的 `source_role` 判定与卡片
  `_filter_cards_to_scope` 的边界口径不一致，raw fallback 就可能成为越界入口。
- 影响面：整卷作答与普通问答的证据边界；属于信息安全性 / 可核查性约束。

## 方案判断

- 核对 `_raw_fallbacks` 依赖的上游节点是否必然已满足 `pair_key` 与评分资料排除边界；
  若纯依赖上游，则在 `_raw_fallbacks` 内显式重申 `pair_key` 与 `source_role` 过滤，
  使 raw fallback 与卡片在来源边界上闭合一致。
- 补充针对“pair_key 非空时 raw fallback 不跨场次、不含评分资料”的单元测试。

## 验证

- 新增测试：构造含跨场次原始节点的 rerank 结果，断言 raw fallback 排除非同场次节点、
  且不含 mark_scheme / examiner_report / question_paper。
- 既有：`backend/tests/test_rag.py`、`test_paper_answering.py` 相关证据映射用例。

## 关闭回写

- project spec：`codestable/spec/index.md` “配对键先于语义相似”，确认 raw fallback 与
  知识卡片在 `pair_key` 边界上闭合一致。