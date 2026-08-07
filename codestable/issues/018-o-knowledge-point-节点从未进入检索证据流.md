---
kind: issue
title: "knowledge_point 节点从未进入检索证据流"
type: bug
status: open
created: 2026-08-07
epic: ""
---

# knowledge_point 节点从未进入检索证据流

## 目标

索引中的 knowledge_point 节点应当能如其设计那样进入检索证据流，使知识点卡片能直接绑定
知识点节点证据（`queries.py` 中 `node_kind == "knowledge_point"` 的高分路径真正生效）；
或者，若知识卡片本就不依赖这些节点，则删除相关死代码并把 knowledge_point 节点从索引中
移除，消除索引侧与检索侧的契约漂移。

## 范围

- 包含：knowledge_point 节点 metadata 的 `source_role` 契约；检索侧 Qdrant 过滤与
  `_in_scope` 对 knowledge_point 节点的放行；`queries.py` 中 knowledge_point 分支的激活
  或移除。
- 不包含：改变 evidence_chunk 的检索逻辑、改 dense/sparse 融合或 rerank 参数。

## 归属

- 独立 issue（不隶属现有 epic）。
- 相关 spec：`codestable/spec/index.md` “用证据回答问题”“整卷证据作答”能力边界。
- 关联：`codestable/issues/012-o-原始证据回退的-pair-key-闭合验证.md`（同为检索边界闭合的
  同类问题）。

## 当前证据

- 预期行为：index 构建写入的 knowledge_point 节点与其关联证据正常参与检索，`build_retrieval_cards`
  能收到 `node_kind == "knowledge_point"` 的 evidence 并给知识点直达高分。
- 实际行为：knowledge_point 节点被写入 Qdrant，但因缺少 `source_role` 字段，在检索侧被
  Qdrant payload 过滤与 `_in_scope` 双重拦截，永远无法进入证据流；`queries.py` 的知识点
  高分路径是死代码。
- 最小场景：任一次 `retrieve()` 使用 `source_roles=("core_knowledge","supplementary_knowledge")`
  过滤，knowledge_point 节点（无 `source_role` payload）在 Qdrant 层即被排除。
- 原始证据：
  - 写入：`backend/src/examtwin/knowledge/ingestion.py` 的 `_knowledge_point_nodes`（metadata
    无 `source_role`）与 `build_vector_index`（`nodes = [*evidence_nodes, *_knowledge_point_nodes(catalog)]`）。
  - 检索过滤：`backend/src/examtwin/assessment/rag.py` 的 `_in_scope`（要求
    `source_role in {"core_knowledge","supplementary_knowledge"}`）及 `retrieve` 中
    `retrieval_filters(source_roles=(...))`。
  - 消费端：`backend/src/examtwin/knowledge/queries.py` 的 `build_retrieval_cards`（159 行
    给 `node_kind == "knowledge_point"` 特殊高分，193 行跳过它——证明其本应出现在 evidence_items）。

## 根因定位

- 最可能根因：`source_role` 过滤（模块化重构引入）最初只针对 evidence 节点设计，重构时没有
  同步给 `_knowledge_point_nodes` 补 `source_role`，生产者 / 消费者 / 检索过滤器三处对
  knowledge_point 节点的预期不一致。
- 证据：`ingestion.py:127` 只在 `_documents_with_pages` 的 `common_metadata` 设 `source_role`，
  `_knowledge_point_nodes` 的 metadata 字典没有该字段。
- 影响面：知识卡片当前完全依赖 evidence_chunk 的 `knowledge_code` 注解与 `match_knowledge_points`
  词面匹配；知识点直达的高分绑定路径长期无效。

## 方案判断

采用方案 A：`knowledge_point` 是已发布核心知识图谱节点在检索索引中的投影，不是普通原文块；
它应使用 `source_role="core_knowledge"` 通过当前作答检索门禁，并由 `queries.py` 的显式高分
分支把节点身份绑定到知识卡片。删除节点会让已实现的图谱直达语义退化为词面匹配，同时索引和
消费端已有明确契约，因此不选方案 B。

该选择不把知识点摘要冒充可引用原文：最终答案引用仍必须落到卡片关联的 syllabus/textbook
`evidence_chunk`。`knowledge_point` 只提供规范代码、标题、层级和图谱关系，不单独成为答案
正文的引用来源。

## 实现设计

1. `_knowledge_point_nodes` 写入 `source_role="core_knowledge"`，并保持 subject、Unit、
   `node_kind`、知识版本和 graph 版本 payload 完整。
2. 增加生产者契约测试，断言节点能通过 `retrieval_filters` 与 `_in_scope`；增加消费端测试，
   断言 `build_retrieval_cards` 命中 knowledge_point 高分分支并仍绑定原文 evidence。
3. 用 staging collection 重建索引，先验证 knowledge_point 可召回、范围越界为 0、引用仍只
   来自允许的 evidence_chunk，再原子切换 live alias；不得直接修改现有 live collection。
4. 分别对 9660/9640 运行现有黄金集与一条知识点直达真实查询；Recall/MRR/空结果率不得低于
   各科当前门禁，`scope_violations` 必须为 0。
## 影响范围

- 必须修改：`backend/src/examtwin/knowledge/ingestion.py`（`_knowledge_point_nodes` metadata）
  或 `backend/src/examtwin/knowledge/queries.py`（死代码）。
- 需要验证：`backend/tests/test_rag.py`、`test_vector_retrieval.py`、`test_knowledge_enrichment.py`
  中 knowledge_point 相关断言。
- 仍待调查：使用当前 9660/9640 索引确认 knowledge_point 节点是否真被 `_in_scope`/Qdrant 过滤
  丢弃（可在 `_in_scope` 加临时日志或核对 `retrieval-traces` 的 `node_kind` 分布）。

## 验证

- 方案 A：新增/调整测试，断言 knowledge_point 节点带 `source_role` 且可通过 `_in_scope`，
  `build_retrieval_cards` 能收到 `node_kind == "knowledge_point"` 证据并命中高分分支。
- 方案 B：断言 `queries.py` 不再引用 knowledge_point 分支，索引不含 knowledge_point 节点。
- 回归：整卷作答与普通问答的引用/卡片构建不回归。

## 关闭回写

- project spec：`codestable/spec/index.md` “用证据回答问题”能力边界，记录 knowledge_point
  节点在检索中的角色（绑定知识点节点证据，或从索引中移除）。
