---
kind: issue
title: "交互式知识图谱浏览"
type: ff
status: closed
created: 2026-08-06
epic: ""
---

# 交互式知识图谱浏览

## 做了什么

知识库的图谱生产视图由静态 SVG 改为可交互画布：节点按关系自动布局，支持平移、缩放、小地图、节点与关系选择；悬浮节点可查看定义、置信度、关系数、审核状态和别名。画布可进入全屏，公式与说明沿用 Markdown + KaTeX 渲染。

最终收口补齐图谱请求竞态、保存后选择保持、运行时主题同步、可滚动悬浮详情和全屏焦点管理，避免慢响应覆盖当前版本或校订后跳回首节点。

## 改了哪些

- `frontend/src/components/KnowledgeGraphCanvas.tsx` — 新增 React Flow 画布、Dagre 布局、节点卡片、关系线、悬浮详情、视口聚焦与画布控制。
- `frontend/src/pages/Knowledge.tsx` — 图谱生产视图接入交互画布，增加全屏状态、Escape 退出和正文滚动锁定；节点与关系选择继续驱动原有右侧校订面板。
- `frontend/src/styles.css` — 新增图谱画布、节点、悬浮卡片、全屏、深浅主题和窄屏布局样式。
- `frontend/src/components/KnowledgeGraphCanvas.test.tsx` — 覆盖关系计数、节点选择、悬浮详情和 KaTeX 渲染。
- `frontend/package.json`、`frontend/pnpm-lock.yaml` — 增加 `@xyflow/react` 与 `@dagrejs/dagre`。
- `frontend/src/pages/Knowledge.test.tsx` — 覆盖版本切换慢响应隔离和节点保存后选择保持。
- `frontend/src/lib/use-modal-focus.ts` — 统一全屏焦点圈定、Escape 退出、滚动锁定与原焦点恢复。

## 怎么验证的

- `pnpm test`：13 个测试文件、27 项测试全部通过。
- `pnpm lint` 与 `pnpm build` 通过。
- 真实 9640 已发布图谱烟雾检查：加载 201 个节点和 253 条关系，右侧编辑器保持当前节点；最终全页截图确认布局与画布可见。
- Browser Act 端到端检查过节点悬浮详情、关系点击、全屏进入、Escape 退出和正文滚动恢复；深色与浅色主题均完成截图复核。

## 对 codestable/ 的影响

- 无 API、持久化结构或既有产品真相变化；只替换知识图谱的前端浏览与校订交互机制。
