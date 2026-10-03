# 2026-07-29 整卷同步请求在 MinerU 超时后整体失败

## 现象

真实 PDF 上传后浏览器等待十几分钟，返回 `Paper answering provider error: Request timed out.`；后台对应
请求为 502，任务不再运行，也无法续跑。

## 根因链

1. 上传路径把整份 PDF 作为单个 MinerU precision 请求，超时上限 1200 秒。
2. 该阶段没有进度事件、页段缓存或任务持久化；异常由 API 统一映射为 502。
3. 临时 PDF 在 `finally` 中删除，失败后无可续跑的输入。

逐题作答不是来源：逐题异常在编排器内已转为单题失败；十几分钟的时长与 MinerU 等待边界吻合。

## 修复

整卷处理移出 HTTP 请求：PostgreSQL 持久任务 + 独立 Worker、5 页一段的 MinerU 检查点、租约接管、
WebSocket 进度与只重试失败步骤。见 [paper-jobs](../subsystems/paper-jobs.md) 与
[持久任务决策](../../.agents/notes/implemented/architecture/2026-07-29-persistent-paper-jobs-on-postgresql.md)。

## 教训

外部依赖不确定时，调大超时只会延长无反馈的等待。长任务必须有持久状态、分段检查点和可观察进度。
