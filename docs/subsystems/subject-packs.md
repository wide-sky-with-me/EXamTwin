# SubjectPack 与科目运行时

SubjectPack 是版本化的学科运行契约，位于 `subject-packs/<pack-id>/`。它是声明式数据，不是插件：
包内不能导入或执行任意代码，只能引用宿主已注册的 provider ID。

## 包内容

| 文件 | 内容 |
|---|---|
| `manifest.json` | `schema_version`、`version`、`id`、`subject_code`、标题、图标、颜色、`board_id`、`specification_ref`；`runtime`（corpus 根、Qdrant collection 与 alias）；`curriculum`（Unit 规则、编号模式、Unit 解析正则、`paper_unit_map`、完整性下限、`extractor_key`、`normalizer_key`）；`answering`（工具 allowlist、必需与强制工具、`visual_policy`、是否需要 Source Booklet） |
| `SKILL.md` | 已审核的学科作答语义，作为答题 system prompt 的学科层 |
| `retrieval-eval.json` | 该科检索黄金集与门禁阈值，供 `retrieval-evaluate` 使用 |

加载器在服务启动边界用 Pydantic 失败关闭地校验：schema 版本、文件越界、科目与 Unit 唯一性、
正则合法性、工具名必须是宿主能力子集，并记录 Package 与 SKILL 摘要。

## 宿主 provider 注册表

`subjects/providers.py` 的 `SubjectProviderRegistry` 拥有可被包引用的实现：

- `BoardPack`（如 `oxfordaqa`）：来源分类、权威等级、文件名资格代码模式、配对键规则；
- 课纲文本 normalizer（如 `subjects/mathematics_9660.py` 的数学正规化）；
- 答案视觉政策（如数学原图叠加）；
- 答题能力（工具）由 `assessment` 的能力注册表提供，包只按名称选择。

新增专用能力的唯一路径是在宿主注册 provider，再由包引用其 ID。

## SubjectContext

每个领域写入都要求显式 `SubjectContext`；缺少上下文立即失败，不存在默认科目。通用模块不得出现
已安装科目代码字面量，由 `scripts/check_architecture.py` 机械检查。合成科目 `9999` 的测试证明已有
通用能力的新科目只需添加包。

## 科目工作区

Web 中的科目与包分离：包是创建科目时可复用的能力模板，科目实例保存名称、图标、颜色与资料。
每个科目拥有：

- 资料工作区：上传原件写入对象存储，corpus 目录为 `var/subjects/<workspace-id>/corpus`；
- 核心与补充知识库（见 [corpus-and-knowledge](corpus-and-knowledge.md)）；
- 独立 Qdrant collection 与 alias。

科目基本信息只能修改名称、图标、颜色；标识、科目代码、课程体系和能力模板只读。删除科目会物理
删除数据库业务数据、对象存储内容和该科 Qdrant collection/alias；存在运行中任务时拒绝删除。

## 新增科目

步骤见 [cookbook/adding-a-subject](../cookbook/adding-a-subject.md)。真实接入还需要真实语料、黄金检索集和
已审核的作答 SKILL 一起通过门禁。
