# 资料、知识库与难度证据

`knowledge/` 把原始资料变成可追溯的语料、不可变知识库版本、课程图谱和难度证据。

## 资料身份

每份资料保存稳定文档 ID、`source_type`、`source_role`、`authority_tier`、授权状态、校验和、页数与
考试身份（年份、考季、Unit、配对键）。

- 来源类型：知识类 `syllabus / textbook / slide / revision_note / topic_practice`；评估类
  `question_paper / insert / mark_scheme / examiner_report / answer_booklet / specimen_paper`；`other`。
- 权威等级：`official`、`licensed_core`、`supplementary`，描述来源地位，与难度证据等级无关。
- 来源角色：`core_knowledge`、`supplementary_knowledge`、`assessment_only`、`excluded`。

两条入口共用 `knowledge/inventory.py` 的分类与身份解析：CLI `inventory` 扫描 SubjectPack corpus 根；
Web 上传由 `knowledge/workspace_service.py` 的 `CorpusWorkspaceService` 处理，类型由用户声明，归属
规则由 `subjects/document_assignment.py` 决定。

考试身份只在年份、考季、Unit 都能解析时完整。以下资料不进入当前科目严格配对：样卷；文件名带其他
资格代码；PDF 首页印有其他资格组件代码（如 `7136/1`）。`IN-` 前缀加日期才识别为 Source Booklet，
文件名含独立单词 `report` 识别为 Examiner Report。

上传原件先写入对象存储（键 `corpus-sources/<subject>/<type>/<sha256>.<ext>`），注册失败时只删除本次
新建对象；同校验和重复上传沿用已有完整身份，身份冲突时拒绝。

## 转换

MinerU precision 模式保留 OCR、公式、表格与页码。超过 200 页或超出安全上传字节的 PDF 先物理切成
不超过 200 页的小 PDF 逐段缓存；`.ppt` 由镜像内 LibreOffice 转临时 PDF。超时、重试（默认三次）与
退避由配置声明；最终缓存经临时文件原子替换，失败状态写回资料清单。转换后按来源策略生成层级文档块：
表格保持原子，Question Paper 与 Mark Scheme 正文块为 450 字符、重叠 60。

## 知识库版本

每科有核心与补充两类知识库：

| 知识库 | 允许来源 |
|---|---|
| 核心 | `syllabus`；确认授权的 `textbook`（`licensed_core`） |
| 补充 | `slide / revision_note / topic_practice`；确认授权的 `textbook`。`syllabus` 只能入核心 |

评估资料（QP、MS、ER、Insert）不进入任何知识库。构建一次产生不可变版本：转换 → 索引 → 发布。
索引写入带 build id 的 staging collection，记录输入哈希与检查点；`count(exact=true)` 点数门禁通过后
原子切换该科 live alias，失败时上一版本保持在线，`--resume` 按节点 ID 补缺。`index --limit` 不能发布。
节点带稳定内容指纹，embedding 服务、模型、索引 schema 与内容都一致时复用旧稠密向量。

## 课程图谱

`CurriculumExtractor` 从已转换课纲生成版本化候选（Unit / Topic / Learning Objective），经结构、数量、
父子关系和已发布节点漂移门禁后单事务发布。`curriculum-preview` 只预检不写库。关系只有官方层级
`contains`、同主题官方列举顺序 `syllabus_sequence`，以及带来源与置信度的关系；不从课纲顺序推断先修。

## 难度证据

| 等级 | 含义 |
|---|---|
| A | 官方量化（facility、mean mark、discrimination） |
| B | 官方定性或比例描述 |
| C | 有验证依据的历史估计 |
| D | 证据化模型冷启动评级 |

`knowledge-build` 是唯一调用模型的知识构建入口，要求已发布核心库含 syllabus 与授权 textbook。它为每个
Topic / Learning Objective 选取双来源原文，按 Unit 分批让模型在完整目标标尺下给出 `[0,1]` 分数、相对
位置、分项判断与逐字引用；代码只校验结构、双来源引用和完整性，按 `0.34 / 0.67` 映射 easy / medium /
hard，置信度上限 `0.45`。任一目标证据不足、引用不能逐字回到输入块或模型输出不完整时不发布。
同一完整输入、核心版本、模型和提示词复用检查点。

Examiner Report 题目观测：结构化模型只提出候选；代码逐项校验报告与 QP 校验和、配对键、规范题号、
页码、逐字引用、指标方向与限定词；教师审核后按 run 事务发布到 `question_difficulty`。B 级不换算为
伪精确数值。题目观测尚未映射到 `knowledge_codes`，知识点 A/B/C 聚合未实现。
