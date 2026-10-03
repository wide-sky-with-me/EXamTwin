# frontend 规则

React + TypeScript + Vite，pnpm 11.1.1 固定，store 在 `frontend/.pnpm-store`。工作台结构见
[frontend-workbench](../docs/subsystems/frontend-workbench.md)。

## 界面设计

- 非必要不在界面上写无用注释和提示。
- 不要滥用副标题。
- 每页只有一个主要任务；危险删除写明范围并二次确认。
- 颜色与表面只用主题 token；不覆盖 `.ant-*` 内部 DOM；桌面与窄屏共享同一信息结构。

## 状态

- 业务身份放 URL，服务端数据放 TanStack Query，表单放 Ant Design Form；不要在页面复制长期 `useState`。
- 每次请求显式带科目上下文；query key 含科目与业务身份；查询消费 `AbortSignal`。
- `localStorage` 只存用户偏好，不存活动任务或流程步骤。
- 评分阶段由后端事实派生，不另存步骤状态。

## 契约

`src/generated/openapi.ts` 只由 `pnpm api:types` 从 `openapi.json` 生成，不手改。

## 检查

`pnpm test && pnpm lint && pnpm build && pnpm api:types:check`；视觉回归需显式端口
`PLAYWRIGHT_PORT=<空闲端口> pnpm test:visual`，基线说明见 `e2e/__screenshots__/README.md`。
