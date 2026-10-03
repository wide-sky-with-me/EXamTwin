# Agent Note: 资料分类收紧 Insert 与报告规则，并按首页印刷代码排除外部资格试卷

Status: implemented

## Problem

只读复核原始资料目录发现四个分类缺陷，都会污染考试身份与严格配对：

- Insert 规则把标题里的英文单词 “in” 当作 `IN-` 代码，7 份笔记、课件与练习被判为身份不完整的 Insert。
- 文件名 `...-report-jan22`、`... Exam Report ...` 未被识别为考官报告：5 份成为 `other`，另 5 份被当成
  Question Paper，与真题共用配对键。
- 经济目录名为“分类练习”而规则只认“章节分类练习”，14 份专题练习无法进入补充知识库。
- 2018–2019 年 `AQA-A-Level/AS-JUN20xx-Economics-Paper-N` 的文件名没有资格代码，20 份 UK AQA
  7135/7136 资料经 `paper_unit_map` 进入 9640 的 6 个配对键，AS 与 A-level 试卷同键冲突。

## Decision

- `IN` 只在文件名开头且后接日期时识别为 Source Booklet。
- 文件名含独立单词 `report` 即为 Examiner Report，在 Question Paper 判断之前生效。
- 路径含“分类练习”即为 `topic_practice`。
- 清点与工作区上传都读取 PDF 首页印刷的组件代码（`dddd/d`，排除年份）；该代码或文件名代码不属于当前
  科目时，资料不进入严格配对，与文件名带外部代码的既有处理一致。
- 整卷作答的试卷身份仍按文件名推断，未接入首页代码检查。

## Alternatives considered

- **按目录或文件名模式排除 2018–2019 经济资料** — 实现最小。只修这一批文件，新上传的同类资料仍会混入；
  首页印刷代码对上传与清点两条入口都成立。
- **上传外部资格试卷时直接拒绝** — 反馈更明确。与文件名带外部代码的既有行为（保留但不配对）不一致。

## Consequences

- **收益**：只读复跑显示身份不完整数学 3→0、经济 4→0；经济严格配对 40→34，任一配对键无重复 QP/MS。
  首页代码检测在数学 192 份考试 PDF 中 0 命中，经济 36 份均为 7135/7136。
- **代价与已知上限**：首页没有文字层的扫描件读不到代码，仍按文件名判断；每份考试 PDF 清点时多读一页文本。

## Verification

`backend/tests/test_inventory.py` 与 `test_workspace_uploads.py` 覆盖误判样例、首页代码与上传路径。
