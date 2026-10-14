# ExamTwin 文档

ExamTwin 面向 OxfordAQA International AS/A-level 数学与经济，把考试资料转成可核查知识、整卷作答和待教师
复核的建议分。本机单用户部署，没有登录、学生端或成绩发布入口。

## 开始使用

- [本地开发与运行](cookbook/local-development.md)：Linux、Docker Desktop / WSL、代理与启动验证。
- [工作台使用](cookbook/workbench.md)：科目、资料、试卷、作答、评分和复核的完整路径。
- [架构全景](architecture.md)：产品不变量、运行拓扑、领域边界与数据所有权。

## 子系统参考

| 主题 | 文档 |
|---|---|
| 科目能力与资料身份 | [SubjectPack](subsystems/subject-packs.md)、[资料与知识库](subsystems/corpus-and-knowledge.md) |
| 检索与逐题作答 | [检索](subsystems/retrieval.md)、[答题 Agent](subsystems/answering-agent.md) |
| 整卷与策略 | [试卷任务](subsystems/paper-jobs.md)、[目标分数策略](subsystems/target-strategy.md) |
| 评分与导出 | [评分复核](subsystems/grading-and-review.md)、[原卷 PDF 导出](subsystems/answer-pdf-export.md) |
| 运行依赖 | [模型供应商](subsystems/model-providers.md)、[对象存储](subsystems/object-storage.md) |
| 开发定位 | [代码组织](subsystems/code-organization.md)、[前端工作台](subsystems/frontend-workbench.md) |

## 操作与维护

- [数据管线](cookbook/data-pipeline.md)：清点、转换、发布与评测；涉及模型和资料外发的步骤单独授权。
- [存储运维](cookbook/storage-operations.md)：迁移、回收与数据卷核对。
- [新增科目](cookbook/adding-a-subject.md)：声明能力、验证课纲与检索门禁。
- [测试与检查](cookbook/testing.md)：隔离回归、契约、集成与视觉测试。
- [Wiki 发布](cookbook/wiki-publishing.md)：从同一份文档生成首页、侧栏及参考页。
- [仓库治理](cookbook/repository-governance.md)：代码许可、第三方与资料边界、密钥保护和主分支规则。

## 规则与设计依据

[根规则](../AGENTS.md) 与各目录 `AGENTS.md` 约束开发；[决策笔记](../.agents/notes/) 记录选择原因和代价。
当前事实写在本目录，历史验收与设计取舍不作为当前完成声明。

## 事故复盘

- [整卷 MinerU 超时](postmortem/2026-07-29-whole-pdf-mineru-timeout.md)
- [启动同步清空定义证据](postmortem/2026-08-03-startup-seed-cleared-definition-evidence.md)
- [旧数据卷删除](postmortem/2026-10-03-legacy-volumes-deleted.md)
