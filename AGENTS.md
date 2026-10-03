# ExamTwin Agent 规则

OxfordAQA 多科目证据型知识、整卷作答与评分工作台。全景见 [docs/architecture.md](docs/architecture.md)。
进入哪个目录，先读该目录的 `AGENTS.md`；子目录已有的规则不在这里重复。

## 仓库地图

- `backend/src/examtwin/`：`subjects → knowledge → assessment → app`，`platform` / `contracts` 在底层。规则见 [backend/AGENTS.md](backend/AGENTS.md)。
- `frontend/`：React 工作台。规则见 [frontend/AGENTS.md](frontend/AGENTS.md)。
- `subject-packs/`：声明式科目包。规则见 [subject-packs/AGENTS.md](subject-packs/AGENTS.md)。
- `docs/`：当前事实。规则见 [docs/AGENTS.md](docs/AGENTS.md)。
- `.agents/notes/`：决策笔记。规则见 [.agents/notes/AGENTS.md](.agents/notes/AGENTS.md)。
- `scripts/`：架构、文档、笔记、OpenAPI 校验与实验脚本。

## 运行禁区

- API、Worker 与 GC 只通过 Compose 以同一镜像运行，不在宿主机另起进程连接开发库；本机步骤见
  [local-development](docs/cookbook/local-development.md)。
- 付费模型调用与资料外发（转换、索引、知识构建、检索评测、冒烟、整卷任务、`--live` 实验）只在用户明确
  授权后执行，见 [授权笔记](.agents/notes/implemented/process/2026-08-16-explicit-authorization-for-external-calls.md)。
- 删除数据卷、数据库、对象或资料前，先检索 `docs/`、`.agents/notes/` 与 git 历史中对目标的记录，并向用户
  说明，见 [复盘](docs/postmortem/2026-10-03-legacy-volumes-deleted.md)。
- `.env` 只在本机，不打印、不提交密钥。

## 检查

改了哪层只跑哪层，完整矩阵交给 CI；命令见 [testing](docs/cookbook/testing.md)。

- 后端：`uv run ruff check .`、`uv run basedpyright`、`uv run python scripts/check_architecture.py`、
  `uv run pytest -m "not integration and not local_assets" -q`
- 契约：`uv run python scripts/export_openapi.py --check frontend/openapi.json`，前端 `pnpm api:types:check`
- 文档与笔记：`uv run python scripts/check_docs.py`、`uv run python scripts/agent_notes.py check`

## 约定

- **非平凡改动必须带笔记**：改了行为、架构、跨文件契约、流程与工具链、测试策略或落盘/网络/配置格式时，
  同一次改动写或更新 `.agents/notes/` 笔记；纯格式、样式、不改行为的补丁直接提交。
- **事实与原因分开**：当前怎样运转写 `docs/`，为什么这样定写笔记，历史留给 git。改代码时同批更新受影响的文档事实。
- **产品不变量**：严格配对键决定 QP/MS 归属；模型输出必须回到证据，无法证明即失败关闭；评分只形成
  `pending_review`，最终分来自教师。
- **一次性迁移**：重构后删除旧路径，不留 re-export、别名或兼容 shim。
- **显式科目上下文**：领域写入必须带 `SubjectContext`，通用模块不出现科目代码字面量。
- **依赖优先**：有维护良好的库能净删除手写代码时优先用库。

## 前端设计注意事项

- 非必要不在界面上写无用注释和提示
- 不要滥用副标题
