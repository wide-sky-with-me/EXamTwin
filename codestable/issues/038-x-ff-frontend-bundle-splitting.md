---
kind: issue
title: "前端共享依赖与路由分包优化"
type: ff
status: closed
created: 2026-08-20
epic: ""
---

# 前端共享依赖与路由分包优化

## 做了什么

将首屏共享运行时与低频科目页面从原始大入口包中拆开，使每个生产 JS chunk 都低于 Vite 的 500 kB 默认告警线，并保留按路由加载能力。

## 改了哪些

- `frontend/vite.config.ts` — 为 React、数据客户端、图标、Motion 和 Ant Design CSS-in-JS 建立稳定 vendor 边界；保留原有 KaTeX/Markdown 边界；将测试 worker 收敛为 2，避免完整 UI 套件资源竞争。
- `frontend/src/App.tsx` — 将科目概览和科目工作区改为路由级懒加载。
- `frontend/src/pages/SubjectOverview.tsx` — 承接原科目概览页面及原有 404 行为。

## 结果

- 最大 JS chunk：`865.72 kB / 281.00 kB gzip` → `466.39 kB / 150.91 kB gzip`。
- 最大 chunk 原始体积下降约 46%，构建不再出现 large chunk 警告。
- 科目概览独立为约 `2.32 kB`，科目工作区入口约 `6.69 kB`。

## 怎么验证的

生产构建通过且无大 chunk 告警；OpenAPI 类型检查与 ESLint 通过；Vitest 全量 `18 files / 169 tests` 通过。

## 对 codestable/ 的影响

- 不改变产品或领域契约；仅调整前端加载和缓存边界。
