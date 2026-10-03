# Agent Note: 核心与补充知识库按来源角色隔离，评估资料不进入作答检索

Status: implemented

## Problem

所有已转换资料曾进入同一索引：Mark Scheme 与 Examiner Report 可以被作答检索读到，等于让模型看着答案
作答；未授权资料与官方课纲混在一起，引用的权威性无法区分。

## Decision

- 每科两类知识库：核心只接受 `syllabus` 与确认授权的 `textbook`；补充接受 `slide`、`revision_note`、
  `topic_practice` 与确认授权的 `textbook`；`syllabus` 只能入核心。
- Question Paper、Mark Scheme、Examiner Report、Insert 的来源角色为 `assessment_only`，不进入任何知识库。
- 作答检索只允许 `core_knowledge` 与 `supplementary_knowledge`；Source Booklet 只经 `paired_exam_lookup`
  按精确配对键读取。
- `knowledge_search` 不按当前试卷配对键过滤：核心知识库不属于某一场考试；配对键只约束配卷资料。
- 资料归属规则只由 `subjects/document_assignment.py` 决定，Repository 不重复判断。
- 作答运行冻结实际使用的知识库与图谱版本。

## Alternatives considered

- **全部资料进入同一索引** — 召回面最大。评估资料泄漏会让答案与评分失去意义。
- **对核心知识检索也施加试卷配对键** — 看起来更“严格”。会把与具体场次无关的课纲和教材全部过滤掉；
  严格配对只适用于考试资料。
- **在每个下游 helper 再做一遍范围过滤** — 多一层保险。范围已由公开 `retrieve` 的预过滤与后置门禁保证，
  第三套过滤会与前两层漂移；改为用公开路径契约测试固化。

## Consequences

- **收益**：答案只引用允许的原文；评分资料与作答隔离。
- **代价与已知上限**：补充资料需要人工标注类型与授权；未分类资料不能进入知识库。
