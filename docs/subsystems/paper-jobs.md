# 试卷单元与整卷任务

## 试卷单元

`paper_units` 以 `(subject_id, pair_key)` 唯一标识一次考试单元，保存显示名、年份、考季、Unit 与归档
状态；`paper_unit_documents` 显式记录单元内每份资料及其角色（Question Paper、Mark Scheme、Source
Booklet）。一份资料只属于一个单元，同一角色可有多份。绑定时服务校验资料属于当前科目、状态可用、
配对键完全一致且角色与 `source_type` 一致。存在关联作答时拒绝归档单元。

## 任务生命周期

整卷作答不在 HTTP 请求内执行。上传接口校验格式与大小（QP 默认上限 25 MiB，ASGI 层按请求头和实际
接收字节双重限制）、写入对象存储、建 PostgreSQL 任务后返回 `202 + job_id`。

```text
queued → parsing → vision_review → splitting → answering → completed
                                                     └→ partial_failed（至少一题失败）
任一前置阶段重试预算耗尽 → failed
```

| 阶段 | 行为 |
|---|---|
| `parsing` | PDF 按 5 页一段调用 MinerU，每段 Markdown 成功即保存检查点；结构化模型按实际内容分类文档，只有高置信 Question Paper 继续 |
| `vision_review` | 视觉模型逐物理页对照原页图修复题号、子问、公式、表格、图形描述与分值；每页一请求，默认每 Worker 两路并发；供应商、JSON 或低置信失败最多重试三次；结果存 `.vision.md` / `.vision.json` |
| `splitting` | 按物理页标记把视觉主源切成约 4,000 字符批次，快速结构模型两路并发拆题；每批检查点按模型、提示契约和输入摘要复用 |
| `answering` | 每题一个有界 Agent run，单卷内最多四题并发；见 [answering-agent](answering-agent.md) |

MinerU 的 `content_list` 先按 `page_idx` 生成页级 Markdown，视觉请求只携带当前页文本。图片只保留
Markdown 中有明确位置且达到实质尺寸的资产；字形碎片与未引用图片不归属到题目。

## 分题完整性

视觉复核 Markdown 是唯一权威主源。每个持久化题目必须与主源逐项守恒：顶层题号顺序、子问标签、
逐项分值、总分与来源页。视觉依赖 `requires_visual_context` 在这次对账中判定一次并持久化。

- 重叠批次出现同题冲突时，只调用一次有界结构化模型选择权威候选；结果仍须通过守恒门禁，否则失败。
- PDF 文本层只定位主源完全缺失的题号，不覆盖、不逐字段补写已有主源题目，不按文本长度择优。
- 任务与题目保存 `source_integrity_status`、分题契约版本、主源摘要与来源页。

未通过当前契约的已结束任务标为 `legacy_unverified`，不能原地重试；`POST /papers/jobs/{id}/replace`
从同一原卷创建新任务并双向记录替代关系。导入答案的替代任务复制原答案，原答案缺失时拒绝。

## Worker 与租约

PostgreSQL 是持久队列真相。Worker 以 `FOR UPDATE SKIP LOCKED` 领取任务并写入 lease token，租约
60 秒、每 20 秒续租；每次提交带原 token 做条件更新，晚到的旧 Worker 不能覆盖。`LISTEN/NOTIFY`
即时唤醒，轮询兜底。Compose 默认两个 Worker，每份试卷由一个租约 Worker 持有。进程崩溃后新 Worker
从第一个未完成页段或题目续跑。

## 接口

- `POST /api/v1/papers/answer`、试卷单元内的作答入口：创建任务。
- `WS /api/v1/papers/jobs/{id}/events`：权威任务快照流；`GET /api/v1/papers/jobs/{id}` 用于刷新恢复。
- `POST /api/v1/papers/jobs/{id}/retry`：只重试失败步骤，不重复已完成页段或题目。
- 删除作答为永久删除，同时清除关联评分与复核审计，并让对应对象进入立即回收。
