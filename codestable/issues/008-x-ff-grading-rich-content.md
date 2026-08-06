---
kind: issue
title: "评分报告富文本与图形展示"
type: ff
status: closed
created: 2026-08-06
epic: ""
---

# 评分报告富文本与图形展示

## 做了什么

评分工作台现在完整展示被评分的原题、已保存答案及其图形/图片产物；评分规则、判分理由、学生证据和改进建议统一按 Markdown + KaTeX 渲染。

同时收紧评分数据一致性：报告只显示当前 rubric 版本的 assessment；逐题生成前必须存在已接受得分点；快速切换答卷时旧请求不能覆盖新选择；评分失败在当前步骤直接展示。

## 改了哪些

- `frontend/src/pages/Grading.tsx` — 接入统一富文本渲染并展示答案图形、图片产物。
- `frontend/src/components/AnswerDiagramView.tsx` — 图形标题和说明支持公式。
- `frontend/src/components/AnswerImageView.tsx` — 图片标题和说明支持公式。
- `frontend/src/styles.css` — 补齐评分富文本、公式横向溢出与响应式图片样式。
- `frontend/src/pages/Grading.test.tsx` — 覆盖公式、Markdown 图片和答案图片产物。
- `frontend/src/pages/Grading.tsx` — 仅加载已转换 Mark Scheme，按当前 rubric 过滤历史评分，校验已接受得分点，并为答卷切换增加竞态保护。
- `frontend/src/lib/markdown-math.ts` — 保留正文货币金额，同时继续识别合法行内公式。
- `frontend/src/pages/Grading.test.tsx` — 增加旧 rubric 隔离、答卷竞态、缺少得分点和评分失败回归覆盖。

## 怎么验证的

`pnpm test` 通过 13 个测试文件、27 项测试；`pnpm lint` 与 `pnpm build` 通过。实机评分页确认已完成答卷与 Mark Scheme 选择区正常加载；此前 9660 完整报告实测渲染 36 个 KaTeX 节点、1 个答案图形。

## 对 codestable/ 的影响

- 无已记录真相受影响；仅修正既有评分工作台的内容呈现。
