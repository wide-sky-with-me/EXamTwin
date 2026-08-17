---
kind: issue
title: "删除冗余标题说明"
type: ff
status: closed
created: 2026-08-12
epic: ""
---

# 删除冗余标题说明

## 做了什么

删除页面、列表和评分阶段标题下方的解释性小字，让任务名称和操作直接成为视觉主层级；保留分值、来源、进度、错误恢复和确认后果等必要信息。

## 改了哪些

- `frontend/src/App.tsx`、`frontend/src/pages/` — 移除品牌副标题和页面级说明文案。
- `frontend/src/components/PaperJobHistory.tsx`、`frontend/src/components/grading/` — 移除记录区与评分阶段的重复说明，题目标题仅保留实际分值。
- `frontend/src/styles.css` — 删除失效的副标题样式并收紧标题间距。

## 怎么验证的

`pnpm lint` 与 `pnpm build` 通过；真实浏览器复核科目管理、试卷作答、作答详情和人工复核页面，标题层级与间距正常。

## 对 codestable/ 的影响

- 无已记录真相受影响；本次改动落实 `codestable/epics/002-x-科目与考试工作流重构/spec.md` 已有的去除品牌副标题和解释性废话约束。
