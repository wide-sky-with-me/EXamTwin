# 架构全景

ExamTwin 是面向 OxfordAQA International AS/A-level 的本机单用户工作台：把考试局资料变成可核查的
知识库，对整卷试题逐题证据作答，并在严格配对的 Mark Scheme 上给出待教师复核的建议分。
已注册科目为 Mathematics 9660 与 Economics 9640。

三条产品不变量贯穿全部模块：

- syllabus 决定知识边界；Question Paper 与 Mark Scheme 只按 `{subject_code}:{year}:{session}:{unit}`
  严格配对，不用语义相似度猜配对。
- 模型只提出有证据的答案或建议分；证据不足时拒答，无法证明完整时失败关闭。
- 自动评分一律进入 `pending_review`，只有教师确认或改分才形成最终分。

## 运行拓扑

```text
浏览器 ── Vite dev / 静态前端 ── FastAPI /api/v1 ──┬── PostgreSQL（事实、任务队列、审计）
                                                  ├── Qdrant（按科目 live alias 的向量索引）
paper-worker ×2 ── 同一镜像 ──────────────────────┼── 对象存储（本地或 SeaweedFS S3）
storage-gc ─────── 同一镜像 ──────────────────────┘
                     └── 外部服务：MinerU、LLM（LiteLLM→DMXAPI）、Embedding/Rerank（SiliconFlow）
```

- API、Worker 与 GC 来自同一个 uv 锁定镜像，由 `compose.yaml` 统一运行；只绑定 loopback。
- PostgreSQL 同时是业务事实源和整卷持久队列，Alembic 是唯一 schema 来源。
- 前端由 pnpm 管理，OpenAPI 快照 `frontend/openapi.json` 是前后端契约的单一来源。

## 后端模块

`backend/src/examtwin/` 按业务能力组织：

| 模块 | 责任 | 详细说明 |
|---|---|---|
| `subjects/` | SubjectPack 加载、科目工作区、资料归属规则、宿主 provider 注册表 | [subject-packs](subsystems/subject-packs.md) |
| `knowledge/` | 资料清点、转换、知识库版本、课程图谱、难度、检索 | [corpus-and-knowledge](subsystems/corpus-and-knowledge.md)、[retrieval](subsystems/retrieval.md) |
| `assessment/` | 试卷单元、整卷任务、答题 Agent、评分与复核、目标策略、PDF 导出 | [paper-jobs](subsystems/paper-jobs.md)、[answering-agent](subsystems/answering-agent.md)、[grading-and-review](subsystems/grading-and-review.md) |
| `platform/` | 配置、数据库会话、对象存储、模型适配器、通用 Agent runtime | [model-providers](subsystems/model-providers.md)、[object-storage](subsystems/object-storage.md) |
| `contracts/` | 稳定 HTTP 与任务数据契约，不依赖运行时模块 | — |
| `app/` | FastAPI/CLI 入口、HTTP 适配、唯一组合根 `app/composition.py` | — |

依赖方向固定为 `subjects → knowledge → assessment → app`，`platform` 与 `contracts` 在底层且不反向
依赖业务模块。跨模块只经 `<feature>.public`。`scripts/check_architecture.py` 在 CI 中拒绝反向依赖、
绕过公共入口、业务模块直接引入 FastAPI、通用模块出现已安装科目代码字面量。

## 前端

React + TypeScript + Vite 单页工作台，主导航只有“科目、试卷、复核”三个领域入口；作答与评分在
具体试卷和作答记录的 URL 上下文内展开。见 [frontend-workbench](subsystems/frontend-workbench.md)。

## 数据所有权

| 数据 | 所有者 | 不变量 |
|---|---|---|
| 资料清单、考试身份、配对键 | `knowledge` 清点与工作区服务 | 身份不完整或外部资格的考试资料不进入严格配对 |
| 知识库版本、Qdrant collection | `knowledge` 发布 | staging 构建、门禁通过后原子切换 live alias |
| 课程图谱、难度证据 | `knowledge` 构建流水线 | 单事务发布；每个难度值带证据等级与来源 |
| 整卷任务、页段、题目 | `assessment` `PaperJobService` | 租约条件提交；检查点按契约版本与输入摘要复用 |
| Rubric、assessment、复核 | `assessment` 评分服务 | 人工审核与 AI 建议分开追加；最终分只来自教师 |
| 文件字节 | `platform` `ManagedObjectStore` | PostgreSQL 对象目录记录用途、owner、哈希与保留期 |

## 安全边界

单机单用户、无认证。API、PostgreSQL、Qdrant、SeaweedFS 只监听 loopback；HTTP 与 WebSocket 校验
Host 与 Origin。关闭 `LOCAL_ACCESS_ONLY` 且绑定非 loopback 时健康检查返回 `degraded`。多用户部署
前必须先建立认证、授权与租户绑定，对象目录中的 owner 只表示生命周期归属。

## 决策记录

架构取舍与被否方案在 `.agents/notes/implemented/architecture/`；产品行为取舍在
`.agents/notes/implemented/feature/`。修改相关代码前先按 [notes 规则](../.agents/notes/AGENTS.md) 检索。
