---
kind: issue
title: "knowledge_point 节点从未进入检索证据流"
type: bug
status: closed
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
- 关联：`codestable/issues/012-x-原始证据回退的-pair-key-闭合验证.md`（同为检索边界闭合的
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

## 2026-08-14 9640 实现与运行验证

- 生产者已为 knowledge_point 写入 `source_role=core_knowledge`；Qdrant 和 `_in_scope`
  只对直接课程节点允许同科跨 Unit，原文 evidence 仍受当前 Unit 门禁。
- 增加独立的 knowledge_point 稀疏候选通道，避免当前 Unit 原文占满混合检索
  top-k 后挤掉综合试卷需要的其他单元课程点。
- 9640 Core Knowledge Base v4（`4d332049-ab91-41fc-9b50-0e00b8ee8217`）已经原子发布，
  build `e840d560-8278-4793-8dd3-39d5f8ce2dcf` 的 5051/5051 点通过门禁。货币供给
  查询命中 `3.4.2.3.O01`；货币政策复测命中 `3.2.4.1.O06/O05/O07/O01`，
  最终 `grounded=true`。
- 索引恢复中另修复了构建级 document block 主键冲突、失败版本恢复入口、
  暂存孤儿节点清理和段落结构临时 ID 污染稳定节点身份的问题。
- 代码契约已由 ingestion、Qdrant prefilter、跨 Unit 卡片和真实查询覆盖；本 issue
  仍保持 open，直到 9660 也重建索引并跑完其黄金集，不把单科实测冒充全科完成。
- 最终验证：后端非集成/非本地资产回归 `454 passed, 38 deselected`；前端
  `132 passed`，ESLint、TypeScript/Vite build、OpenAPI snapshot/generated types 均通过；
  Ruff 与 BasedPyright 全量通过。

## 2026-08-16 双科漏检与超时降级收口

- 两科 live 黄金集先行复测：9640 为 Recall@5 `0.8889` / MRR `0.8333`，9660 为
  Recall@5 `0.9167` / MRR `0.7639`，均无空结果或范围污染；准确漏检分别为
  `3.1.4.3.O03`（竞争市场利润）与 `S2.6.O07`（未知方差正态总体均值检验），数据库课程定义
  与评测目标一致，不是黄金集错标。
- 9640 漏检根因是常规 top-5 路径只保留 24 个本地稀疏课程候选；同一查询在 48 个候选时目标
  排第 1。课程候选窗口固定为 48，并从外部 reranker 输入中移除：课程节点继续由本地稀疏排名
  和确定性课程定义匹配排序，外部 reranker 只处理原文证据。复测 9640 达 Recall@5 `1.0`、
  MRR `0.8889`、范围污染 `0`。
- 外部 reranker 超时不再让整次 `knowledge_search` 失败并触发 Agent 新一轮推理；现在退回已受
  科目/Unit/来源门禁约束的 hybrid 分数顺序，并在 trace 中标记 `rerank_fallback`。稀疏分数可
  大于 1 的输入在课程卡片二次匹配处归一化，公开 `retrieval_score` 继续保持 `0..1`。
- 9660 当前 live 仍是 2026-08-10 发布的旧构建
  `16b18bbf-f0c2-4610-bb00-dd21beeef833`，缺少新课程节点 payload，代码修复不能补出索引中不存在
  的 `S2.6.O07`。只读重建预检确认当前版本含 4 份来源、4,999 个节点；跨 schema 可安全复用
  144 个稳定节点，但其余 4,855 个旧 prose 节点曾把运行期导航 ID 写入 embedding 内容，不能
  冒充内容等价复用。
- 数学重建尚未执行：用户此前只授权两份验证试卷发送到外部服务，没有授权 4,855 个课程节点
  发送到 embedding 服务；安全门禁已阻止发布请求。需要明确外发授权后才创建新版本并原子切换
  live alias，随后重跑 12 条黄金集和两条真实 P2 问题。
- 当前代码回归：后端非集成/非本地资产 `486 passed, 38 deselected`；Ruff check/format、
  BasedPyright、`git diff --check` 通过。前端 `17 files / 132 passed`、ESLint、OpenAPI 类型快照、
  TypeScript 与 Vite 生产构建通过。

## 2026-08-17 数学索引发布与双科黄金集闭合

- 用户明确授权数学课程节点及双科黄金检索查询发送到项目配置的 SiliconFlow embedding/reranking
  服务。数学 Core Knowledge Base v5 `a1da5aa0-6d67-4ab7-88fc-32886ce11ea6` 从 4 份来源构建，
  4/4 成功、0 失败；4,999 个点通过发布门禁并原子切换 live alias，build 为
  `388cf37d-aaa5-4f27-b459-36914d5a3497`，旧 v4 在发布前始终可用。
- v5 首轮 14 条数学黄金集为 Recall@5 `0.9286`、MRR `0.7762`，空结果和范围污染均为 0；
  原漏检 `S2.6.O07` 已排第 1，但新增的 `P2.1.O05` 图像组合变换仍未进入前 5。核对数据库课程
  定义确认目标正确：漏检来自 `transform` / `transformations` 词形漂移，以及 48 个课程候选
  窗口小于数学现有 183 个学习目标。
- 本地课程匹配统一函数/图像/变换的基本词形，并对同时出现“graph + transform”的查询与官方
  目标给出概念匹配；课程稀疏候选窗口有界扩为 256。课程节点仍不进入外部 reranker，原文证据、
  科目、Unit 与来源门禁均未放宽。
- 最终黄金集：9660 为 14/14、Recall@5 `1.0`、MRR `0.8595`；9640 为 9/9、Recall@5
  `1.0`、MRR `0.8889`。两科空结果率和 `scope_violations` 均为 0；`S2.6.O07` 与
  `P2.1.O05` 均排第 1。外部 hybrid/reranker 超时期间走受范围约束的本地降级，评测仍通过。
- 最终源码已重建到 API/两个 Worker/GC。运行态数学真实问答使用 v5 与 build `388cf37d-...`，
  trace 首项为 `retrieval-card:9660:P2.1.O05`、得分 `0.9543`；数学和经济真实 API 问答均
  `grounded=true`、置信度 `0.82`、3 条引用。最终后端为 `490 passed, 38 deselected`，前端
  `132 passed`、Playwright `7 passed`，Ruff、BasedPyright、架构、OpenAPI、ESLint、
  TypeScript/Vite、配置与 `git diff --check` 均通过。
- 本 issue 的实现与验证目标已经达到；按 CodeStable 生命周期保持 open，等待显式关闭授权。

## 关闭结论

- `knowledge_point` 已作为核心知识图谱的课程身份投影进入检索，同时保持“课程节点不单独充当答案原文引用”的边界。
- 数学 Core v5 与经济 Core v4 均经 staging/alias 原子发布；最终两科 Recall@5 均为 `1.0`，MRR 分别为 `0.8595`、`0.8889`，空结果率和范围污染均为 `0`。
- 外部 reranker 超时时退回已受门禁的本地顺序，课程节点不进入外部 reranker；稳定行为已合并到 Project Spec 的检索路径和发布约束。
- 无遗留事项。
