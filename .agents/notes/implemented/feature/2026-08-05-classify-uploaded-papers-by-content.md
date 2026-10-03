# Agent Note: 整卷作答按文档实际内容分类，只放行高置信 Question Paper

Status: implemented

## Problem

整卷作答曾依据文件名判断上传的是否为试卷；重命名的 Mark Scheme、Examiner Report 或资料册可以绕过
判断进入视觉复核与作答，浪费模型调用并产出无意义结果。

## Decision

- MinerU 解析后，结构化模型按采样内容把文档分为八类考试文档并给出置信度；只有高置信 Question Paper
  继续视觉复核、拆题和作答，其余返回明确的用户错误。
- 分类结果按输入摘要、模型与契约版本持久复用。
- 上传阶段只保留格式、大小与 PDF 可读性等低成本校验，不用文件名做业务判定。

## Alternatives considered

- **按文件名判定** — 零成本、即时。重命名文件即可绕过，且真实文件名格式并不统一。

## Consequences

- **收益**：评估资料不会被当作试题作答。
- **代价与已知上限**：每份上传增加一次分类调用；低置信的真实试卷会被拒绝，需要用户确认文件。

资料库存（`inventory` 与工作区上传）仍按文件名与 PDF 首页印刷代码识别来源，见
[资料分类修正](../bug-fix/2026-10-03-corpus-classification-and-foreign-qualifications.md)。
