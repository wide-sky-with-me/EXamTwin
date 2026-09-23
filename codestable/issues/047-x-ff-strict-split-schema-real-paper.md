---
kind: issue
title: "实卷验证：修复严格拆题Schema并记录额度阻断"
type: ff
status: closed
created: 2026-09-08
epic: ""
---

## 做了什么
用户授权2026年1月数学P1一套实卷（11大题/80分）调用真实服务；首轮拆题失败后，另行明确授权最小修复并继续同卷。修复严格Schema兼容性并实测通过拆题。修复后答题受到供应商额度阻断，用户明确选择暂停；这里只关闭已验证的小修复，不宣称整卷评价完成。

## 改了哪些
- `backend/src/examtwin/assessment/paper_answering.py`：将_QuestionSplitPayload.questions的任意字典替换为六个明确字段的_QuestionSplitItem；嵌套SubpartRequirement局部forbid-extra；model_dump(mode=json)交回原有规范化、checkpoint与来源完整性链路。不放宽strict，不改模型/预算/公共契约或split-v12。
- `backend/tests/test_paper_split_schema.py`：7例回归，真实LiteLLM/OpenAI序列化到MockTransport，检查发送Schema所有对象层均有字段、required齐全、additionalProperties=false，且非空子题payload匹配；验证来源页不信模型、可选/nullable默认与原有规范化。
- `backend/tests/test_paper_answering.py`：移除一个provider mock中过时且未被消费的knowledge_codes字段。
- `data/local-runs/p1-202601-20260908/`：同卷输入checksum、两个尝试快照、官方MS独立清单、部分评分、页面截图、单次提交/观察脚本和恢复说明。

## 怎么验证的
Ruff/format/basedpyright通过；父会话复跑92项拆题/Worker测试与架构检查通过。README规定的常规单测546 passed/39 deselected。额外尝试只排integration时遇到1个local_assets测试缺旧var/corpus/md/388f...md，548passed；没有伪造资源或削弱断言，随后使用文档规定的排除integration和local_assets命令。

构建并重建原API/2Worker/GC及loopback代理，四个Python容器image均为sha256:7bac7776912a7ca24a77e86a3bfdd6dce52d1a1b9ec38234e0712697b7995e51；原18000健康检查通过。未更改原数据卷。前端原5173服务已退出，恢复同端口并实测页面。

首轮独立API任务71ae71c5-b88f-4545-a70c-d679d5dbaa42：20页解析、0答案，因Schema失败，约275秒。使用同PDF正式PaperUnit入口后的任务46991d76-24f0-4cca-9b26-62915f68f0da：11大题/80分、source_integrity verified，约247秒结束partial_failed；Q3完成，经独立MS p7核对为3/3，其他10题空答案，最终错误均为额度/预扣费不足。不能把这当整卷准确率；其余77分未能评估。页面显示1题已处理、10题失败，无JS错误。MS未上传或喂给作答模型，数学核心库固定v1。

## 对 codestable/ 的影响
严格结构化输出必须检查实际SDK发送Schema，不仅检查Pydantic接受结果。独立/papers/answer接口不自动建当前UI PaperUnit；新实卷应走Workspace资料→PaperUnit→answer入口。此次schema修复已验证，整卷效果验证因额度不足按用户要求暂停，恢复应只重试canonical任务失败题，不重做Q3、不覆盖失败证据、不改模型挑高分。
