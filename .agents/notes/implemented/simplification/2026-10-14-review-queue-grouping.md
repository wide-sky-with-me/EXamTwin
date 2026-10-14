# Agent Note: 复核队列分组规则与页面展示分离

Status: implemented

## Problem

复核页面将纯分组、排序和标题派生与提交状态、评分表单及证据抽屉放在同一文件。
既有页面测试保护交互链路，但精确的排序与分组边界也需要独立测试，避免依赖 DOM 文本定位来表达规则。
本次只整理代码所有权，不改变产品行为。

## Decision

[review-groups.ts](../../../../frontend/src/lib/review-groups.ts) 承接原有实现，仅导出
`groupPendingReviews` 和 `reviewItemLabel`；分组类型、比较器和中文自然排序器保持私有。
模块只 type-import `../types`，没有 React、Ant Design、API 或 Query 运行时依赖。
[Reviews.tsx](../../../../frontend/src/pages/Reviews.tsx) 显式导入两个函数，删除原实现，不保留旧路径 re-export。

分组仍只看 `paper_job_id`，跨科目同 job 仍合并；未关联项逐项独立，试卷组先于独立项。
排序、标题回退、项目引用与输入不变性沿用现状；提交状态、请求、改分校验、确认流程和 UI 文案留在页面。
[纯规则测试](../../../../frontend/src/lib/review-groups.test.ts) 锁定边界，
[页面集成测试](../../../../frontend/src/pages/Reviews.test.tsx) 原样保留。

检索 proposed、implemented、rejected 中复核、分组和前端相关记录后，
[领域工作台](../feature/2026-08-10-domain-first-workbench.md) 与
[人工评分门禁](../feature/2026-08-05-human-gated-grading.md) 是继续有效的背景约束，不被本次结构整理替代；
其余命中涉及作答、资料分类和视觉复核，与队列分组无关。没有需要合并或替代的既有分组笔记。

## Alternatives considered

- **规则留在页面**：没有新增模块，阅读页面时可就地查看全部逻辑。规则边界仍与组件和交互实现耦合，
  独立测试需要扩大页面导出面或依赖 DOM；此次已有完整纯函数边界，抽出更直接。
- **继续拆队列卡片与证据抽屉**：可以缩短页面 JSX，并分别定位展示组件。组件拆分会新增 props 接口、
  分散状态与回调的阅读路径，却没有隔离分组规则；本次没有 UI 复用需求，因此只抽纯规则。

## Consequences

- **收益**：页面聚焦交互，规则有单独入口与边界测试；纯规则测试不调用 UI、网络或状态管理。
- **代价**：增加模块文件与一层导入，维护时需跨文件定位；页面集成测试与规则测试都需保留。
- **限制**：不引入新能力或性能优化，仍依赖运行时的 `Intl.Collator`。
  若未来要按科目隔离同 job、去重或调整排序，应单独评审行为变更，而非借结构整理修改规则。

## Verification

2026-10-14 在本机完成以下代码验证，均退出 0：

- 基线 `pnpm test -- src/pages/Reviews.test.tsx` 实际运行全前端套件：28 个文件、210 个测试通过，
  包含原有 5 个复核页面测试。范围外测试有既有 AntD 弃用及 jsdom 样式提示，本次不处理。
- 完成后 `pnpm exec vitest run src/lib/review-groups.test.ts src/pages/Reviews.test.tsx`：
  2 个文件、21 个测试通过，其中纯规则 16 个，页面集成 5 个。
- `pnpm lint` 与 `pnpm exec tsc --noEmit -p tsconfig.app.json` 通过。
- 对照改前 git 内容做字节比较：抽出算法除导出声明与笔记锚点外一致；页面只有删除与导入，
  页面集成测试原文一致。边界测试覆盖跨科目同 job、独立项、题位与中文自然题序、标题回退、空输入及稳定输入。

合并后本机完整回归 `pnpm exec vitest run`：29 个文件、226 个测试通过；`pnpm lint`、`pnpm build`、
`pnpm api:types:check` 通过。后端 OpenAPI 快照校验、文档预算/链接、笔记与 Wiki 生成校验亦通过。
未运行浏览器视觉或真实服务集成；本次没有契约、样式或 UI 行为变更。
