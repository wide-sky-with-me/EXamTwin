# Wiki 发布

`docs/` 是唯一事实来源；[build_wiki.py](../../scripts/build_wiki.py) 离线生成 Wiki 首页、侧栏、页脚及参考页。
文档链接指向 Wiki，代码和笔记链接指向指定源版本；围栏和行内代码保持原样。产物放 `var/`，不提交主仓库。

## 1. 校验源文档

```bash
uv run python scripts/check_docs.py
uv run python scripts/build_wiki.py --check
```

检查必须成功；缺失路径、页面名冲突或无首页时停止。内容修改在源文档完成，不编辑生成页。

## 2. 准备远端

在 [GitHub Wiki](https://github.com/wide-sky-with-me/EXamTwin/wiki) 保存一次 `Home` 首页，初始化独立仓库。
设置 `has_wiki=true` 不等于独立仓库已就绪；私有 Wiki 的账户条件见 [GitHub 说明](https://docs.github.com/en/communities/documenting-your-project-with-wikis/about-wikis)。

```bash
gh api repos/wide-sky-with-me/EXamTwin --jq .has_wiki
git ls-remote https://github.com/wide-sky-with-me/EXamTwin.wiki.git HEAD
```

返回 `Repository not found` 时核对网页首页、私有 Wiki 功能和登录权限；不改变主仓库可见性，不把凭据写入 URL。

## 3. 生成与审查

```bash
git clone https://github.com/wide-sky-with-me/EXamTwin.wiki.git var/github-wiki
test -z "$(git -C var/github-wiki status --porcelain)"
uv run python scripts/build_wiki.py --output var/github-wiki --ref "$(git rev-parse HEAD)"
git -C var/github-wiki diff --stat
```

已有本地 Wiki 用 `git -C var/github-wiki pull --ff-only` 代替 clone。首次首页、侧栏等手写页与生成名冲突时，
先检查其内容，再给生成命令加 `--overwrite`。无关页面保留；过期生成页提示显式审查删除，链接或 symlink
检查失败时不覆盖文件。主仓库源版本必须已推送，否则 Wiki 的代码链接会缺失。

## 4. 提交与核实

```bash
uv run python scripts/build_wiki.py --check --output var/github-wiki --ref "$(git rev-parse HEAD)"
git -C var/github-wiki add -- '*.md'
git -C var/github-wiki diff --cached --check
git -C var/github-wiki diff --cached --stat
git -C var/github-wiki commit -m "docs: synchronize wiki from repository documentation"
git -C var/github-wiki push origin HEAD
git -C var/github-wiki rev-parse HEAD
git -C var/github-wiki ls-remote origin HEAD
```

复核暂存差异只含本轮生成页；无变化时跳过 commit。两处 HEAD 相同后，在网页验证首页、导航和源码链接。
