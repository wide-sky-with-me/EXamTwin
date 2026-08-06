---
kind: epic
title: "多科目知识生产与难度证据流水线"
status: active
created: 2026-08-03
---

# 多科目知识生产与难度证据流水线

## 这个 Epic 要改变什么

把当前依赖 9660 专用常量、API 启动时写图谱、chunk 关键词直连知识点的实现，改造成可以按
科目注册、显式运行、审计、失败恢复并安全发布的知识生产流程。原始文档结构、检索片段、
知识点版本、证据链接和难度观测各自有明确归属，新增科目不再修改建库主流程。

## 为什么现在做

运行态审计确认，现有 183 个学习目标全部只有置信度 0.3 的 D 级冷启动难度，正式难度证据
和题目难度均为 0；chunk 到知识点的词面匹配出现单点 817 条证据的热点失真。容器中的宿主机
缓存路径还会令 syllabus 读取失败，而启动 seed 先删除定义证据，已经把正式环境的
`definition_evidence` 清空。继续导入新资料或新科目会放大错误，必须先建立稳定生产边界。

## 关联 Project Spec

- `codestable/spec/index.md`：本 Epic 改造“建立证据基础”“知识与难度”和当前整体重建索引的
  当前真相；关闭前不把尚未验证的目标写成已实现能力。

## 当前方案

系统提供一个窄而深的知识构建入口。`BoardPack` 保存考试局的来源、配对和权威规则；
`SubjectPack` 只保存科目标识、Unit/试卷映射、课纲编号规则和完整性阈值，不保存逐科知识点。
`CurriculumExtractor` 从真实课纲结构生成版本化 `CurriculumCandidate`；知识流水线显式执行资料
定位、结构提取、候选校验、难度观测和事务发布，记录每次 run 的输入哈希、阶段、配置、结果
和错误。

```mermaid
flowchart LR
    A[资料清单] --> B[转换与结构块]
    B --> C[知识候选提取]
    C --> D[结构校验]
    D --> E[难度观测]
    E --> F[质量门禁]
    F --> G[事务发布图谱]
    G --> H[版本化检索索引]
```

课纲没有官方量化难度时，显式知识构建必须让模型同时阅读课纲目标、已发布核心知识库中的
匹配课纲块和授权教材块，并在同一 Unit 的完整目标清单中直接给出 Topic / Learning
Objective 的相对位置和 `[0,1]` 难度分。固定代码只负责证据材料选择、结构与逐字引用校验、
分数到标签映射和完整性门禁，不再用动作词或人工权重生成发布分数，也不提供规则回退。
结果必须标为 D 级“证据化模型冷启动评级”，保留模型、提示词、核心知识库版本、参与评估的
块与内容哈希、输入哈希、相对位置、分项判断、理由和置信度。后续 A/B/C 级观测加入聚合时
保留该历史证据，按证据强度和版本重新计算。

## 需求变化

- API 启动只初始化 schema 和执行无破坏的兼容检查，不发起 AI 调用，不因来源不可读删除证据。
- 新科目通过配置选择已注册的 `SubjectPack`；科目专用解析和规则留在科目包内，库存、流水线、
  证据和发布主流程不感知具体科目代码。
- Web 工作台不预选 9660 或任何科目；用户显式选择 SubjectPack 后，资料、知识、答题、评分、
  复核和资源请求共享同一科目上下文。已明确选择的上下文可以在本机保存，但不是产品默认值。
- 状态总览在选择科目前展示全部已安装科目及基础设施状态；依赖降级时仍应显示科目目录，
  不得把“统计暂不可用”伪装为零。界面提供浅色、深色和跟随系统三种主题偏好。
- 表格、图片、公式、页码属于原始结构块；检索 chunk 是派生物，不能反向充当知识点真相。
- 难度页同时展示聚合分数、证据等级、置信度、方法和来源；证据化模型冷启动评级可以用，
 但必须可识别，不能表述为官方数据。
- 构建失败、模型不可用、任一目标缺少 syllabus 或 textbook 证据、引用不属于所给材料或
  模型返回不完整时保持上一正式版本可用，质量门禁不过不发布。

## 架构考量

- 不把各科目规则做成任意可执行配置。服务端注册经审查的科目包，配置只选择包，避免配置
  文件成为不受控插件执行面。
- 模型在同一 Unit 的完整目标清单中，结合每个目标匹配到的 syllabus / textbook 原文直接
  评定难度、相对位置、认知负荷、抽象度、先修广度、过程深度和表示转换；固定代码从分数
  派生标签并验证引用，不用供应商输出替代官方评级，也不用词表启发式伪造稳定性。
- 每批只携带有界目标及其证据块，但同时提供所在 Unit 的完整目标摘要作为标尺；同一输入、
  核心知识库版本、模型和提示词可复用检查点，资料或版本改变后重新评定。
- 原始块、检索块和知识点分层。完整表格继续保持原子结构；超长表的检索投影不能替代原文。
- PostgreSQL 图谱用单事务发布保证失败不留下半套数据；Qdrant 写入带 build id
  的 staging collection，点数门禁通过后使用稳定 alias 原子切换，不再删正式
  collection 后就地重建。

## 多科目前端上下文（目标）

角色与入口：内容维护者或教师先进入状态总览，检查平台与各科目就绪度，再显式选择一个科目
进入该上下文中的工作页面。图示状态：本 Epic 的目标界面。

```text
┌─ ExamTwin ─────────────┬─ 状态总览 ─────────────── [主题] [系统状态] ┐
│ 状态总览               │ PostgreSQL / Qdrant / 对象存储             │
│                        │ ┌─ 9660 状态 ─┐ ┌─ 9640 状态 ─┐ …         │
│ 选择科目上下文 [     ▾]│ │资料/知识/索引│ │资料/知识/索引│           │
│ 未选择时不开放科目页面 │ └─────────────┘ └─────────────┘           │
├────────────────────────┤                                             │
│ 选择后显示当前科目导航 │ 当前科目的详细状态；切换科目不强制跳页，   │
│ 作答 / 知识 / 评分 / 复核│ 不支持的页面能力回到状态总览              │
└────────────────────────┴─────────────────────────────────────────────┘
```

稳定约束：科目选择是请求、WebSocket 和资源 URL 的共同上下文；切换时清空上一科的页面数据，
晚返回的旧请求不得覆盖新科目。主题只改变视觉呈现，不改变证据风险色和业务状态。加载、异常与
未建索引必须是不同状态；统计服务异常时用“—”而不是 0。

## 质量约束与取舍

- 可靠性：来源缺失、解析为空、代码重复、父节点不存在、模型返回不完整、证据不足或引用
  不能逐字回到输入块时 fail closed，正式图谱和证据不得被清空；不回退到旧规则分数。
- 可核查性：每个难度值至少关联一条 syllabus 和一条已授权 textbook 原文，能回到文档、
  页码、章节、块、内容哈希、核心知识库版本、模型及提示词；D 级推断不得冒充官方事实。
- 可维护性：科目变化集中在 `SubjectPack`，知识构建调用方只理解一个运行入口和运行结果；
  不保留科目或语言专用的难度关键词表。
- 成本与性能效率：API 启动和普通测试绝不调用云模型；只有显式 `knowledge-build` 调用模型，
  按 Unit 有界批处理并按完整输入哈希复用，不能为每个知识点各发一次请求。
## 统一语言

- **BoardPack**：考试局级来源分类、权威和试卷配对规则。
- **SubjectPack**：一个科目的标识、课程结构识别策略、Unit/试卷映射和知识构建约束；不含知识点清单。
- **CurriculumCandidate**：从指定课纲输入和提取器版本生成、经校验后才能发布的完整课程候选。
- **KnowledgeBuildRun**：一次有输入版本、阶段、状态、产物与错误的可审计知识生产运行。
- **证据化模型冷启动评级**：缺少表现资料时，模型结合课纲与已发布核心知识库中的授权教材
 原文，在 Unit 内比较后直接给出的 D 级知识点难度；必须带可验证引用，不是官方评级。
- **发布**：候选和全部难度评级通过质量门禁后原子替换正式图谱或索引的动作，不等同于转换
 或生成候选。

## 当前推进

### epic 内直接推进

- [已实现] P0 路径与安全 seed：统一 Markdown 缓存定位；来源不可读或抽取为空时禁止删除
  定义证据。真实 9660 发布已把 `definition_evidence` 从 0 恢复为 183。
- [已实现] P1 科目包骨架：`BoardPack` / `SubjectPack` 承载科目标识、Unit 映射、编号模式、
  配对键、权威来源和质量门禁；库存与知识构建不再直接写死 9660 常量。
- [已实现] P2 图谱构建 run：新增显式 `knowledge-build`、运行状态/输入哈希/产物/指标/错误，
  API 启动、`init`、`inventory` 和 `index` 不再隐式建图；正式图谱在单事务内发布。
- [已替换] P3 AI 冷启动：旧实现曾让结构化模型评定课纲特征，再由动作词/权重函数归一化；
  其历史 D 级证据保留，但新发布路径已由 P10 完整替换，不再提供旧模式或规则回退。
- [已实现] P10 证据化模型直接评级：从已发布 Core Knowledge Base 的层级块为每个 Topic /
  Learning Objective 选择 syllabus 与 licensed_core textbook 原文；模型在 Unit 完整标尺中
  分批直接给分，固定代码验证双来源逐字引用并派生标签。缓存绑定候选、核心版本、证据内容和
  提示词；任一目标证据不足即阻止发布。后端 237 个普通测试、17 个基础设施集成测试通过；
  9640 的 568 个目标均成功组装双来源材料，真实模型已对首批 3 个目标给分并通过引用门禁。
- [已实现] P4 ORM 边界：知识构建 run 与课纲资料定位改用 SQLAlchemy 2.0 Model、Session 和
  Repository；流水线服务不再拼接 SQL。SQLAlchemy 显式使用 psycopg 3 driver，并经真实容器
  PostgreSQL 验证。
- [已实现] P5 向量索引安全发布：新建 `VectorIndexBuildRun` 检查点、不可变 staging
  collection、输入哈希、完整点数门禁和 `examtwin_9660_live` alias 原子切换；失败只保留
  staging 和错误，不影响上一正式索引。部分 `limit` 索引被禁止发布到 live alias。
- [已实现] P6 版本化 schema：引入 Alembic，记录 legacy baseline 并以 revision
  `20260803_0002` 新增向量构建表；API 启动和 `examtwin db-upgrade` 幂等执行 migration。
  向量构建检查点与文档索引状态已完整收口到 ORM/Repository。
- [已实现] P7 第二真实科目：新增 OxfordAQA Economics 9640 SubjectPack，只包含 U1–U4 映射、
  课纲编号模式、完整性阈值和真题 Unit 命名规则；用已购买的 47 页官方 specification 按
  SHA-256 真实核对 84/84，缺失和多余主题均为 0。
- [已实现] P8 课纲候选工作流：删除 9660/9640 逐科知识 seed；统一提取器支持 HTML/Markdown
  表格、项目符号和课纲说明段，从真实 9660 Markdown 生成 5/38/183，从真实 9640 课纲文本
  生成 4/84/484。候选持久化输入/内容哈希、提取器版本、完整结构、校验和审核状态；已发布
  节点消失时 fail closed。9660 新候选复用 183 条 AI 难度缓存发布，并删除 72 条无来源的旧
  顺序推断 `prerequisite_of`。
- [已实现] P9 检索质量流水线：Qdrant 在召回前按 subject/Unit/配对键/来源/
  权威等级做 must 过滤，稠密向量与确定性词法稀疏向量混合召回后再 rerank。知识卡片
  在当前证据范围内无引用时退出，由原始 rerank 节点补位，不得用 syllabus 元数据伪装
  为 mark scheme 证据。QP/MS prose chunk 收窄为 450/60，表格仍整体保留。每次检索持久化
  有界 trace；SubjectPack 自持黄金集和 Recall@K/MRR/空结果/范围越界门禁。新索引节点使用
  稳定内容指纹，仅在 embedding endpoint/model、schema 与内容全部一致时复用旧稠密
  向量；中断恢复按节点 ID 查缺，不再把 collection 点数当成写入顺序。

### 剩余阻碍

- 9660 与 9640 的资料已全部转换、索引并发布到各自 live alias；2026-08-05 清点后两科
  `exam_identity_incomplete=0`。历史章节练习、样卷和显式属于其他资格代码的试卷不再污染
  当前科目严格配对。仍有 9660 的 5 份和 9640 的 4 份 Question Paper 没有 Mark Scheme，
  只能用于检索或作答，不能用于自动评分。
- 两科 `question_difficulty_rows=0`。当前正式图谱仍是 P3 生成的 D 级课纲 AI 冷启动历史值；
  P10 全量付费构建尚未执行，因此不会把 3 个冒烟样本伪装成已迁移数据。Examiner Report 的
  A/B 级观测抽取、题号映射和聚合发布仍是本 Epic 未完成的核心能力。

### 难度证据范围

- **知识点难度**聚合多个带来源的观测；D 级冷启动可以兜底，但 A/B/C 级观测加入后必须
  保留历史、来源页、提取版本和聚合版本，不能覆盖成一个无出处分数。
- **题目难度**只表示可回到具体 Question Paper 题号的表现观测。只有官方 facility、
  mean mark、discrimination、明确的 Examiner Report 定性描述，或经人工确认的历史观测
  才能写入；不得从题面长度、LLM 主观判断或知识点冷启动分反推并冒充题目观测。
- 第一批验收以 9660 和 9640 各一组可严格配对且带 Examiner Report 的真实样本为边界：
  观测能回到科目、考试配对键、题号、来源页和原文；重复运行幂等；无法确定题号时保留为
  待审核候选而不发布。全量付费抽取仍受费用上限和样本质量门禁约束。

## 暂不推进范围

- 本切片不自动调用付费模型，不在没有费用上限和样本门禁时全量生成 AI 难度。
- 不把 AI 推断的知识关系升级为官方关系；细粒度先修边继续区分来源和置信度。
- 不在本切片重做整卷答题 Agent、评分或前端整体布局。
- 不把现有全部 SQL 一次性机械翻译为 ORM；每次迁移必须由一个领域 Repository 收口查询、
  事务和测试面，并逐步引入 Alembic 等版本化 schema migration。

## 执行记录

- 2026-08-03：新增可移植 Markdown 缓存解析边界，宿主绝对路径在容器内按稳定 document ID
  映射到挂载缓存；`source_context`、知识构建、索引和 Examiner Report 读取统一复用。
- 2026-08-03：新增默认 `oxfordaqa-mathematics-9660` SubjectPack，并把知识点唯一性扩展为
  `subject_code + code`，避免未来科目间 `P1`、`ROOT` 等代码冲突。
- 2026-08-03：建立 `KnowledgeBuildRun`。课纲少于 100 个目标、代码重复、父节点未知或 AI
  批次缺项均 fail closed；每个 AI 批次把进度和结构化产物立即写回检查点。
- 2026-08-03：首次真实 AI 运行生成 183 个 D 级分项估计；抽样发现旧函数会用认知要求替代
  缺失的历史难度、用课纲复杂度替代 Examiner 严重度，造成重复计权，随后改为仅对存在特征
  归一化权重，并复用缓存重新发布，没有再次调用模型。
- 2026-08-03：用户要求标准数据库形式后，新增 SQLAlchemy ORM、Session Factory 和
  `KnowledgeBuildRepository`。首次容器穿刺发现 `postgresql://` 默认寻找 psycopg2，修正为
  `postgresql+psycopg://` 并增加回归，第二次真实容器运行成功。
- 2026-08-03：线上物理 collection `examtwin_9660` 保持不变，新建 live alias 指向它。
  用独立 1 点临时 collection 真实验证门禁和 alias 切换，清理后确认临时 collection/alias
  都不存在，9660 live alias 全程仍指向原 collection。
- 2026-08-03：首次部署 Alembic 时发现镜像未复制 `alembic.ini`，API 启动失败但数据
  未变更；补齐 Dockerfile 后重建，API 启动幂等 migration 成功并恢复 healthy。
- 2026-08-03：用户指出逐科 seed 不是可复用工作流后，把知识内容从 SubjectPack 中移除，
  新增通用课程候选提取、校验、漂移门禁和 `curriculum_candidates` 审计表。首次真实发布因
  PostgreSQL `LIKE` 百分号未经过兼容包装器转义而在事务入口失败，正式图谱未变；修正后重跑
  成功，失败候选与成功候选均保留用于审计。
- 2026-08-04：以 9640 独立环境变量执行库存、确定性知识发布和 Qdrant staging/alias
  发布；正式图谱为 4 Unit / 84 topic / 484 objective，独立索引为 822 points。
  使用“maximum price below equilibrium”问题真实走通硅基流动 embedding/rerank、
  Qdrant 和知识点卡片，返回 3 个 U1 候选，首项定位官方课纲第 12 页。总览统计
  同时改为按当前 SubjectPack 过滤，避免 9660/9640 入同库后在前端混算。
- 2026-08-04：工作台取消任何 UI 默认科目，SubjectPack 选择作为持久化的请求上下文传入
  REST、上传、资源 URL 与 WebSocket；切换只更新上下文，不再强制跳到试卷作答，且丢弃
  旧科目晚返回的知识/复核结果。状态总览列出全部安装科目和独立就绪度；PostgreSQL 统计
  不可用时保留科目目录并返回空统计。新增浅色/深色/跟随系统主题并使用同一组设计 token。
- 2026-08-04：完成 9640 全量向量发布。首次全量构建因 Qdrant 后台 segment 合并期间
  `get_collection().points_count` 短暂从精确的 18,307 偏高为 18,502，安全门禁拒绝了切换且保留
  旧 822 点 alias。发布门禁改用 `count(exact=true)`，并将新 build 的证据写入从逐条
  SELECT/INSERT 改为先清理该 build 后批量 INSERT；断点恢复后原子切换至 18,307 点。
- 2026-08-05：确认数学目录是 403 PDF + 53 PPT，456/456 份在 PostgreSQL 均有 Markdown
  路径且无 error，逐份检查 S3 对象缓存为 456/456 存在。当前 live alias 指向今日
  发布的 456 文档 / 22,011 节点混合索引；旧“209 已索引 / 247 discovered”是未处理
  完老 PPT 与超大 PDF 时的历史快照，不再是运行态真相。
- 2026-08-05：首次 12 条真实检索黄金集暴露了知识卡片在精确 mark scheme 范围下回退
  syllabus 元数据的 8 个越界结果。修复为“卡片必须有当前范围内原文，否则原始证据
  补位”后复验 12/12 命中，Recall@5=1.0000、MRR=0.9167、空结果率 0、范围越界 0。
  不默认增加 LLM HyDE/查询改写：当前 Agent 已可迭代调用 `knowledge_search`，强制每次多一次
  生成会增加延迟和伪关键词；仅在黄金集出现可复现多跳漏召回时再作有门槛 fallback。
- 2026-08-05：部署契约 `2026-08-05.hybrid-retrieval-v24`。仅替换 API、两个 Paper Worker 与
  storage-gc，PostgreSQL/Qdrant/SeaweedFS 和持久化卷保留；基础设施三项健康，9660 仍为
  456 indexed / 22,011 live points。当前 live 是混合索引；稳定节点指纹会在下一次完整
  索引构建写入，其后的构建才能跨版本复用未变向量；本次未为追求指纹而付费重算
  已验证可用的 22,011 个稠密向量。

- 2026-08-05：完成动态学科知识生产闭环。新增来源角色/授权、科目工作区、核心与补充知识库、
  不可变版本、层级文档块、AI 图谱草稿与审核发布；RAG 以科目、知识版本、来源角色和 Unit
  payload 预过滤，再做 dense/lexical 融合、rerank 和图谱扩展。作答运行账本冻结实际知识库与
  图谱版本，Mark Scheme / Examiner Report 从作答检索面移除，Insert 仅按严格配对题目读取。
- 2026-08-05：9640 受控核心知识库 v3 以 4 份 syllabus / textbook 发布 5,101 个向量点；
  真实图谱 v2 发布 201 个已接受节点、253 条关系；新作答运行确认同时使用该核心库和图谱。
  已完成 2024 June U1 21/21 题整卷作答只引用 syllabus、textbook 和 6 条按题 Insert。
- 2026-08-05：评分工作流改为“选择既有作答 → 选择严格配对 Mark Scheme → 解析并审核
  版本化类型化评分原子 → 逐题初评 → 人工确认/改分”。真实 U1 评分方案生成并确认 24 条规则，
  第 1 题得到 1/1 后进入复核队列并完成审计确认。题号规范化和 rubric 父记录 flush 的生产
  缺陷均有回归保护。

## 验证

- 本轮多科目前端上下文：科目包/状态/统计相关后端测试 `6 passed`；后端 Ruff check/format、
  basedpyright、OpenAPI 快照和 Compose 配置通过。前端 Vitest `18 passed`、ESLint、OpenAPI
  类型一致性、TypeScript/Vite production build 和 Playwright 无默认科目/主题切换、桌面作图、
  窄屏作图与 1024px 布局四项通过。
  全量非集成后端测试在当前沙箱另暴露 `paired_exam_lookup` 的阻塞工具 future 已完成、
  `asyncio.wait_for` 仍在 30 秒后走 timeout 的问题；本轮未把它冒充为多科目回归或通过。
- 后端：Ruff 通过；`153 passed, 11 deselected`，额外的局部 API/PostgreSQL 集成穿刺
  `1 passed`。新增测试覆盖 alias 原子切换/门禁失败不切换、禁止部分索引上线、
  VectorIndex Repository 领域和经济 9640 真实课纲漂移四类独立风险。
- 前端：Vitest `5 passed`、ESLint、TypeScript 与 Vite 生产构建通过；Compose 配置通过。
- 真实数据：9660 候选校验为 5 Unit、38 topic、183 objective、零错误/警告；最新候选状态
  `published/auto_approved` 且 `ai_reused=true`。正式图谱为 1 subject、5 unit、38 topic、
  183 objective、226 条 `contains` 和 145 条 `syllabus_sequence`，无旧顺序推断先修边；聚合版本全部为
  `weighted-available-features-v2`。分布为 easy 21、medium 82、hard 80，所有结果仍标 D 级。
- 真实服务：API 契约 `2026-08-03.knowledge-pipeline-v10`；API 与两个 Worker 使用镜像
  `sha256:9d15f558…`，API healthy，Alembic revision `20260803_0003`；`examtwin_9660_live`
  仍指向 `examtwin_9660`。有界 P1 知识请求返回 Unit、topic、objective 共 41 个节点，每个节点
  都有课纲定义引用；现有检索关联证据的热点治理仍由后续检索切片负责，不在本次候选重构中
  冒充已解决。
- 9640 全量发布：精确向量计数 18,307，273 份资料均为 `indexed`，活跃 build 为
  `published` 且 18,307/18,307；关联证据 34,959 条。本地 Qdrant/PostgreSQL/API 三方统计一致，
  经济学 U1 真实 RAG 请求返回 HTTP 200（约 49.8 秒）。相关仓储/发布回归 `17 passed`，
  Ruff format/check 和 basedpyright 通过。
- 9660 检索与部署：后端 Ruff format/check、basedpyright、206 个非集成测试通过；
  PostgreSQL/Qdrant/对象存储集成测试 17 passed；前端 18 项 Vitest、ESLint、OpenAPI 类型一致性
  与生产构建通过。真实 live 黄金集 12 cases 的 Recall@5=1.0000、MRR=0.9167、
  empty_rate=0、scope_violations=0；检索 trace 在 PostgreSQL 按科目有界保留。
- 2026-08-05 动态知识与评分闭环：9640 Core v3 为 5,101 个向量点，证据图谱 v2 为
  201 节点 / 253 关系并已发布；新作答运行冻结 Core v3 + Graph v2。2024 June U1 整卷
  21/21 完成，引用统计为 syllabus 459、textbook 92、Insert 6，评估资料泄漏为 0。真实
  Mark Scheme 生成并确认 24 条规则，第 1 题 1/1 且人工审计确认。
- 2026-08-05 最终自动门禁：后端 Ruff format/check、basedpyright、OpenAPI 快照、
  `235 passed, 20 deselected`；PostgreSQL/S3 集成 `17 passed, 238 deselected`；前端
  OpenAPI 类型一致、Vitest `20 passed`、ESLint 和生产构建全部通过。

## 关闭条件

- 容器和宿主机均能解析同一份 Markdown 缓存，来源不可用的回归测试证明定义证据不会删除。
- 默认 9660 科目包经现有语料生成稳定知识结构；流水线运行记录可查询和失败恢复。
- 假模型证明 AI 特征经过严格结构校验、归一化并以 D 级证据落库；普通测试零云端调用。
- 第二个真实科目包或等价的独立适配器验证主流程无需修改。
- Qdrant 使用 staging/alias 安全发布，或者关闭时明确保留为未完成范围。

## 合并回 Project Spec 的候选

- 多科目资料、知识和难度流水线的使用路径、统一语言与发布约束。
- 难度证据 A/B/C/D 分层、AI 冷启动边界和正式图谱/索引的版本发布规则。

## 关闭回写

- 状态：保持 `active`，实现完成不自动关闭。
- 合并位置：关闭时写回 `codestable/spec/index.md`。
- Vision 同步：当前没有来源 Vision；关闭时复核项目边界是否从 9660 扩展到多科目。
- 保留材料：运行态审计数字、实现取舍和验证命令保留在本 Epic。

## 相关材料

- `codestable/issues/001-o-整卷证据作答与细粒度知识图谱.md`：查看触发本 Epic 的 9660 运行态
  审计和容器路径根因；整卷答题行为仍由原 issue 承载。
