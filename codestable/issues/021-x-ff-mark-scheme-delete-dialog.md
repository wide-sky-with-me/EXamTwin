---
kind: issue
title: "Mark Scheme 删除与确认弹窗修复"
type: ff
status: closed
created: 2026-08-11
epic: "002"
---

# Mark Scheme 删除与确认弹窗修复

## 做了什么

修正成功删除 Mark Scheme 后被误报失败的问题；删除当前使用项时立即清空选择。所有确认弹窗统一保留微透、模糊的页面背景。

## 改了哪些

- `frontend/src/lib/api.ts` — 接受成功的 `204 No Content` 响应。
- `frontend/src/pages/Grading.tsx` — 删除成功后先更新本地材料列表和当前选择，后续刷新失败不反转结果。
- `frontend/src/styles.css` — 统一确认弹窗遮罩为 28% 深色透明度和 5px 背景模糊。
- `frontend/src/pages/Grading.test.tsx`、`frontend/e2e/layout.responsive.spec.ts` — 覆盖删除当前项置空与遮罩视觉契约。

## 怎么验证的

前端 16 个 Vitest 文件 / 110 项测试、ESLint、OpenAPI 类型检查、TypeScript/Vite 生产构建和 6 项 Chrome/Playwright 检查通过；后端资料删除专项 5 项测试通过。宿主 5173 前端已用当前源码重启，API 健康。

## 对 codestable/ 的影响

- 已同步 Epic Spec：`codestable/epics/002-o-科目与考试工作流重构/spec.md`。
