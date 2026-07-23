# curl / VPN 代理检查

## 2026-07-01 11:34 CST — 当前 shell 中 curl 是否用上代理（agent: Codex）

### 目的

确认当前 VPN/代理环境下，`curl` 是否没有用上网络代理，还是代理已生效但其他上下文没有继承。

### 命令与关键输出

初始备注：Codex 默认沙箱内命令启动失败，所有只读检查改为沙箱外执行。

```bash
ls docs
```

关键输出：

```text
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

检查当前进程代理环境变量：

```bash
env | sort | rg -i '(^|_)proxy=|all_proxy|http_proxy|https_proxy|no_proxy|curl|vpn'
```

关键输出：

```text
all_proxy=socks5://127.0.0.1:7897
http_proxy=http://127.0.0.1:7897
https_proxy=http://127.0.0.1:7897
```

检查 curl 版本与代理能力：

```bash
curl --version
```

关键输出：

```text
curl 8.5.0 (x86_64-pc-linux-gnu) libcurl/8.5.0 OpenSSL/3.0.13
Features: ... HTTPS-proxy ... AsynchDNS ...
```

检查本机代理端口监听：

```bash
ss -lntp
```

关键输出：

```text
LISTEN 0 128  127.0.0.1:33331 0.0.0.0:* users:(("clash-verge",pid=2553,fd=24))
LISTEN 0 4096 127.0.0.1:7897  0.0.0.0:*
```

检查 GNOME 系统代理：

```bash
gsettings get org.gnome.system.proxy mode
gsettings list-recursively org.gnome.system.proxy
```

关键输出：

```text
'manual'
org.gnome.system.proxy autoconfig-url 'http://127.0.0.1:33331/commands/pac'
org.gnome.system.proxy.http host '127.0.0.1'
org.gnome.system.proxy.http port 7897
org.gnome.system.proxy.https host '127.0.0.1'
org.gnome.system.proxy.https port 7897
org.gnome.system.proxy.socks host '127.0.0.1'
org.gnome.system.proxy.socks port 7897
```

检查是否有用户级 curl / git proxy 覆盖：

```bash
test -f ~/.curlrc && sed -n '1,120p' ~/.curlrc
git config --global --get-regexp 'http.*proxy|https.*proxy'
```

关键输出：两条命令都无输出，退出码为 `1`。当前没有发现 `~/.curlrc` 或全局 git proxy 覆盖。

用当前环境变量跑 curl：

```bash
curl -v -m 15 https://www.google.com/generate_204 -o /tmp/curl-env-proxy-google.out
```

关键输出：

```text
* Uses proxy env variable https_proxy == 'http://127.0.0.1:7897'
*   Trying 127.0.0.1:7897...
* Connected to 127.0.0.1 (127.0.0.1) port 7897
* Establish HTTP proxy tunnel to www.google.com:443
< HTTP/1.1 200 Connection established
< HTTP/2 204
```

禁用代理做对照：

```bash
curl -v --noproxy '*' -m 15 https://www.google.com/generate_204 -o /tmp/curl-direct-google.out
```

关键输出：

```text
* Host www.google.com:443 was resolved.
*   Trying 69.171.235.22:443...
* Immediate connect fail for 2001::1: Network is unreachable
* Connection timed out after 15002 milliseconds
curl: (28) Connection timed out after 15002 milliseconds
```

用当前环境变量访问 GitHub API：

```bash
curl -v -m 15 https://api.github.com -o /tmp/curl-env-proxy-github.out
```

关键输出：

```text
* Uses proxy env variable https_proxy == 'http://127.0.0.1:7897'
* Establish HTTP proxy tunnel to api.github.com:443
< HTTP/1.1 200 Connection established
< HTTP/2 200
```

显式用 SOCKS5 代理访问 Google：

```bash
curl -v --socks5-hostname 127.0.0.1:7897 -m 15 https://www.google.com/generate_204 -o /tmp/curl-explicit-socks-google.out
```

关键输出：

```text
* SOCKS5 connect to www.google.com:443 (remotely resolved)
* SOCKS5 request granted.
< HTTP/2 204
```

### 结论

当前登录 shell / Codex 命令环境里，`curl` 已经用上代理，不是“curl 没吃到代理变量”：

- `http_proxy`、`https_proxy`、`all_proxy` 都已指向 `127.0.0.1:7897`。
- `curl -v` 明确显示使用 `https_proxy == 'http://127.0.0.1:7897'`。
- HTTP CONNECT 代理访问 Google 返回 `HTTP/2 204`，访问 GitHub API 返回 `HTTP/2 200`。
- 显式 SOCKS5 代理同样可用。
- 禁用代理后直连 Google 15 秒超时，说明当前外网路径依赖本机代理。

### 影响

如果用户在其他终端、`sudo`、容器、IDE、systemd 服务或某个脚本里看到 `curl` 失败，优先检查那个具体执行上下文是否继承了这些环境变量：

```bash
env | grep -i proxy
curl -v https://www.google.com/generate_204
```

临时强制走代理可用：

```bash
curl -x http://127.0.0.1:7897 https://www.google.com/generate_204
curl --socks5-hostname 127.0.0.1:7897 https://www.google.com/generate_204
```

如果是 `sudo curl`，默认可能清掉代理环境，需要显式保留环境或在 root 环境中设置代理。机器人本地地址、局域网地址和 DDS/ROS2 链路不应走公网代理。
