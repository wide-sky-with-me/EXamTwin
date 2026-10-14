# 工作台使用

先按[本地开发](local-development.md)启动；选择科目并把页面中的科目 ID 设为 `SUBJECT`。后续把作答任务和
评分规则 ID 分别设为 `JOB`、`RUBRIC`。查询命令只读，模型作答、转换与构建单独确认资料范围和费用。

```bash
API=http://127.0.0.1:18000/api/v1
get() { curl -fsS -H "X-ExamTwin-Subject: ${SUBJECT:?}" "$API/$1"; }
```

## 1. 准备知识

科目详情上传 syllabus 与教材，构建并发布核心库，按[数据管线](data-pipeline.md)通过检索评测。查看科目
状态，核对已发布版本与来源；有资料不等于知识已构建。

```bash
curl -fsS "$API/subjects/status"
```

## 2. 建立试卷

科目卡片进入试卷列表，绑定 Question Paper、Mark Scheme 和所需 Source Booklet；科目、年份、考季、
Unit 严格一致。核对列表中的资料角色和完整配对身份；样卷和其他资格试卷不进入正式配对。

```bash
get "subject-workspaces/$SUBJECT/paper-units"
```

## 3. 创建作答记录

试卷详情启动 AI 作答或导入外部答案。目标分策略在创建 AI 任务时配置；任务后台解析与逐题作答，刷新后
从作答记录打开同一任务。核对状态、题号、总分和失败原因；部分完成不标成整卷完成。

```bash
get "papers/jobs/${JOB:?}"
```

## 4. 确认评分规则

从作答记录进入评分，用严格配对的 Mark Scheme 生成规则原子。教师审核、编辑并填写审核人，AI 审核只
提出建议。核对所有原子都有人工作出决定且至少一条被接受，规则版本才可确认。

```bash
get "grading/rubrics/${RUBRIC:?}"
```

## 5. 初评与复核

对已确认规则逐题初评，在“复核”查看建议与证据并确认最终分。核对初评为 `pending_review`、最终分来自
教师；暂缓占位零分不表示答错。门禁与总分语义见[评分复核](../subsystems/grading-and-review.md)。

```bash
get "grading/papers/${JOB:?}/assessments"
```

## 6. 导出 PDF

已结束且来源核对通过的作答记录可导出原卷答案。检查答案区域、公式和续答页，预览并下载；只复用保存
答案，不调用模型。核对布局来源与区域门禁，部分任务附未完成清单；见[PDF 导出](../subsystems/answer-pdf-export.md)。

```bash
get "papers/jobs/${JOB:?}/answer-pdf/layout"
```
