# 前端工作台

`frontend/` 是面向本机受信教师与内容维护者的 React + TypeScript + Vite 单页应用；没有登录、角色、
学生端或成绩发布入口。

## 信息架构

主导航只有“科目、试卷、复核”：桌面使用可折叠侧栏，窄屏使用底部导航。

| 入口 | 内容 |
|---|---|
| 科目 | 目录和科目详情，资料入口为 `/subjects/:subjectId/documents`，知识入口为 `/knowledge` 子路由 |
| 试卷 | 科目卡片进入 `/subjects/:subjectId/papers`；试卷详情展开 AI 作答、外部答案导入、作答记录与评分 |
| 复核 | 跨科目待复核项按 `paper_job_id` 分组；题位排序，并标明外部答卷或 AI 作答 |

`/papers` 是按当前或最近科目重定向的入口，不是独立试卷目录。科目、试卷、任务、复核项身份在 URL 中；
任务详情允许直接打开并刷新恢复。路由注册以 [App](../../frontend/src/App.tsx) 为准，试卷路径构造、模式与
身份解析由 [paper-routes](../../frontend/src/lib/paper-routes.ts) 统一定义，不手抄完整路由表。

## 当前状态所有权

| 状态 | 实现 |
|---|---|
| 平台科目状态、跨科目复核队列 | App 中的 TanStack Query |
| 科目、试卷、任务、assessment 的业务路由身份 | React Router URL |
| 试卷列表、资料、筛选、页码和编辑草稿 | PaperManagement、SubjectManagement 局部状态 |
| 题目任务快照 | PaperAnswering 局部状态，由任务订阅更新 |
| 评分材料、Rubric、assessment、overview | Grading 局部状态，由加载和写入后重新对账 |
| 表单输入、弹窗、抽屉和展开项 | 页面受控草稿与局部状态；Ant Design 提供表单展示和交互组件 |

请求显式携带科目身份；页面使用请求序号忽略晚返回结果。Query 的查询取消与 `setQueryData` 任务缓存不是
全工作台已完成能力。评分业务门禁由后端事实约束，当前展示阶段由 Grading 的瞬时 `step` 状态选择。

`localStorage` 保存主题、复核人、侧栏和最近科目等偏好；Grading 的外部答案导入路径还保存科目级导入任务
ID，终态或订阅不可用时清除。这是已知实现差异，不把它描述为偏好存储。新开发的状态约束见
[frontend 规则](../../frontend/AGENTS.md)；统一迁移需独立验证恢复、切换科目和晚响应场景。

## 组件与样式

Ant Design 6 承担主题、表单、表格、上传、弹窗、抽屉、分页和反馈，根节点为
`ConfigProvider + App + zhCN`；Lucide 为图标；React Markdown + KaTeX 渲染答案。颜色与表面使用明暗
主题 token，支持浅色、深色与跟随系统；领域 CSS 负责空间关系，不覆盖 `.ant-*` 内部 DOM。

响应式：≥1024px 固定侧栏与双栏；600–1023px 可折叠侧栏、详情单栏；<600px 底部导航、整页详情、领域
卡片代替表格。复核分组、题序与标题派生由 [review-groups](../../frontend/src/lib/review-groups.ts) 的纯规则承担。

## 契约

`src/generated/openapi.ts` 由 `frontend/openapi.json` 生成，`pnpm api:types:check` 校验一致；后端快照由
`scripts/export_openapi.py --check` 校验。原卷 PDF 编辑器按需加载，见[PDF 导出](answer-pdf-export.md)。
