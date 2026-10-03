# Agent Note: 模型请求统一经 LiteLLM，参数由角色配置而非模型名决定

Status: implemented

## Problem

主 ReAct 模型经 LlamaIndex `OpenAILike`，整卷视觉与图片生成直接拼 HTTP；多个调用点按模型名前缀决定是否
发送推理强度或温度。更换供应商或模型需要改业务代码，供应商格式变化会在多处同时失败。

## Decision

- 文本、结构化、视觉与图片请求统一经 `platform/litellm_provider.py`；provider 前缀只在适配层添加，审计
  记录供应商原始模型名。主 Agent 依赖 provider-neutral `ChatModelPort` 的 LiteLLM 实现。
- 每个角色（主答题、评分、拆题、视觉、知识难度、图谱、图片）独立配置模型与 `reasoning_effort`；`none`
  表示不发送。业务代码不按模型名推断参数，不自动添加模型特定温度。
- 结构化请求使用 strict JSON Schema，响应仍经本地 Pydantic 与业务门禁。
- LiteLLM 下限为 1.103，以支持 GPT-6 系列的推理参数；不启用全局 `drop_params`。
- 未配置自动的跨模型故障回退。
- Embedding 与 Rerank 独立配置为检索供应商，不经此边界。

## Alternatives considered

- **保留 LlamaIndex OpenAILike 与直接 HTTP** — 不改现有路径。四类请求各自处理协议差异，换供应商要改多处。
- **按模型名分支设置参数** — 对单一模型族最省事。模型升级或换供应商时需要改业务代码。
- **启用全局 `drop_params`** — 旧库拒绝新参数时可直接通过。会静默丢弃推理强度等关键参数，掩盖兼容问题；
  正确做法是升级到支持该参数的 LiteLLM。
- **超时后自动回退到更强模型（Astra）** — 看似能恢复长请求。同题实测表明回退模型同样超时，未证明能恢复。

## Consequences

- **收益**：更换模型或 OpenAI-compatible 供应商只改配置；协议差异集中在一个适配层。
- **代价与已知上限**：依赖 LiteLLM 对供应商新参数的支持节奏；长请求超时目前只靠逐题重试兜底。
