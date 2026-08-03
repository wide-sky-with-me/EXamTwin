# ExamTwin 9660

OxfordAQA International AS/A-level Mathematics (9660) 的证据型知识库、整卷逐题
RAG 作答与 mark scheme 自动初评工作台。

系统的基本约束是：

- syllabus 决定知识边界与官方从属结构；
- question paper、mark scheme 必须按年份、考季和 unit 严格配对；
- examiner report 的 facility/mean 等量化数据与定性描述分别记录证据等级；
- LLM 只能基于检索证据提出答案或 rubric 逐项建议分；
- 自动评分一律进入人工复核，不直接发布。

## 技术栈

| 层 | 实现 |
|---|---|
| Python | `uv`、FastAPI、LlamaIndex |
| 文档解析 | `llama-index-readers-mineru`，precision 模式，PDF 超过 200 页时分段且可续跑 |
| 解题/评分 | OpenAI-compatible API，默认 `gpt-5.6-sol`，解题为 medium reasoning |
| 试卷视觉复核 | PyMuPDF 渲染页图，`gpt-5.6-terra` 对照 MinerU 逐页修复并保存检查点 |
| 整卷拆题 | OpenAI-compatible API，默认 `gpt-5.6-luna`，独立 90 秒超时 |
| 通用答案图片 | `gpt-image-2` 生成受控 PNG artifact；数学精确图仍优先使用本地矢量工具 |
| Embedding | 硅基流动 `Qwen/Qwen3-Embedding-8B` |
| Rerank | 硅基流动 `Qwen/Qwen3-Reranker-8B` |
| 关系与任务数据 | Docker 中的 PostgreSQL，SQLAlchemy Repository + Alembic 分批迁移 |
| 向量数据 | Docker 中的 Qdrant，staging collection + live alias 原子发布 |
| 文件存储 | 统一 `ManagedObjectStore`；本地或 SeaweedFS S3 后端、PostgreSQL 对象目录、保留期与 GC |
| Python 运行时 | API 与整卷 Worker 使用同一个 uv 锁定的 Docker 镜像 |
| 整卷后台任务 | PostgreSQL 持久任务/租约/检查点，`LISTEN/NOTIFY` 唤醒，超时轮询兜底 |
| 前端 | 项目固定 `pnpm 11.1.1`、React、TypeScript、Vite |

运行约束：PostgreSQL、Qdrant、FastAPI 和整卷 Worker 统一通过 `compose.yaml` 运行；
API 与 Worker 必须来自同一个 uv 锁定镜像，避免前端命中新旧不一致的 Python 进程。
转换缓存、任务文件和答案图片统一经 `ManagedObjectStore` 写入；默认本地后端位于
`EXAMTWIN_STORAGE_ROOT`（`./var`），并按 `corpus/md`、`paper-jobs`、`answer-artifacts` 分区。
每个对象在 PostgreSQL 中记录用途、owner、SHA-256、大小、MIME、保留期和删除状态；API、Worker
和 GC 只依赖同一个深接口，不再各自拼路径。前端仍由 `pnpm` 管理，不依赖宿主机安装数据库或
任务队列服务。
前端的 pnpm v11 store 固定在 `frontend/.pnpm-store`（不纳入版本控制），避免依赖用户级
可写状态；允许执行安装脚本的依赖目前只有锁定的 `esbuild`。
当前部署边界是单机、单用户工作台；PostgreSQL、Qdrant、SeaweedFS 端口均只允许 loopback，
API 还会在 ASGI 边界拒绝非 loopback HTTP/WebSocket 客户端。不要在反向代理后关闭这条边界
并直接暴露到 LAN 或公网。多用户部署前必须补齐统一认证、授权和 tenant 绑定；对象目录中的
owner 是生命周期归属，不是当前缺失的用户鉴权替代品。

## 启动

密钥已经放在不受 Git 跟踪的 `.env`。新环境应从 `.env.example` 复制，并手工
填写密钥。`.env.example` 同时列出应用字段与 Compose-only 字段；修改后先运行配置契约检查。

```bash
uv sync
uv run examtwin config-check
docker compose up -d --build
uv run examtwin init
uv run examtwin inventory
```

另开终端启动前端：

```bash
cd frontend
pnpm install
pnpm dev
```

前端地址为 `http://localhost:5173`，FastAPI 文档为
`http://localhost:8000/docs`。

默认 `OBJECT_STORE_BACKEND=local`，不依赖额外镜像即可运行。需要 S3 兼容后端时，项目已固定
SeaweedFS 4.27，并按官方 `weed mini` 方式创建带凭据的 bucket：

```bash
OBJECT_STORE_BACKEND=s3 docker compose --profile s3 up -d --build
OBJECT_STORE_BACKEND=s3 uv run examtwin storage-migrate --dry-run
OBJECT_STORE_BACKEND=s3 uv run examtwin storage-migrate --execute
```

迁移是幂等复制/登记，不删除旧文件；`storage-gc` 服务按保留期做有界批处理，删除失败会在
`stored_objects` 中保留并重试。手工对账可运行 `uv run examtwin storage-gc`。上传试卷及其
派生页图默认保留 30 天，答案 PNG 默认保留 30 天；Markdown 课程缓存无自动过期。

`docker compose ps` 中 `api` 必须显示为 `healthy`。其健康检查不仅要求 HTTP 200，
还会校验 v11 契约、持久化保护层、课纲候选流水线与答案作图门禁；因此旧 API 不会被误判成可用。原始 9660
资料以只读方式挂载进 API/Worker，单一 `var/` 根目录用于可写缓存、任务和答案图片。代码变化后重新执行
`docker compose up -d --build api paper-worker storage-gc`，由 API 服务唯一构建共享镜像，保证
API、Worker 与 GC 同版本，同时避免 Compose 为同一镜像重复执行三次构建。

## 数据管线

先清点全部 9660 文件并建立严格配对清单：

```bash
uv run examtwin inventory
uv run examtwin stats
```

按类型调用 MinerU 转换。任务会缓存每份 Markdown；大于 200 页的 PDF 会按
200 页分段缓存，因此失败后可以续跑：

```bash
uv run examtwin convert --type syllabus
uv run examtwin convert --type textbook
uv run examtwin convert --type question_paper --type mark_scheme
```

转换完成后，调用硅基流动 embedding 并安全发布 Qdrant 索引：

```bash
uv run examtwin curriculum-preview --output /tmp/curriculum.json
uv run examtwin knowledge-build --no-ai-difficulty
uv run examtwin index
```

`index` 每次写入新的 staging collection，记录输入哈希与检查点，全部点数门禁通过后
才把 `examtwin_9660_live` alias 原子切换到新版本。失败可使用 `--resume`继续，上一版仍可用；
为防止小样本误覆盖线上知识库，`index --limit` 不允许发布。

`curriculum-preview` 从当前科目的真实课纲 Markdown 生成完整候选并运行结构、数量、父子关系
和已发布节点漂移门禁，不写候选表也不发布图谱。`knowledge-build` 是显式、可审计的发布入口；
它先把同一候选、提取器版本、输入/内容哈希和校验结果写入 `curriculum_candidates`，只有零错误、
零警告的候选才自动发布。API 启动、`init` 和 `inventory` 不会隐式改写正式图谱。运行记录保存
输入哈希、阶段、产物、指标和失败原因。若需要在缺少真实表现资料时让 AI 根据课纲估计难度
分项，显式执行：

```bash
uv run examtwin knowledge-build --ai-difficulty
```

AI 结果只作为 D 级冷启动证据，置信度上限为 0.45；同一课纲输入和同一模型会复用已完成
批次。每批结果都会立即写入运行检查点，失败后只补缺失批次，全部知识点通过门禁后才事务
发布。普通启动、确定性建图和测试都不会调用模型。

知识构建、向量索引、语料、整卷任务、评分与总览投影都使用 SQLAlchemy 2.0 ORM、领域
Repository 与显式 Session 事务；
业务流水线不直接拼 SQL。项目使用 psycopg 3，因此 ORM 连接统一规范为
`postgresql+psycopg://`。Alembic 会在 API 启动时幂等升级，也可显式执行 `uv run examtwin db-upgrade`。
业务服务和 API 不再持有旧 `Database` 包装器或拼接 SQL；Alembic 是唯一 schema 来源。

知识点不再维护在 `seed/knowledge_<subject>.py` 一类逐科常量文件中。新增科目在
`examtwin/subjects/` 注册一个小型 `SubjectPack`：考试局、科目代码、Unit 映射、课纲编号模式、
试卷 Unit 识别、学科文字正规化策略和最小完整性阈值；通用提取器不包含数学或经济学术语；
主题、学习目标、来源页、层级和初始特征全部由统一 `CurriculumExtractor` 从已转换课纲生成。

已注册第二个真实科目包 `oxfordaqa-economics-9640`。可用已购买的官方 PDF 做零模型调用的结构漂移检查：

```bash
uv run examtwin subject-pack-audit --pack oxfordaqa-economics-9640
```

当前 PDF 漂移检查覆盖 84/84 个官方课纲主题；同一通用提取器还从该 47 页课纲文本生成了 4 个
Unit、84 个主题和 484 个学习目标且零未映射。这个证据证明主流程不依赖逐科知识常量；它不代表
9640 已完成 MinerU 入库、正式建图和独立 RAG 索引发布。

用于首次验通的小批量命令：

```bash
uv run examtwin bootstrap --convert-limit 6
```

## 难度模型

知识点和题目难度统一输出到 `[0,1]`。聚合函数最多使用六类特征：syllabus
复杂度、先修深度、AO 认知要求、历史 facility 的反值、解题步数和 examiner
严重度。缺少历史 facility 或 examiner 证据时不会拿别的特征重复代替，而是只对实际存在
的特征重新归一化权重，再通过端点归一化 sigmoid 映射到完整区间。

难度值必须与 `confidence` 和证据等级一起使用：

- A：官方量化数据（facility、mean mark、discrimination 等）；
- B：官方定性或比例描述；
- C：有验证依据的历史估计；
- D：课程结构与 LLM 冷启动推断。

当前 9660 知识图从官方 specification 建立 5 个 Unit、38 个主题和 183 个学习目标节点，
并显式保存官方层级的 `contains` 和同一主题内官方列举顺序的 `syllabus_sequence`。旧 seed 仅凭
课纲顺序推断的 72 条 `prerequisite_of` 已删除；只有后续带明确来源和置信度的关系才能发布。
主题与学习目标
学习目标当前已有由结构化 AI 分项评定、统一函数归一化的 D 级课纲冷启动值；模型、输入
哈希、理由、置信度和构建 run 均保留。后续从 examiner report 或真实作答抽取的 A/B/C
证据应参与重新聚合，而不是把 D 级推断冒充官方结论。

## 整卷逐题作答

Web 端“试卷逐题作答”支持上传 UTF-8 Markdown 或不超过 25 MB 的 PDF。ASGI 层会在 multipart
解析完成前按请求头和实际接收字节双重限制请求体，避免超大请求先占满内存或临时磁盘。上传接口保存文件和
PostgreSQL 任务后立即返回；Docker Worker 按 5 页分段调用 MinerU，每段成功后保存 Markdown
检查点和页数进度。PDF 页段会先由视觉模型对照原页图复核，恢复 MinerU 漏掉的题号、子题、
公式、表格、图形描述和分值，并保存独立 `.vision.md/.vision.json` 检查点；供应商、JSON
或低置信结果最多自动重试三次。视觉校正完成后，快速结构模型根据题号、子题、分值和翻页
信息恢复顶层题目。结构抽取、视觉核对与数学解题使用不同模型和超时预算。每题建立一个
有界 Answering Agent run；Agent 能看到课程、unit、试卷配对、来源类型和权威等级的检索
范围，并在最终作答前通过 `knowledge_search` 工具取得知识库证据。它可以继续读取完整原文、
校验计算或调用学科绘图/通用图片工具，并返回：

- 保留全部子题的题干和分步 Markdown 解答；
- 可直接展示、全屏查看的受控矢量图或 PNG 答案图片；
- 可展开的来源文件、页码和证据片段；
- 匹配到的细粒度 syllabus 学习目标及 `[0,1]` 难度；
- grounded、置信度、警告和单题失败状态。

`POST /api/v1/papers/answer` 返回 `202 + job_id`；前端通过 WebSocket
`/api/v1/papers/jobs/{job_id}/events` 接收权威任务快照，并逐步展示页数、题数、Agent 工具步骤
和已完成答案；`GET /api/v1/papers/jobs/{job_id}` 保留为刷新恢复与诊断接口。刷新页面会恢复最近
任务。解析失败或部分题目失败时，`POST /api/v1/papers/jobs/{job_id}/retry` 只重试失败步骤，
不重复已完成 MinerU 或视觉页段。Compose 默认两个 Worker，单份试卷由一个租约 Worker
持有并在内部最多四题并发，因此可同时推进两份试卷；原 `POST /api/v1/rag/ask` 保留为兼容
接口。Worker 空闲时由 PostgreSQL 任务事件立即唤醒，通知丢失时仍按配置间隔重新扫描；
任务行而不是瞬时通知承担持久队列真相。Worker 用 60 秒 PostgreSQL 租约并每 20 秒续租；
进程异常退出时，新 Worker 最多约一分钟后接管，不会重做已完成页段或题目。

## 评分契约

`POST /api/v1/grading/assess` 接收学生 Markdown 答案。题目和 mark scheme
可以直接传 Markdown，也可以给出已入库的严格配对引用。没有 mark scheme 时
服务拒绝给分。响应包含：

- 每个 M/A/B rubric 原子的满分、建议分和学生答案证据；
- 总分与模型置信度；
- 可选的受限符号等价检查；
- 来源和风险警告；
- `pending_review` 状态。

教师通过 `POST /api/v1/grading/reviews/{assessment_id}` 确认或改分，之后状态
才变为 `confirmed` 或 `overridden`。

## 测试

```bash
uv run examtwin config-check
uv run ruff check backend/src backend/tests
uv run pytest -m 'not integration'
cd frontend && pnpm test && pnpm lint && pnpm build
```

PostgreSQL 集成测试需要显式提供 `EXAMTWIN_TEST_DATABASE_URL`；测试进程会创建唯一临时同级
数据库并在结束时只删除自己创建的库，因此不会复用或清空固定共享库。测试不会读取或调用
真实模型密钥；云端连通性通过单独的显式 smoke test 验证。
