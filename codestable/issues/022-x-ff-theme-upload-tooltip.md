---
kind: issue
title: "主题与上传图标悬浮修复"
type: ff
status: closed
created: 2026-08-11
epic: "002"
---

# 主题与上传图标悬浮修复

## 做了什么

修正 Tooltip Portal 继承整页高度与背景、遮挡后续点击的问题，并统一主题按钮 hover/active 外观。Mark Scheme 的“上传官方版本”改为纯图标，文案仅在悬浮时显示。

## 改了哪些

- `frontend/src/components/ThemeSwitch.tsx` — 固定主题提示方向与按钮样式归属。
- `frontend/src/components/grading/GradingMaterialsStage.tsx` — 官方文件上传改为可访问的图标按钮和 Tooltip。
- `frontend/src/styles.css` — 删除冲突的主题样式，将整页几何限定到 Root Theme，并让非交互式 Tooltip 不截获指针事件。
- 前端组件与 Playwright 测试 — 覆盖图标文案、按钮尺寸、悬浮提示和相邻点击。

## 怎么验证的

前端 16 个 Vitest 文件 / 111 项测试、ESLint、TypeScript/Vite 生产构建和两条 Chrome 悬浮交互回归通过；真实 5173 页面复核主题与上传 Tooltip 分别为 64×24px、88×24px，均无整页白块；`git diff --check` 通过。

## 对 codestable/ 的影响

- 已同步 Epic Spec：`codestable/epics/002-o-科目与考试工作流重构/spec.md`。
