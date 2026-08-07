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

确认 `RagService.retrieve` 的公开结果在显式检索范围下始终闭合，并消除“raw fallback 会跳过
pair_key 门禁”的不实风险描述。若公开路径已经保证该不变量，则只补契约回归并关闭，不在私有
helper 中复制一套容易漂移的过滤逻辑。

## 范围

- 包含：`RagService._raw_fallbacks` / `_filter_cards_to_scope` 与 `_in_scope` 之间
  `pair_key` 边界的一致性核对与修复。
- 不包含：改变知识卡片构建规则、改检索的 dense/sparse 融合或 rerank 参数。

## 归属

- 独立 issue（不隶属现有 epic）。
- 相关 spec：`codestable/spec/index.md` “配对键先于语义相似”“整卷证据作答”边界。

## 当前证据

- `retrieve` 在 Qdrant 召回前把 `subject_code`、Unit、`pair_key`、来源类型、权威等级和
  `source_role` 写入 payload must 过滤；召回后又由 `_in_scope` 对同一组字段做第二次门禁。
- `SiliconFlowReranker.rerank` 只按服务返回的索引重新引用输入 `nodes[index].node`，不能创建、
  改写或注入节点；`_expand_parent_context` 只用已通过门禁的子节点 metadata 替换其正文为同
  build 的父块内容，不改变节点作用域身份。
- `_raw_fallbacks` 的输入因此是已经通过两层过滤、且 rerank 不可扩张的节点集合。它只负责
  排除已由知识卡片表示的原文和去重，不是新的召回边界。
- 整卷 Answering Agent 的 `knowledge_search` 有意不传 `pair_key`：核心知识库的 syllabus /
  textbook 不是某一场试卷的配对资料；当前卷的 `pair_key` 只供 `paired_exam_lookup` 严格读取
  Question Paper Insert。Mark Scheme / Examiner Report 已从作答工具和允许的 source role
  中排除。
- 原事项的最小场景要求“rerank 结果凭空混入跨场次节点”，不可能由当前生产 reranker 构造；
  直接把越界节点塞给私有 `_raw_fallbacks` 只是在测试不可达状态，不能证明公开路径有漏洞。

## 根因定位

- 根因不是生产代码泄漏，而是审计时把去重 helper 误当成独立信任边界，并混淆了知识检索与
  严格配对试卷资料两个通道。
- 剩余真实风险是未来重构绕过 `retrieve` 的双层门禁，或让 reranker/父块扩展获得节点扩张
  能力；应由公开 `retrieve` 契约测试防止，而不是在每个下游 helper 重复过滤。

## 方案判断

1. 保持 `_raw_fallbacks` 单一去重职责，不新增第三套 `pair_key` / 来源过滤。
2. 补一个公开 `retrieve` 回归：底层召回同时返回同场次、跨场次和评分资料节点，断言只有合法
   节点能进入 reranker、知识卡片和 raw fallback。
3. 补一个 Answering Agent 工具回归：`knowledge_search` 不把当前试卷 `pair_key` 施加给
   syllabus/textbook；`paired_exam_lookup` 则必须使用该 `pair_key`。
4. 测试通过后将本事项按“风险不成立、契约已固化”关闭；无需改 project spec，因为现有
   “配对键先于语义相似”只适用于配对资料，不应扩张为核心知识库过滤规则。

## 验证

- `test_rag.py`：公开 `retrieve` 的 prefilter、postfilter、rerank 与 raw fallback 端到端范围
  完整性。
- `test_answering_tools.py` / `test_paper_answering.py`：知识检索与配对试卷工具的作用域分离。
- 若任一公开路径测试失败，才恢复为代码修复；否则不制造重复门禁。

## 关闭回写

- 不改 project spec；关闭结论需明确记录：核心知识检索不受当前试卷 `pair_key` 限制，
  严格配对资料由独立工具按 `pair_key` 读取。