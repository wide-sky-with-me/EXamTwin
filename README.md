# ExamTwin

面向 OxfordAQA International AS/A-level 的多科目证据型知识库、整卷逐题作答与 Mark Scheme 初评工作台。
已注册 Mathematics（9660）与 Economics（9640），科目能力由版本化 SubjectPack 声明。

- syllabus 决定知识边界，Question Paper 与 Mark Scheme 按科目、年份、考季和 Unit 严格配对。
- 答案与建议分必须回到证据；结构完整性与引用校验不通过时停止相应流程。
- 自动评分只进入 `pending_review`，最终分来自教师；本机单用户部署，只监听 loopback，没有认证。

## 使用与开发

从[本地开发](docs/cookbook/local-development.md)选择 Linux 或 Docker Desktop / WSL 启动方式；完整使用
路径见[工作台使用](docs/cookbook/workbench.md)。API、Worker 与 GC 只经 Compose 使用同一镜像运行。

| 需要 | 入口 |
|---|---|
| 文档总览与子系统参考 | [docs/README.md](docs/README.md) |
| 架构与代码定位 | [架构全景](docs/architecture.md)、[代码组织](docs/subsystems/code-organization.md) |
| 测试与 Wiki 发布 | [测试矩阵](docs/cookbook/testing.md)、[Wiki 发布](docs/cookbook/wiki-publishing.md) |
| 开发约束与设计依据 | [AGENTS.md](AGENTS.md)、[决策笔记](.agents/notes/) |
| 许可与公开维护 | [LICENSE](LICENSE)、[仓库治理](docs/cookbook/repository-governance.md) |

## 技术栈

uv、FastAPI、SQLAlchemy + Alembic、PostgreSQL、Qdrant、SeaweedFS（可选 S3）、MinerU、LiteLLM；
React + TypeScript + Vite + Ant Design + TanStack Query，pnpm 11.1.1。
