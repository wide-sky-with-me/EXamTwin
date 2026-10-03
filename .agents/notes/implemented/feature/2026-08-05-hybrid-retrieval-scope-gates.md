# Agent Note: 混合召回在双层范围门禁内进行，课程节点只提供知识身份

Status: implemented

## Problem

真实黄金集暴露两类问题：知识卡片在精确范围下回退到 syllabus 元数据，产生越界结果（12 条中 8 条）；
`knowledge_point` 节点因缺少 `source_role` 被过滤，知识点直达路径从未生效，两科各有目标稳定漏检。
外部 reranker 超时还会让整次 `knowledge_search` 失败并触发 Agent 重新推理。

## Decision

- Qdrant payload 预过滤科目、版本、Unit、配对键、来源类型、权威等级与来源角色；召回后 `_in_scope`
  再校验一次。reranker 与父块展开不能扩张节点身份。
- 稠密向量与确定性词法稀疏向量混合召回，再对原文证据 rerank。
- `knowledge_point` 节点以 `source_role=core_knowledge` 进入检索，作为核心图谱的身份投影；由本地稀疏
  排名与确定性课程匹配排序（窗口 256），不进入外部 reranker，不单独充当答案引用。
- 知识卡片必须有当前范围内的真实召回节点支撑；无支撑时退出，由原文证据补位。
- reranker 超时退回已通过门禁的混合分数顺序，trace 标记 `rerank_fallback`。
- 默认不做 LLM 查询改写。

## Alternatives considered

- **从索引删除 `knowledge_point` 节点** — 消除契约漂移最快。会让图谱直达语义退化为词面匹配。
- **课程候选窗口保持 24 或 48** — 小窗口便宜。实测经济漏检目标在 48 窗口排第一而在 24 窗口缺失，数学 183 个
  目标超出 48 窗口。
- **默认 HyDE / 查询改写** — 可能改善多跳召回。见 [被否记录](../../rejected/feature/2026-08-05-default-query-rewrite.md)。
- **reranker 失败即整体失败** — 语义最严格。会触发 Agent 新一轮推理，放大外部波动。

## Consequences

- **收益**：双科黄金集 Recall@5 为 1.0、范围越界为 0（实测 MRR 数学 0.8595、经济 0.8889）。
- **代价与已知上限**：课程节点窗口随科目目标数增长需重新评估；降级顺序的排序质量低于 rerank。
