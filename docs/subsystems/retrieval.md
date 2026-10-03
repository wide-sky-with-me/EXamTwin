# 检索

`assessment/rag.py` 的 `RagService.retrieve` 是检索的唯一公开入口，服务普通问答与答题 Agent 的
`knowledge_search` 工具。检索永远在当前科目的已发布知识库版本内进行。

## 管线

1. **范围预过滤**：Qdrant payload `must` 条件限定 `subject_code`、知识版本、Unit、配对键、来源类型、
   权威等级与 `source_role`（作答检索只允许 `core_knowledge`、`supplementary_knowledge`）。
2. **候选召回**：稠密向量与确定性词法稀疏向量混合召回；已发布图谱可提供查询扩展词。
3. **课程节点**：`knowledge_point` 节点是核心图谱在索引中的身份投影（`source_role=core_knowledge`）。
   它们由本地稀疏排名与确定性课程定义匹配排序，候选窗口为 256，不进入外部 reranker。
4. **重排**：外部 reranker 只处理原文证据；超时或失败时退回已通过门禁的混合分数顺序，并在 trace
   标记 `rerank_fallback`。
5. **后置门禁**：`_in_scope` 对同一组字段做第二次校验；reranker 与父块展开都不能扩张节点身份。
6. **知识卡片与原始补位**：知识卡片必须有当前范围内真实召回节点的代码绑定或原文匹配，每张最多两条
   去重强证据；纯题干词面相似不生成卡片。未被卡片覆盖的原文证据保留少量补位。

课程节点只提供规范知识身份，不单独充当答案引用；最终引用必须落到允许的 syllabus / textbook 原文。

## 作答检索的来源边界

- Question Paper、Mark Scheme、Examiner Report 不是作答证据。
- `knowledge_search` 不按当前试卷配对键过滤，因为核心知识库不属于某一场考试。
- Source Booklet 只经 `paired_exam_lookup` 按精确配对键读取。

## 结果契约

响应返回答案、引用、置信度、`grounded` 与警告；没有证据时拒答。`grounded` 表示回答声称由当前
检索证据支撑，不是独立事实核验。

## 评测与诊断

- `uv run examtwin retrieval-evaluate`：对 live alias 运行 SubjectPack 的 `retrieval-eval.json`，计算
  Recall@K、MRR、空结果率与范围越界数，未达包内门禁时非零退出。
- `uv run examtwin retrieval-traces`：查看 PostgreSQL 中按科目有界保留的检索 trace（查询哈希、过滤条件、
  索引 build、候选阶段）。

评测查询会发送到外部 embedding / rerank 服务，运行前需要明确授权。
