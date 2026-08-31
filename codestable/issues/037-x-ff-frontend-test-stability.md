---
kind: issue
title: "前端回归测试稳定性修复"
type: ff
status: closed
created: 2026-08-20
epic: ""
---

# 前端回归测试稳定性修复

## 做了什么

修复整套前端测试并发运行时四个 UI 用例超时的问题，并恢复作答详情懒加载阶段的可访问状态提示。

## 改了哪些

- `frontend/vite.config.ts` — 将 Vitest worker 上限收敛为 4，避免 jsdom 与 Ant Design 并发导入争抢内存和 CPU。
- `frontend/src/pages/PaperManagement.tsx` — 为作答详情 Suspense fallback 增加可访问的加载状态与文案。

## 怎么验证的

Vitest 全量 `18 files / 169 tests` 通过；OpenAPI 类型检查、ESLint 和 TypeScript/Vite production build 通过。

## 对 codestable/ 的影响

- 无已记录真相受影响：仅恢复既有加载反馈与回归验证稳定性，不改变产品或领域契约。
