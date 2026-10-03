# Agent Note: 付费模型调用与资料外发只在明确授权后执行

Status: implemented

## Problem

转换、索引、知识构建、检索评测、供应商冒烟和整卷实验都会把已购买的资料或查询发送到外部服务并产生费用。
自动化 Agent 在验证改动时容易顺手运行这些命令，导致未经同意的数据外发与费用。

## Decision

- API 启动、`init`、`inventory` 与全部普通测试不调用任何模型或外部服务；单测阻止外部网络访问。
- 会外发或付费的命令（`convert`、`index`、`knowledge-build`、`retrieval-evaluate`、`provider-smoke`、
  `backend/evals/`、`scripts/validate_*.py --live`、真实整卷任务）只在用户明确授权后执行；授权范围按资料与
  查询集合界定，已授权的试卷不等于授权全部课程节点或评测集。
- 实验脚本必须显式 `--live` 才调用模型，输出目录必须全新。
- 授权缺失时停在门禁前，并说明尚未验证的部分，不以离线结果冒充。

## Alternatives considered

- **在 CI 或验证中自动运行真实冒烟** — 能更早发现供应商契约变化。会持续产生费用并外发资料；改为显式
  `provider-smoke` 命令。

## Consequences

- **收益**：资料外发与费用都有明确的授权记录。
- **代价与已知上限**：部分验证（真实检索质量、长题稳定性）需要等待授权，期间只能报告为未验证。
