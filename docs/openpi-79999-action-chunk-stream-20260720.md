# 79999 checkpoint 的 10 ms action chunk streaming（2026-07-20）

## 结论

- 本地 policy 服务已从 wrist-only `20000` 切换为用户指定的 wrist-only `79999`，
  当前继续监听 `127.0.0.1:8000`。
- `openpi_p7_persistent_loop.py` 新增显式 `--stream-action-chunk` 和
  `--action-step-interval-s`：每个选中 action 行对每侧最多发一个非阻塞 servo 目标，
  相邻 action 起点保持最小间隔；`--min-motion-command-interval-s 0` 可关闭原 4 ms
  aggregate RPC limiter。默认参数保持旧行为。
- 用户指定“每轮 2-4 个”没有唯一固定数量。本轮按最保守的 `chunk_steps=2` 做一次
  单轮真机 pilot，不启动长循环。
- pilot 的 action 索引为 `[0,1]`，第二行实际起点间隔 `12.027 ms`；左右 ARM 和
  左右 EEF 共 8 次 RPC 均返回 `True`，双臂最终回到 `IDLE/idle/valid`。
- 但延迟回读显示：相对启动位置，左臂 TCP 实际变化约 `24.98 mm`，右臂约
  `3.40 mm`。左臂实际变化明显大于两行命令中单条最大 `3.526 mm` 的目标，故没有
  继续长时间推理。
- X5 同期日志没有 `UNKNOWN_ERROR`、命令拒绝或 queue drop，只记录 ARM/EEF CSP
  模式切换和内部 250 Hz state stream。当前最可信判断是：P7 非阻塞 servo 只收到
  两帧、随后出现长于 10 ms 的空窗并很快切 idle，这种短 burst 不能视为稳定的
  100 Hz 轨迹流；在解释清楚左臂额外运动前不应直接扩大到 3/4 行或长时间循环。

## 代码改动

文件：
[`examples/airbot/openpi_p7_persistent_loop.py`](../examples/airbot/openpi_p7_persistent_loop.py)

新增参数：

```text
--stream-action-chunk
--action-step-interval-s 0.01
--min-motion-command-interval-s 0
--no-servo-blocking
--no-gripper-blocking
```

stream 模式语义：

1. 每次 policy 返回 `(50,32)` 后，由 `--chunk-start-index` / `--chunk-steps` 选择行。
2. 每行仍相对本轮 observation TCP pose 解码，不把 chunk 行串联成增量。
3. 每侧从“上一条已命令 pose”到当前行目标取一个 waypoint；本轮
   `--max-step-translation-m=0.009`，所以每条手臂命令小于等于 9 mm。
4. ARM 使用 `blocking=False`；关闭 RPC limiter 时左右线程不再被 limiter 锁串行化。
5. 行与行的节拍是 start-to-start 最小 10 ms；如果一行内 SDK RPC 已超过 10 ms，
   下一行立即开始并记录实际间隔，不会追赶或并发调用同一个 client。
6. chunk 内不做 TCP 回读，chunk 结束后统一回读，避免回读 RPC 破坏 10 ms 节拍。

验证：

```bash
.venv/bin/ruff check --select E,F examples/airbot/openpi_p7_persistent_loop.py
.venv-p7-sdk/bin/python -m py_compile examples/airbot/openpi_p7_persistent_loop.py
.venv-p7-sdk/bin/python examples/airbot/openpi_p7_persistent_loop.py --help
```

结果均通过。纯内存 fake client 验证：20 mm 目标经 9 mm 上限均分后，每侧只发送
一条 `6.667 mm` 命令；线程屏障证明关闭 limiter 后左右调用可同时进入。前两版测试
断言曾失败，原因分别是错误假设首 waypoint 必定等于 9 mm、错误使用可复用的线程 ID
判断并发；改为验证 `<=9 mm` 和线程屏障后通过，并非执行函数错误。

## 79999 服务与无控制推理

17:16 CST 停止无客户端连接的旧 20k 服务，然后启动：

```bash
env \
  TMPDIR=/home/discover/Desktop/Openpi_RL/.tmp/serve_policy_79999 \
  XDG_CACHE_HOME=/home/discover/Desktop/Openpi_RL/.tmp/serve_policy_79999/xdg_cache \
  JAX_COMPILATION_CACHE_DIR=/home/discover/Desktop/Openpi_RL/.tmp/serve_policy_79999/jax_cache \
  uv run scripts/serve_policy.py --port 8000 policy:checkpoint \
    --policy.config pi05_vio_plant_collection_535_clean_wrist_only \
    --policy.dir checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/vio_pi05_535_clean_wrist_only_80k_260717/79999
```

关键日志：

```text
Finished restoring checkpoint in 3.14 seconds
Loaded norm stats from .../79999/assets/vio_plant_collection_30hz_relpose_535_clean
server listening on 0.0.0.0:8000
GPU memory: 12184 MiB
```

固定双腕 observation 做 1 次 warmup + 10 次推理，`chunk_steps=4` 仅模拟、不连接
机器人：

```text
action_shape=(50,32)
wall=1.59244 s
inference=6.27967 Hz
client mean=158.116 ms
server mean=155.098 ms
robot SDK imported=false
robot connection opened=false
control commands sent=0
```

结果文件：`/tmp/openpi_fixed_observation_smoke_79999_20260720.json`；服务日志：
`logs/openpi_policy/serve_79999_20260720_1715.log`。

## 真机前置检查

17:18 CST：

- `192.168.25.1:22/50071/50072` 均可达。
- 左右服务均为 `ServiceState(True, IDLE, idle, valid=True)`。
- 左关节约
  `[0.0170,0.6316,-0.0013,-0.8995,0.0040,0.0038,-1.2374] rad`；右关节约
  `[0.0067,0.6436,-0.0008,-0.9234,0.0022,-0.0006,-1.2484] rad`，接近准备位。
- wrist-only 相机守护 PID `18180` 正在写
  `/tmp/openpi_cam_daemon_wrist/latest.{npz,json}`，检查时文件年龄小于 1 秒。
- NPZ 只有左右腕 RGB 和 `state`：两图均为 `(480,640,3) uint8`、非空；state 为
  `(16,) float32` 全零占位。
- 旧路径 `/tmp/openpi_cam_daemon/latest.*` 不存在；这是首次预检的路径错误，不是
  相机断流，改用实际 daemon 参数中的 `_wrist` 路径后通过。

## 单轮真机 pilot

命令：

```bash
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --iterations 1 --period-s 0 \
  --controller servo --no-servo-blocking --stream-action-chunk \
  --action-step-interval-s 0.01 --chunk-start-index 0 --chunk-steps 2 \
  --min-motion-command-interval-s 0 \
  --max-step-translation-m 0.009 --max-step-rotation-rad 3.141592653589793 \
  --max-measured-translation-m 0 --max-envelope-m 0 \
  --arm-speed-rad-s 0.55 --enable-gripper --no-gripper-blocking \
  --capture-mode latest-file \
  --latest-obs-npz /tmp/openpi_cam_daemon_wrist/latest.npz \
  --latest-obs-meta /tmp/openpi_cam_daemon_wrist/latest.json \
  --wrist-only --no-advantage --work-dir logs/openpi_p7_stream_79999 \
  --execute --allow-robot-motion
```

结果：

```text
policy infer_ms: 176.608
selected indices: [0,1]
actual action gap: 12.027444 ms

action 0 ARM translation: left 2.177 mm, right 3.526 mm
action 1 ARM translation: left 0.968 mm, right 2.218 mm
all move_end_pose/move_eef: True
final state: both IDLE/idle/valid
```

完整日志：`logs/openpi_p7_stream_79999_pilot_20260720_1718.log`；结构化记录：
`logs/openpi_p7_stream_79999/summary_20260720_171844.jsonl`。

## 延迟回读与停止原因

chunk 刚结束时的立即回读几乎还未运动，这是非阻塞调用的预期现象。进程切 idle、
释放控制后再次回读：

```text
left final xyz ~= [-0.0494,-0.0050,0.5495]
right final xyz ~= [-0.0821,0.0006,0.5604]
left displacement from run start ~= 24.98 mm
right displacement from run start ~= 3.40 mm
```

连续 5 次、间隔 200 ms 的只读采样完全稳定，排除单次反馈毛刺。同期 X5 当前日志
`/userdata/arm_app_logs/20260720_162226/{left,right}_arm.log` 显示模式切换成功，未出现
本轮 queue drop、UNKNOWN_ERROR 或 RPC rejection；但 left 在 EEF 切 CSP 时出现一次
`fsm_service_node proc() 40 ms exceeded period (4 ms)`，right 为 35 ms，说明板内实时
线程仍有明显超期。

影响：本轮只完成 2 行单轮 pilot，**没有启动长时间 inference**。在确认短 burst 后
左臂额外运动的原因，以及明确每轮固定 2/3/4 行和运行时长前，继续执行会扩大真机风险。

最终进程检查：`pgrep -af 'openpi_p7_persistent_loop.py|p7_.*(move|wave|servo|loop)'`
返回码 `1` 且无输出，确认没有残留真机控制进程；相机守护 PID `18180` 和 79999
policy server PID `74687/74691` 仍在运行。最终 `ruff --select E,F` 再次通过。

## 2026-07-21 00:56 CST - 默认执行 chunk 前 15 行并锁定 4 ms 指令间隔（agent: Codex）

### 目的与代码结论

按本轮要求修改常驻真机推理入口 `examples/airbot/openpi_p7_persistent_loop.py`：

- 默认 `chunk_start_index=0`、`chunk_steps=15`，因此一次 policy 返回后依次选择 action
  索引 `0..14`；15 行循环结束和 chunk readback 完成后，外层循环才采集新观测并再次调用
  `policy.infer()`。
- `stream_action_chunk` 改为默认开启。每个 action row 对每个 active side 最多发送一条
  `move_end_pose`；启用夹爪时，每侧再发送一条 `move_eef`。当前 side 集合只允许
  `left/right`，所以每行最多 2 条臂指令 + 2 条夹爪指令，共 4 条运动 RPC。
- 四路运动 RPC 继续共用同一个 `MotionCommandRateLimiter`。参数
  `--min-motion-command-interval-s` 默认 `0.004`，现在小于 `0.004`（包括旧的 `0` 禁用值）
  会在连接相机、policy 或机器人之前被 `validate_args()` 拒绝。

这里的“15 行执行完”是指每行对应的非阻塞 servo/EEF RPC 已返回、该行调用完成，并在全部
15 行发完后才进入下一次推理。它不表示等待机械臂在每个目标处物理静止；streaming 模式明确
要求 `--no-servo-blocking`，启用夹爪时也要求 `--no-gripper-blocking`。

### 离线验证

本轮没有连接 policy server、ROS2 相机或机器人，也没有获取控制权或发送真机指令。

```bash
.venv-p7-ros/bin/python -m pytest -q \
  examples/airbot/openpi_p7_persistent_loop_test.py
.venv-p7-ros/bin/python -m py_compile \
  examples/airbot/openpi_p7_persistent_loop.py \
  examples/airbot/openpi_p7_persistent_loop_test.py
uv run ruff check --select E,F \
  examples/airbot/openpi_p7_persistent_loop.py \
  examples/airbot/openpi_p7_persistent_loop_test.py --output-format concise
```

关键输出：

```text
3 passed in 0.14s
All checks passed!
```

测试确认默认选择正好为 `list(range(15))`；`0.0039s` 被参数校验拒绝；模拟四条命令的
起发时刻为 `10.000/10.004/10.008/10.012s`。两个 Python 文件编译成功，限定 E/F Ruff
和 whitespace 检查通过。完整 Ruff 仍报告主文件此前已有的 8 条非致命告警，与本次行为修改
无关。现行 `scripts/README.md` 启动命令也已同步为显式
`--stream-action-chunk --chunk-start-index 0 --chunk-steps 15` 和
`--min-motion-command-interval-s 0.004`；历史 pilot 章节中的 0 ms 命令仅保留为当时实验记录。
