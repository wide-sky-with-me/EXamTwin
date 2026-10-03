# Agent Note: Alembic 为唯一 schema 来源，领域 Repository 拥有查询与事务

Status: implemented

## Problem

服务层通过旧 `Database` 包装器拼接 SQL，部分工具用 `isinstance(Database)` 在真实存储与测试替身之间
分支；29 个时间字段为 Text，租约领取与排序依赖 ISO 字符串格式一致。

## Decision

- Alembic 是唯一 schema 来源；空库只靠 `alembic upgrade head` 得到完整 schema，API 启动与
  `examtwin db-upgrade` 幂等执行迁移。
- 数据访问统一为 SQLAlchemy 2.0 Model、显式 Session 与按领域划分的 Repository；业务服务与 API 不拼 SQL。
- 驱动为 psycopg 3，ORM 连接统一规范为 `postgresql+psycopg://`。
- 时间字段为 `TIMESTAMPTZ`，比较由数据库时间语义保证。
- 迁移逐个领域进行：每次由一个 Repository 收口查询、事务与测试面。

## Alternatives considered

- **保留 `Database` SQL 兼容层** — 不改调用方。但 SQL 继续散落，测试依赖类型分支，schema 没有版本。
- **一次性把全部 SQL 机械翻译为 ORM** — 一步到位。没有领域 Repository 收口时只是换了写法，测试面和
  事务边界仍然不清。

## Consequences

- **收益**：schema 可版本化回放；事务与查询有单一所有者；测试替换 Repository 而不是数据库类型。
- **代价与已知上限**：迁移必须向前兼容现有数据，不能 drop/recreate；每次 schema 变化都要写迁移并在
  临时库验证。
