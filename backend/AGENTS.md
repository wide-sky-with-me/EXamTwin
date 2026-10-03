# backend 规则

Python 3.11+，由 uv 锁定；包根 `backend/src/examtwin/`。模块职责见 [架构全景](../docs/architecture.md)。

## 依赖与边界

- 方向固定：`subjects → knowledge → assessment → app`；`platform`、`contracts` 不依赖业务模块。跨模块只经
  `<feature>.public`。违反时 `scripts/check_architecture.py` 失败。
- domain 与 application 代码不导入 FastAPI、SQLAlchemy、Qdrant、boto3、LiteLLM；这些只出现在 adapter。
- HTTP handler 只做协议转换与错误映射；依赖只在 `app/composition.py` 构造。
- 通用模块不出现科目代码字面量；科目差异进 SubjectPack 或宿主 provider。
- 不新建 `common`、`utils`、`base_service` 一类横向抽象层，只在需要时创建 `ports.py` 等文件。

## 数据

- schema 只由 Alembic 迁移定义，迁移向前兼容现有数据，不 drop/recreate；新迁移须在临时库上验证。
- 查询与事务属于所在领域的 Repository，服务层不拼 SQL。
- 文件只经 `ManagedObjectStore` 读写，数据库只存对象键。
- 跨越人工门禁的状态迁移（评分原子、assessment、发布）必须在仓储事务内校验，不能只靠 HTTP 契约。

## 外部服务

- 模型请求只经 `platform/litellm_provider.py`，参数来自角色配置，不按模型名分支。
- 新增配置项同时更新 `platform/config.py` 的 `Settings`、`.env.example` 与私有 `.env`，并通过
  `uv run examtwin config-check`；Compose-only 键登记在 `platform/config_contract.py`。
- 普通测试不得调用真实模型、数据库或网络；需要真实基础设施的测试标记 `integration`。

## 契约

改动 HTTP 契约后运行 `uv run python scripts/export_openapi.py frontend/openapi.json` 更新快照，再在前端
重新生成类型；`--check` 在 CI 中拦截漂移。
