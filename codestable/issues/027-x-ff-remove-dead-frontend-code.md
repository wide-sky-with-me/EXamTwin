---
kind: issue
title: "删除不可达前端代码"
type: ff
status: closed
created: 2026-08-12
epic: ""
---

# 删除不可达前端代码

## 做了什么

从 `frontend/src/main.tsx` 出发核对生产导入图，删除已经被当前四入口工作流替代、且没有生产调用方的旧总览、旧知识库和旧知识图谱实现；同步清理孤立测试、依赖、类型别名和样式，保留当前科目管理、试卷作答、答案评分与复核队列行为。

## 改了哪些

- 删除 4 个不可达生产模块：`pages/Overview.tsx`、`pages/Knowledge.tsx`、`components/Evidence.tsx`、`components/KnowledgeGraphCanvas.tsx`。
- 删除 3 个只覆盖上述旧实现的测试文件。
- 从 `frontend/package.json` 和 `pnpm-lock.yaml` 移除仅供旧知识图谱使用的 `@dagrejs/dagre`、`@xyflow/react` 及其传递依赖。
- `frontend/src/types.ts` 删除 22 个无调用方的 API 类型别名。
- `frontend/src/styles.css` 删除旧页面、旧图谱、旧弹层与失效响应式规则；样式表由 2722 行收敛到 2173 行。剩余无静态字面调用的选择器仅为 Radix 运行时类和答案图动态 `fill-*` / `tone-*` 类。

## 怎么验证的

- 生产导入图从 `main.tsx` 可达所有 36 个运行时 TypeScript 模块，无剩余不可达模块。
- `uv run ruff check backend scripts` 与 `uv run python scripts/check_architecture.py` 通过。
- `pnpm api:types:check`、`pnpm lint`、`pnpm test`（14 个文件、112 项）和 `pnpm build` 通过。
- 真实浏览器依次打开科目管理、试卷作答、答案评分和复核队列；页面可渲染、切换稳定，科目卡片布局正常。

## 对 codestable/ 的影响

- 无已记录业务真相变化；本次仅删除当前路由和组件树不可达的旧前端实现，不修改 `codestable/epics/002-o-科目与考试工作流重构/spec.md` 的工作流契约。
