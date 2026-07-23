# GitHub fork 与 push 检查（2026-07-23）

检查时间：2026-07-23 14:49-16:59 CST

检查人：Codex

## 目的

把 `Robot-K/Openpi_RL` fork 到 `by-luckk/Openpi_RL`，并通过 SSH 推送当前本地提交。

## 命令与关键输出

```bash
git remote -v
ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new -T git@github.com
git ls-remote git@github.com:by-luckk/Openpi_RL.git HEAD
curl -sS -o /dev/null -w '%{http_code}' https://github.com/by-luckk/Openpi_RL
```

结果：

- `origin` 为 `https://github.com/Robot-K/Openpi_RL.git`。
- 首次 SSH 因本机缺少 `github.com` host key 被拒；使用 OpenSSH `accept-new` 写入 host key 后，
  GitHub 返回 `Hi by-luckk! You've successfully authenticated`，确认本机 SSH key 对应账号
  `by-luckk`。
- `by-luckk/Openpi_RL` 的 SSH `ls-remote` 返回 `Repository not found`，网页请求为 HTTP 404，
  确认 fork 尚不存在。
- 本机没有 `gh`、`GH_TOKEN`、`GITHUB_TOKEN` 或既有 `gh` 登录配置。SSH git 协议只能访问和
  push 已存在仓库，不能创建 GitHub fork，因此创建 fork 还需要 GitHub API/OAuth 授权。

临时从 GitHub CLI 官方 release 下载 `gh 2.96.0` 到 `/tmp`，并用官方 checksums 文件验证
SHA-256 后启动 GitHub device login。设备授权在等待期间未由 GitHub 确认，随后已停止后台登录
进程；未创建 fork，也未 push。临时 CLI 没有安装到系统目录。

## 本地提交身份

用户提供 GitHub 账号 `by-luckk` 和邮箱 `by-chen22@mails.tsinghua.edu.cn`。本地仓库级 Git
identity 已更新为该身份，并对尚未 push 的功能提交执行：

```bash
git commit --amend --no-edit --reset-author
```

提交作者和提交者均已变为 `by-luckk <by-chen22@mails.tsinghua.edu.cn>`。

## 结论与后续

SSH push 前置条件已满足，但 fork 创建被 GitHub API 授权阻塞。用户完成一次 GitHub CLI device
authorization，或在网页手动点击 Fork 创建 `by-luckk/Openpi_RL` 后，即可把 fork 添加为 SSH
remote 并推送本地 `master`。当前未向 `Robot-K/Openpi_RL` 写入任何内容。
