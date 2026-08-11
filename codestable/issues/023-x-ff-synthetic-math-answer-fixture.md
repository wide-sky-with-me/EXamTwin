---
kind: issue
title: "新增合成数学作答测试样本"
type: ff
status: closed
created: 2026-08-11
epic: "002-o-科目与考试工作流重构"
---

# 新增合成数学作答测试样本

## 做了什么

初始化当前仓库 Codegraph，并为严格配对的 OxfordAQA 9660 2019 JAN P1 新增一份合成外部
作答样本。样本明确声明非真实学生数据，保留 5 个已标注错误供导入、评分和复核测试。

## 改了哪些

- `data/test-fixtures/oxfordaqa-mathematics-9660-2019-jan-p1/` — 新增答案、来源元数据、预期评分和使用说明。
- `.gitignore` — 只放行可版本化的 `data/test-fixtures/**`，其余正式语料继续忽略。
- `.codegraph/` — 生成本地忽略的代码索引，不进入 Git。

## 怎么验证的

Codegraph 状态为 297 文件、5,640 节点、13,563 边且索引最新；实际外部答案切分器识别
Q1–Q10。JSON、80/74 分值合计、5 个错误、QP/MS 身份与 SHA-256 均通过校验；相关测试 1 passed。

## 对 codestable/ 的影响

- 无已记录真相受影响：本次只增加支持现有外部答案工作流的隔离测试资产，不改变产品契约。
