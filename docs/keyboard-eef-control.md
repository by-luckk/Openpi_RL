# 键盘控制双臂末端位姿现状

## 2026-07-24 13:20 CST（Codex）

- **目的**：确认仓库是否已有程序，可用键盘直接控制左右两个机械臂末端的 `x/y/z + roll/pitch/yaw`。
- **检查命令**：

  ```bash
  rg --files -g '!docs/VIO_Test/**' | rg -i 'key|teleop|operator|joy|cartesian|pose|servo'
  rg -n -i 'keyboard|pynput|curses|termios|keypress|按键|key_enter' \
    examples scripts src README.md docs --glob '!docs/VIO_Test/**' \
    --glob '*.py' --glob '*.sh' --glob '*.md'
  rg -n -i 'move_end_pose|CartesianPose|servo_pose|airbot-driver|roll|pitch|yaw' \
    examples scripts src --glob '*.py' --glob '*.sh'
  ```

- **关键证据**：
  - `README.md:413-416` 的键盘监听只有 `Enter/R/Q`，用于开始、重置和退出 episode。
  - `examples/airbot/dagger_controller.py:176-219` 的键盘监听只有进入/退出 DAgger、保存/丢弃 episode 和退出；DAgger 的人类示范来自物理 leader arm，不是键盘生成末端位姿。
  - `examples/airbot/play_operator.py:108-135` 的 `send_action()`/`send_leader_action()` 下发的是每臂 6 个关节角加 1 个夹爪值，属于关节空间接口。
  - `docs/teleop-and-data-collection.md` §1、§8 记录的 `airbot-driver` 按键是 `O/P/Z/M/L`（遥操开关、暂停、回零、安全退出），它读取 E2 主臂位姿，不是键盘 XYZ/RPY 控制器。
  - 仓库有双臂末端笛卡尔控制能力：`examples/airbot/p7_replay_vio_dual_arm_trajectory.py:318-322` 构造 `CartesianPose`，`491-503` 并发调用左右 `AirbotClient.move_end_pose()`；但输入是轨迹文件，没有键盘事件或 XYZ/RPY 按键映射。

- **当时结论**：检查时没有现成程序实现“键盘直接控制双臂末端 `xyz + roll/pitch/yaw`”。现有代码分别覆盖键盘状态控制、物理主臂遥操作、关节目标下发和轨迹/P7 CartesianPose 执行，尚未把键盘增量映射到双臂 TCP pose。

## 2026-07-24 13:35 CST（Codex）- 新增键盘双臂六自由度遥操作

- **目的**：新增可用键盘为左右 P7 机械臂末端分别或同步下发 `XYZ + roll/pitch/yaw` 小增量的程序。
- **实现**：新增 `examples/airbot/keyboard_dual_arm_teleop.py`，通过 Arm-P7 SDK gRPC：启动时读取左右 TCP pose，真实执行时为两臂申请 lease、切到 `servo_control`、设置 7 轴速度；每次按键重新读取所选臂 TCP pose，计算绝对 `CartesianPose` 后并发调用 `move_end_pose()`。退出或异常时切回 `idle` 并释放 lease。
- **按键**：`1` 左臂、`2` 右臂、`b` 双臂；`w/s` 为 `+X/-X`，`a/d` 为 `+Y/-Y`，`r/f` 为 `+Z/-Z`；`i/k` 为 roll 正/负，`j/l` 为 pitch 正/负，`u/o` 为 yaw 正/负；`h` 输出帮助，`q` 或 Ctrl-C 退出。默认是 world frame；`--frame local` 改为 TCP 局部坐标系。
- **安全边界**：默认 dry-run；真实运动必须同时传入 `--execute --allow-robot-motion`。默认单次 `2 mm/2 deg`、P7 臂速 `1.5 rad/s`、命令最小间隔 `40 ms`、相对启动 TCP 的平移包络 `5 cm` 和旋转包络 `30 deg`；不控制夹爪。超出任一包络的命令会拒绝下发。
- **运行命令**：

  ```bash
  # 仅检查连接、显示按键目标；不会申请控制权或运动
  .venv-p7-sdk/bin/python examples/airbot/keyboard_dual_arm_teleop.py

  # 清空工作空间后，启用实际末端控制
  .venv-p7-sdk/bin/python examples/airbot/keyboard_dual_arm_teleop.py \
    --execute --allow-robot-motion
  ```

  同时提供参数封装 `scripts/cmds/keyboard_dual_arm_teleop.sh`，可直接以
  `bash scripts/cmds/keyboard_dual_arm_teleop.sh` dry-run；真实运动命令为
  `bash scripts/cmds/keyboard_dual_arm_teleop.sh --execute --allow-robot-motion`。

- **验证命令与结果**：

  ```bash
  .venv/bin/ruff check examples/airbot/keyboard_dual_arm_teleop.py \
    examples/airbot/keyboard_dual_arm_teleop_test.py
  .venv/bin/python -m py_compile examples/airbot/keyboard_dual_arm_teleop.py \
    examples/airbot/keyboard_dual_arm_teleop_test.py
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
    examples/airbot/keyboard_dual_arm_teleop_test.py
  .venv/bin/python examples/airbot/keyboard_dual_arm_teleop.py --help
  .venv/bin/python examples/airbot/keyboard_dual_arm_teleop.py --execute
  bash scripts/cmds/keyboard_dual_arm_teleop.sh --help
  git diff --check
  ```

  Ruff、编译、Python/封装 `--help`、`git diff --check` 均通过；数学/按键映射测试为 `3 passed`；只给 `--execute` 被正确拒绝并输出 `--execute requires --allow-robot-motion`。普通 pytest 会被工作站自动加载的 ROS Jazzy `launch_testing` 插件阻断（其 Python 3.12 依赖缺少 `lark`），禁用外部插件后测试通过。此次未连接机器人，未申请控制权，未发送任何运动命令。

## 2026-07-24 13:43 CST（Codex）- 修正 P7 最小臂速

- **目的**：处理用户首次真实启动键盘遥操作时 `set_arm_speed()` 被拒绝的问题。
- **实际命令**：

  ```bash
  bash scripts/cmds/keyboard_dual_arm_teleop.sh --execute --allow-robot-motion
  ```

- **关键输出**：左右服务初始均为 `IDLE/idle/valid`，左臂 lease 获取成功；随后输出
  `FAILED: left: set_arm_speed returned False` 和
  `Max speed must not higher than max speed 7.854981633974483 and no less than 0.5499000081647326!`。
  清理输出为 `left switch_idle True`、`left release_control done`。
- **结论**：原脚本默认 `--arm-speed-rad-s=0.25` 低于 SDK 最小允许值约 `0.5499 rad/s`；没有下发
  `move_end_pose()`。当时先将默认值提高到 `0.55`；当前默认值已按用户要求提高到 `1.5 rad/s`（见下一节）。
  脚本会在申请 lease 前拒绝范围外的 `--arm-speed-rad-s`（`0.55..7.85`）。
- **影响**：重新运行同一命令会以 SDK 接受的最小附近速度继续启动。现场仍需清空工作空间，首次按键前
  保持 `2 mm/2 deg` 默认小步并观察实际位移。
- **修正后验证**：`P7_TELEOP_ARM_SPEED_RAD_S=0.25 bash scripts/cmds/keyboard_dual_arm_teleop.sh`
  在 SDK import、连接和 lease 之前退出 `2`，输出
  `REFUSE: --arm-speed-rad-s must be within [0.55, 7.85]`；Ruff、`py_compile` 与
  `git diff --check` 通过。未连接机器人，未申请控制权或下发动作。

## 2026-07-24 13:53 CST（Codex）- 提高键盘遥操作响应速度

- **目的**：按用户要求提高末端键盘控制的响应速度。
- **修改**：默认 P7 `--arm-speed-rad-s` 和 shell 环境变量 `P7_TELEOP_ARM_SPEED_RAD_S` 从 `0.55`
  提高到 `1.5 rad/s`；`--command-interval-s` 从 `80 ms` 降到 `40 ms`，以便按住按键时能以最高约
  25 Hz 发送增量命令。单步仍为 `2 mm/2 deg`，启动位姿包络仍为 `5 cm/30 deg`，不扩大工作空间。
- **影响**：重启脚本后生效。需要更快或更慢时，分别使用
  `P7_TELEOP_ARM_SPEED_RAD_S=<0.55..7.85>` 或 Python 参数 `--command-interval-s` 调整；实际运动前
  仍应确认双臂周围无障碍物。
- **验证**：`.venv/bin/ruff check`、`py_compile`、禁用外部 ROS pytest 插件后的
  `keyboard_dual_arm_teleop_test.py`（`3 passed`）及 `git diff --check` 均通过；未连接机器人。

## 2026-07-24 14:38 CST（Codex）- 当前 shell 封装参数与 gRPC 环境对照

- 初次检查确认键盘封装默认 `.venv-p7-sdk/bin/python`，而 replay 使用 `.venv-p7-ros/bin/python`；后续
  源码对照发现真正的区别是 replay 在 SDK 建连前清除本机 HTTP/SOCKS proxy。现已改为默认
  `.venv-p7-ros/bin/python`，并复用 replay 的直连代理配置；详见
  [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md) §10-11。
- 检查时 shell 封装的实际覆盖参数为 `P7_TELEOP_STEP_MM=5`、`P7_TELEOP_STEP_DEG=3`、
  `P7_TELEOP_MAX_ENVELOPE_M=1.0`、`P7_TELEOP_MAX_ROTATION_DEG=90`。它们覆盖 Python 程序的
  `2 mm/2 deg`、`5 cm/30 deg` 安全默认值；该差异不引起连接超时，但会显著扩大键盘真实运动的单步和
  可达包络。使用前需明确这是有意的现场配置。

## 2026-07-24 14:50 CST（Codex）- 复用 replay 的无代理 gRPC 建连

- **根因**：本机有 `all_proxy=socks5://127.0.0.1:7897`、`http_proxy/https_proxy=http://127.0.0.1:7897`。
  键盘脚本原先继承代理，SDK 对机器人私网地址的 gRPC handshake 超时；replay 的
  `configure_direct_grpc()` 会先清除这些变量，因此每次都能直连。
- **修改**：删除无效的建连重试；键盘脚本新增与 replay 相同的 `configure_direct_grpc()`，输出
  `grpc_direct_host=192.168.25.1 removed_proxy_variables=[...]`，并把机器人 IP 加入 `NO_PROXY`。
  Shell 默认解释器改为 `.venv-p7-ros/bin/python`。
- **验证**：以同样的无代理环境运行 `.venv-p7-ros` one-shot probe，左右均立即返回
  `ServiceState(... fsm_state='IDLE', controller_state='idle', valid=True)`；Ruff、编译、封装 `--help` 和
  代理清理单测通过，合计 `4 passed`。另以伪终端运行
  `(sleep 2; printf 'q') | timeout 10 script -q -c 'bash scripts/cmds/keyboard_dual_arm_teleop.sh' /dev/null`，
  输出 `removed_proxy_variables=['http_proxy', 'https_proxy', 'all_proxy']` 及左右 `IDLE/idle/valid`，随后由
  `q` 正常退出。全程未带 `--execute`，未申请控制权或发送运动命令。
# 2026-07-24 - 取消键盘遥操作累计平移/旋转限位

按用户要求，`keyboard_dual_arm_teleop.py` 已删除相对启动 TCP 的 `--max-envelope-m` 平移包络和
`--max-rotation-deg` 旋转包络，以及越界拒绝逻辑；shell 封装也不再传入这两个参数。每次按键仍按
`--step-mm` / `--step-deg` 生成增量，并保留命令间隔、SDK 速度参数、双重真实运动开关及 SDK/机器人
自身限制。本次未连接或控制机器人。
