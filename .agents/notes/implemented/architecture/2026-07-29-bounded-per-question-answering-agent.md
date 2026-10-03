# Agent Note: 每道题一个有界 Agent run，框架类型不进入业务层

Status: implemented

## Problem

单次 RAG 调用无法完成需要读原文、计算、作图和读原卷图的考试题；而无上限的自主 Agent 难以控制成本、
时限和可审计性，也会让答案的证据来源变得不可核查。

## Decision

- 粒度固定为一题一个 `AgentRun`，循环为 `prepare → decide → tool_call → observe → verify → finalize`，
  受步数、单题时限、工具时限和取消约束。拆题、视觉复核、评分仍是各自独立的服务。
- 运行器为 `LlamaIndexReActRunner`：模型适配器设 `is_function_calling_model=False`，用 ReAct
  formatter/parser 驱动确定性工具循环。
- `platform/agent_runtime` 定义消息、模型、协议、工具执行与结构化输出 Port，不导入 LlamaIndex 或
  LiteLLM；框架只作为 adapter。学科 allowlist、预算与审计在项目自己的能力注册表执行。
- 强制知识检索、引用闭合、必需产物、配卷权威由领域 Policy 执行，不交给模型决定。
- 运行账本保存公开步骤、工具摘要与结果，不保存或展示隐式思维链；只有 replay-safe 的确定性工具结果
  可跨 attempt 复用。
- 每题开始前按 `QuestionSpec`、图片与配对键确定性缩小工具面，不引入第二个路由 Agent。

## Alternatives considered

- **LlamaIndex `AgentWorkflow`** — 框架自带的完整编排，代码最少。实测锁定版本在第一次 LLM 调用前停在
  runtime `wait_receive`，超时与取消无法可靠收束，见
  [被否记录](../../rejected/architecture/2026-07-29-llamaindex-agentworkflow-runner.md)。
- **原生 function calling runner** — 协议更稳、解析失败更少。当前端点未验证稳定支持原生 tool calling；
  验证通过后可新增 runner，`AgentTool`、Skill 与结果契约不变。
- **多 Agent 协作 / 无上限自主运行** — 理论上能处理更复杂任务。没有可观察证据表明单题需要，且会让成本、
  时限和证据归属失控。
- **Tool Search 或路由 Agent 选择工具** — 工具多时能降低 prompt 体积。当前工具数量与 schema 体积不是
  可观测瓶颈；确定性缩小已足够。触发重访：工具 schema 成为可测成本瓶颈。

## Consequences

- **收益**：每题失败只影响该题；工具调用可审计、可重放；新增学科只注册政策和能力，不改 Worker 与主循环。
- **代价与已知上限**：ReAct 文本协议有格式失败率，由单题有界重试和终稿本地验收兜底；外部模型长请求
  超时仍会让个别长题失败。
