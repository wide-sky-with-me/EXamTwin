# Agent Note: 后端按业务能力组织，依赖方向由脚本强制

Status: implemented

## Problem

后端按 `api / schemas / services / persistence / composition.py` 横向分层：一个功能变化横跨多个目录，
路由内直接构造 Session 与 Repository，根级组合根成为依赖热点，Agent 还反向导入根级服务。约束只靠约定。

## Decision

- 顶层只有 `subjects`、`knowledge`、`assessment`、`platform`、`contracts`、`app`。依赖方向
  `subjects → knowledge → assessment → app`；`platform` 与 `contracts` 在底层，不依赖业务模块。
- 业务领域间只经上游 `<feature>.public`；`app` 适配与组合根可导入内部实现。domain/application 不依赖
  FastAPI、SQLAlchemy、Qdrant、boto3、LiteLLM，具体客户端和数据库访问属于 adapter。
- Persistence adapter 归属所在业务模块；`platform` 只提供连接、Session 与客户端。
- `app/composition.py` 是唯一组合根，只构造和连接依赖；HTTP handler 只做协议转换与错误映射。
- 只在需要时创建 `domain.py`、`ports.py` 等文件，不预建空层；迁移不保留旧路径 re-export 或兼容 shim。
- `scripts/check_architecture.py`（含相对导入解析）在 CI 中强制以上规则。
- 同领域纯规则与运行编排的局部划分见[候选题规则](../simplification/2026-10-14-paper-question-candidate-rules.md)，
  保留整卷服务与持久化入口，不扩展领域间公共接口。

## Alternatives considered

- **保留横向分层** — 不需要迁移。责任归属只能靠文件名和记忆判断，新增科目、工具或 Worker 会放大散落。
- **引入 DI 框架或消息总线** — 自动装配依赖。单进程组合根已足够，额外框架增加间接层而不解决归属问题。
- **把全部数据库代码集中到 `platform/database`** — 看起来统一。事务与查询语义属于业务，集中后平台层
  反向拥有业务规则。
- **全仓一次性重写** — 一步到位。风险集中且难以验证；实际按 `subjects → knowledge → assessment →
  platform/app` 垂直切片迁移，每片完成即删除旧路径。

## Consequences

- **收益**：一次业务变化集中在一个模块；依赖违规在 CI 失败。
- **代价与已知上限**：跨模块需求必须先在 `public` 暴露最小契约；少数共享 ORM model 的归属需要逐案决定。
