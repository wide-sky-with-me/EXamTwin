# 代码组织与定位

后端按业务能力组织，前端按页面、领域组件与客户端规则组织；按职责定位，不按文件行数重切事务或运行编排。

## 后端边界

| 边界 | 入口与责任 |
|---|---|
| `subjects` | [packages](../../backend/src/examtwin/subjects/packages.py) 加载声明包；[public](../../backend/src/examtwin/subjects/public.py) 向下游暴露科目上下文 |
| `knowledge` | [workspace_service](../../backend/src/examtwin/knowledge/workspace_service.py) 管资料；[pipeline](../../backend/src/examtwin/knowledge/pipeline.py) 管知识构建；[public](../../backend/src/examtwin/knowledge/public.py) 暴露下游能力 |
| `assessment` | 试卷单元、任务、检索作答、策略、评分与复核；服务和 Repository 同属业务领域 |
| `platform` | 配置、连接、存储、模型适配、[agent_runtime](../../backend/src/examtwin/platform/agent_runtime/) 协议与结构化执行 |
| `contracts` | HTTP 和持久任务的稳定数据契约，不导入运行时模块 |
| `app` | [main](../../backend/src/examtwin/app/main.py)、[cli](../../backend/src/examtwin/app/cli.py)、[api/router](../../backend/src/examtwin/app/api/router.py) 适配入口；[composition](../../backend/src/examtwin/app/composition.py) 唯一依赖装配点 |

业务领域之间只经上游 `public`，依赖由 `subjects → knowledge → assessment` 向下游消费。`app` 可访问领域
内部实现进行适配与装配，但 HTTP handler 只转换协议并委派服务；不为每个目录机械增加 `public.py`。
数据库查询与事务归属领域 Repository，schema 由 [Alembic](../../backend/migrations/) 定义。

## 关键调用链

- **整卷**：[PaperJobService](../../backend/src/examtwin/assessment/paper_jobs.py) 管任务与响应，
  [PaperWorker](../../backend/src/examtwin/assessment/paper_worker.py) 编排阶段，
  [PaperJobRuntime](../../backend/src/examtwin/assessment/paper_job_runtime.py) 管租约与检查点，
  [PaperJobRepository](../../backend/src/examtwin/assessment/paper_job_repository.py) 条件提交事务。
- **分题**：[paper_answering](../../backend/src/examtwin/assessment/paper_answering.py) 编排模型与修复，
  [paper_question_candidates](../../backend/src/examtwin/assessment/paper_question_candidates.py) 归并候选，
  [paper_parsing](../../backend/src/examtwin/assessment/paper_parsing.py) 校验来源完整性。
- **索引与检索**：[ingestion](../../backend/src/examtwin/knowledge/ingestion.py) 编排来源到索引，
  [vector_index_publication](../../backend/src/examtwin/knowledge/vector_index_publication.py) 管发布门禁，
  [vector_index_reuse](../../backend/src/examtwin/knowledge/vector_index_reuse.py) 管向量复用，
  [vector_retrieval](../../backend/src/examtwin/knowledge/vector_retrieval.py) 召回；
  [RagService](../../backend/src/examtwin/assessment/rag.py) 是检索业务入口。
- **评分**：[rubrics](../../backend/src/examtwin/assessment/rubrics.py) 管规则与整卷聚合，
  [grading](../../backend/src/examtwin/assessment/grading.py) 做逐题建议，
  [assessment_repository](../../backend/src/examtwin/assessment/assessment_repository.py) 保存与复核；人工门禁在事务内强制。

## 前端边界

[App](../../frontend/src/App.tsx) 装配导航与路由；[paper-routes](../../frontend/src/lib/paper-routes.ts) 定义试卷
路径与身份解析。[pages](../../frontend/src/pages/) 编排交互，[components](../../frontend/src/components/) 展示
领域内容，[lib](../../frontend/src/lib/) 管客户端协议与纯规则；
[review-groups](../../frontend/src/lib/review-groups.ts) 只负责复核队列分组、题序与标签。

[generated/openapi.ts](../../frontend/src/generated/openapi.ts) 从快照生成，不手工维护；具体状态所有权与已知
实现差异见[前端工作台](frontend-workbench.md)。

## 修改与验证

领域边界由 [check_architecture](../../scripts/check_architecture.py) 强制；跨文件结构调整同步调用方、测试和
所属决策，不留旧路径兼容出口。按[测试矩阵](../cookbook/testing.md)执行相应层检查；
[根规则](../../AGENTS.md)与[领域组织决定](../../.agents/notes/implemented/architecture/2026-08-05-feature-first-backend-modules.md)约束结构。
