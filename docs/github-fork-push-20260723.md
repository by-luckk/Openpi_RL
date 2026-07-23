# GitHub fork 与 push 检查（2026-07-23）

检查时间：2026-07-23 14:49-17:07 CST

检查人：Codex

## 目的

把 `Robot-K/Openpi_RL` fork 到 `by-luckk/Openpi_RL`，并通过 SSH 推送当前本地提交。

## 命令与关键输出

```bash
git remote -v
ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new -T git@github.com
git ls-remote git@github.com:by-luckk/Openpi_RL.git HEAD
curl -sS -o /dev/null -w '%{http_code}' https://github.com/by-luckk/Openpi_RL
gh repo fork Robot-K/Openpi_RL --clone=false
git remote add fork git@github.com:by-luckk/Openpi_RL.git
git push -u fork master
git ls-remote fork refs/heads/master
```

首次检查结果：

- `origin` 为 `https://github.com/Robot-K/Openpi_RL.git`。
- 首次 SSH 因本机缺少 `github.com` host key 被拒；使用 OpenSSH `accept-new` 写入 host key 后，
  GitHub 返回 `Hi by-luckk! You've successfully authenticated`，确认本机 SSH key 对应账号
  `by-luckk`。
- `by-luckk/Openpi_RL` 的 SSH `ls-remote` 返回 `Repository not found`，网页请求为 HTTP 404，
  确认 fork 尚不存在。
- 本机没有 `gh`、`GH_TOKEN`、`GITHUB_TOKEN` 或既有 `gh` 登录配置。SSH git 协议只能访问和
  push 已存在仓库，不能创建 GitHub fork，因此创建 fork 还需要 GitHub API/OAuth 授权。

临时从 GitHub CLI 官方 release 下载 `gh 2.96.0` 到 `/tmp`，并用官方 checksums 文件验证
SHA-256 后启动 GitHub device login。首次 device code 过期后停止旧进程；第二次 device login
由用户在 GitHub 页面确认，CLI 返回 `Logged in as by-luckk`，权限包含 `repo`。

授权后 `gh repo fork` 成功创建 `https://github.com/by-luckk/Openpi_RL`。GitHub API 复核结果为
`isFork=true`，parent 为 `Robot-K/Openpi_RL`，默认分支为 `master`。本地新增 SSH remote：

```text
fork  git@github.com:by-luckk/Openpi_RL.git
```

`git push -u fork master` 成功把 `master` 从上游基线 `87b5ac9` 推到功能提交 `593fb0d`，并设置
本地 `master` 跟踪 `fork/master`。随后 `git rev-parse HEAD` 与
`git ls-remote fork refs/heads/master` 均返回
`593fb0dca712d18c9bb635acc57192f98d7fd427`。

## 本地提交身份

用户提供 GitHub 账号 `by-luckk` 和邮箱 `by-chen22@mails.tsinghua.edu.cn`。本地仓库级 Git
identity 已更新为该身份，并对尚未 push 的功能提交执行：

```bash
git commit --amend --no-edit --reset-author
```

提交作者和提交者均已变为 `by-luckk <by-chen22@mails.tsinghua.edu.cn>`。

## 结论

fork 创建和 SSH push 均已完成：`by-luckk/Openpi_RL:master` 包含当前功能提交，本地分支已跟踪
`fork/master`。`origin` 仍指向 `Robot-K/Openpi_RL`，本轮未向上游仓库写入任何内容。

完成 API 操作后已执行 `gh auth logout --hostname github.com --user by-luckk`，确认本机
`~/.config/gh/hosts.yml` 不再包含 `oauth_token` 或用户条目；临时 GitHub CLI 和设备登录日志已移入
系统回收站。SSH remote 随后仍能正常读取远端 `master`。`gh auth logout` 只删除本地凭据，不会
自动撤销 GitHub 侧 OAuth 授权；如需撤销，应在 GitHub Settings -> Applications 中管理
`GitHub CLI` 授权，注意撤销该应用会影响同账号其他 GitHub CLI 登录。
