---
kind: issue
title: "收口整卷作答状态文案"
type: ff
status: closed
created: 2026-08-05
epic: ""
---

# 收口整卷作答状态文案

## 做了什么

把处理进度、题目作答状态和证据充分性分开表达：整卷使用“处理完成 / 部分题目失败 / 处理失败”，单题使用“等待作答 / 作答中 / 已作答 / 证据不足 / 作答失败”。有答案且引用闭合的完成题显示“已作答”，证据不足题继续明确告警，不再把“证据充分”当作完成状态。

## 改了哪些

- `frontend/src/lib/paper-job.ts` — 集中维护整卷阶段、整卷状态与单题状态文案。
- `frontend/src/pages/PaperAnswering.tsx` — 统一进度、汇总、导航、当前题和通知文案，并让证据不足题保持告警色。
- `frontend/src/components/PaperJobHistory.tsx` — 对齐筛选项、历史状态与处理数量文案。
- 相关 Vitest — 覆盖状态与证据语义分离及实际组件呈现。

## 怎么验证的

前端 OpenAPI 类型检查、14 个 Vitest 文件共 36 项测试、ESLint、TypeScript/Vite 生产构建全部通过。浏览器打开真实 9660 已完成任务：整卷显示“处理完成 / 9 题已处理”，Q1 显示“已作答”；切到 Q8 后导航与当前题均显示“证据不足”，没有冒充“已作答”。

## 对 codestable/ 的影响

- 无新增产品真相；实现重新对齐 `codestable/issues/001-x-整卷证据作答与细粒度知识图谱.md` 中“已作答”和“证据不足”必须可区分的既有约束。
