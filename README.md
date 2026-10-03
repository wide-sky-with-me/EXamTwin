# ExamTwin

面向 OxfordAQA International AS/A-level 的多科目证据型知识库、整卷逐题作答与 Mark Scheme 初评工作台。
已注册 Mathematics（9660）与 Economics（9640），科目边界由版本化 SubjectPack 声明。

- syllabus 决定知识边界；Question Paper 与 Mark Scheme 按年份、考季和 Unit 严格配对。
- 模型只基于检索证据提出答案或建议分；证据不足时拒答，结构无法证明完整时失败关闭。
- 自动评分一律进入人工复核，不直接发布。
- 本机单用户部署，只监听 loopback，没有认证；不要直接暴露到 LAN 或公网。

## 快速开始

从 `.env.example` 复制私有 `.env` 并填写密钥，然后：

```bash
uv sync
uv run examtwin config-check
docker compose up -d --build
uv run examtwin init
cd frontend && pnpm install && pnpm dev
```

页面 `http://localhost:5173`，API 文档 `http://localhost:8000/docs`。Docker Desktop / WSL、代理与端口设置见
[本地开发](docs/cookbook/local-development.md)。

## 文档

| 想了解 | 阅读 |
|---|---|
| 系统全景、模块与数据所有权 | [docs/architecture.md](docs/architecture.md) |
| 各子系统行为与契约 | [docs/subsystems/](docs/subsystems/) |
| 数据管线、测试、存储运维、新增科目 | [docs/cookbook/](docs/cookbook/) |
| 事故复盘 | [docs/postmortem/](docs/postmortem/) |
| 设计取舍与被否方案 | [.agents/notes/](.agents/notes/) |
| 参与开发的规则 | [AGENTS.md](AGENTS.md) |

## 技术栈

uv、FastAPI、SQLAlchemy + Alembic、PostgreSQL、Qdrant、SeaweedFS（可选 S3 后端）、MinerU、LiteLLM、
React + TypeScript + Vite + Ant Design + TanStack Query，pnpm 11.1.1。
