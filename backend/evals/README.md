# 模型评分回归

`grading_cases.json` 是调用前冻结的 28 个合成样例。数学 12 个；经济 16 个。
其中 23 个非空短答交给模型，3 个空白走正式服务的零分规则，2 个不可查看图片走正式服务的
暂缓授分规则。不要把后两类算作模型判断能力。正确分值由作者依据官方评分标准标注，
不是教师双评金标准、真实学生数据或官方示范答卷；不能推导整卷等级准确率。

数学来源为 MA01 January 2019 MS 第 4–5 页，原 PDF SHA-256 见每个样例；经济来源为
EC01 January 2024 MS 第 11–12 页，样例中 SHA-256 对应最初抽取的页文本 JSON。
对应原经济 MS PDF SHA-256 为 `df3385ecdc5734d6c74af283b77f66ca3959d5da215b0c347c24c326a675bce2`。
数学覆盖独立得分点、方法/准确分、部分正确和错误答案；经济覆盖定义的 0–3 分，含恶意要求
改分的学生文本。没有覆盖长论述等级判断、所有 FT 情形或真实手写识别。

运行（调用已配置 API，会计费）：

```sh
uv run python scripts/evaluate_grading.py --live \
  --models gpt-5.6-sol gpt-6-sol --output data/local-runs/grading-comparison-new
```

通过正式 `GradingService` 和 LiteLLM 结构化适配器；标准分不进入请求。输出目录必须不存在，
先保存样例及哈希，再保存每个首次调用的结果。失败保留在样本分母内，MAE 明确仅覆盖返回数值
的样例；人工复核门禁不被测试脚本绕过。结果仅写本地目录，不写生产数据库。

目标分链路另用 `validate_target_strategy.py` 和 `validate_strategy_runtime.py`。答案冻结后，
可用另一模型盲评（问题文件只能用未附策略的 `split.json`）：

```sh
uv run python scripts/grade_strategy_submission.py --live --model gpt-6-astra \
  --bundle data/local-runs/RUN/9660/blind-judge-bundle.json \
  --questions data/local-runs/PLAN/9660/split.json \
  --output data/local-runs/RUN/9660/blind-grade
```

盲评器只读题目、材料、官方 MS 和实际答案及矢量图，不读目标、方案或历史分。
每个印刷子问固定一个评分项，保留子问内部官方方法分/准确分或整体等级规则。
这是独立模型初评，未经过教师审核评分规则，不等同于正式数据库端到端评分或教师真值。
失败和暂缓评分明确显示 incomplete，不将缺失的评分冒充最终整卷分。

评测的取舍与局限见 `.agents/notes/implemented/testing/2026-09-28-frozen-grading-evals.md`。
