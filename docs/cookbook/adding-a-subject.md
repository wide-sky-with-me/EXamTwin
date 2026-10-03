# 新增科目

科目能力由 SubjectPack 声明，见 [subject-packs](../subsystems/subject-packs.md)。

1. 新建 `subject-packs/<board>-<subject>-<code>/manifest.json`：填写科目代码、Unit 规则、课纲编号模式、
   Unit 解析正则、`paper_unit_map`、完整性下限、`board_id`、`extractor_key`、`normalizer_key`，以及答题工具
   allowlist 与 `visual_policy`。所有引用必须是宿主已注册的 provider 或能力 ID。
2. 写 `SKILL.md`：只放已审核的学科作答语义，不写平台不变量。
3. 写 `retrieval-eval.json`：真实查询、期望知识编号与门禁阈值。
4. 需要专用能力（课纲 normalizer、视觉政策、工具）时，先在 `subjects/providers.py` 或答题能力注册表中
   注册受审查的实现，再由包引用其 ID；不得让包加载代码。
5. 运行 `uv run python scripts/check_architecture.py`：通用模块不得出现新科目代码字面量。
6. 用官方 specification 运行 `uv run examtwin subject-pack-audit --pack <pack-id>`，核对主题覆盖。
7. 在 Web“科目”中以该包为能力模板创建科目，上传 syllabus 与授权教材，构建并发布核心知识库，
   执行 `retrieval-evaluate` 达到包内门禁后再投入作答。
