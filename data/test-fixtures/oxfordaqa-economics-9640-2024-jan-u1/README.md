# OxfordAQA 9640 U1 合成作答测试样本

这是一份用于 ExamTwin 本地端到端验收的**合成经济学作答**。它不是 OxfordAQA 发布的
考生答卷，也不来自真实学生，不包含个人信息。作答中保留了少量故意错误和不充分论证，
用于检查外部答案导入、levels-based Mark Scheme、AI 初评和人工复核。

## 配套材料

- Question Paper：`data/牛津AQA/经济/AQA alevel经济2024年真题/1月/qp-202401-economics-u1.pdf`
- Source Booklet：`data/牛津AQA/经济/AQA alevel经济2024年真题/附件/IN-202401-Economics-U1A-Level-AQA经济学-9640.pdf`
- Mark Scheme：`data/牛津AQA/经济/AQA alevel经济2024年真题/1月/ms-202401-economics-u1.pdf`
- 合成答案：`student-answer.synthetic.md`
- 机器可读元数据：`fixture.json`

Question Paper、Source Booklet 与 Mark Scheme 的目标解析身份均为 `9640:2024:JAN:U1`。本目录不复制
官方 PDF；`fixture.json` 保存原始路径、页数和 SHA-256。

## 验收步骤

1. 进入“答案评分”，选择 Economics（9640）和“上传答卷”。
2. 上传配套 QP、Source Booklet 与 `student-answer.synthetic.md`，选择 U1。
3. 等待导入任务完成；预期题号为 Q1–Q21，`answer_mode=uploaded`。
4. 上传或选择上述官方 Mark Scheme，审核并确认细目，逐题初评到整卷报告。
5. 检查故意错误能进入逐题诊断/复核；不把模型分数写成固定真值。

答案只使用 `# Q1` 至 `# Q21` 作顶层分割标题；子问使用普通粗体标签，避免被导入器
错当成新的顶层题。
