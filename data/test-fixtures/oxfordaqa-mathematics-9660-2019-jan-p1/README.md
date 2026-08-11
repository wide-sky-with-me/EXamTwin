# OxfordAQA 9660 P1 合成作答测试样本

这是一份用于 ExamTwin 本地功能测试的**合成学生作答**。它不是 OxfordAQA 发布的考生
答卷，也不来自真实学生，不包含个人信息。答案中有意保留了 5 处错误，用来验证外部答卷
导入、逐题切分、Mark Scheme 评分和人工复核流程。

## 配套材料

- Question Paper：
  `data/牛津AQA/数学/5.AQA-alevel数学-历年真题/AS/2019 January/as-level-maths-unit-1-question-paper-Jan19.pdf`
- Mark Scheme：
  `data/牛津AQA/数学/5.AQA-alevel数学-历年真题/AS/2019 January/as-level-maths-unit-1-mark-scheme-Jan19.pdf`
- 合成答案：`student-answer.synthetic.md`
- 机器可读元数据：`fixture.json`
- 人工预期评分：`expected-assessment.json`

Question Paper 与 Mark Scheme 的解析身份均为 `9660:2019:JAN:P1`。本目录不复制官方
PDF，以避免重复语料和库存污染；`fixture.json` 保存了相对路径、页数与 SHA-256，可用于
确认测试时选择的是同一份文件。

## 手工功能测试

1. 进入“答案评分”，选择 Mathematics（9660）。
2. 选择“自行上传”，Question Paper 使用上面的原卷 PDF，答案使用
   `student-answer.synthetic.md`。
3. 等待外部答案任务完成；预期识别顶层题号 Q1–Q10，且答案模式为 `uploaded`。
4. 选择上面的官方 Mark Scheme，审核并确认评分细目后执行逐题评分。
5. 参考 `expected-assessment.json` 检查系统是否能定位 5 个故意错误。人工按官方 Mark
   Scheme 预估为 74/80；模型评分允许有小幅波动，最终仍以教师复核为准。

答案文件使用系统现有的 `# Q1` / `# Q2` 标题协议。不要把子问写成新的 Markdown 数字
标题，否则可能被外部答案切分器当成重复的顶层题号。

## 使用边界

- 可用于本地导入、解析、评分、复核和回归测试。
- 不得标注为真实考生数据、官方 exemplar 或真实学生表现证据。
- 不得用于推断 OxfordAQA 的总体成绩分布或验证学生数字孪生。
