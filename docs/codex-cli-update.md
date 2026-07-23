# Codex CLI 更新检查

## 2026-07-01 15:23 CST — 通过代理更新 Codex CLI 到 0.142.5（agent: Codex）

### 目的

用户反馈无法执行：

```bash
sh -c 'curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh'
```

本次确认问题是否出在 `curl` 没有走代理，并尝试用官方自更新入口完成更新。

### 命令与关键输出

读取官方 Codex manual（openai-docs skill helper）：

```bash
node /home/discover/.codex/skills/.system/openai-docs/scripts/fetch-codex-manual.mjs
```

关键输出：

```text
Manual path: /tmp/openai-docs-cache/codex-manual.md
Outline path: /tmp/openai-docs-cache/codex-manual.outline.md
Manual status: local manual was updated.
```

官方 manual 中安装器变量说明确认：

```bash
sed -n '9443,9486p' /tmp/openai-docs-cache/codex-manual.md
```

关键输出：

```text
CODEX_NON_INTERACTIVE ... skip installer prompts
CODEX_INSTALL_DIR ... ~/.local/bin on macOS/Linux
curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh
```

检查当前版本和路径：

```bash
which codex
codex --version
```

关键输出：

```text
/home/discover/.local/bin/codex
codex-cli 0.142.4
```

只下载官方安装脚本，不执行：

```bash
curl -v -m 20 -fsSL https://chatgpt.com/codex/install.sh -o /tmp/codex-install.sh
```

关键输出：

```text
* Uses proxy env variable https_proxy == 'http://127.0.0.1:7897'
* Establish HTTP proxy tunnel to chatgpt.com:443
< HTTP/2 302
< location: https://github.com/openai/codex/releases/latest/download/install.sh
* Establish HTTP proxy tunnel to github.com:443
< location: https://github.com/openai/codex/releases/download/rust-v0.142.5/install.sh
* Establish HTTP proxy tunnel to release-assets.githubusercontent.com:443
< HTTP/2 200
< content-length: 21674
```

检查下载脚本开头：

```bash
sed -n '1,220p' /tmp/codex-install.sh
```

关键输出：

```text
BIN_DIR="${CODEX_INSTALL_DIR:-$HOME/.local/bin}"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
STANDALONE_ROOT="$CODEX_HOME_DIR/packages/standalone"
```

确认 CLI 自更新入口：

```bash
codex update --help
```

关键输出：

```text
Update Codex to the latest version
Usage: codex update [OPTIONS]
```

执行更新：

```bash
codex update
```

关键输出：

```text
Updating Codex via `sh -c 'curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh'`...
==> Updating Codex CLI from 0.142.4 to 0.142.5
==> Detected platform: Linux (x64)
==> Resolved version: 0.142.5
==> Installing standalone package to /home/discover/.codex/packages/standalone/releases/0.142.5-x86_64-unknown-linux-musl
Codex CLI 0.142.5 installed successfully.
🎉 Update ran successfully! Please restart Codex.
```

更新后验证：

```bash
codex --version
readlink -f /home/discover/.local/bin/codex
```

关键输出：

```text
codex-cli 0.142.5
/home/discover/.codex/packages/standalone/releases/0.142.5-x86_64-unknown-linux-musl/bin/codex
```

### 结论

- 本机当前环境中 `curl` 可以通过 `127.0.0.1:7897` 代理下载 `https://chatgpt.com/codex/install.sh`，并成功跟随到 GitHub release asset。
- 失败原因不在本次 Codex 命令环境的 `curl` 代理配置；更可能是用户执行该命令的具体 shell / `sudo` / IDE / 容器环境没有继承 `http_proxy`、`https_proxy`、`all_proxy`。
- Codex CLI 已从 `0.142.4` 更新到 `0.142.5`。
- 安装器提示需要重启 Codex，让当前运行中的 Codex 进程完全使用新版本。

### 建议

如果需要在其他 shell 中复现官方管道命令，先显式导出代理：

```bash
export http_proxy=http://127.0.0.1:7897
export https_proxy=http://127.0.0.1:7897
export all_proxy=socks5://127.0.0.1:7897
curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh
```

或者直接用当前 CLI 的自更新入口：

```bash
codex update
```
