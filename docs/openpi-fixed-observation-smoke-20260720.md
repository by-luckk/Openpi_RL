# OpenPI 固定首帧无控制 smoke test（2026-07-20）

## 结论

- 本地 OpenPI 服务使用用户指定的 wrist-only checkpoint：
  `checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/vio_pi05_535_clean_wrist_only_80k_260717/20000`。
- 固定同一份双腕 RGB、`state[16]` 和双臂 TCP pose，完成 3 次 warmup + 100 次实测；
  本地策略推理频率为 **5.4788 Hz**，客户端端到端延迟均值 **182.125 ms**，
  服务端推理耗时均值 **179.131 ms**。
- 每次推理返回 `(50, 32)`。`5.4788 * 50 = 273.94 rows/s` 是模型生成的
  horizon 预测行数吞吐，**不是控制指令发送频率**。当前控制路径 `chunk_steps=1`，
  每轮只消费第 1 行。
- 按本轮预测输出和 9 mm 插值规则模拟，100 轮会产生 184 条 ARM 命令和 200 条
  夹爪命令，平均每轮 3.84 条。完全不加 1 s 周期时，受推理速度限制的需求约
  **21.04 commands/s**；再施加相邻命令至少 4 ms 的限制后约 **19.85 commands/s**。
  按当前真机循环 `period_s=1`，预期约 **3.84 commands/s**，实际阻塞 RPC 只会更低。
- smoke 脚本不导入 P7 SDK、不创建机器人连接、不申请控制权，实际控制指令发送数为 **0**。

## 频率为什么会看起来超过 250 Hz

这里有三种不同的频率，不能混为一谈：

| 指标 | 本轮数值 | 含义 |
|---|---:|---|
| policy inference | 5.4788 Hz | 每秒完成的 OpenPI 请求数 |
| predicted rows | 273.94 rows/s | 每次返回 50 行 horizon 后的数学乘积，不会自动全部下发 |
| client simulated commands | 3.84 commands/s | 现有 1 s policy 周期、`chunk_steps=1` 下 ARM+EEF 调用总数 |
| X5 servo refresh | 250 Hz/stream | X5 内部 `4 ms` servo/FSM 刷新，不是 PC 端 OpenPI 或 gRPC 请求频率 |

此前 400 s 真机日志中的 `queue_dropped` 来自 X5 内部 servo/FSM 到 `arm_control`
的 4 ms 命令队列。X5 在接受一个高层目标后会在板内持续维持 ARM/EEF CSP 流；
所以即使 PC 每秒只做一次推理和少量阻塞 gRPC 调用，板内仍可看到 250 Hz 刷新和
队列丢弃。特别是 ARM 与 EEF 同时运行时，两条板内流的调度/消费能力不足仍可能
积压。证据和 8 次失败的逐次日志见
[`openpi-400s-interruption-analysis-20260720.md`](openpi-400s-interruption-analysis-20260720.md)。

## 固定输入

测试输入文件：

```text
/tmp/openpi_fixed_observation_smoke_20260720_1643.npz
size: 1130595 bytes
file sha256: 9a35dd83866d4e094795c08be646d6758eb91a76d49b3e61c8835ed8da2606d6
```

载入内存后，测试前后 observation hash 均为：

```text
df491d2e27d3e3685d38d8ca71c6fde8a1730501718bf47a94687d0b52e62b8b
```

输入内容：

```text
left_wrist_0_rgb:  (480, 640, 3) uint8
right_wrist_0_rgb: (480, 640, 3) uint8
state:             (16,) float32
state values:      all zero (min=0, max=0)

left TCP xyz+xyzw:
[0.0831899965, -0.1158003640, 0.6415565825,
 -0.1213537513, -0.0183576204, 0.0622352284, 0.9904862650]

right TCP xyz+xyzw:
[-0.0007004470, -0.0483688704, 0.6556112506,
  0.0301009499, -0.0144612439, 0.0216083585, 0.9992086289]
```

两张图和全零 state 占位只在启动时载入一次，之后 103 次请求始终复用同一内存对象；
测试前后 hash 相同。TCP pose 也固定不变，用于把 policy 的 relpose 输出换算为模拟
的绝对 TCP 目标。按当前 wrist-only PI05 policy 契约，模型请求接口接收双腕图像和
`state[16]`，但配置为 `discrete_state_input=False`，模型前向不消费 continuous state
数值；因此实际模型条件输入是固定双腕图像和 prompt。TCP pose 是执行侧参考，不作为
额外模型张量输入。也就是说，本测试冻结了用户要求的图片和 Pose，但两者分别作用于
策略推理与模拟执行后处理。

## 服务与测试命令

2026-07-20 16:51 CST 复核服务进程：

```bash
uv run scripts/serve_policy.py --port 8000 policy:checkpoint \
  --policy.config pi05_vio_plant_collection_535_clean_wrist_only \
  --policy.dir checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/vio_pi05_535_clean_wrist_only_80k_260717/20000
```

smoke test：

```bash
.venv/bin/python examples/airbot/openpi_fixed_observation_smoke.py \
  --observation-npz /tmp/openpi_fixed_observation_smoke_20260720_1643.npz \
  --left-tcp '0.0831899965,-0.1158003640,0.6415565825,-0.1213537513,-0.0183576204,0.0622352284,0.9904862650' \
  --right-tcp=-0.0007004470,-0.0483688704,0.6556112506,0.0301009499,-0.0144612439,0.0216083585,0.9992086289 \
  --policy-host 127.0.0.1 --policy-port 8000 \
  --warmup-iterations 3 --iterations 100 --chunk-steps 1 \
  --max-step-translation-m 0.009 --min-command-interval-s 0.004 \
  --output-json /tmp/openpi_fixed_observation_smoke_20260720_1643_result.json
```

结果文件：

```text
/tmp/openpi_fixed_observation_smoke_20260720_1643_result.json
logs/openpi_smoke/fixed_observation_20260720_1643.log
```

关键输出：

```text
action shape:                         (50, 32)
benchmark wall time:                  18.2523 s
inference frequency:                   5.4788 Hz
client latency mean / p50 / p95:     182.125 / 182.033 / 187.123 ms
server inference mean / p50 / p95:   179.131 / 178.944 / 183.892 ms
predicted rows, not commands:         273.9379 rows/s
unpaced simulated command demand:      21.0384 commands/s
4 ms limited simulated upper bound:    19.8465 commands/s
1 s current-loop expected rate:          3.8400 commands/s
robot SDK imported:                  false
robot connection opened:             false
control commands sent:               0
```

## 实现与验证

实现位于
[`examples/airbot/openpi_fixed_observation_smoke.py`](../examples/airbot/openpi_fixed_observation_smoke.py)。
脚本使用单个持久 WebSocket 连接，避免把反复建连开销误算为模型推理；模拟下发只计数
并推进虚拟时间线，不调用任何硬件 API。

2026-07-20 16:51 CST 静态检查：

```bash
.venv/bin/ruff check --select E,F examples/airbot/openpi_fixed_observation_smoke.py
# All checks passed!
```

同一时刻复核占位 state：

```bash
.venv/bin/python -c "import numpy as np; d=np.load('/tmp/openpi_fixed_observation_smoke_20260720_1643.npz'); s=d['state']; print(s.dtype, s.shape, s.min(), s.max(), np.all(s == 0))"
# float32 (16,) 0.0 0.0 True
```

16:55 CST 另用 `pgrep -af 'examples/airbot/p7_joint6_triangle_wave.py'` 排查与本测试
无关的真机运动进程，返回码为 `1` 且无输出，确认该进程已不在运行。本检查未连接
机器人，也未停止或修改任何进程。

## 2026-07-20 17:29 CST — “250 Hz”是客户端总限流还是 X5 内部刷新

### 检查目的

澄清“左臂、右臂、左右夹爪四路控制合计不超过 250 Hz”是否等同于当前代码和
X5 日志里的 `250 Hz`。

### 代码证据

检查命令：

```bash
nl -ba examples/airbot/openpi_p7_persistent_loop.py | sed -n '54,70p;141,146p'
```

关键输出：`MotionCommandRateLimiter` 的注释为
`Keep aggregate motion-command start times below the configured rate.`；
`--min-motion-command-interval-s` 的帮助为
`Minimum aggregate interval between motion gRPC command starts`，默认值为
`0.004` 秒。这个 limiter 实例在主循环中只创建一个，并传给 ARM 和 EEF 的
`move_end_pose` / `move_eef` 调用。

用四个 fake 命令模拟 `left_arm`、`right_arm`、`left_gripper`、`right_gripper`
并发调用同一个 limiter：

```text
labels= ['left_arm', 'right_arm', 'left_gripper', 'right_gripper']
intervals_ms= [4.059, 4.056, 4.126]
all_intervals_ge_4ms= True
```

结论：**对当前这个 Python 客户端进程而言，4 ms/250 Hz 限制是四类运动 RPC
起发时间的 aggregate 限流**。四路若都由该进程调用，应把它们合计计算；不是
每一路各自再给 250 Hz。理论上限是 250 次“命令调用起点”/秒，实际还会被 RPC
耗时、线程调度和阻塞模式进一步降低。

### X5 日志中的另一个 250 Hz

检查命令：

```bash
rg -n -C 3 -i "250 Hz|4 ms|queue_dropped|ARM.*EEF|EEF.*ARM" \
  docs/openpi-400s-interruption-analysis-20260720.md \
  docs/openpi-fixed-observation-smoke-20260720.md
```

关键输出：X5 配置/日志为 `arm_control_command_publish_period_ms=4`、
`update_period_us=4000`，并分别记录 ARM 与 EEF 的 `queue_drop`；文档还记录
左右侧各自的 `arm_control` 周期超时。这表示 X5 在板内持续维护 ARM/EEF CSP
servo/FSM 流。它不是 PC 端四路 gRPC 调用共享的一个已公开“总 250 Hz 配额”，
也不能据此推出四路可以安全地各跑 250 Hz。ARM+EEF 并发时仍可能因为板内实时
线程/队列调度不足出现丢弃。

### 对控制策略的影响

- 若问题是**本仓库客户端发命令**：保留单个 aggregate limiter，四路合计按
  `>=4 ms` 排队；若使用多个独立进程/客户端，当前 limiter 不会跨进程汇总。
- 若问题是**X5 板内 250 Hz**：把它视为每个 ARM/EEF servo 流的刷新周期和实时
  处理约束，而不是可由 PC 端简单分配的四路总预算。是否能稳定同时运行双臂和
  双夹爪，需要以 X5 的 queue drop/线程超时实测为准；现有 400 秒日志已经出现
  ARM/EEF queue drop。
