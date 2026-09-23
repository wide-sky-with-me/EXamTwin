# ExamTwin

面向多科目的证据型知识库、整卷逐题 RAG 作答与 mark scheme 自动初评工作台。默认部署包为
OxfordAQA International AS/A-level Mathematics (9660)，科目边界由版本化 SubjectPack 声明。

系统的基本约束是：

- syllabus 决定知识边界与官方从属结构；
- question paper、mark scheme 必须按年份、考季和 unit 严格配对；
- examiner report 的 facility/mean 等量化数据与定性描述分别记录证据等级；
- LLM 只能基于检索证据提出答案或 rubric 逐项建议分；
- 自动评分一律进入人工复核，不直接发布。

## 技术栈

| 层 | 实现 |
|---|---|
| Python | `uv`、FastAPI；内部 provider-neutral Agent Harness，LlamaIndex/LiteLLM 作为适配器 |
| 文档解析 | `llama-index-readers-mineru`，precision 模式；超大 PDF 物理分片，旧 PPT 经 LibreOffice 转 PDF 后可续跑 |
| 解题/评分 | LiteLLM → DMXAPI，默认 `gpt-5.6-sol`，解题为 medium reasoning |
| 试卷视觉复核 | PyMuPDF 渲染页图，`gpt-5.6-terra` 对照 MinerU 逐页修复并保存检查点 |
| 整卷拆题 | LiteLLM → DMXAPI，默认 `gpt-5.6-luna`，独立 90 秒超时 |
| 通用答案图片 | LiteLLM → DMXAPI `gpt-image-2-ssvip` 生成受控 PNG artifact；数学精确图仍优先使用本地矢量工具 |
| Embedding | 硅基流动 `Qwen/Qwen3-Embedding-8B` |
| Rerank | 硅基流动 `Qwen/Qwen3-Reranker-8B` |
| 关系与任务数据 | Docker 中的 PostgreSQL，SQLAlchemy Repository + Alembic 分批迁移 |
| 向量数据 | Docker 中的 Qdrant，staging collection + live alias 原子发布 |
| 文件存储 | 统一 `ManagedObjectStore`；本地或 SeaweedFS S3 后端、PostgreSQL 对象目录、保留期与 GC |
| Python 运行时 | API 与整卷 Worker 使用同一个 uv 锁定的 Docker 镜像 |
| 整卷后台任务 | PostgreSQL 持久任务/租约/检查点，`LISTEN/NOTIFY` 唤醒，超时轮询兜底 |
| 前端 | 项目固定 `pnpm 11.1.1`、React、TypeScript、Vite |

### 后端模块边界

`backend/src/examtwin/` 按业务能力组织，而不是按 `services`、`schemas`、`persistence`
技术层横切：

| 边界 | 责任 |
|---|---|
| `app/` | FastAPI/CLI 入口、HTTP 适配器和 composition root |
| `subjects/` | 学科包、运行时学科上下文与公开入口 `subjects.public` |
| `knowledge/` | corpus、课程图谱、检索和知识库发布；跨 feature 只经 `knowledge.public` |
| `assessment/` | 整卷作答、Agent、rubric、评分、复核和持久任务 |
| `platform/` | 配置、数据库、对象存储、模型适配器和通用 Agent runtime |
| `contracts/` | 稳定 HTTP/任务数据契约，不依赖运行时模块 |

依赖方向固定为 `subjects → knowledge → assessment → app`；`platform` 和 `contracts`
位于底层，不反向依赖业务 feature。`scripts/check_architecture.py` 在 CI 中拒绝反向依赖、
绕过 feature 公共入口、业务模块直接引入 FastAPI，以及重新建立旧横向包。

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
API 默认以 `API_BIND_HOST=127.0.0.1` 监听，并在 ASGI 边界拒绝非 loopback HTTP/WebSocket
客户端。若同时把 `LOCAL_ACCESS_ONLY=false` 与 `API_BIND_HOST` 配成非 loopback，健康接口会
返回 `degraded` 并指出当前没有认证边界；不要把该状态直接暴露到 LAN 或公网。多用户部署前
必须补齐统一认证、授权和 tenant 绑定；对象目录中的 owner 是生命周期归属，不是用户鉴权替代品。

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

前端默认地址为 `http://localhost:5173`，FastAPI 默认文档地址为
`http://localhost:8000/docs`；本机可通过 `.env` 的 `API_PORT` 改端口，Vite 代理会同步读取。
本机访问边界同时校验 Host 和浏览器 Origin；自定义前端域名需加入 `CORS_ORIGINS`。
无 Origin 的本机命令行请求仍可使用。若提高 `KNOWLEDGE_UPLOAD_MAX_BYTES`，也应同步调整
本地代理的请求容量；默认代理允许 25 MiB 试卷与 256 MiB 配套材料及 multipart 开销。

### Docker Desktop / WSL 本地开发

Docker Desktop 的 `host` 网络可能只在 Docker VM 内可达，表现为容器健康但宿主机无法访问 API。
此时使用本地覆盖文件，数据库、向量库与 S3 在 Compose 网络中互联；API 仍只监听容器 loopback，
同网络命名空间的 Nginx 代理只通过宿主机 `127.0.0.1` 发布，不关闭 `LOCAL_ACCESS_ONLY`。
代理内部使用 `18001`，不要将 `API_PORT` 设为该值。

1. 在私有 `.env` 中选择空闲的 `API_PORT`（例如 `18000`）。如使用 S3，设置非默认的
   `OBJECT_STORE_ACCESS_KEY` 和随机 `OBJECT_STORE_SECRET_KEY`；容器 DNS 地址同样受凭据门禁约束。
2. 同步依赖并启动（S3 配置必须带 `--profile s3`）：

```bash
uv sync --frozen --group dev
uv run examtwin config-check
docker compose -f compose.yaml -f compose.local.yaml --profile s3 up -d --build --wait
cd frontend
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1 --strictPort
```

使用上述端口时，页面为 `http://127.0.0.1:5173`，API 文档为 `http://127.0.0.1:18000/docs`。
后端修改后仍需以**相同的两个 Compose 文件**重新构建并启动；不要混用仅主文件的启动命令，
否则会恢复 `host` 网络。该覆盖文件沿用主配置的数据卷，不删除或自动导入其他版本遗留的数据卷。
新数据库自动迁移并注册两个内置科目；原始资料存在不表示已有课程图谱、转换缓存或向量索引。

普通回归从项目根目录执行，不依赖容器，不继承本地供应商凭据；真实基础设施测试单独显式启用：

```bash
uv run pytest -m "not integration and not local_assets" -q
cd frontend
pnpm test && pnpm lint && pnpm build && pnpm api:types:check
# 默认 4173 不可用时，为浏览器测试指定空闲端口，禁止静默漂移
PLAYWRIGHT_PORT=4175 pnpm test:visual
```

`integration` 测试需显式提供 `EXAMTWIN_TEST_DATABASE_URL`，仅对本次生成的临时数据库迁移、
清理，不使用开发库；S3 往返测试另需 `EXAMTWIN_TEST_S3_ENDPOINT`、`EXAMTWIN_TEST_S3_BUCKET`、
`EXAMTWIN_TEST_S3_ACCESS_KEY` 和 `EXAMTWIN_TEST_S3_SECRET_KEY`。密钥只通过本机环境注入。
浏览器截图基线按平台分目录，旧参考图仍保留；环境与对照说明见
[`frontend/e2e/__screenshots__/README.md`](frontend/e2e/__screenshots__/README.md)，不要用放宽阈值替代人工对照。

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

`docker compose ps` 中 `api` 必须显示为 `healthy`。健康检查要求 HTTP 200、当前 API 契约、
持久任务、知识/检索发布和答案产物能力同时存在，因此旧 API 不会被误判成可用。两科原始
资料只读挂载，单一 `var/` 根目录用于可写缓存、任务和答案图片。代码变化后重新执行
`docker compose up -d --build api paper-worker storage-gc`；API 服务唯一构建共享镜像，
保证 API、Worker 与 GC 同版本，避免同一镜像重复构建。

## 数据管线

先选择 SubjectPack，清点该科目文件并建立严格配对清单：

```bash
uv run examtwin inventory
uv run examtwin stats
```

按类型调用 MinerU 转换。任务会缓存每份 Markdown；超过 200 页或安全上传字节上限的 PDF
会先物理切成最多 200 页的小 PDF，再逐段上传并缓存，因此不会把超大原文件反复交给供应商。
旧 `.ppt` 由镜像内的 LibreOffice 无界面转成临时 PDF，派生文件仅存在于任务临时目录：

```bash
uv run examtwin convert --type syllabus
uv run examtwin convert --type textbook
uv run examtwin convert --type question_paper --type mark_scheme
```

转换完成后，调用硅基流动 embedding 并安全发布 Qdrant 索引：

```bash
uv run examtwin curriculum-preview --output /tmp/curriculum.json
uv run examtwin index
uv run examtwin retrieval-evaluate
uv run examtwin retrieval-traces --limit 20
```

`index` 每次写入当前科目的新 staging collection，记录输入哈希与检查点，全部点数门禁通过
后才切换该 SubjectPack 的 live alias。失败可使用 `--resume` 继续，上一版仍可用；为防止
小样本误覆盖正式知识库，`index --limit` 不允许发布。

新索引同时保存稠密向量与确定性词法稀疏向量；`subject_code`、Unit、严格配对键、来源类型和
权威等级在 Qdrant 召回前过滤，rerank 后始终保留少量未被知识卡片覆盖的原始证据。
每个 SubjectPack 可以携带 `retrieval-eval.json`，`retrieval-evaluate` 对真实 live alias 计算
Recall@K、MRR、空结果率和过滤越界数，未达到包内门禁时以非零状态退出。普通检索还会把有界
trace 写入 PostgreSQL，便于按查询、过滤条件、索引 build 和候选阶段定位漏召回。
索引节点使用稳定内容指纹；首次升级构建写入指纹，之后只复用同一 embedding 服务、模型和
索引 schema 下内容未变化的稠密向量，变化节点才重新调用 embedding。中断恢复按节点 ID 补缺，不再把
collection 点数误当成节点顺序偏移。

`curriculum-preview` 从当前科目的真实课纲 Markdown 生成完整候选并运行结构、数量、父子关系
和已发布节点漂移门禁，不写候选表也不发布图谱。`knowledge-build` 是显式、可审计且必定调用
模型的发布入口；它要求当前科目已有包含官方 syllabus 与授权 textbook 的已发布 Core
Knowledge Base。流水线先为每个 Topic / Learning Objective 从层级文档块选择双来源材料，
再按 Unit 提供完整目标标尺、分批让模型直接给出 `[0,1]` 分数、相对位置、分项判断和逐字引用。
固定代码只校验结构、双来源引用、证据块归属与完整性，并把分数映射为 easy / medium / hard；
不再根据动作词、文本长度或人工权重生成难度，也没有规则回退。

```bash
uv run examtwin knowledge-build
```

结果只作为 D 级“证据化模型冷启动评级”，置信度上限为 0.45；运行记录保留核心知识库版本、
模型、提示词哈希、候选与证据内容哈希、块/文档/页码/章节、逐字引用、理由和置信度。同一完整
输入和模型会复用已完成检查点；资料、核心版本或提示词变化后重新评级。模型不可用、任一目标
缺少 syllabus / textbook 证据或引用校验失败时不发布，上一正式图谱保持可用。API 启动、
`init`、`inventory` 和普通测试不会调用模型。

知识构建、向量索引、语料、整卷任务、评分与总览投影都使用 SQLAlchemy 2.0 ORM、领域
Repository 与显式 Session 事务；
业务流水线不直接拼 SQL。项目使用 psycopg 3，因此 ORM 连接统一规范为
`postgresql+psycopg://`。Alembic 会在 API 启动时幂等升级，也可显式执行 `uv run examtwin db-upgrade`。
业务服务和 API 不再持有旧 `Database` 包装器或拼接 SQL；Alembic 是唯一 schema 来源。

知识点不再维护在 `seed/knowledge_<subject>.py` 一类逐科常量文件中。新科目放在
`subject-packs/<pack-id>/`：`manifest.json` 声明考试局、科目代码、Unit 映射、课纲编号模式、
完整性阈值和答题工具 allowlist，`SKILL.md` 仅保存已审核的学科作答语义。加载器在
服务启动边界校验 schema 版本、文件越界、科目/Unit 唯一性、正则和工具子集，并记录
Package/SKILL 摘要。Manifest 不能加载任意 Python；确实需要学科专用规则时，只能按键引用
服务端已注册的 visual policy 或 curriculum normalizer。主题、学习目标、来源页、层级和
初始特征仍由统一 `CurriculumExtractor` 从已转换课纲生成。

已安装并启用第二个真实科目包 `oxfordaqa-economics-9640`。其已审核 Skill 要求同场次 Source
Booklet、知识证据和原题图优先，并提供确定性的经济计算与标准经济图工具，不会套用数学 Skill。
可用已购买的官方 PDF 做零模型调用的结构漂移检查：

```bash
uv run examtwin subject-pack-audit --pack oxfordaqa-economics-9640
```

当前 PDF 漂移检查覆盖 84/84 个官方课纲主题；同一通用提取器从该 47 页课纲文本发布了 4 个
Unit、84 个主题和 484 个学习目标且零未映射。经济学库存中的 273 份资料均已转换并发布到独立
别名 `examtwin_9640_live`，当前索引包含 18,307 个向量节点；其中 34 组 Question Paper / Mark
Scheme 已形成严格配对。仍有 36 份考试资料身份不完整、4 份 Question Paper 没有匹配的 Mark
Scheme，状态总览会继续显式展示这些资料质量缺口。

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
- D：缺少官方表现资料时，模型基于课纲和授权教材原文给出的可审计冷启动推断。

当前 9660 知识图从官方 specification 建立 5 个 Unit、38 个主题和 183 个学习目标节点，
并显式保存官方层级的 `contains` 和同一主题内官方列举顺序的 `syllabus_sequence`。旧 seed 仅凭
课纲顺序推断的 72 条 `prerequisite_of` 已删除；只有后续带明确来源和置信度的关系才能发布。
新的知识构建会对主题与学习目标统一生成 `model-evidence-direct-v1` D 级评级，直接保存模型
分数和 Unit 内相对位置，并关联 syllabus / textbook 的文档块、内容哈希和逐字引用。后续从
examiner report 或真实作答抽取的 A/B/C 证据应参与重新聚合，而不是把 D 级推断冒充官方结论。

## 整卷逐题作答

Web 端“试卷逐题作答”支持上传 UTF-8 Markdown 或不超过 25 MB 的 PDF。ASGI 层会在 multipart
解析完成前按请求头和实际接收字节双重限制请求体，避免超大请求先占满内存或临时磁盘。上传接口保存文件和
PostgreSQL 任务后立即返回；Docker Worker 按 5 页分段调用 MinerU，每段成功后保存 Markdown
检查点和页数进度。PDF 页段会进入独立、可持久恢复的 `vision_review` 阶段，默认以每个 Worker 两路并发由
视觉模型对照原页图复核，恢复 MinerU 漏掉的题号、子题、
公式、表格、图形描述和分值，并保存独立 `.vision.md/.vision.json` 检查点；供应商、JSON
或低置信结果最多自动重试三次。每次重试会以结构化日志记录任务、页段、次数、耗时和错误类型。
视觉校正完成后，试卷按物理页标记拆成约 4,000 字符的单页/相邻页批次，默认两路并发调用快速结构模型。
拆题模型只恢复题目结构，不重复携带整份知识目录；知识点映射仍由后续检索与答题 Agent 完成。
每个拆题批次按模型、提示契约和输入摘要保存独立检查点；批次失败时，后续重试只调用未完成或摘要失配的批次，
最后再按题号确定性合并。结构抽取、视觉核对与数学解题使用不同模型和超时预算。每题建立一个
有界 Answering Agent run；Agent 能看到课程、unit、试卷配对、来源类型和权威等级的检索
范围，并在最终作答前通过 `knowledge_search` 工具取得知识库证据。它可以继续读取完整原文、
校验计算或调用学科绘图/通用图片工具，并返回：

- 保留全部子题的题干和分步 Markdown 解答；
- 可直接展示、全屏查看的受控矢量图或 PNG 答案图片；
- 可展开的来源文件、页码和证据片段；
- 匹配到的细粒度 syllabus 学习目标及 `[0,1]` 难度；
- grounded、置信度、警告和单题失败状态。

Agent system prompt 由三层合成：包内 `prompt_templates/answering/SYSTEM.md` 平台不变量、
Package `SKILL.md` 学科政策和本题运行时数据；合成摘要随 run ledger 保存。评分与课纲难度
也复用同一结构化任务原语，各自的静态政策位于受版本控制的模板，动态题目/证据作为单独
消息传入。账本不保存模型隐式思维，只保存可审计的
Package/Prompt 摘要、预算、工具调用与结果摘要。同一题后续 attempt 只会复用服务端明确标记为
replay-safe 的 CAS/确定性矢量工具结果；知识检索和配对试卷证据依赖可变索引，仍每次重新执行。

运行时的 `platform/agent_runtime` 只定义消息、模型、协议、工具执行/治理和结构化输出
Port，不导入 LlamaIndex 或 LiteLLM。现有 ReAct 格式、LlamaIndex 工具和终答/视觉
provider 适配器归入 `assessment/answering_agent`，通用模型、embedding 与 rerank
适配器归入 `platform/providers.py`。每题先根据 `QuestionSpec`、来源图片和严格配卷键
确定性缩小工具面：知识检索及学科基础验证能力保留，视觉、配卷、绘图和通用生图仅在任务
确实需要时暴露；强制检索、引用闭合和必需产物门禁仍由领域 Policy 执行，不交给模型自行决定。

`POST /api/v1/papers/answer` 返回 `202 + job_id`；前端通过 WebSocket
`/api/v1/papers/jobs/{job_id}/events` 接收权威任务快照，并逐步展示页数、题数、Agent 工具步骤
和已完成答案；`GET /api/v1/papers/jobs/{job_id}` 保留为刷新恢复与诊断接口。刷新页面会恢复最近
任务。解析失败或部分题目失败时，`POST /api/v1/papers/jobs/{job_id}/retry` 只重试失败步骤，
不重复已完成 MinerU 或视觉页段。Compose 默认两个 Worker，单份试卷由一个租约 Worker
持有并在内部最多四题并发，因此可同时推进两份试卷；原 `POST /api/v1/rag/ask` 保留为兼容
接口。Worker 空闲时由 PostgreSQL 任务事件立即唤醒，通知丢失时仍按配置间隔重新扫描；
任务行而不是瞬时通知承担持久队列真相。Worker 用 60 秒 PostgreSQL 租约并每 20 秒续租；
进程异常退出时，新 Worker 最多约一分钟后接管，不会重做已完成页段或题目。

分题进入作答前必须与视觉复核主源逐项对齐题号、子问、分值和来源页，并持久化主源摘要、
分题契约版本与唯一视觉依赖判定；PDF 文本恢复只用于定位完全漏题，不能覆盖已有主源题目。
升级前的已结束任务会显示为 `legacy_unverified`，不能原地重试。调用
`POST /api/v1/papers/jobs/{job_id}/replace` 可从同一原卷创建新任务；旧任务、新任务及替代
方向保留用于审计。
导入答案的替代任务会复制原答案并保留导入模式；原答案缺失时明确拒绝创建。

### 目标分数与双时间预算

在“试卷管理”的试卷详情中，可为 **AI 自动作答** 开启 **目标分数模拟**，填写目标分数、容差、可备考小时、考试分钟、检查
预留及当前基础。分题完成后先分析知识/前置知识、学习投入、练习与作答时间，再在两个预算
内选择路径。共同知识学习只计一次，两个预算的使用比例等权比较；同时展示较少学习与较短
作答的候选方案。当前用有限容量搜索，截断时明确显示近似推荐，不能声称全局最优。

`target-score-v2` 的规划分数指 **正确完成选定内容时的得分**：完整小题由服务端使用原题
印刷分值，不把假想学生答对概率打折后多选题；部分作答估计同一受限步骤/论证的得分，并
约束整条路径的得分上界不超过目标加容差；可达候选的下界也必须不低于目标减容差。
文字论述型部分答案暂按 0 至该小题满分的保守区间筛选：少写一个论点并不能证明等级分
存在固定上限，停止点合规也不等于估分准确。
能力自评只影响学习、练习与作答成本。没有画像
和耗时校准时不预测学生个人成绩；预算不足或无法找到目标附近方案会明确说明。

计划在生成答案前持久化；重试复用同一计划，完成题不能原地重做凑分。支持同一大题内向前
的小题依赖；跨大题/反向依赖暂不支持。规划读取题面、知识目录与严格配对、校验和一致的
Source Booklet，不读取 Mark Scheme/考官报告；实际评分仍走独立评分和教师确认。主动留空
保存为已处理且 `skipped_by_strategy=true`，不是失败；空白答卷按已确认评分标准记录零分，
仍需复核。策略报告提供学习清单、限时作答顺序与 JSON 下载；原卷 PDF 保留计划内空白。

部分方案新增明确的停止边界 `stop_before`，与每题考试用时、当前题目知识及前置一起传给
答题 Agent，并在策略报告展示。最终文字／矢量图经过独立范围复核，检查越界扩写和隐藏的
跳题答案；这次调用不读取目标、评分材料或求解轨迹。违规、不确定、复核不可用或无检索
证据均不能标记成功，解释和短证据进入审计事件。当前不能复核位图，遇到位图返回不确定。
旧部分方案缺少停止边界时明确提示新建任务；普通作答不增加复核调用。

数据库迁移 `20260914_0029` 新增请求与冻结计划两列，已有任务保持普通作答模式。启动 API
时按现有机制迁移；本次代码修改未部署服务。双科实验入口为 `scripts/validate_target_strategy.py`，
需显式 `--live` 才调用模型，输出目录必须全新；实验的独立分题、文字作答与完整 Worker
端到端验证分别记录，不混为一项通过。
工具链实验入口 `scripts/validate_strategy_runtime.py` 使用同一冻结范围编译器及生产答题
Runtime、计算、作图、配套材料工具，但以本地只读大纲检索代替线上数据库／向量检索。
`scripts/validate_strategy_scope.py` 检查合成的越界作答与合法引用，两者也须显式 `--live`。

### 导出原卷作答 PDF

PDF 作答任务结束且来源核对通过后，在作答记录中选择 **导出原卷作答 PDF**。
系统建议可可靠归属的答题横线区域；选择子问、核对原卷页，必要时点击“框选答题区”或输入
位置。确认区域不遮挡题干/原图后生成预览，再下载。扫描卷、填空和表格等没有可靠建议位置时
需要人工定位；当前不自动圈选选项或逐单元格填表。

导出复用已保存的正文、公式、图片和图形，不调用模型。已校准图形直接叠到对应原图；正文按
固定清晰字号排入所选区域，空间不足时在原区写 `See PDF p. N` 并追加带题号的续答页。
部分作答可以导出，文件名带 `partial`，并附未完成题目清单。位置调整仅用于本次导出，
不修改原件、答案或评分记录，也不跨导出窗口保存。

原 PDF 的页面内容保留，新增答案以透明高清图像层写入；新增正文当前不是可选择的 PDF
文本。生成前检查原件 SHA-256、对应来源页、区域越界/重叠、公式溢出、图片加载及空白图形；
单段超过一页且无法在空白行处分割时停止导出，不能裁掉答案。前端按需加载锁定的
`pdf-lib` 与 `html-to-image`，不增加后端浏览器或新的云服务。

离线浏览器导出回归：`cd frontend && PLAYWRIGHT_PORT=4175 pnpm test:visual e2e/answer-pdf.spec.ts`。
可选真实样本测试需显式设置 `EXAMTWIN_PDF_SAMPLE_DIR`，目录内提供 `source.pdf`、原有
`job.json`、布局接口对应的 `layout.json` 和已完成答案来源页的 `page-N.png`；普通测试会跳过。

## 评分契约

`POST /api/v1/grading/rubrics` 只能为已完成的 Question Paper 作答任务创建评分规则，
且所选 Mark Scheme 必须具有完整、完全相等的年份、考季与 Unit 身份。模型抽取出的每个
M/A/B/FT 评分原子最初都是 `pending`：

- 教师通过
  `POST /api/v1/grading/rubrics/{rubric_id}/criteria/{criterion_id}/review`
  逐条接受、拒绝或编辑后接受；请求必须包含审核人，操作前后内容与说明写入不可变审计记录；
- 所有原子均已明确处理、且至少一条被接受后，才能通过
  `POST /api/v1/grading/rubrics/{rubric_id}/confirm` 确认整个版本；
- `POST /api/v1/grading/papers/{paper_job_id}/questions/{position}/assess`
  只使用该试卷已确认版本中当前题目的已接受原子，不接受客户端直接提交任意 Mark Scheme。

逐题自动结果仍进入 `pending_review`。教师最后通过
`POST /api/v1/grading/reviews/{assessment_id}` 确认或改分，之后状态才变为
`confirmed` 或 `overridden`。

模型输出必须与已确认原子逐项对应，上限及说明以确认版本为准；正分缺少非空逐字证据时
会纠错，仍无证据则暂缓授分。实际矢量图随文字进入评分并保存。位图或依赖原卷底图的图形
尚不能可靠检查时，整题明确暂缓为零置信度占位，教师需查看实际产物；占位零分不表示答错。

待复核列表通过 `GET /api/v1/grading/reviews/all` 跨科目返回，并携带
`paper_job_id`、试卷显示名/文件名、题位和 `answer_mode` 来源信息。Web 端据此按试卷分组、
按题位排序，并区分外部答卷、AI 作答与未记录来源；未关联试卷的旧评估仍作为独立复核项展示。

## 测试

```bash
uv run examtwin config-check
uv run ruff check backend scripts
uv run python scripts/check_architecture.py
uv run pytest -m 'not integration and not local_assets'
uv run python scripts/export_openapi.py --check frontend/openapi.json
cd frontend && pnpm api:types:check && pnpm test && pnpm lint && pnpm build
```

PostgreSQL 集成测试需要显式提供 `EXAMTWIN_TEST_DATABASE_URL`；测试进程会创建唯一临时同级
数据库并在结束时只删除自己创建的库，因此不会复用或清空固定共享库。CI 在 Python
3.11、3.12 和 3.13 上执行非集成测试。普通测试不读取或调用真实模型密钥。

需要核对真实供应商兼容性时显式运行以下付费冒烟；它分别验证结构化 LLM、embedding 和
rerank 的当前响应契约，失败以非零状态退出且不打印密钥：

```bash
uv run examtwin provider-smoke
uv run examtwin provider-smoke --provider llm,embedding
```
