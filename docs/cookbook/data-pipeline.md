# 数据管线操作

以下命令作用于 `SUBJECT_PACK` 指定的科目（CLI/Worker 的引导上下文）。转换、索引、知识构建和检索评测
会把资料或查询发送到外部服务（MinerU、Embedding、Rerank、LLM），执行前需要明确授权和费用预期。

## 1. 清点

```bash
uv run examtwin inventory
uv run examtwin stats
```

`inventory` 扫描 SubjectPack corpus 根，登记来源类型、权威等级、校验和、页数与考试身份；`stats` 输出
资料、配对、图谱与复核统计。

## 2. 转换

```bash
uv run examtwin convert --type syllabus
uv run examtwin convert --type textbook
uv run examtwin convert --type question_paper --type mark_scheme
```

每份 Markdown 独立缓存；超大 PDF 物理分段，旧 `.ppt` 经 LibreOffice 转换后可续跑。

## 3. 课程预检与索引

```bash
uv run examtwin curriculum-preview --output /tmp/curriculum.json
uv run examtwin index
uv run examtwin index --resume
```

`curriculum-preview` 只运行结构与漂移门禁，不写库。`index` 写入新的 staging collection，门禁通过后切换
live alias；失败用 `--resume` 继续，上一版保持可用。`index --limit` 只用于验通，不能发布。

## 4. 检索评测

```bash
uv run examtwin retrieval-evaluate
uv run examtwin retrieval-traces --limit 20
```

未达到 `retrieval-eval.json` 门禁时以非零状态退出。

## 5. 知识构建

```bash
uv run examtwin knowledge-build
```

唯一调用模型的知识构建入口；要求已发布核心库含 syllabus 与授权 textbook。结果是 D 级证据化模型冷启动
评级，模型不可用或任一目标证据不足时不发布，上一正式图谱保持可用。

## 首次验通与审计

```bash
uv run examtwin bootstrap --convert-limit 6
uv run examtwin subject-pack-audit --pack oxfordaqa-economics-9640
```

`bootstrap` 只是首次验通入口，不代表全量入库完成。`subject-pack-audit` 用已购买的官方 specification PDF
做零模型调用的课纲结构漂移检查。

API 启动、`init`、`inventory` 与普通测试都不调用模型。
