# Agent Note: 使用 LlamaIndex AgentWorkflow 运行答题 Agent

Status: rejected — 锁定版本在首次 LLM 调用前挂起且超时与取消无法收束

## Problem

答题需要有界的工具循环；自己实现循环会增加维护面，框架自带的编排看起来能省去这部分代码。

## Proposal

以 `llama-index-core 0.14.23 + llama-index-workflows 2.22.2` 的 `AgentWorkflow` 作为答题运行器，工具以
`FunctionTool` 注册，由框架负责决策循环、超时与取消。

## Alternatives considered

- **项目自有 `LlamaIndexReActRunner`** — 自己维护循环，但只复用 ReAct formatter/parser 与工具抽象，超时、
  取消、预算与审计完全可控。最终采用，见
  [有界答题 Agent](../../implemented/architecture/2026-07-29-bounded-per-question-answering-agent.md)。

## Risks

实装穿刺中 `AgentWorkflow` 在第一次 LLM 调用前停在 runtime `wait_receive`，超时与取消都无法可靠收束，
会让 Worker 题目永久挂起。重提前提：升级后的版本在相同端点上证明首次调用、超时与取消都能可靠完成，且
不改变项目的预算与审计边界。
