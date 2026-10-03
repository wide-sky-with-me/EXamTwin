# Agent Note: 以 AGENTS.md 层级、docs/ 与 Agent Notes 管理项目知识

Status: implemented

## Problem

项目知识集中在 `codestable/`（vision、spec、epics、issues，约 25 万字）：当前事实、变更流水与验证日志混在
同一批文档里，spec 随每次改动膨胀，issue 以“做了什么、怎么验证”记录过程而很少记录被否方案；根目录
`AGENTS.md` 只有两条前端约定。新会话难以快速判断哪些是当前约束、哪些是历史，也看不到某个设计当初为什么
不选更直观的方案。

## Decision

- 根目录 `AGENTS.md` 只放全仓常驻短规则，每条一到三行并给链接；`backend/`、`frontend/`、`subject-packs/`、
  `docs/`、`.agents/notes/` 各有专属 `AGENTS.md`，就近约束。
- `docs/` 只写当前事实：`architecture.md` 导航，`subsystems/` 参考，`cookbook/` 操作，`postmortem/` 事故。
  禁止变迁叙述；`docs/doc-budgets.json` 为每篇设字数上限。
- `.agents/notes/{proposed,implemented,rejected,archived}/{6 类}/` 记录非平凡改动的原因、被否方案与代价，
  遵循 `write-notes-like-deepseek` skill；没有全局索引。
- 校验用 Python 实现并接入 CI：`scripts/agent_notes.py`（树、格式、归档封印）与 `scripts/check_docs.py`
  （预算、变迁用词、相对链接）。
- `codestable/` 与 `cs` skill 移除；其中仍然成立的事实迁入 `docs/`，非平凡决定按主题提炼为本目录的笔记，
  界面微调类记录不迁移。原文保留在 git 历史中。

## Alternatives considered

- **保留 codestable 并行使用** — 不需要迁移。两套规则会在“何时写、写在哪”上冲突，Agent 无法确定哪份是现行真相。
- **迁移后保留只读 codestable 目录** — 便于翻阅旧记录。仓库中长期存在一份与 docs 重复且不再维护的事实来源，
  检索时会命中过期内容；git 历史已能提供原文。
- **一个 issue 转一篇笔记** — 信息最完整。大量界面微调与验证流水不满足“非平凡”，会稀释检索。
- **直接复制上游 TypeScript 校验脚本** — 与上游一致，附带看板。项目后端与 CI 以 uv/Python 为主，引入 tsx
  只为文档校验不划算；上游脚本未入库。

## Consequences

- **收益**：当前事实、决定原因与事故各有归宿，且有机械校验。
- **代价与已知上限**：非平凡改动需要同批维护笔记与文档；字数预算会迫使文档持续重构。提炼过程可能遗漏
  旧 issue 中的细节，需要时从 git 历史 `codestable/` 查阅原文。
