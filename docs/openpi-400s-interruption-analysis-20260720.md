# 2026-07-20 OpenPI 400 秒运行中断分析

## 结论

- 日期：2026-07-20 16:15-16:23 CST；检查人：Codex。
- 整个任务最终结束不是 OpenPI 推理崩溃，而是外层命令配置的 `timeout 400s` 在
  `16:22:25` 准时向 supervisor 发送 TERM；启动时间为 `16:15:45`。
- 命令最终显示退出码 `137`，原因是 `--kill-after=20s` 在 supervisor 的 X5 重启清理尚未完成时发送了 SIGKILL；不是模型、相机或 policy server 退出。
- 400 秒内有 8 次子推理进程中断。直接表现均为某一侧
  `move_end_pose ok=False`，随后该侧 FSM 为 `UNKNOWN_ERROR`。这 8 次不是 10mm 回读限制触发，退出码均为普通错误 `rc=1`，supervisor 随后重启并继续。
- X5 原始日志显示，8 次失败前均出现 X5 内部 ARM/EEF 命令队列丢弃，随后在
  `90-913ms` 内进入 `UNKNOWN_ERROR`。这是当前最强的共同原因证据。
- 这些 `queue_dropped` 是 X5 内部 4ms/250Hz servo/FSM 到 `arm_control` 的命令队列，不是本机 OpenPI 每秒一次 policy 请求，也不是本机 gRPC 运动调用超过 250Hz。
- 不能仅凭现有日志进一步断言队列拥塞一定由 CPU 饱和造成：本次没有同期 X5 CPU 采样文件。CAN 重启日志均为 `ERROR-ACTIVE`，绝大多数 tx/rx error counter 为 0，没有 bus-off 证据。

## 主日志时间线

主日志：

`/home/discover/Desktop/recording/openpi_wrist_400s_retry_20260720_1614/openpi_p7_recovery_20260720_161545.log`

关键命令参数：

```bash
timeout --foreground --signal=TERM --kill-after=20s 400s \
  env LOCAL_LOG_DIR=/home/discover/Desktop/recording/openpi_wrist_400s_retry_20260720_1614 \
  scripts/cmds/openpi_p7_unlimited_recovery.sh \
  --duration-s 400 --period-s 1 \
  --max-step-translation-m 0.009 \
  --max-measured-translation-m 0 \
  --min-motion-command-interval-s 0.004 \
  --wrist-only --no-advantage --execute --allow-robot-motion
```

8 次动作失败：

| 尝试 | 时间 | 侧 | 主日志表现 |
|---|---|---|---|
| 1 | 16:15:54 | left | `move_end_pose=False` -> left `UNKNOWN_ERROR` |
| 2 | 16:16:26 | left | 同上 |
| 3 | 16:17:00 | right | 同上 |
| 4 | 16:18:08 | right | 同上 |
| 5 | 16:19:49 | right | 同上 |
| 6 | 16:20:28 | right | 同上 |
| 7 | 16:20:59 | left | 同上 |
| 8 | 16:21:36 | right | 同上 |

每次 `clear_error()` RPC 都返回 True，但 X5 日志明确写的是
`FSM clear_error accepted, arm_control clear_error RPC placeholder triggered`，状态没有离开
`UNKNOWN_ERROR`，所以快速清错失败并升级为 full arm_app restart。

## X5 底层共同证据

检查命令示例：

```bash
ssh root@192.168.25.1 \
  "grep -nE 'RateCheck|UNKNOWN_ERROR|Timeout waiting for mode switch|ARM_GET_DATA timeout' \
  /userdata/arm_app_logs/20260720_1612/left_arm.log"
```

8 次失败前最后一组队列统计：

| X5 日志周期/侧 | ARM queue drop | EEF queue drop | 到 UNKNOWN_ERROR |
|---|---:|---:|---:|
| `1612/left` | 11.3% | 26.4% | 638ms |
| `161601/left` | 13.1% | 30.5% | 543ms |
| `161635/right` | 7.0% | 18.4% | 90ms |
| `161707/right` | 10.1% | 20.4% | 913ms |
| `161907/right` | 13.5% | 28.3% | 362ms |
| `162003/right` | 8.4% | 23.7% | 300ms |
| `162036/left` | 6.4% | 14.7% | 321ms |
| `162108/right` | 30.2% | 61.0% | 160ms |

第一次失败的完整顺序尤其清楚：

1. X5 配置显示 `arm_control_command_publish_period_ms=4`、servo `update_period_us=4000`。
2. `16:15:52.301`：ARM `queue_drop=11.3%`，EEF `queue_drop=26.4%`。
3. servo engine 随即 pause。
4. `16:15:52.939`：FSM 灯更新为 `UNKNOWN_ERROR`。
5. 模式切换第一次等待超时，后续 `ARM_GET_DATA` 三次重试超时。
6. PC SDK 的 servo pose RPC 得到未接受结果，`move_end_pose()` 返回 False。

SDK 源码证据：servo controller 路径调用 `CallServoPoseCommand` 后直接
`return bool(rep.accepted)`；若发生 gRPC exception 会额外打印 `gRPC error`。8 个
`move_end_pose=False` 点没有对应的网络 RPC exception，说明 X5 返回了未接受，而不是 WebSocket、相机或 TCP 网络调用抛错。

## 最终 400 秒停止为何是 137

`16:22:25` 主日志明确记录：

```text
stop requested; terminating the active inference process group
```

这正好是启动后 400 秒。停止时 X5 仍显示 `SERVO_CONTROL/csp`，旧客户端 lease 尚未释放；清理客户端重新获取控制权时收到：

```text
StatusCode.RESOURCE_EXHAUSTED
controller already held
```

supervisor 因此启动 full X5 restart。重启期间 50071 暂时不可连接，随后服务处于初始化中的 `ERROR/ERROR`；外层 `kill-after=20s` 在 ready 探针完成前终止 supervisor，所以 shell 报 137。独立后检查已确认左右臂最终均恢复：

```text
ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
```

## 影响与下一步判断

- 取消 10mm 回读硬停止解决了“回读阈值阻断恢复”，但没有解决 X5 内部命令队列丢弃。
- 本机运动 gRPC 起发限制 4ms 不是这次失败的瓶颈；X5 自身同时维持 ARM 和 EEF CSP 4ms 流，EEF queue drop 始终高于 ARM，是优先排查方向。
- 下一轮定位应同步采集 X5 CPU/load，并做 A/B：关闭 `--enable-gripper`，只让 ARM 进入 servo；若 queue drop 和 UNKNOWN_ERROR 显著消失，可确认 EEF CSP 并发流是主要放大因素。
- 若保留夹爪，应从 X5/arm_app 配置或厂商实现层解决队列容量、线程调度或 ARM+EEF 发送节拍；单纯降低 OpenPI policy 频率不能消除内部 250Hz 队列问题。
