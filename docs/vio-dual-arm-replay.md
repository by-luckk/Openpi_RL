# VIO 双臂 TCP 轨迹 replay

## 2026-07-24 13:14 CST - 输入文件检查与 replay 脚本实现（agent: Codex）

### 目的

为 `data/vio_dual_arm_trajectory_10s.replay.npz` 提供一个不把 TCP 轨迹误当作关节角的双臂 replay
入口。

### 输入检查

```bash
.venv-p7-ros/bin/python -c '
import numpy as np
z = np.load("data/vio_dual_arm_trajectory_10s.replay.npz", allow_pickle=False)
print(z.files)
print(z["time_s"].shape, z["time_s"][0], z["time_s"][-1])
print(z["tcp_pose_command_14d"].shape)
print(z["metadata_json"].item())
'
```

关键结果：`time_s=(273,)`，范围 `0.0..9.066658s`，`tcp_pose_command_14d=(273,14)`。metadata 的
`schema_version=vio_dual_arm_trajectory_v1`、`is_direct_airbot_joint_command=false`，并定义 14 维顺序为
`left dx/dy/dz, rotvec, gripper, right dx/dy/dz, rotvec, gripper`。它是相对 TCP 位姿，绝不能传给
`move_joint()`。

左右原始最大位移分别为约 `0.228m`、`0.381m`，峰值平移速度约 `0.73m/s`、`0.93m/s`。因此新脚本
`examples/airbot/p7_replay_vio_dual_arm_trajectory.py` 会在真实 replay 开始时读取当前双臂 TCP，将
相对位姿按 `base_T_tcp_start @ start_T_tcp(t)` 合成绝对目标，并将每个采样间隔细分为至多 `10mm` 和
`0.10rad` 的 Cartesian servo 小步。默认 `--time-scale 5`，默认 `--max-envelope-m 0.05` 会拒绝本文件，
防止没有审查工作空间时直接执行 38cm 轨迹。默认不重放夹爪；`--replay-grippers` 才会把记录的
夹爪绝对值直接作为 P7 毫米值发送，并截断到 `0..95mm`。因此本文件中右夹爪的最高
`101.913887mm` 会下发为 `95mm`，不做比例缩放。

### 使用

先进行纯离线计划检查（不会创建 SDK client 或连接机器人）：

```bash
.venv-p7-ros/bin/python examples/airbot/p7_replay_vio_dual_arm_trajectory.py \
  --trajectory data/vio_dual_arm_trajectory_10s.replay.npz \
  --max-envelope-m 0.40
```

仅在双臂完整工作空间已清空、确认当前 TCP 起点适合映射整段相对轨迹后，才执行：

```bash
.venv-p7-ros/bin/python examples/airbot/p7_replay_vio_dual_arm_trajectory.py \
  --trajectory data/vio_dual_arm_trajectory_10s.replay.npz \
  --host 192.168.25.1 \
  --time-scale 2 \
  --max-envelope-m 1 \
  --max-measured-envelope-m 0 \
  --execute --allow-robot-motion --replay-grippers
```

加 `--replay-grippers` 才会同步重放夹爪。脚本完成、拒绝或收到 `SIGINT/SIGTERM` 时都会尽力把已接管的
臂控制器和 EEF 控制器切回 idle 并释放控制权；它不会自动回到 replay 起点。

### 离线验证

```bash
.venv-p7-ros/bin/python -m py_compile \
  examples/airbot/p7_replay_vio_dual_arm_trajectory.py \
  examples/airbot/p7_replay_vio_dual_arm_trajectory_test.py
.venv/bin/ruff check \
  examples/airbot/p7_replay_vio_dual_arm_trajectory.py \
  examples/airbot/p7_replay_vio_dual_arm_trajectory_test.py
.venv-p7-ros/bin/python examples/airbot/p7_replay_vio_dual_arm_trajectory.py \
  --trajectory data/vio_dual_arm_trajectory_10s.replay.npz \
  --max-envelope-m 0.40
.venv-p7-ros/bin/python -m pytest -q \
  examples/airbot/p7_replay_vio_dual_arm_trajectory_test.py
git diff --check
```

结果：编译、Ruff、`--help`、`git diff --check` 均通过；pytest 为 `2 passed`。离线 dry-run 成功生成
`326` 个插值帧，计划时长 `45.333s`，并明确输出没有创建 SDK client、没有申请控制权或下发 arm/EEF
命令。本轮未连接或控制机器人。

## 2026-07-24 13:19 CST - 夹爪值按毫米截断（agent: Codex）

用户确认保留独立 replay 脚本，不改 `p7_continuous_servo_smoke.py` 或 `scripts/README.md`。将
`--replay-grippers` 的值转换规则改为直接使用记录的毫米值，并用
`min(max(value, eef_min_mm), eef_max_mm)` 截断；默认范围仍为 `0..95mm`。不再使用
`0..102 -> 0..95mm` 的线性映射。

验证命令使用 `--replay-grippers --max-envelope-m 0.40` 执行 dry-run；结果仍明确没有创建 SDK client
或下发控制命令。`py_compile`、Ruff、`--help` 和 `git diff --check` 均通过，轨迹数学与夹爪截断测试为
`3 passed`。本轮未连接或控制机器人。

## 2026-07-24 22:18 CST - 实测包络保护拒绝右臂跟踪偏离（agent: Codex）

用户真机回放收到：

```text
REFUSE: measured envelope {'left': 0.11636117986346409, 'right': 0.4278791776133816} exceeds 0.420000
```

只读查看 `/tmp/p7_vio_dual_arm_replay_latest.json` 确认这次是 `time_scale=2`、物理臂已按
VIO source 反向标签交换，计划相对位移包络为 left=`0.380988m`、right=`0.227870m`。
代码中实测包络是 `norm(current_tcp_xyz - replay_start_xyz)`，每 `1/feedback_hz` 读回一次；
右臂实测 `0.427879m` 比其整段计划最大值多 `0.200010m`，约为计划的 `1.878`
倍。因此这不是 `--max-envelope-m 0.40` 的离线计划检查，而是
`--max-measured-envelope-m 0.42` 在真机运动中正常中止了明显偏离。不应通过调大该阈值继续。

当前 ready joint 为 `[0,0.78,0,0,0,0,1.04]rad`，其 joint4=`0` 相比旧 ready pose 的
joint4=`-0.933` 明显更接近伸直奇异位形，是 Cartesian 伺服同时跟踪平移与姿态时失稳的
首要嫌疑。但现有 summary 未记录触发 frame、当帧 target TCP 和 target-vs-measured 误差，
因此这是有物理依据的根因推断，不是已被单条报错完全证实的结论。本轮未连接机器人、
未申请控制权、未发送动作。
