# 模型供应商

文本、结构化、视觉和图片请求统一经过 `platform/litellm_provider.py` 的 provider-neutral 边界；
Embedding 与 Rerank 由 `platform/providers.py` 独立配置为检索供应商。业务代码只读取角色配置和本地
业务契约，不按模型名称判断请求协议或参数。

## 角色配置

`platform/config.py` 的每个角色独立声明模型与推理强度，`.env` 提供具体值：

| 角色 | 配置前缀 | 用途 |
|---|---|---|
| 主答题 | `LLM_` | 逐题 ReAct、目标策略分析、范围复核 |
| 评分 | `GRADING_` | Rubric 解析、AI 审核、逐题初评 |
| 拆题 | `PAPER_SPLIT_` | 整卷结构拆分与冲突候选选择 |
| 视觉 | `PAPER_VISION_` | 逐页视觉复核、题目视觉观察 |
| 知识难度 / 图谱 | `KNOWLEDGE_DIFFICULTY_`、`KNOWLEDGE_GRAPH_` | `knowledge-build` 与图谱草稿 |
| 图片 | `IMAGE_GENERATION_` | 受控 PNG 答案图 |
| 检索 | `EMBEDDING_`、`RERANK_` | 向量化与重排 |

`reasoning_effort` 取值由角色配置决定，`none` 表示请求中不发送该字段。LiteLLM provider 前缀只在适配层
添加；持久化审计记录供应商原始模型名，作为审计身份而非行为开关。LiteLLM 版本下限为 1.103（支持
GPT-6 系列的推理参数）；不启用全局 `drop_params`，未知参数由本地结构验证暴露。

结构化请求使用供应商 strict JSON Schema 约束，响应仍须通过本地 Pydantic 解析与业务门禁，供应商格式
约束不替代业务校验。

## 密钥与外发

- 密钥只来自未跟踪的 `.env`，不进入示例文件、响应或日志；外部调用前必须显式配置对应凭据。
- 项目没有离线模型回退；供应商不可用时相关任务失败并可重试。
- 普通测试不调用真实供应商。需要核对真实响应契约时显式运行付费冒烟：

```bash
uv run examtwin provider-smoke
uv run examtwin provider-smoke --provider llm,embedding
```

- 本地 Compose 覆盖文件下，容器经 `CONTAINER_PROXY_URL` 访问外部服务，见
  [local-development](../cookbook/local-development.md)。

## 已知运行限制

经济长论述题在当前渠道下可能出现持续接口超时；单题失败由逐题重试接管，不静默补写答案。评分准确性
评测见 `backend/evals/README.md`，结果不构成教师金标准。
