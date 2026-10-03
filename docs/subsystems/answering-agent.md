# 答题 Agent

`assessment/answering_agent/` 为整卷中的每道题运行一个独立、有界的 Agent run，对 Worker 只暴露
`solve(AnswerTask) -> AnswerResult`。拆题、视觉复核与评分是各自有权威边界的服务，不属于 Agent。

## 运行循环

```text
prepare → decide → tool_call → observe → verify → finalize
```

`LlamaIndexReActRunner` 用 ReAct formatter/parser 驱动确定性工具循环；模型适配器设置
`is_function_calling_model=False`。`platform/agent_runtime` 只定义消息、模型、协议、工具执行与结构化
输出 Port，不导入 LlamaIndex 或 LiteLLM。单题总时限默认 300 秒，单次工具 45 秒，终稿整理 45 秒；
步数、时限、取消或证据不足都会停止。

## 能力与工具面

| 工具 | 作用 |
|---|---|
| `knowledge_search` | 检索当前科目已发布知识库，见 [retrieval](retrieval.md)；两科都是必需且强制调用 |
| `source_read` | 按文档 ID、页码或章节读取已转换原文 |
| `paired_exam_lookup` | 按精确配对键读取同场次 Source Booklet |
| `question_vision` | 读取 Worker 按 `source_pages` 绑定的受信页图或已定位图表，生成有界视觉观察 |
| 数学：`math_calculate`、`probability_calculate`、`math_plot`、`math_diagram`、`image_generate` | 受限 SymPy 计算、概率（含 `normal_sf` 上尾）、白名单矢量图、受控 PNG |
| 经济：`economics_calculate`、`economics_diagram` | 经济计算与标准经济图 |

SubjectPack 声明 allowlist；每题开始前按 `QuestionSpec`、来源图片和配对键确定性缩小工具面，视觉、
配卷、绘图和生图只在题目需要时暴露。工具参数校验失败时返回去掉原始输入值、最长 1200 字符的字段
级错误，让 Agent 有界修参。MCP 工具只有经服务端配置且进入学科 allowlist 才能被调用。

## 终稿

公开契约 `AgentFinalPayload`：Markdown 答案（含全部子题）、`citation_ids`、置信度、`grounded`、警告。
主模型候选先在本地按同一契约验收：精确子题标签、正文 `[S#]` 首次出现顺序与 `citation_ids` 一致、
引用属于本题真实检索结果。通过即成为终稿；不通过才请求结构化终稿 provider；两者都失败则该题失败。
兼容恢复路径的引用顺序始终从正文派生。

公开引用只保留答案实际使用的证据并重新编号。`knowledge_points` 只取被答案引用、且属于当前科目目录的
知识编号，按首次出现去重，最多四个；没有可靠绑定时为空列表。编号与答案在同一题目完成事务中保存。

## 产物

矢量图只接受白名单图元、数值几何和受限 path 命令，由 React 转义渲染；不执行模型返回的 SVG、HTML、
脚本或 base64。位图经 PNG 解码、尺寸与大小门禁后写入对象存储。SubjectPack 视觉政策决定哪些题必须
带图形产物。

## Prompt 与运行账本

System prompt 三层合成：平台不变量（`platform/prompt_templates/answering/SYSTEM.md`）、包内 `SKILL.md`
学科政策、本题运行时数据；合成摘要随 run 保存。PostgreSQL 账本保存 Package/Prompt 摘要、预算、工具名、
参数摘要、状态与结果摘要，不保存模型隐式思维链。只有服务端标记为 replay-safe 的确定性工具结果可在
同题后续 attempt 复用；知识检索与配卷读取依赖可变索引，每次重新执行。
