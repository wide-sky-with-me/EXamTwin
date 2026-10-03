# .agents/notes 规则

决策笔记记录代码与测试说不出来的东西：为什么这样定、否定过什么、代价是什么。写法遵循
[write-notes-like-deepseek](../skills/write-notes-like-deepseek/SKILL.md)；本文件与根目录 `AGENTS.md` 优先于该 skill。

## 何时写

- 写：改了行为、架构、跨文件契约、流程与工具链、测试策略、落盘/网络/配置格式，或其他维护者会重访的取舍。
- 不写：纯格式、错别字、样式、不改行为的依赖补丁、单模块内看 diff 即懂的修复。
- 拿不准时问：只看代码和测试，后来的人推得出为什么这样定吗？推不出就写。

## 路径即身份

`{lifecycle}/{class}/yyyy-mm-dd-topic.md`，日期是首次提出日，文件名用小写 kebab-case。

- lifecycle：`proposed`（未落地）、`implemented`（已落地，随代码同步）、`rejected`（防重犯才保留）、
  `archived`（冻结只读，SHA-256 封印）。
- class：`feature`、`bug-fix`、`simplification`、`architecture`、`process`、`testing`，不得自造。
- 禁止全局 `INDEX.md`；按目录切片或检索。

## 格式

前三行固定为 `# Agent Note: <标题>`、空行、`Status: <lifecycle>`（rejected 写 `Status: rejected — <原因>`）。
`implemented` 骨架：`## Problem` → `## Decision`（现在时）→ 自由节 → `## Alternatives considered` →
`## Consequences`（收益与代价都写）。`proposed` 用 `## Proposal`、`## Acceptance criteria`、`## Risks`。
模板在 skill 的 `templates/`。

备选方案只写真实考虑过的，先写它最强的理由再写为何否定。跨笔记引用用相对 Markdown 链接。

## 生命周期

- 动手前：按模块名或机制名检索，排除归档：
  `rg --hidden --glob '!.agents/notes/archived/**' "<关键词>" .agents/notes/`。命中的笔记当场归类：
  无关、部分重叠（互链）、完全吸收（删除或归档）。
- 事实变化（路径、符号、默认值）：就地更新持有该决定的笔记。
- 决定或理由翻转：新写一篇并互链，不把 `## Decision` 改成反面。
- 落地：`proposed` 移到 `implemented/<class>/`，状态改为 implemented，提案节改写为现在时，与代码同一提交。
- 完全被取代：新笔记吸收旧理由后，能删则删；仍有独立价值时归档：
  `uv run python scripts/agent_notes.py archive <path> --superseded-by <new>`。归档后除 `Archived:` 行外不得改动。

## 校验

`uv run python scripts/agent_notes.py check` 检查目录、文件名、头块、必需节、备选方案、相对链接与归档封印，
CI 必跑。skill 文中的 `npm run verify-*` 命令在本仓库由该脚本替代。
