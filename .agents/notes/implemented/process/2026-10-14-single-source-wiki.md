# Agent Note: Wiki 由当前文档单源生成

Status: implemented

## Problem

用户要求完善远端 Wiki，但仓库只有 README 与分散的当前参考、操作手册；没有统一文档入口，也没有 Wiki
同步路径。GitHub 主仓库权限可用且 `has_wiki=true`，独立 `.wiki.git` 仍返回 `Repository not found`。直接手写
第二份 Wiki 会复制领域门禁、路由和命令，增加内容漂移风险；仓库文档已经存在路由和状态所有权的漂移。

## Decision

延续[事实与决策分开](2026-10-03-agent-notes-and-docs-replace-codestable.md)的决定，不设第二份知识维护面。

- [docs/README.md](../../../../docs/README.md) 是统一文档入口及生成的 `Home`；架构页继续只导航，源码定位和
  使用路径分别归属参考与手册。不复制环境变量和完整 API 清单。
- [build_wiki.py](../../../../scripts/build_wiki.py) 从 docs 当前层级确定性生成 Markdown，自动建立 `_Sidebar`
  与 `_Footer`。文档链接改为 Wiki 页，代码、规则和笔记链接绑定指定主仓库版本；代码片段不改写。
- 生成和校验只做文件工作，无网络、Git 或凭据读取；产物在 `var/`，主仓库只存源文档与脚本。CI 校验生成
  内容，真实推送是显式发布步骤，先保证源提交已在远端，再发布 Wiki。
- 预检全部同名页，默认保护手写页，显式 `--overwrite` 才允许替换；保留无关页面，过期生成页要求人工审查。
  禁止覆盖源码目录和输出 symlink，遇到链接错误停止。
- [发布手册](../../../../docs/cookbook/wiki-publishing.md) 区分 Wiki 设置、首次网页首页、私有功能资格与 Git
  仓库可用性。生成器完成不代表远端已发布；首次初始化不更改仓库可见性或账户付费计划。
- [公开仓库保护与许可](2026-10-14-public-repository-governance.md)使用同一单源发布路径，保留本笔记的生成与
  覆盖保护决定；许可和 GitHub 权限策略由该笔记及其当前手册维护。

## Alternatives considered

- **手写 Wiki 页面并独立维护**：可自由组织百科式内容，无生成工具成本。产品不变量、操作命令和路由已经
  有仓库归宿，独立副本会要求每次改动同步审查两份事实，故只维护源文档和自动导航。
- **只整理仓库文档，Wiki 放入口链接**：成本最低且事实不会复制。但不能在 Wiki 内浏览完整工作流与参考，
  不满足本次完整整理目标；生成页通过源码反链保留单源关系。
- **接入完整 Markdown 解析再渲染**：复杂语法处理成熟。当前链接转换无需重排文档，完整渲染会增加公式、
  围栏、表格格式及插件保真的维护面；采用受测试覆盖的局部转换，保留源码文本。若文档出现复杂嵌套链接或
  本转换器不支持的语法，需要重访该选择，不扩大正则来追赶完整 Markdown 标准。
- **在 CI 保存浏览器登录态并自动首次建页**：无人介入即可启动发布。但首次页面走网页表单，不属于标准
  Wiki Git 同步；为一次初始化长期持有网页会话不划算。使用 GitHub 网页完成首次首页，之后普通 Git 同步。

## Consequences

- 当前事实只维护一次，Wiki 首页、导航、来源和相对链接可离线验证；无新依赖和隐式外部调用。
- Wiki 不是独立编辑面；来源文档标题和路径必须稳定，重命名生成页需要审查旧页，复杂 Markdown 需要增加
  回归或改用成熟解析器。发布者要负责源提交与 Wiki 提交的先后和远端核实。
- 私有 Wiki 功能及首次初始化仍依赖 GitHub 账户与网页；本笔记记录工具已实施，不声明远端发布已经成功。

## Verification

[测试](../../../../backend/tests/test_build_wiki.py) 的 16 个用例通过，覆盖稳定生成、文档/源码/目录链接、代码
围栏、参考链接、首页与页面冲突、漂移检测、手写页和源码保护、symlink 与命令行。执行
`uv run pytest -m "not integration and not local_assets" backend/tests/test_build_wiki.py -q`，
`uv run python scripts/check_docs.py`、`uv run python scripts/agent_notes.py check` 与
`uv run python scripts/build_wiki.py --check` 均通过；生成内容为 24 个文档页、侧栏与页脚。
发布前按手册检查生成页和远端 HEAD，远端发布状态单独核实。
