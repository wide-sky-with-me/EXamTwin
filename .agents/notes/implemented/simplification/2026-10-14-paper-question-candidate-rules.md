# Agent Note: 整卷候选题纯规则与运行编排分离

Status: implemented

## Problem

`paper_answering.py` 同时容纳候选题的确定性归并、修复计划校验和整卷模型调用编排。阅读候选冲突或修复计划门禁时，需要越过服务依赖与供应商响应模型；只整理文件长度又容易顺带改变来源权威、重试或检查点语义。本次目标是收窄纯规则的归属，不修业务缺陷、不增加能力。

2026-10-14 重新读取的基线共 1616 行：第 193–849 行是候选题规则；其依赖还包括第 69–85 行的正则与阈值、第 92–103 行的修复组/计划模型和第 129–135 行的冲突异常。该范围不包括批次切分和 `PaperAnswerService`。

## Decision

候选规则集中在同一 assessment 能力内的 [paper_question_candidates.py](../../../../backend/src/examtwin/assessment/paper_question_candidates.py)，保持原函数名、签名、判断顺序、错误文本和字段处理。模块只依赖标准库与现有 Pydantic，不依赖配置、模型接口、文件、数据库或服务回调。

- 规则模块拥有题号/子问归一化、同主源候选归并、恢复候选对齐与去重、修复计划应用，以及必要的修复计划模型和冲突异常。归并结果仍不是可直接持久化的可信题目。
- [paper_answering.py](../../../../backend/src/examtwin/assessment/paper_answering.py) 保留 `PaperAnswerService`、`SPLIT_CONTRACT_VERSION`、拆题 provider payload、Markdown 批次切分、模型构造与调用、并发、重试、检查点及来源页/结构对账。修复模型是否调用、何时重试仍由服务决定。
- 服务导入规则模块并用模块限定名调用；测试直接从新路径导入规则。旧服务模块不保留迁移符号的 re-export、别名或兼容 shim。拆题 schema 测试继续使用原路径，因为 `_QuestionSplitPayload` 不迁移。
- 不增设候选 Repository、策略对象、运行器或跨领域公共入口；不升级拆题契约版本，因为检查点内容、摘要输入和运行行为均保持不变。

### 既有决策核对

动手前检索 proposed、implemented、rejected 的整卷、分题、候选与模型边界记录，未读取或改写冻结归档。以下已实施决定与本次局部归属部分重叠且继续有效，没有被吸收或推翻：

- [来源完整性](../feature/2026-08-05-question-source-integrity.md)：视觉主源权威、冲突后有界模型选择、确定性守恒门禁不变。
- [持久队列与检查点](../architecture/2026-07-29-persistent-paper-jobs-on-postgresql.md)：契约版本/输入摘要匹配复用、失败恢复与运行状态边界不变。
- [供应商无关模型边界](../architecture/2026-08-31-provider-neutral-model-boundary.md)：结构化调用及参数仍属于服务现有路径，规则模块不接触供应商。
- [按业务能力组织](../architecture/2026-08-05-feature-first-backend-modules.md)：只在 assessment 内收窄职责，不建立预置分层或旧路径兼容层。

题目观测到知识难度提案针对人工审核映射，检索查询改写记录针对召回，两者与候选结构整理无关。

## Alternatives considered

- **保留整个大文件**：无需迁移内部导入路径，审查 diff 最小，服务与规则可在一处追踪。实际核对后发现候选规则有连续且封闭的依赖范围；保留现状会继续让纯规则阅读和测试入口绑定整卷运行依赖，因此选择一次最小的模块抽取。没有为了行数继续拆散仍属同一编排的服务。
- **按 domain/application/adapter 分层重写整卷作答**：可把纯规则、来源校验、供应商适配和任务编排全部显式隔开，未来多种运行入口可能受益。当前目标只是行为不变的局部整理；该方案会引入端口、注入和状态传递的新契约，扩大模型重试、检查点及来源门禁的回归面，也违背按需建层的既有决定，因此本批不实施。
- **服务直接导入全部迁移符号或保留旧路径转发**：调用点更短，原测试和潜在调用方迁移成本低。但旧路径仍会暴露规则符号，削弱一次性迁移与归属边界；选择模块限定名与显式测试迁移。

## Consequences

收益是候选规则可从独立模块定位和直接测试；服务文件由 1616 行变为 918 行，规则模块为 710 行。这是职责拆分，不是总代码量压缩或性能优化，也不新增依赖。

代价是服务调用路径变长，排查跨越“候选结果 → 来源对账”的问题需要阅读两个文件。所有旧内部导入均须一次迁移；仓库调用方检索与旧路径无导出测试守住该边界，不承诺仓库外私有符号使用者兼容。

已知限制是原规则对异常输入、候选选择与恢复来源的处理完整保留，不借拆分修正潜在业务问题。只有出现需要复用运行编排的具体入口，或可复现的新职责冲突时，才重新比较更细分层；文件剩余行数本身不是继续拆分的触发条件。

## Verification

- 通过 AST 与本次改动前 HEAD 比较：迁移的 14 个函数、3 个类型和 8 个常量一致；保留的 7 个顶层定义（含完整服务）仅在规则调用路径归一后比较，AST 一致。修复计划的 `model_json_schema()` 也与原类型一致。
- [test_paper_answering.py](../../../../backend/tests/test_paper_answering.py) 的既有纯规则覆盖改从新路径导入，并新增旧服务路径不再暴露迁移符号的测试；并发、重试、检查点与来源对账断言保留。
- 新增 [test_paper_question_candidates.py](../../../../backend/tests/test_paper_question_candidates.py) 的 20 个参数化用例，直接验证候选覆盖恰好一次、修复计划严格字段、题号族与权威选择门禁、选中题干/需求合并、不变更输入、跨源冲突、来源元数据清除及未知/布尔分值处理。
- 实际执行 `uv run pytest backend/tests/test_paper_question_candidates.py backend/tests/test_paper_answering.py backend/tests/test_paper_split_schema.py backend/tests/test_ingestion_knowledge.py backend/tests/test_vector_index_publication.py -m "not integration and not local_assets" -q`：106 passed，7.36 秒；相对只读审计的 85 passed 基线新增 21 个用例，不据此比较性能。一条警告来自依赖 Pydantic 对 `ChatCompletionReasoningItem.summary` 的 `ReadOnly` 支持。
- 上述四个变更 Python 文件的 `uv run ruff check` 与 `uv run ruff format --check` 通过；新测试首次检查的 I001 导入排序在调整后复测通过。`uv run basedpyright` 全仓 0 errors、0 warnings；`uv run python scripts/check_architecture.py`、`uv run python scripts/agent_notes.py check` 和变更文件的 `git diff --check` 均通过。
- 合并所有本轮文件后，全仓 `uv run ruff check .` 与 `uv run ruff format --check .` 通过。未运行 integration/local_assets、真实模型或基础设施测试。
