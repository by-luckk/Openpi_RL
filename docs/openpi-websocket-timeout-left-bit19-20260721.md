# 2026-07-21 WebSocket timeout 与左 joint7 bit 19

## 2026-07-21 00:27 CST - 事故只读复盘（agent: Codex）

### 现象与当前安全状态

00:15:06 启动的 OpenPI attempt 在完成 30 次动作后，第 31 次停在 `policy` 请求，随后报
WebSocket `keepalive ping timeout`。清理流程成功把双臂 controller 切到 idle 并释放控制权，
但左臂进入持续 `UNKNOWN_ERROR`；快速恢复的 `clear_error()` 连续返回 `True` 仍无效。

00:22-00:27 只读复核：

- inference supervisor/persistent loop 已退出，没有继续下发动作；仅 policy server PID `119852`
  保持监听 `0.0.0.0:8000`；空 lock 文件仍在，但没有对应控制进程。
- 左臂 `UNKNOWN_ERROR/idle/valid`，左 EEF idle；右臂 `IDLE/idle/valid`，右 EEF idle。
- 双臂关节速度接近 0。X5 上 left/right `arm_app` 和相机 `robot_app` 仍在运行。
- 两路 CAN 均为 `ERROR-ACTIVE`，实时 tx/rx error counter 为 0，位速率为 `1M/5M`。

### 时间线与证据

1. 本轮 30 次成功 policy latency 明显恶化：iteration 1 为 `351 ms`，10 为 `884 ms`，
   18-30 多数为 `1460-1845 ms`，iteration 30 为 `1844.7 ms`。iteration 31 没有响应记录。
2. WebSocket client 在 `00:16:03.929` 发 ping，`00:16:23.929` 等待 pong 超时，
   `00:16:33.930` 关闭连接。client/server 都在 `127.0.0.1`，不是机器人网络链路。
3. server handler 在 asyncio event loop 中同步执行 `self._policy.infer(obs)`；推理卡住时 event
   loop 无法及时处理 WebSocket control frame，因此 keepalive timeout 是“推理/event-loop
   超过 20 秒无响应”的结果，不是根因本身。
4. X5 左臂从 `00:16:24.102`、右臂从 `00:16:25.091` 开始密集出现 servo `3-6 ms`
   execution time，部分超过 `4 ms` period。它们和 policy 卡顿处于同一时间窗，但本轮没有
   X5 CPU 采样，不能证明由 `robot_app` 或某个单一负载直接导致。
5. client 在 `00:16:34.514` 请求左臂退出 servo；左 `arm_app` 于 `00:16:34.578` 首次记录
   `Motor 7 error: Unknown motor error bit 19`，随后约每秒持续打印。右臂正常回到 IDLE。
6. 每次 `clear_error()` 的板端日志都是
   `FSM clear_error accepted, arm_control clear_error RPC placeholder triggered`。返回 `True` 只表示
   RPC 被接受，不表示电机错误位已清除。

仓库既有真机记录已把同类错误读成 joint7 `error_id=524288=1<<19`。此前它曾在右臂、且在
arm-only/无 command queue drop 的运行中复现；软件重启和 SDK clear 均不能清除，必须给对应
机械臂驱动断电复位。因此本次不能把 bit 19 单独归因于 `robot_app`。但本次 `robot_app` 并发时
双臂密集出现 4 ms deadline miss，是否放大实时抖动仍需受控 A/B。

### Policy 服务复测

第一次 policy-only smoke 误用了只含双腕图像、不含 `state` 的 preview NPZ，在本地校验阶段
以 `missing keys: ['state']` 退出，没有触达 server。随后改用完整
`/tmp/openpi_cam_daemon_wrist/latest.npz`，只运行一轮模拟请求：

```text
iteration=1 infer_ms=367.206 action_shape=[50,32]
server_infer_ms=361.743
robot_sdk_imported=false
robot_connection_opened=false
control_commands_sent=0
```

这证明 policy server 已从瞬态卡顿恢复；没有 NVIDIA Xid、OOM 或 killed-process 内核日志。
当前 GPU 进程仍只有 PID `119852`，显存约 `12202 MiB`，复核时 GPU 31%、50C。

### 结论与处理边界

本次是两个需要分别处理的问题：

1. policy inference 瞬态卡住超过 20 秒，阻塞 server event loop，触发 WebSocket keepalive；
2. 左 joint7 bit 19 锁存为硬件/驱动错误，SDK quick clear 是 placeholder，不能恢复。

不得在左臂仍为 `UNKNOWN_ERROR` 时重跑。现场恢复需要先给左臂驱动断电复位，再做 no-motion
状态和 joint error 检查；这不是本次只读诊断的授权范围，本轮没有执行。

代码层后续应增加独立于 keepalive 的短 inference deadline：超时立即让双臂 idle/release 并
丢弃请求；server 侧把同步 `policy.infer` 移出 asyncio event loop，使 ping/pong 不被推理阻塞。
但仅延长或关闭 keepalive 会让机械臂在无新 policy 响应时更久地停留在 servo，不是安全修复。
板端则需在断电清零后，对 `robot_app` on/off 做低速、无夹爪的 servo deadline/bit19 A/B；
在拿到证据前不把 `robot_app` 写成确定根因。

### 复现检查命令

```bash
pgrep -af 'openpi_p7_(unlimited_recovery|persistent_loop)|serve_policy.py'
rg -n 'keepalive ping|UNKNOWN_ERROR|quick_recovery' \
  logs/openpi_p7_recovery_20260721_001506.log logs/app.log
jq -r '[.iteration, .policy_infer_ms] | @tsv' \
  /tmp/openpi_p7_persistent_loop/summary_20260721_001522.jsonl

ssh root@192.168.25.1 \
  'grep -aniE "Motor 7|execution time|clear_error" /tmp/openpi_arm_app_left.log | tail; \
   grep -aniE "execution time" /tmp/openpi_arm_app_right.log | tail'

.venv-p7-sdk/bin/python - <<'PY'
from arm_p7_sdk import AirbotClient
for side, port in (("left", 50071), ("right", 50072)):
    client = AirbotClient(host="192.168.25.1", port=port, backend="grpc")
    print(side, client.get_service_state())
    print(side, client.get_eef_mode())
    print(side, client.get_arm_joint_state())
PY

timeout 20 .venv/bin/python examples/airbot/openpi_fixed_observation_smoke.py \
  --observation-npz /tmp/openpi_cam_daemon_wrist/latest.npz \
  --left-tcp=-0.0038,-0.1608,0.5572,0,0,0,1 \
  --right-tcp=-0.0908,-0.0071,0.6019,0,0,0,1 \
  --iterations 1 --warmup-iterations 0 --no-enable-gripper --report-every 1 \
  --output-json /tmp/openpi_policy_post_timeout_smoke.json
```

本轮没有修改代码、没有清错、没有重启应用、没有获取控制权或发送机器人命令。

### 2026-07-21 00:30 CST - 当前运行态补充

最终只读复核发现现场已被其他操作改变：X5 上已没有 `arm_app`、`robot_app` 或
`arm_dual_app` 进程，`50071/50072` 均未监听；此前 `/tmp/openpi_arm_app_left.log` 和
`right.log` 也已消失。本轮没有执行这些停止操作。

因此当前不会继续下发动作，但不能因进程消失就认定 joint7 bit 19 已清零。必须在对应臂驱动
完成断电复位、重新启动 `arm_app` 后，再用 SDK 做 no-motion service state 和 joint error
检查；端口未恢复前无法读取新的状态。
