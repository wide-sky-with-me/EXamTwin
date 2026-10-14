# 公开仓库治理

前提：从仓库根目录操作，GitHub CLI 已登录；读取治理状态需要仓库管理权限。公开源码不改变本机单用户、
loopback 部署边界，运行方式见[本地开发](local-development.md)。

1. 核对许可与范围。

   项目原创代码和原创文档采用 **AGPL-3.0-only**，正文见 [LICENSE](../../LICENSE)，包声明见
   [pyproject.toml](../../pyproject.toml) 与[前端包](../../frontend/package.json)。第三方内容遵循各自许可；
   教材、课纲、试卷、Mark Scheme、用户输入及其提取或生成资料按来源权利处理，不纳入项目原创内容授权。
   [测试资料](../../data/test-fixtures/)是合成夹具，不包含官方 PDF 或真实学生数据。
   PyMuPDF 的[官方说明](https://github.com/pymupdf/PyMuPDF#licensing)提供 AGPLv3 与商业双授权；
   分发或提供修改后的网络服务时遵循 LICENSE 的源码提供和许可通知要求。

   ```bash
   gh api repos/wide-sky-with-me/EXamTwin/license --jq '{path,license:.license.spdx_id}'
   ```

2. 核对密钥保护。

   GitHub 密钥扫描与推送保护均启用。它们覆盖 GitHub 支持的密钥类型，不替代历史规则扫描；`.env` 留在本机，
   不在报告、提交或 Wiki 中保存凭据。聚合状态中的对应字段应为 `enabled`。

   ```bash
   gh api repos/wide-sky-with-me/EXamTwin --jq '.security_and_analysis'
   ```

3. 核对依赖漏洞更新。

   Dependabot 告警和漏洞修复更新启用；修复以 PR 提交，由维护者审查合并。不设常规版本更新任务，不启用自动
   合并。告警查询成功、修复状态为 `enabled:true` 且 `paused:false`。

   ```bash
   gh api repos/wide-sky-with-me/EXamTwin/vulnerability-alerts --silent
   gh api repos/wide-sky-with-me/EXamTwin/automated-security-fixes
   ```

4. 核对主分支完整性。

   [规则定义](../../.github/rulesets/main-integrity.json)针对 `refs/heads/main`，生效状态为 `active`，没有绕过
   名单；规则包含 `deletion` 与 `non_fast_forward`，限制删除及强推。普通快进直推保留，不强制 PR 或前置
   状态检查；[CI](../../.github/workflows/ci.yml)仍验证提交。用读取规则验证，不以删除或重写主分支试验。

   ```bash
   gh api repos/wide-sky-with-me/EXamTwin/rules/branches/main --jq '[.[] | {type,ruleset_id}]'
   ```

状态不符时先查仓库 Settings 的规则和安全设置，不以放宽规则绕过失败。文档修改按
[Wiki 发布](wiki-publishing.md)同步；第三方依赖版本和许可变更需重新核对分发范围。
