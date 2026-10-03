# Agent Note: 每次检索默认先做 LLM 查询改写（HyDE）

Status: rejected — Agent 已可迭代检索，强制改写增加延迟和伪关键词且无漏召回证据

## Problem

部分考试题的用词与课纲表述不同，直接用题干检索可能漏召回相关知识点。

## Proposal

在 `retrieve` 前固定调用一次 LLM 生成假设答案或改写查询，用改写结果召回。

## Alternatives considered

- **由答题 Agent 自行多次调用 `knowledge_search`** — Agent 能根据观察调整查询，不对每次检索都付出生成成本。
  采用此方式。
- **扩大课程候选窗口并统一词形** — 针对已观察到的漏检（如 transform / transformations）直接修复，见
  [混合召回](../../implemented/feature/2026-08-05-hybrid-retrieval-scope-gates.md)。

## Risks

每次检索多一次生成会增加延迟，并可能引入题目中不存在的伪关键词。重提前提：黄金集出现可复现的多跳漏召回，
且只作为有门槛的回退路径而不是默认步骤。
