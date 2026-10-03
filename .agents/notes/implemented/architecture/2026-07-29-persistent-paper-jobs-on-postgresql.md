# Agent Note: 整卷任务使用 PostgreSQL 持久队列与租约 Worker

Status: implemented

## Problem

整卷作答包含 MinerU 解析、逐页视觉复核、拆题和十几道题的 Agent 作答，耗时以分钟计且依赖多个外部服务。
放在 HTTP 请求内执行时，任何一个外部超时都会让整次请求失败、丢失已完成的工作且无法续跑
（[事故复盘](../../../../docs/postmortem/2026-07-29-whole-pdf-mineru-timeout.md)）。

## Decision

- 上传接口只校验、写对象存储、建任务并返回 `202 + job_id`；处理由独立 `paper-worker` 进程完成。
- PostgreSQL 是队列真相：Worker 在短事务内以 `FOR UPDATE SKIP LOCKED` 领取任务并写入随机 lease token
  与过期时间，事务外调用外部服务；每次提交结果都带原 token 做条件更新，晚到的旧 Worker 写入无效。
- 租约 60 秒、每 20 秒续租；进程崩溃后新 Worker 从第一个未完成页段或题目继续。
- `LISTEN/NOTIFY` 负责即时唤醒，超时轮询兜底；任务行而非通知承担持久状态。
- PDF 5 页一段解析，每段、每页视觉结果、每个拆题批次和每道题都是独立检查点；重试只执行失败步骤。
- `PaperJobService` 唯一拥有状态转换、进度投影、失败与重试规则，API 与 Worker 都经它改变状态。
- 一份试卷只由一个租约 Worker 持有，内部逐题并发上限 4；Compose 默认两个 Worker。

## Alternatives considered

- **FastAPI `BackgroundTasks`** — 零新增进程、实现最快。但任务仍绑定 Web 进程，重启即丢失，无法提供
  租约、接管和续跑。
- **Redis + Celery** — 成熟的任务队列，支持优先级和弹性扩容。但单机低并发下 PostgreSQL 已能安全领取
  任务，新增消息基础设施不会消除外部服务超时风险，还会产生第二份重试状态。触发重访：多机 Worker、
  弹性扩容或数据库轮询成为可观测瓶颈；届时只替换“领取任务”这一层，任务状态仍以数据库为真相。
- **调大外部调用超时** — 改动最小。但只会延长无反馈等待，不能恢复已完成的工作。

## Consequences

- **收益**：HTTP 断开、页面刷新、Worker 重启都不丢已完成的页段和题目；单题失败不影响其他题。
- **代价与已知上限**：Worker 与 API 必须来自同一镜像，否则检查点契约可能不一致；轮询与 NOTIFY 只适合
  单机部署。检查点契约变化时必须升级契约版本，旧检查点按输入摘要拒绝复用。

## Verification

`backend/tests` 中的租约过期接管、旧租约拒写、页段失败续跑由 PostgreSQL 集成测试覆盖
（`uv run pytest -m integration`）。
