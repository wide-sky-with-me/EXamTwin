# 前端工作台

`frontend/` 是面向本机受信教师与内容维护者的 React + TypeScript + Vite 单页应用；没有登录、角色、
学生端或成绩发布入口。

## 信息架构

主导航只有三个领域入口：桌面为可折叠侧栏，窄屏为底部导航。

| 入口 | 内容 |
|---|---|
| 科目 | 目录展示名称、代码、资料、知识点与向量状态；详情子路由为基本信息、资料、知识库 |
| 试卷 | 按科目归档试卷单元；详情是 AI 作答、外部答案导入、作答记录、评分和整卷报告的共同上文 |
| 复核 | 跨科目待复核项，按 `paper_job_id` 聚合为试卷组、按题位排序，并标明外部答卷或 AI 作答 |

```text
/subjects  /subjects/:subjectId(/materials|/knowledge)
/papers    /subjects/:subjectId/papers/:paperUnitId(/answers)
           /subjects/:subjectId/papers/:paperUnitId/jobs/:jobId/(answering|grading)
/reviews   /reviews/:assessmentId
```

## 状态所有权

| 状态 | 所有者 |
|---|---|
| 科目、试卷、任务、Rubric、assessment、复核项 | TanStack Query cache |
| `subjectId`、`paperUnitId`、`jobId`、`assessmentId`、筛选、页码 | URL（React Router） |
| 表单草稿与校验 | Ant Design Form |
| 任务事件快照 | 对应 job query 的 `setQueryData` |
| 弹窗、抽屉、展开项 | 局部组件 |

Query key 含科目与业务身份；查询消费 `AbortSignal`，切换科目时旧请求取消，晚返回结果不能覆盖当前
页面。每次请求显式携带科目上下文。`localStorage` 只保存主题、复核人与侧栏等用户偏好，不保存活动任务。
评分阶段由 Rubric 状态、assessment 完成度与复核状态派生，不保存独立步骤。

## 组件与样式

Ant Design 6 承担主题、表单、表格、上传、弹窗、抽屉、分页和反馈，根节点为
`ConfigProvider + App + zhCN`；Lucide 为图标；React Markdown + KaTeX 渲染答案。颜色与毛玻璃表面由
明暗主题 token 驱动，支持浅色、深色、跟随系统。自定义 CSS 只用于页面空间关系与试卷、证据、评分领域
内容，不覆盖 `.ant-*` 内部 DOM。通用列表共享分页策略。

响应式：≥1024px 固定侧栏与双栏；600–1023px 可折叠侧栏、详情单栏；<600px 底部导航、整页详情、领域
卡片代替表格，不靠横向滚动暴露关键列。

## 契约

`src/generated/openapi.ts` 由 `frontend/openapi.json` 生成；`pnpm api:types:check` 校验一致，后端快照由
`scripts/export_openapi.py --check` 校验。原卷 PDF 导出编辑器按需加载，见
[answer-pdf-export](answer-pdf-export.md)。
