# Agent Note: 试卷单元显式关联资料，作答冻结单元与 Question Paper 文档

Status: implemented

## Problem

页面把每份 Question Paper 当作一张试卷，再按 `pair_key` 临时搜索 Mark Scheme 与 Insert；无法表达显式
绑定、解绑和整组归档。同一配对键可能存在多份 Question Paper，作答任务也不知道自己属于哪一份。

## Decision

- `paper_units` 以 `(subject_id, pair_key)` 唯一标识一次考试单元；`paper_unit_documents` 显式保存单元内
  每份资料及其角色。一份资料只属于一个单元，同一角色允许多份。
- 绑定时服务校验资料属于当前科目、状态可用、配对键完全一致且角色与 `source_type` 一致。
- `paper_jobs` 保存 `paper_unit_id` 与 `question_paper_document_id`；新作答同时冻结两者，迁移前的任务
  只能可靠回填单元。
- 存在关联作答时拒绝归档单元；被作答、评分或难度证据引用的资料不能经单元删除绕过审计。
- `pair_key` 只由考试身份解析器生成，不能由向量相似度或界面自由输入。

## Alternatives considered

- **在 `paper_units` 上放 QP / MS / Insert 三个单值外键** — 结构最简单。现有数据已证明同一角色可能有多份
  来源，单值外键会在迁移时静默丢数据。
- **继续按 `pair_key` 临时聚合** — 无需迁移。无法表达显式绑定和删除保护，作答与评分只能临时配对。

## Consequences

- **收益**：试卷是有生命周期的业务对象；作答、评分与 URL 都有稳定上下文。
- **代价与已知上限**：上传资料与绑定单元是两步；旧作答缺少精确 Question Paper 文档。
