# Agent Note: 协议常量具名固定，部署能力入配置，科目差异入包，视觉值入主题 token

Status: implemented

## Problem

API 前缀可配置但资源 URL 固定写 `/api/v1`；端口在 Compose、CLI 与健康检查重复；模型预算、超时与重试
散落在业务代码；难度分档阈值重复实现；内置科目展示信息维护两份；前端大量直接颜色绕过主题变量。
这些值会在不同位置悄悄分叉。

## Decision

- API v1 路径是稳定协议常量，不提供会令公开资源路径分叉的前缀开关；监听端口由同一部署配置驱动
  Uvicorn、健康检查与前端代理。
- 供应商端点、模型预算、终稿超时、MinerU 超时与重试均为 `Settings` 配置；`.env.example` 与 `Settings`
  由 `examtwin config-check` 保证一致，Compose-only 键单独登记。
- 难度分档 `0.34 / 0.67`、评分置信度与成绩建议阈值集中为具名政策常量；改变数值必须经产品决定。
- 科目图标、颜色与架构门禁的科目代码清单来自 SubjectPack。
- 前端颜色与毛玻璃表面来自明暗主题 token；分页策略共享。
- 数学与图形算法常量、防御性上限保留为代码常量，不伪装为部署选项。

## Alternatives considered

- **全部做成可配置项** — 最灵活。协议路径与防御上限变成可配置后，部署间会出现不兼容的资源 URL 和
  不安全的上限，且配置面难以验证。

## Consequences

- **收益**：同一事实只有一个来源；配置缺漏由 `config-check` 在启动前发现。
- **代价与已知上限**：新增配置项必须同时更新 `Settings`、`.env.example` 与私有 `.env`。
