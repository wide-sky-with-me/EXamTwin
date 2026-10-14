# Agent Note: 公开仓库采用 AGPLv3 并保护主分支完整性

Status: implemented

## Problem

用户在仓库公开后要求完成密钥保护、许可证和 GitHub 维护配置。仓库没有项目许可证；已安装 PyMuPDF 1.28.0
声明 AGPLv3 / Artifex 商业双授权。GitHub 密钥扫描、推送保护和 Dependabot 修复均关闭，main 没有生效规则。
仅公开源码不能替代许可声明或防止历史被强推重写；全面强制 PR 又会改变已有单人直推路径。

## Decision

- 项目原创代码及原创文档采用 **AGPL-3.0-only**。[LICENSE](../../../../LICENSE)逐字保留 GitHub 官方许可证
  API 的 AGPLv3 正文，[Python](../../../../pyproject.toml)及[前端](../../../../frontend/package.json)声明同一
  SPDX 标识；Python wheel 包含许可证正文。前端 `private:true` 继续控制 npm 发布，与 GitHub 公开性无关。
- 选择匹配现有 PyMuPDF 开源路线，不默认拥有 Artifex 商业授权，不采购许可或替换 PDF 处理链。第三方内容
  保留原许可；外部教材、考试资料、用户输入和提取或生成资料按来源权利处理。边界的唯一当前说明归属
  [仓库治理手册](../../../../docs/cookbook/repository-governance.md)。
- 开启 GitHub 密钥扫描、推送保护、Dependabot 告警和漏洞修复更新。修复生成 PR，交由维护者审查，不开启
  自动合并或另设版本升级任务；配置不是凭据轮换或全类型数据审计的替代品。
- [main-integrity](../../../../.github/rulesets/main-integrity.json)是主分支规则定义，部署到 GitHub 的 active
  branch ruleset；目标仅 `refs/heads/main`，空绕过名单，限制删除与非快进推送。普通直推保留，CI 继续运行，
  不增加强制 PR、审批人数或推送前状态检查。
- 延续[单源 Wiki](2026-10-14-single-source-wiki.md)的发布流程；治理手册随文档自动发现和生成，不另立手写
  Wiki 或全局笔记索引。不调整应用认证、监听地址、运行服务或数据卷。

## Alternatives considered

- **项目标 MIT / Apache-2.0**：原创代码可以采用宽松许可，且这些许可不天然与 AGPLv3 冲突；但组合分发
  仍需履行 AGPL 义务。当前项目保持 PyMuPDF 处理链，选择整体声明清晰的 AGPLv3，而不是让仓库标识给出
  宽松分发的误导预期。
- **购买 Artifex 商业许可或替换 PDF 库**：可支持另一条产品授权路线。此次目标是公开仓库善后，不含采购，
  替换会牵动渲染、坐标和源页完整性行为，故保持依赖与产品行为。
- **强制 PR、审批和前置检查**：为多人协作提供更强审查门禁，但会阻断已有单人正常直推。此次只保护 main
  历史与存在性；需要多人协作时另行决定审查门禁，不能把当前规则表述为 CI 强制阻断。

## Consequences

- 源码获得明确许可，wheel 携带许可文件；公开仓库的密钥保护和主分支完整性可通过专用 API 读取验证。
- AGPL 带来分发及网络交互场景的源码提供、许可通知等义务；本声明不替第三方或考试资料授予额外权益。
  尚未进行所有传递依赖及资料类型的法律审计，后续镜像或二进制分发需核对实际随包内容及各许可通知。
- GitHub 设置不随 clone 复制；版本化规则 JSON 记录期望，实际生效必须核对远端 API。规则变更由维护者
  审查，不能通过强推、删除 main 或添加绕过账号验证配置。
- 本次不升级运行依赖、不触发真实模型、不恢复 Compose 或改动持久数据。自动修复 PR 仍有兼容性与测试
  成本，由维护者判断合并。

## Decision audit

按许可、PyMuPDF、密钥保护、Dependabot 和分支规则关键词检索 proposed / implemented / rejected，无同项
许可或权限决定；单源 Wiki 笔记部分重叠，双方互链并保留各自职责，没有删除或归档历史决定。

## Verification

许可证正文与官方 API 原件逐字一致。远端密钥扫描、推送保护和漏洞修复聚合状态均为 `enabled`；专用修复
API 返回 `enabled:true, paused:false`，告警开关查询成功。远端 main 展开规则包含 `deletion` 和
`non_fast_forward`，ruleset 为 active 且没有绕过名单。未对 main 执行强推或删除测试。

`uv run --frozen --no-sync python scripts/check_docs.py`、`scripts/agent_notes.py check`、`uv lock --check` 与
`scripts/build_wiki.py --check` 通过，Wiki 生成覆盖 27 个文件；隔离的 Wiki 回归 16 个用例通过。
`uv build --wheel` 成功，wheel 的 `License-Expression` 为 `AGPL-3.0-only`，`License-File` 为 `LICENSE`，
所携正文与根 LICENSE 逐字一致，归档仅含应用包和 dist-info，没有缓存、运行资料或环境文件。

已核对安装环境中直接运行依赖的许可元数据；该核对不包含所有传递依赖全文。前端许可字段匹配 Python，
`private:true` 保留，锁文件未变化。普通推送、许可证识别、Wiki 发布和 CI 以远端提交及运行结果核实，不以
读取规则代替破坏性测试；本轮未在本机重跑产品全量套件、真实模型或运行服务。
