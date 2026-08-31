---
kind: issue
title: "DMXAPI 模型供应商迁移"
type: refactor
status: open
created: 2026-08-31
epic: ""
---

# DMXAPI 模型供应商迁移

## 目标

将解题、评分、拆题、知识处理、视觉核对和答案图片生成迁移到 DMXAPI，并让文本、结构化、视觉和图片模型统一经过 LiteLLM 适配边界；业务代码不再通过具体模型名称猜测请求能力。

## 范围

- 包含：DMXAPI Base URL 与临时密钥配置；Sol/Luna/Terra 与 `gpt-image-2-ssvip` 路由；LiteLLM 文本、结构化、视觉、图片调用；模型参数硬编码收口；自动测试和真实供应商穿刺；经济与数学现有流程回归。
- 不包含：SiliconFlow embedding/reranker 迁移；数据库业务数据迁移；更换学科策略或题目/评分契约；生产密钥长期托管。

## 归属

- 独立 issue。
- 相关 spec：`codestable/spec/index.md` 的 RAG、Agent 与供应商边界及逐页视觉结构化请求约束。

## 当前问题

项目已经安装并在结构化收口中使用 LiteLLM，但主 ReAct 模型仍通过 LlamaIndex `OpenAILike`，整卷视觉复核和图片生成仍直接拼接 HTTP。多个调用点还用 `gpt-5.6` 名称前缀决定推理与采样参数，使更换供应商或模型时必须修改业务代码。

## 行为保持

- 必须保持的外部行为：现有 Sol/Luna/Terra 角色分工、ReAct 提示词工具协议、严格结构化输出、本地业务门禁、视觉逐页隔离、图片大小/格式/落盘校验和错误重试。
- 兼容性边界：配置继续使用供应商原始模型名；LiteLLM provider 前缀只在适配层添加，持久化审计与前端展示不泄漏路由细节。
- 不借重构顺手改变的行为：不更改 embedding/rerank、作答流程、评分规则、并发和业务超时默认值。

## 现状如何工作

环境变量给出 OpenAI-compatible 地址、密钥和各角色模型；业务构造器分别走 LlamaIndex、LiteLLM 或直接 HTTP。模型名称条件分支决定是否发送 `reasoning_effort` 或 `temperature`。

## 影响范围

- 必须修改：模型配置、LiteLLM 适配层、主 Agent 模型构造、整卷视觉请求、图片请求、拆题结构化调用及相应测试。
- 需要验证：`/v1/models`、Sol 普通与结构化响应、Luna 结构化拆题、Terra 多模态严格 JSON、Image base64 PNG；经济与数学关键回归。
- 仍待调查：DMX 账户的实际计价和限流；真实图片接口是否完整遵守 LiteLLM `b64_json` 请求。

## 质量目标

- 兼容性 / 互操作性：四类模型请求通过同一个 LiteLLM 路由规则调用 DMX，既有结构化和多模态契约保持有效；以单元测试和四类真实请求证明。
- 灵活性 / 可替换性：业务模块不判断具体模型家族；更换模型和 OpenAI-compatible 服务商只需配置；以硬编码检索和配置契约测试证明。
- 可靠性 / 容错性：保留视觉与图片的有界重试、非重试确定性错误和本地载荷校验；以故障分支回归证明。
- 信息安全性 / 保密性：密钥仅进入被 Git 忽略的 `.env`，测试和日志不打印密钥；以 Git ignore、差异和脱敏检查证明。

## 方案判断

- 新增一个平台级 LiteLLM 路由模块，负责 provider 前缀、公共请求参数和响应文本提取；调用方继续拥有各自业务 schema 与本地门禁。
- `reasoning_effort` 由角色配置决定，`none` 表示不发送；不再依据模型名称推断参数，也不再自动添加模型特定 temperature。
- 主 Agent 直接依赖 provider-neutral `ChatModelPort` 的 LiteLLM 实现；测试仍可通过现有 LlamaIndex mock 兼容入口注入。
- 图片使用 LiteLLM image generation 并显式请求 base64；生成物仍通过现有 PNG 解码、尺寸和大小门禁。

## 验证

- 静态质量门：`uv run ruff check backend/src backend/tests` 通过；`uv run basedpyright backend/src` 通过，0 errors / 0 warnings。
- 全量后端：PostgreSQL、Qdrant、SeaweedFS 启动后，`uv run pytest backend/tests` 为 535 passed、21 skipped、1 条既有 Qdrant payload index warning。
- 真实 DMX 穿刺：`/v1/models` 返回的 574 个模型中包含 Sol、Luna、Terra 和图片模型；Sol 普通文本及严格结构化、Luna 严格 JSON、Terra JPEG 多模态及 `gpt-image-2-ssvip` base64 PNG 均成功。Sol 严格结构化请求通过项目正式适配器在 5.24 秒返回正确 schema。
- 故障修正：Sol 首次结构化短超时触发有界失败，按正式 120 秒配置复测成功；图片请求发现 LiteLLM 1.94 会在本地拒绝该模型的 `response_format`，移除该非兼容参数后生成 1024x1024 PNG 成功。
- 运行态：重建并启动 API、两个 Paper Worker、Storage GC；容器健康检查连续 200，API 报告 PostgreSQL、Qdrant、对象存储均健康；API 与 Worker 均解析到 DMX Base URL、`openai` LiteLLM provider 和预期模型。
- 双科回归：运行态 `/api/v1/subject` 分别识别数学 9660 与经济 9640；覆盖两科包、作答、评分、拆题、视觉与持久化路径的全量后端测试通过。
- 安全检查：临时密钥仅写入 Git 忽略的 `.env`，运行态检查只输出 `api_key_configured=True`；`git diff --check` 通过。

## 执行记录

- 2026-08-31：完成现状与 DMX 公开文档核对；确认 DMX 提供 Sol/Terra/Luna，图片建议使用 `gpt-image-2-ssvip`。确认当前仓库同时存在 LlamaIndex、LiteLLM 和直接 HTTP 三条模型调用路径以及具体模型名前缀分支。
- 2026-08-31：新增平台级 LiteLLM 适配边界；主 Agent、结构化输出、拆题、视觉复核和图片生成统一经 LiteLLM；provider 前缀仅在适配层添加，业务配置与审计继续保留供应商原始模型名。
- 2026-08-31：删除运行时代码中按 `gpt-*` 名称判断 reasoning、temperature 或请求协议的分支；请求能力改由角色配置和适配器契约决定。
- 2026-08-31：写入本地 DMX 环境配置，完成自动测试、四类真实模型穿刺、容器重建和经济/数学运行态回归。issue 保持 open，等待提交/评审后再执行关闭回写。

## 关闭回写

- 完成后把稳定的 LiteLLM 供应商边界、模型配置和验证要求回写 `codestable/spec/index.md`。
