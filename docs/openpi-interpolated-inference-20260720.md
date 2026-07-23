# 2026-07-20 OpenPI 双腕录制与插值真机推理

## 结论

- 日期：2026-07-20 14:42-15:19 CST；检查人：Codex。
- 策略服务实际加载 wrist-only 20k checkpoint：
  - config：pi05_vio_plant_collection_535_clean_wrist_only
  - checkpoint：checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/vio_pi05_535_clean_wrist_only_80k_260717/20000
  - 请求均带 --wrist-only --no-advantage，实际 observation_shapes 只有左右腕 640x480 RGB 和 state[16]，没有头相机。
- 2026-07-20 的历史真机检查中，双臂曾多次以 planning PTP、velocity/acceleration scaling=0.03 回到用户指定目标
  [0, 0.647, 0, -0.933, 0, 0, -1.15] rad。最后一次复位最大误差：
  - left：0.000202 rad
  - right：0.000144 rad
- 自 2026-07-21 11:30 起，production ready 回位不再使用 planning PTP，改为 P7 高级 SDK
  `servo_control + move_joint(final_target, blocking=True)` 单次目标调用；闭环完全由 SDK 内部处理。
- idle 控制会释放保持，现场观察到关节（尤其 joint7）随后漂移；所以最终复位和启动推理必须紧邻执行。
- 真机执行改为每条策略 action 只取 index 0，并从每个子步发令前的实际 TCP 位姿重新插值：
  - 正常命令平移上限 0.005 m；
  - 正常命令旋转上限 0.02 rad；
  - 每个子步后回读 TCP；
  - 用户随后把实测单步硬越界阈值从 0.01 m 放宽为 0.03 m；
  - 实测硬越界使用独立退出码 3，supervisor 不会自动重试；
  - move_end_pose=False、通信/控制错误由 supervisor 快速 clear_error/切 idle；快速清错成功后用新观测继续，失败则退出，不启动或重启 X5 上的任何应用。
- 独立的相对本轮起点总包络仍为 0.05 m。最终 3 cm 阈值运行在第 17 次迭代因 left envelope=0.053222 m 停止，不是 3 cm 单步越界。
- 收尾没有真机推理进程；双臂均 IDLE/idle/valid；策略服务仍只读待命。

## 代码改动

- src/openpi/shared/airbot_relpose.py
  - 新增四元数最短角距离；
  - 新增不依赖 SciPy 的 xyzw quaternion SLERP；
  - 新增同时限制平移和旋转的 TCP waypoint 生成器。
- examples/airbot/openpi_p7_persistent_loop.py
  - 策略目标超过 5 mm 时不再拒绝，改为自适应 waypoint；
  - 每个 waypoint 发令前和发令后均读取实际 TCP；
  - 日志记录 command_translation_m、measured_translation_m、最终目标误差和 service state；
  - 最终 waypoint 成功发送并回读后结束该臂本次 action，不追逐 P7 的毫米级稳态误差；
  - max-measured-translation-m 默认值按用户新指令改为 0.03 m。
- scripts/cmds/openpi_p7_unlimited_recovery.sh
  - rc=3 安全越界时停止 supervisor；
  - 普通控制错误快速清错成功后继续；失败时退出并要求人工恢复，不自动启动或重启板端应用。

## 可复现检查

### 离线测试

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q src/openpi/shared/airbot_relpose_test.py

输出：9 passed in 0.07s。

23 mm 平移 fake-client：左臂 5 个 4.6 mm 子步；11 mm 右臂 3 个 3.667 mm 子步；最大命令/实测均 4.6 mm。

80% 跟踪 fake-client：5.2 mm 目标分两次命令，最终误差 0.624 mm；每臂仅 2 次命令，证明最终 waypoint 不会被重复追逐。

Python 编译与 bash -n 均通过。限定 ruff E/F 仍报告 airbot_relpose.py 原有 3 个 E501 超长行，不是本轮新增逻辑。

### 真实 observation dry-run

    .venv-p7-sdk/bin/python examples/airbot/openpi_p7_persistent_loop.py \
      --iterations 1 --capture-mode latest-file \
      --latest-obs-npz /tmp/openpi_cam_daemon_wrist/latest.npz \
      --latest-obs-meta /tmp/openpi_cam_daemon_wrist/latest.json \
      --wrist-only --no-advantage --chunk-steps 1 \
      --max-step-translation-m 0.005 --max-measured-translation-m 0.01

输出：policy actions (50,32)，left policy translation=7.454 mm，自动规划 2 段；right=4.219 mm，规划 1 段。双臂前后均 IDLE/idle/valid，未获取控制。

### 真机执行结果

修复最终 waypoint 行为后的单 action：

- left policy target=5.535 mm，命令 2.768 mm + 3.288 mm；
- right policy target=1.888 mm，命令 1.888 mm；
- 最大实测单步 2.432 mm；
- move_end_pose 全部 True，结束后双臂 IDLE/idle/valid。

用户放宽实测硬阈值后的持续运行：

    scripts/cmds/openpi_p7_unlimited_recovery.sh \
      --duration-s 86400 --period-s 1 --wrist-only --no-advantage \
      --chunk-steps 1 --max-step-translation-m 0.005 \
      --max-measured-translation-m 0.03 --max-envelope-m 0.05 \
      --arm-speed-rad-s 0.55 --execute --allow-robot-motion

- 完成 17 次策略迭代；
- 最大命令平移 0.004021 m；
- 最大实测平移 0.003479 m；
- 无 move_end_pose=False、UNKNOWN_ERROR 或快速恢复事件；
- left 总包络 0.053222 m 超过独立 0.05 m 守卫后 rc=3 停止，控制清理成功。

## 双腕录制

目录：/home/discover/Desktop/recording/openpi_wrist_20260720_150624

- camera_left_wrist_0_rgb.mp4：10996 帧，15 fps，640x480；
- camera_right_wrist_0_rgb.mp4：10996 帧，15 fps，640x480；
- camera_tiled.mp4：10996 帧，15 fps，1280x480；
- camera_metadata.json：两路原始 topic、nv12 编码、frame_id、原始 message count；
- openpi_p7_recovery_*.log：首步、持续运行、3 cm 阈值运行完整控制日志。

三份 MP4 均经 cv2.VideoCapture 验证 opened=True、帧数/尺寸一致。头相机不可用且 wrist-only checkpoint 不消费头相机，因此本轮按用户指令只录左右腕。

## 停止命令

    pkill -TERM -f '[o]penpi_p7_unlimited_recovery.sh'

该信号由 supervisor 转发给活动 inference process group，Python finally 会切回 idle 并 release_control。

## 2026-07-20 17:47 CST - 移除推理中的板端应用自动启动

检查人：Codex。

目的：确认推理为何会拉起板端应用，并按要求去掉该行为。

定位命令：

```bash
rg -n "ARM_START_SCRIPT|restart_arm_apps|ssh|starting X5 arm services" \
  scripts/cmds/openpi_p7_unlimited_recovery.sh logs/openpi_p7_recovery_*.log
```

证据：旧 supervisor 的 `restart_arm_apps()` 会 SSH 到 `192.168.25.1`，后台执行
`/root/start-arm-dual-app-2arm.sh`。历史日志多次出现 `starting X5 arm services`，例如
`logs/openpi_p7_recovery_20260719_210347.log:1347`。这条路径只在快速清错失败或停止清理
失败时触发，不属于正常的 policy 请求流程。

修改：已从 `scripts/cmds/openpi_p7_unlimited_recovery.sh` 删除 `ARM_START_SCRIPT`、SSH、
`restart_arm_apps()` 和 ready 等待逻辑。现在快速清错失败时 supervisor 直接非零退出并输出
`robot-side applications were left untouched; manual recovery is required`；收到停止信号且清理失败时
也只报告状态，不触碰板端应用。快速清错成功后的 fresh-observation 重试行为保持不变。

影响：推理进程今后只连接已经存在的 `50071/50072` 服务，不会自行启动、停止或重启
`robot_app`、`arm_app`、`arm_dual_app` 或它们的启动脚本。板端服务未就绪时需要先人工处理。

离线验证（未连接机器人、未下发动作）：

```bash
bash -n scripts/cmds/openpi_p7_unlimited_recovery.sh
RESET_RUNNER=/bin/true INNER_RUNNER=/bin/true LOCAL_LOG_DIR="$(mktemp -d)" \
  bash scripts/cmds/openpi_p7_unlimited_recovery.sh
RESET_RUNNER=/bin/true INNER_RUNNER=/bin/false SDK_PYTHON=/bin/false \
  LOCAL_LOG_DIR="$(mktemp -d)" bash scripts/cmds/openpi_p7_unlimited_recovery.sh
RESET_RUNNER=/bin/false INNER_RUNNER=/bin/true SDK_PYTHON=/bin/false \
  LOCAL_LOG_DIR="$(mktemp -d)" \
  bash scripts/cmds/openpi_p7_unlimited_recovery.sh
```

结果：shell 语法通过；成功路径首轮以 `0` 完成；模拟推理失败且快速清错失败时以 `1`
退出，关键输出为 `robot-side applications were left untouched; manual recovery is required`。
静态搜索也确认脚本已无 `ARM_START_SCRIPT`、`restart_arm_apps`、`ssh` 或
`starting X5 arm services`。检查期间并行加入的推理前关节 reset 仅调用 P7 SDK，不启动应用；
故障注入同时发现其旧写法会在 `wait` 失败后丢失退出码并继续推理，随后该处已改为在
`else` 分支捕获退出码。现在模拟 reset 失败会以 `1` 退出，且不会进入 inner inference。
17:52 CST 复测输出为 `pre-inference joint reset failed rc=1` 和
`robot-side applications were left untouched`，日志中没有真正的 `inference attempt=` 行。

## 2026-07-20 17:43 CST - 79999 period=0 被右臂 joint7 bit 19 阻断

检查人：Codex。运行目录：
`/home/discover/Desktop/recording/openpi_wrist_79999_period0_20260720_1732`。

本轮使用 wrist-only `79999`、`chunk_steps=1`、`period_s=0` 和
`max_step_translation_m=0.009`。4 次 attempt 分别写入 13、10、8、17 条成功 summary，
均未跑满 400 秒。最后失败前，右臂 policy 平移为 `1.563mm`，实际命令为
`1.542mm`，不是大步或 9mm 命令限额触发；X5 返回 `move_end_pose=False`。

SDK 回读右臂为 `UNKNOWN_ERROR/idle/valid`，第 7 关节电机错误数组为
`(0,0,0,0,0,0,524288)`，即仅 `1<<19` 置位；该关节温度 48C，EEF error 为 0。X5
`right_arm.log` 从 `17:35:39` 起持续输出
`Motor 7 error: Unknown motor error bit 19`。`clear_error()` 连续返回 True，但板端日志明确
写为 `clear_error RPC placeholder triggered`，状态和错误位不变；急停复位接口也返回 False。

结论：这是右臂 joint7 的持续驱动错误，不能当作瞬时网络丢包继续发动作。supervisor 已停止，
没有 inference/control process 残留；仅保留不下发动作的 wrist-only 79999 policy server 和
相机守护。后续检查时 `192.168.25.1:50071/50072` 均为 connection refused，因此未再次
尝试真机运动。

## 2026-07-20 17:52 CST - 每次 inference attempt 前强制双臂复位

检查人：Codex。

`scripts/cmds/openpi_p7_unlimited_recovery.sh` 现在每次 attempt（包括错误恢复后的重试）先
执行 `scripts/cmds/move_p7_to_ready_joint_pose.sh`，把双臂 planning PTP 到
`[0,0.647,0,-0.933,0,0,-1.15]rad`。复位速度/加速度缩放默认均为 `0.03`。只有复位
进程退出 0 后才打印 `inference attempt=N` 并启动 inner policy runner；复位失败时明确记录
`policy inference was not started`，快速清错仍失败则退出等待人工恢复，不触碰板端应用。

`bash -n`、mock reset 成功路径和 mock reset 失败门禁均通过。成功路径日志顺序为
`reset completed -> inference attempt`；失败路径返回 1，且无真正的 `CST inference attempt=`
日志。测试发现并修复了第一版在 `wait` 失败后误取 `rc=0` 的 shell 错误。因真机端口当前
拒绝连接，本轮未执行真实复位或真机推理。

## 2026-07-20 19:35 CST - 79999 period=0 重跑、SDK/X5 故障与恢复语义修正

检查人：Codex。目的：从指定关节位复位后运行 wrist-only 79999、`chunk_steps=1`、
`period_s=0`、每个 TCP 插值命令段不超过 `9mm` 的 400 秒双臂闭环，并完整记录 SDK 与
X5 问题。

### 前置与实际配置

每次启动前均用 P7 SDK 检查左右 `ServiceState`、14 个 arm motor error、两个 EEF error、
TCP pose，并实际 acquire/release 一次控制权。健康时结果均为 `IDLE/idle/valid`、所有
`error_id=0`、pose 可读、`acquire_probe=True`。策略持续使用
`pi05_vio_plant_collection_535_clean_wrist_only` 的 `79999`，请求只有左右腕 RGB 640x480
与 `state[16]`；返回 `actions=(50,32)`，每轮只选择 index 0。

核心参数为：`--duration-s 400 --period-s 0 --controller servo --chunk-steps 1
--action-step-interval-s 0 --max-step-translation-m 0.009
--max-step-rotation-rad 3.141592653589793 --max-measured-translation-m 0
--max-envelope-m 0 --min-motion-command-interval-s 0 --capture-mode latest-file
--wrist-only --no-advantage --execute --allow-robot-motion`。

### 发现并修正的问题

1. 一次终端工具 1 秒 timeout 在 planning reset 持有 `lease_ms=60000` 时杀死 client，
   X5 此后虽显示 `IDLE/idle/valid`，但 acquire 持续返回
   `RESOURCE_EXHAUSTED: controller already held`。旧 quick recovery 只看 FSM，导致 58 次
   快速误重试。已修改 supervisor：即使 FSM 为 IDLE，也必须实际 acquire/release 成功才
   判定恢复。孤立 lease 最终通过停止并重启当时由本轮启动的双臂 arm_app 清除。
2. 带 `--enable-gripper` 的真实重跑在第一个 action 失败：左右
   `move_end_pose=True`，右 `move_eef=True`，左 `move_eef=False`，随后左 FSM
   `UNKNOWN_ERROR`。X5 同秒记录 ARM command queue drop `13.4%`、EEF command queue
   drop `35.1%`。`clear_error=True` 仍只是板端 placeholder。因此后续保留完整 32 维模型
   输出但不下发物理夹爪，不进入 EEF CSP。
3. `scripts/tools/monitor_x5_cpu.sh` 首次运行暴露两个脚本错误：双引号替换表达式缺少转义，
   以及把 awk 内建名 `system` 当作 `-v` 变量。分别改为正确转义和 `system_ticks`；
   `bash -n` 及真实 `--samples 1` 验证通过，CSV 能写出 X5 CPU/load/process 数据。
4. supervisor 原先在每个 retry 都重新传 `--duration-s 400`。现把 400 秒定义为 supervisor
   总预算，reset/recovery 也计时，每次只把剩余秒数传给 inner runner。
   `--duration-s 2` 和 `--duration-s=2` 两种 mock 均验证传参正确。

### arm-only 结果与当前阻断

目录 `/home/discover/Desktop/recording/openpi_wrist_79999_period0_arm_only_20260720_190734`
中，前三次 attempt 分别完成 `17/18/17` 个成功循环，连续段约 `11.1-11.6s`，循环约
`1.47-1.60Hz`。前两次 right `move_end_pose=False` 后 FSM 仍 IDLE，quick recovery 可
acquire/release 并继续；第三次右 joint7 出现 `error_id=524288 (1<<19)`，进入持续
UNKNOWN_ERROR，只能停止。

用户再次给机械臂断电并重启 X5 后，目录
`/home/discover/Desktop/recording/openpi_wrist_79999_period0_arm_only_20260720_192503`
做了总预算重跑。attempt 1/2 分别完成 `27/29` 个成功循环；第二段
`29/18.315s=1.583Hz`，最大命令平移 `6.640mm`。总预算日志正确从 `390s` 降到 retry 的
`321s`。但 `19:32:02` 右 joint7 再次报 bit 19，FSM 进入 UNKNOWN_ERROR，无法继续。
X5 同期 CPU 约 `30-34%`，未出现 command queue drop，故这次不是整机 CPU 饱和或 EEF
队列问题；板端同时有多条 servo/arm proc `5-8ms > 4ms period` 警告。

当前结论：物理夹爪 EEF CSP 有独立的高 queue-drop 故障；关闭夹爪后，右 joint7 bit 19
仍会在几十个控制循环后复现并锁存。仅重启 arm_app 或 X5 软件不能清除，必须给右臂驱动
断电重启。下一次建议在硬件清零后把 `--arm-speed-rad-s` 从 `0.55` 降到 `0.2` 做 A/B；
在 bit 19 根因解决前，不能宣称已完成连续 400 秒双臂闭环。

## 2026-07-20 19:56 CST - 用户手动启动第 7 步前的准备与 adopted action 打印

检查人：Codex。X5 重启后，有线口 `enp108s0` 已恢复 `LOWER_UP`，
`ping 192.168.25.1` 延迟约 `0.409ms`。重启清空了 `/root/start-arm-dual-app-2arm.sh`；
从仓库重新部署 `scripts/tools/start-arm-dual-app-2arm.sh` 后，板端启动两个
`/opt/arm_dual_app/bin/arm_dual_app`，分别监听 `50071/50072`。无动作检查确认左右均为
`IDLE/idle/valid`，14 个 arm motor error 和两个 EEF error 全为 0，TCP/关节可读，且两侧
`acquire_control -> release_control` 探针成功。

策略服务进程参数明确为 wrist-only 配置
`pi05_vio_plant_collection_535_clean_wrist_only` 和 checkpoint
`vio_pi05_535_clean_wrist_only_80k_260717/79999`；相机 daemon 的左右腕源帧年龄约
`0.12s`。随后以 planning PTP、velocity/acceleration scaling=`0.03` 将两臂复位到
`[0,0.647,0,-0.933,0,0,-1.15]rad`，左右最大终态误差分别为
`0.000106/0.000144rad`，结束均回到 `IDLE/idle/valid`。

`examples/airbot/openpi_p7_persistent_loop.py` 现在在每个被选择的 action row 转换和下发前，
打印 `adopted_action_2x7=[[left 7],[right 7]]`。索引来自训练/桥接定义：左臂为 `0:7`，
右臂为 `7:14`；每组依次是 TCP-local 平移 3、旋转向量 3、夹爪 1。打印内容同时写入
summary 的 `adopted_action_2x7`。`.venv-p7-sdk/bin/python -m py_compile` 与
`.venv/bin/ruff check --select E,F` 均通过。

用户取消录像和 X5 性能采样后，已停止本轮 `record_openpi_cameras.py` 和
`monitor_x5_cpu.sh`，仅保留相机观测 daemon、79999 policy server 和双臂 gRPC 服务。

## 2026-07-20 20:01 CST - 第 7 步首次启动未进入推理的原因

检查人：Codex。用户执行前台命令后，复位、双臂 acquire、servo 切换和
`set_arm_speed(0.55)` 均成功，但 iteration 1 报
`latest-file capture failed: no daemon observation found`。根因是命令只传了
`--capture-mode latest-file --wrist-only`，而闭环参数默认仍查
`/tmp/openpi_cam_daemon/latest.{npz,json}`；实际 wrist-only daemon 写入
`/tmp/openpi_cam_daemon_wrist/latest.{npz,json}`。检查时 daemon 正常运行，实际文件年龄约
`0.04s`，因此不是相机断流。

失败发生在 capture 阶段，尚未请求 policy、选择 action 或下发 servo 目标，所以没有
`adopted_action_2x7`，机械臂仅执行了推理前复位。修正启动参数需显式增加
`--latest-obs-npz /tmp/openpi_cam_daemon_wrist/latest.npz` 和
`--latest-obs-meta /tmp/openpi_cam_daemon_wrist/latest.json`。
20:01 CST 检查时该次 `openpi_p7_persistent_loop.py` 子进程仍存在，因此应先在原终端
`Ctrl+C` 完整停止，再执行修正命令，避免两个控制客户端重叠。

## 2026-07-20 20:26 CST - X5 重启后新推理再次被右臂内部队列丢失中断

检查人：Codex。X5 重启后重新部署并启动 `/opt/arm_dual_app`，新 400 秒 supervisor
PID 177819。attempt 1 运行至约 iteration 50 后右臂 `move_end_pose=False`，快速恢复成功；
attempt 2 的 iteration 1 右臂 `8.446mm` 目标再次返回 False，随后进入
`UNKNOWN_ERROR`，supervisor 于 20:25:12 因 quick recovery 失败退出。

最终 SDK 状态：左臂 `IDLE/idle/valid`、错误位全 0；右臂
`UNKNOWN_ERROR/idle/valid`、7 个 motor error 仍全 0、joint7 温度 46C。X5 同期日志明确
记录 ARM command loss `6.5%`、EEF command loss `14.8%`，随后 FSM 更新为
`UNKNOWN_ERROR`；`clear_error` 仍为 placeholder，不能清除该 FSM 错误。本轮停止不是 9mm
插值限制或模型推理报错，而是 X5 内部 ARM/EEF 4ms 控制队列丢失。

## 2026-07-20 20:31 CST - 明确丢弃失败 attempt 的模型动作并重新推理

检查人：Codex。`scripts/cmds/openpi_p7_unlimited_recovery.sh` 已明确约束恢复语义：inner
闭环一旦失败，先等待该进程退出，使其内存中的 action chunk 失效；保留 action JSON 仅供
诊断，不会重放。quick recovery 成功后，下一 attempt 从指定初始关节位复位，重新采集最新
相机和 pose，并重新请求 OpenPI action chunk。当前 `chunk_steps=1`，每轮本来也只采用第 0
行，不存在 50 行动作积压。

该修改不能清空 X5 内部 250Hz ARM/EEF 队列；若队列丢失已使 FSM 锁存
`UNKNOWN_ERROR`，SDK placeholder `clear_error` 无法恢复时仍会停止，避免在错误状态继续
发送。`bash -n` 与 `/bin/true`、`/bin/false` 离线故障注入通过，日志明确输出
`discarded the failed attempt's local policy action chunk`；测试未连接机器人、未发送动作。

## 2026-07-20 20:36 CST - OpenPI 推理动作统一改为 blocking=False

检查人：Codex。检查当前真机推理路径发现：`openpi_p7_persistent_loop.py` 的
`servo_blocking` 和 `gripper_blocking` 默认均为 True，planning action 分支硬编码 True；
`policy_to_p7_sdk_bridge.py` 的 servo/planning action 与 gripper 默认也包含 True；共享
`airbot_p7_adapter.py` 同样硬编码 True。这会使模型闭环等待 SDK 运动完成。

现已把上述模型动作路径全部改为 `blocking=False`：常驻闭环 servo、planning 和 gripper，
单次 policy bridge 的 servo、planning 和 gripper，以及共享 P7 adapter。shell 包装器的
夹爪默认同步为 non-blocking。推理前 `p7_move_to_joint_target.py` 的关节 PTP 和夹爪复位仍
保留 blocking=True，因为必须确认初始位到达后才能启动模型，不属于模型闭环动作。

验证：相关 Python `py_compile`、三个 shell `bash -n`、ruff E/F（忽略既有 E501）均通过；
`airbot_p7_adapter_test.py` 为 `5 passed`；默认值断言为
`servo_blocking=False gripper_blocking=False`；静态搜索确认四条推理执行路径无
`blocking=True`。首次 pytest 被系统 ROS 插件自动加载且缺少 `lark` 阻断，设置
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 后正常通过。验证未连接机器人、未发送动作。

## 2026-07-20 20:41 CST - 恢复到 IDLE 后原地重新推理，不再复位

检查人：Codex。按用户要求修改 `scripts/cmds/openpi_p7_unlimited_recovery.sh`：首次
inference attempt 仍复位到指定初始关节位；任一 attempt 失败并通过 quick recovery 回到
`IDLE/idle/valid` 后，设置 `resume_in_place=1`。下一 attempt 跳过关节/夹爪 reset，直接在
当前 TCP pose 重新读取最新相机与 pose、请求新 OpenPI action chunk。失败 attempt 的内存
action chunk 仍丢弃，不重放。

离线验证使用 `/bin/true`、`/bin/false`，未连接机器人。连续失败的 3 秒 mock 中
`reset_count=1`、`resume_count=2`；日志两次出现
`skipping reset and resuming from the current pose`。首次 reset 故障注入中，quick recovery
成功后 attempt 2 跳过 reset 并完成。`bash -n` 通过。

## 2026-07-20 22:12 CST - 停止 arm_app-only OpenPI 推理

检查人：Codex。按用户要求停止 22:09 启动的 supervisor PID 205994 及子进程。supervisor
停止后 Python 子进程 PID 206195 未响应 TERM，首次批量 SIGKILL 因 zsh 标量不自动按换行
拆分而未命中；随后对 PID 206195 精确发送 SIGKILL。最终进程检查无
`openpi_p7_unlimited_recovery` 或 `openpi_p7_persistent_loop` 残留。X5 上仅保留用户要求的
left/right `/opt/arm_app/bin/arm_app` PID 2439/2440；未停止相机 daemon 或 79999 policy。

## 2026-07-20 22:18 CST - scripts/README.md 精简启动命令

检查人：Codex。新增 `scripts/README.md` 启动说明：X5 侧仅配置 can0/can1 并分别启动
`/opt/arm_app/bin/arm_app` 的 left/right 配置，不启动 `wcr_rc_app` 或额外 robot_app；本机
分三个终端启动 wrist-only 相机 daemon、`scripts/cmds/serve_policy.sh` 和 400 秒 supervisor。
复核确认 policy 脚本 checkpoint 为 wrist-only `79999`，推理命令显式传
`--no-servo-blocking --no-gripper-blocking`、正确 wrist latest-file 路径和 9mm 插值上限。

## 2026-07-20 22:25 CST - quick recovery 自动退出 SERVO_CONTROL

检查人：Codex。此前 quick recovery 只在 `fsm_state=IDLE` 且 controller 非 idle 时调用
`switch_controller(idle)`，因此残留的 `SERVO_CONTROL/csp` 会轮询超时。现已修改为：除
`UNKNOWN_ERROR` 仍优先 clear_error 外，只要 controller 非 idle，或 FSM 为
`SERVO_CONTROL/PLANNING_CONTROL`，就用 3000ms timeout 主动切到 `Controller.idle`。

实机验证时左臂初态为 `SERVO_CONTROL/csp/valid`，右臂为 `IDLE/idle/valid`。使用
`RESET_RUNNER=/bin/false`、`INNER_RUNNER=/bin/true` 故障注入运行 supervisor；左臂输出
`quick_recovery_switch_arm_idle True`，随后左右均为 `IDLE/idle/valid`，attempt 2 跳过
reset 并完成。该验证只切控制模式，没有发送运动或模型动作。`bash -n` 和静态分支检查通过。

`scripts/README.md` 同时新增手动重启：先 Ctrl+C 停止推理，在 X5 TERM/KILL 两条
`arm_app`，然后重新执行 X5 启动命令；不会启动其他板端应用。

## 2026-07-20 20:22 CST - 推理前复位同时打开左右夹爪

检查人：Codex。

目的：让 supervisor 每次执行双臂关节复位时，同时把左右夹爪打开，再进入模型推理。

实现：

- `scripts/cmds/move_p7_to_ready_joint_pose.sh` 固定传入 `--open-grippers`，默认打开目标
  `95 mm`、速度 `80 mm/s`、effort `5`；可分别用 `P7_GRIPPER_OPEN_MM`、
  `P7_EEF_SPEED_MM_S`、`P7_EEF_EFFORT` 覆盖。
- `examples/airbot/p7_move_to_joint_target.py` 增加 EEF 参数和控制流程。它先获取左右控制权，
  检查 EEF、切到 `EEFControlMode.csp` 并设置速度，再用 `ThreadPoolExecutor` 并发调用两侧
  blocking `move_eef([95.0])`。两侧都成功后才继续原有 planning PTP 关节复位。
- 任一夹爪准备或打开失败，整个复位返回失败，supervisor 不启动 inner inference。
  `finally` 会把已切换的 EEF 恢复到 idle，再恢复机械臂 controller idle 并释放控制权。

离线验证命令：

```bash
bash -n scripts/cmds/move_p7_to_ready_joint_pose.sh \
  scripts/cmds/openpi_p7_unlimited_recovery.sh
.venv-p7-sdk/bin/python -m py_compile examples/airbot/p7_move_to_joint_target.py
.venv/bin/ruff check --select E9,F examples/airbot/p7_move_to_joint_target.py
.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py --help
.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py \
  --open-grippers --gripper-open-mm 96
```

结果：bash、Python 编译、Ruff E9/F、CLI help 与 `git diff --check` 均通过；非法 `96 mm`
被门禁以退出码 `2` 拒绝。带 `threading.Barrier(2)` 的双 fake-client 测试输出
`PASS parallel_open=left,right target_mm=95 cleanup_tracking_on_speed_failure=true`，证明两侧
`move_eef` 并发进入、参数正确，且 CSP 后续失败仍会进入 idle 清理。完整 Ruff E/F 另报告
该文件原有 `final_error_rad` 日志行 `E501`（138 > 120），不是本次新增问题。

影响：后续运行当前 inference supervisor 时，每个 attempt 都会先真实移动双臂到指定关节位姿，
并同时打开两个夹爪；只有完整复位成功才开始模型推理。本轮只修改代码并使用 fake SDK 验证，
没有运行带 `--execute` 的 wrapper，没有连接或驱动真机。
## 2026-07-20 22:40 CST - recovery 语义核对与空格键回初始位（agent: Codex）

### 目的

核对当前实际入口 `scripts/cmds/openpi_p7_unlimited_recovery.sh` 在什么情况下执行
recovery、recovery 做什么，并为用户当前的 400 秒交互式执行命令增加“运行中按空格回到
初始位”的控制。

### 代码结论

当前 supervisor 首次启动时先调用 `move_p7_to_ready_joint_pose.sh`，把双臂复位到
`[0, 0.647, 0, -0.933, 0, 0, -1.15] rad` 并把双夹爪打开到默认 `95 mm`，然后才启动
`openpi_p7_persistent_loop.sh`。已有自动 recovery 只在以下路径触发：

- 推理子进程以非零状态退出，且退出码不是 `3`；`3` 表示实测运动/guard 违规，会直接停机，
  不自动恢复。
- 推理前关节复位失败。
- 用户按 `Ctrl-C` 停止时会做一次 quick cleanup，但不会自动回 ready pose。

quick recovery 逐臂新建 SDK client，读取 service state，并实际 acquire/release 一次控制权以排除
stale lease；遇到 `UNKNOWN_ERROR` 时调用 `clear_error()`，遇到 servo/planning 或其他非 idle
controller 时切到 `Controller.idle`。只有左右臂都达到 `IDLE/idle/valid` 才算成功。普通推理失败
恢复成功后不会回初始位，而是丢弃失败进程内的 action chunk，从当前位置重新采集观测、请求新
policy action 并重试；恢复失败则退出并要求人工处理。该脚本不会 SSH 重启或启动 X5 板端应用。

本次新增的空格键走独立的人工返回路径：只在 stdin 是交互 TTY 时启用，由 supervisor 主进程
轮询按键。运行中按空格后先向当前推理进程组发送 `SIGTERM`；persistent Python 显式把它
转换为清理请求并进入 `finally`，执行 controller idle 和 release control。等待 5 秒仍未退出
才升级为 `SIGKILL`。随后执行 quick recovery，确认双臂 `IDLE/idle/valid` 后再调用现有 ready-pose
planning PTP 复位并打开双夹爪。复位完成后 supervisor 丢弃被中断 attempt 的 action，重新采集
最新观测、请求新 policy action 并继续推理。quick recovery 失败时不会强行执行复位运动，推理
保持停止。非交互式重定向/nohup 运行没有 TTY，因此热键会明确禁用。

### 检查与验证

执行：

```bash
bash -n scripts/cmds/openpi_p7_unlimited_recovery.sh

RESET_RUNNER=/bin/true INNER_RUNNER=/bin/true SDK_PYTHON=/bin/true \
  LOCAL_LOG_DIR=/tmp/openpi_p7_hotkey_non_tty \
  bash scripts/cmds/openpi_p7_unlimited_recovery.sh

{ sleep 1; printf ' '; } | script -qfec \
  'RESET_RUNNER=/bin/true INNER_RUNNER=<blocking-mock> SDK_PYTHON=/bin/true \
   LOCAL_LOG_DIR=/tmp/openpi_p7_hotkey_tty bash scripts/cmds/openpi_p7_unlimited_recovery.sh' \
  /dev/null
```

关键输出：

```text
stdin is not an interactive terminal; space-key return is disabled
inference completed successfully on attempt=1

keyboard control enabled: press Space to return both arms to the initial pose and continue inference
space pressed; stopping inference before returning to the initial pose
mock inner SIGTERM cleanup
attempting quick SDK error clear
pre-inference joint reset completed
space-key return completed; recapturing observation and continuing inference
```

`bash -n`、ShellCheck、persistent-loop Python 编译、Ruff E9/F、非 TTY 成功路径和伪终端
空格路径均通过。验证中的 reset、inner runner 和 SDK 均为本地 mock；没有连接机器人、获取
控制权或下发真机动作。

2026-07-20 追加修改：按用户要求，空格复位成功后的语义由“退出 supervisor”改为“重新采集观测
并继续推理”。本次仅修改代码和文档，按用户要求未运行验证。

## 2026-07-20 23:09 CST - 同时显示左右最终送模图像（agent: Codex）

目的：模型推理期间常驻显示左右腕相机实际送模前的最终画面，包括推理所需的确定性图像变换。

代码链路核对：相机 daemon 把 `nv12/rgb8/bgr8/mono8` 统一解码成 `uint8 HxWx3 RGB`；当前
wrist-only inference 的 `AirbotInputs` 只解析 HWC/uint8，不做训练期 symmetry/channel
augmentation。服务端 `ResizeImages(224,224)` 使用 `openpi_client.image_tools.resize_with_pad`，
保持宽高比、双边填黑；`model.preprocess_observation(train=False)` 不执行随机 crop、rotate 或 color
jitter。模型随后把像素归一化到 `[-1,1]`，这不改变可视内容。因此可显示的最终几何输入是
224x224 RGB letterbox 图。

实现：`request_policy_from_observation_npz.py` 从本轮实际传给 `policy.infer()` 的同一个
observation 生成左右 224x224 预览，并原子写入 `policy_input_preview.npz`。常驻脚本
`show_openpi_policy_inputs.py` 使用 OpenCV 分别显示 `OpenPI Left Wrist Input` 和
`OpenPI Right Wrist Input`，仅为 OpenCV 显示执行 RGB->BGR。P7 loop 默认启动该预览进程，
现有运行命令无需改动；`--no-show-policy-input` 可显式关闭。P7 SDK venv 没有 cv2，主 venv 的
cv2 又是无 HighGUI 的 headless build，因此预览专用解释器默认使用已有 GUI OpenCV 4.6 的
`/usr/bin/python3`。预览进程若启动失败，会在机械臂 acquire control 前拒绝运行。

验证命令与结果：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  examples/airbot/request_policy_from_observation_npz_test.py
# 2 passed in 0.08s

/usr/bin/python3 examples/airbot/show_openpi_policy_inputs.py \
  --input /tmp/openpi_policy_preview_test.npz
xwininfo -root -tree | rg 'OpenPI (Left|Right) Wrist Input'
```

640x480 常量 RGB fixture 转换后左右均为 `uint8 (224,224,3)`，上下各 28 行黑边、中间 168 行
有效图像。X11 窗口树同时确认两个窗口，左窗口约在 `x=104`、右窗口约在 `x=948`，左右并排；
关闭后无预览进程残留。Python 编译、Ruff E9/F、`git diff --check` 均通过。本轮仅使用合成图像
验证 GUI，没有连接机器人、读取实时相机或运行模型。

## 2026-07-20 23:12 CST - tokenizer 打印实际 prompt（agent: Codex）

核对 `training/config.py` 的当前 PI0.5 wrist-only 配置确认推理使用
`PaligemmaTokenizer`，入口为 `src/openpi/models/tokenizer.py::PaligemmaTokenizer.tokenize()`。
现已在 prompt 执行 `strip()`、下划线转空格和换行转空格之后增加即时输出：
`[PaligemmaTokenizer] prompt='...'`。因此重启 policy server 后，每次模型请求都会在服务端终端
打印模型实际编码的任务文本；未给不参与当前 PI0.5 推理的 FAST/Binning/FSQ tokenizer 增加输出。

## 2026-07-20 23:28 CST - 优雅停止、自动 idle 与孤儿进程防护（agent: Codex）

### 现场根因

只读进程检查发现 3 个 `openpi_p7_persistent_loop.py` 仍在运行：PID `214681/251343/263473`，
启动时间分别为 `22:28:26/22:59:09/23:16:11`，PPID 均为桌面进程 `2051`，且各自拥有独立
PGID/SID。检查时它们已存活约 `60/29/12min`，远超命令中的 `duration-s=387/384/380`；对应
supervisor 已不存在。这证明旧实现会在 supervisor 异常消失时留下孤立控制 loop，并非正常预算
运行。`23:14:34` 和 `23:14:40` 的两次新启动因此读到 right
`SERVO_CONTROL/csp`，随后 quick recovery 的 left acquire 返回
`RESOURCE_EXHAUSTED: controller already held`，最终要求 manual recovery。这是用户反复需要重启的
直接软件原因。

本次没有终止这 3 个既有进程，也没有连接或控制机器人；它们是修改前启动的旧代码，需要用户明确
执行一次新 stop 入口清理。

### 新停止协议

- 交互终端按 `Q`：supervisor 请求当前 persistent loop 清理退出；按空格的“回初始位后继续推理”
  语义保持不变。
- 任一 OpenCV 输入窗口按 `Q` 或 `Esc`：窗口进程通知其 persistent-loop parent 执行同一清理。
- persistent loop 捕获 `SIGTERM` 后进入 `finally`，先关闭预览，再把已启用的 EEF controller 和
  arm controller 切到 idle，最后 release control。停止专用 controller timeout 默认每侧 `3s`，
  supervisor 正常等待上限由 `5s` 增加为 `25s`，避免清理尚未完成就被 SIGKILL。
- supervisor 二次 acquire/release 并严格验证左右 arm 都为 `IDLE/idle/valid`，同时左右
  `get_eef_mode().current_mode_name == idle`；全部通过才以成功结束。
- Linux persistent loop 设置 `PR_SET_PDEATHSIG=SIGTERM`，并核对
  `OPENPI_P7_SUPERVISOR_PID`。supervisor 被外部强杀或工具异常终止时，内核会自动通知 child 走
  cleanup，不再成为桌面进程收养的孤儿。
- supervisor 新增 `flock` 单实例锁，并在启动前拒绝任何已存在的
  `openpi_p7_persistent_loop.py`，避免多个 reset/inference 同时争抢控制权。

新增 `scripts/cmds/stop_openpi_p7_inference.sh`，用于另一个终端或清理旧孤儿：只匹配明确的 OpenPI
P7 supervisor/control 进程；有 supervisor 的 child 仅由 supervisor 发一次信号，真正孤儿才按独立
PGID 停止；等待 `25s` 后才对仍残留的独立 control PGID 强制终止。最后调用
`examples/airbot/p7_ensure_idle.py`，重试 acquire、切 EEF/arm idle、release，并严格复核双侧 idle。
该入口不 SSH、不启动或重启 X5 应用。命令：

```bash
ROBOT_HOST=192.168.25.1 bash scripts/cmds/stop_openpi_p7_inference.sh
```

### 离线验证

`bash -n`、Python compile、Ruff E9/F、`git diff --check` 通过；系统没有 `shellcheck`，该项未执行。
全 mock 伪终端测试输出 `Q pressed`、`mock inner cleanup complete`、`graceful stop completed`；stop
脚本无进程路径通过；持有测试 lock 时第二个 supervisor 正确拒绝并返回 `rc=2`。Linux fork mock
中父进程退出后 child 在 `0.2s` 内输出 `child received SIGTERM`，验证 parent-death signal 生效。
EEF mode 纯函数检查覆盖 `idle/csp/no-eef`。所有验证均未连接机器人，也没有触碰当前 3 个旧进程。

边界：普通用户停止、supervisor 消失和 stale lease 属于本机制可恢复范围；电机 bit error、过流、
通信丢失导致的真实 `UNKNOWN_ERROR` 仍可能无法由当前 SDK placeholder `clear_error()` 清除，不能承诺
用软件 idle 代替硬件故障处理，但停止入口也不会因此擅自重启板端应用。

### 2026-07-20 23:35 CST 补充核对

并发合入 ROS2 内存采集路径后重新核对主循环：`capture_fresh_rgb()` 返回的同一个 `images` 字典，
先经 `resize_with_pad(..., 224, 224)` 写入左右 OpenCV 预览，再原样交给 `request_policy()`；旧的
`capture_observation()`/NPZ policy subprocess 调用已不存在。Python compile、Ruff E9/F、Bash
`-n` 和 `git diff --check` 再次通过。

同时补严两个停止结果：推理正常到时/迭代完成后，supervisor 也必须重新 acquire/release 并严格
确认双 arm 与双 EEF idle，才返回成功；独立停止脚本现在会传播 `p7_ensure_idle.py` 的失败，不再在
idle 校验失败时误打印成功或返回 0。系统仍未安装 ShellCheck。检查仅为本地只读/静态验证，没有
连接机器人，也没有停止 PID `214681/251343/263473`。

## 2026-07-21 00:24 CST - 更新常驻推理默认 task name（agent: Codex）

- **目的**：确认真机推理的文字 task name 从哪里进入模型，并将当前默认值更新为用户指定文本。
- **检查命令**：

  ```bash
  rg -n "prompt|PaligemmaTokenizer" \
    examples/airbot/openpi_p7_persistent_loop.py \
    src/openpi/models/tokenizer.py \
    src/openpi/transforms.py
  ```

- **结论与修改**：常驻入口的 `--prompt` 在
  `examples/airbot/openpi_p7_persistent_loop.py` 定义，并随每次 observation 发给 policy server；
  `TokenizePrompt` 最终调用 `PaligemmaTokenizer.tokenize()`。默认 task name 已改为
  `collect plant observations with dual-arm wrist cameras`。命令行显式传入的 `--prompt` 仍优先于默认值。
- **可观测性**：`src/openpi/models/tokenizer.py` 当前会在服务端输出
  `[PaligemmaTokenizer] prompt='...'`，因此实际收到的文字 task name 可直接在
  `scripts/serve_policy.sh` 创建的日志中确认。
- **影响**：不改变模型、图像、动作或控制参数，只改变未显式传 `--prompt` 时的文字任务描述。
- **验证**：Ruff 致命错误范围（`E9,F63,F7,F82`）通过；AST 读取输出
  `prompt_default='collect plant observations with dual-arm wrist cameras'`；
  `git diff --check` 通过。完整 Ruff 另报告该文件原有的 8 条非致命告警，本次未做无关整理。
  两次组合验证命令分别因 Ruff 非零后的 `&&` 和 heredoc 写法未完成，改用单行 AST 命令后
  验证成功。

## 2026-07-21 01:10 CST - recovery 循环且未调用模型的原因（agent: Codex）

- **目的**：确认当前真机任务为何持续进入 quick recovery、没有产生模型推理。
- **运行态证据**：当前 recovery supervisor PID 为 `300938`，其启动参数仍包含：

  ```text
  --capture-mode latest-file
  --latest-obs-npz /tmp/openpi_cam_daemon_wrist/latest.npz
  --latest-obs-meta /tmp/openpi_cam_daemon_wrist/latest.json
  ```

  每次启动内层推理时都立即输出：

  ```text
  REFUSE: --capture-mode latest-file is retired; use --capture-mode ros2 and do not run the camera daemon
  ```

  随后内层 runner 以 `rc=2` 退出，发生在相机采集和 `policy.infer()` 之前。外层 supervisor
  没有区分该命令行/配置错误与真机控制错误，仍执行 quick SDK recovery；左右臂检查实际反复为
  `IDLE/idle/valid`，恢复结束后再次用相同废弃参数拉起，因而形成无限循环。
- **排除项**：本机 policy server PID `119852` 仍监听 `:8000`；本次现象不是模型服务未启动。
  板端已去重后的进程为 left `arm_app` PID `185775`（`:50071`）、right `arm_app` PID
  `185776`（`:50072`）、`robot_app` PID `185777`。所需 ROS2 相机话题为
  `/robot/camera/left_wrist/left/image` 和 `/robot/camera/right_wrist/left/image`。
- **结论**：模型没有被调用的直接原因是启动命令过期。应停止 PID `300938`，改用
  `--capture-mode ros2`，并删除两个 `--latest-obs-*` 参数；`scripts/README.md` 已有正确命令。
  此外 supervisor 应把 `rc=2` 视为不可 recovery 的配置错误并直接退出，避免健康机械臂被反复
  acquire/release。
- **本次动作边界**：只做诊断和记录，没有停止 supervisor、重启板端应用、清错或发送运动指令。

## 2026-07-21 01:17 CST - 仅复位双臂并保持推理停止（agent: Codex）

- **用户指令**：先要求“复位，再开始”，随后明确改为“不用检查，现在安全，直接复位，不要再开始”。
  因此最终只执行复位，没有重新启动 inference supervisor。
- **起始状态**：上一轮 ROS2 推理已实际运行到 iteration 37；按 Space 停止后，标准 PTP 复位因
  左臂最大关节差约 `2.97 rad` 超过 `1.5 rad` guard 而拒绝。尝试的低速 planning PTP 返回
  `move_joint=False`，未移动。servo 初次尝试又依次暴露左臂 joint2、joint5、joint6 的读数略在
  SDK 命令限位之外；相关命令均被 SDK 整体拒绝，控制权正常释放。
- **执行**：先用 `examples/airbot/p7_servo_move_to_joint_target.py` 将左臂越界轴退入命令范围，
  再以 `max-step-rad=0.04`、`speed-rad-s=0.55` 将双臂小步移动至
  `[0,0.647,0,-0.933,0,0,-1.15]`，最后以 `max-step-rad=0.02`、`settle-s=0.15`
  补一次短距离收敛。
- **结果**：左臂最终最大关节误差 `0.010498 rad`，右臂 `0.013217 rad`；两侧最终均为
  `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`，lease
  已释放。没有启动 supervisor、没有请求模型推理，也没有重启板端应用。本次 servo 复位工具
  只控制机械臂关节，未执行夹爪开合。

## 2026-07-21 09:24 CST - 再次直接复位被 arm gRPC 不可用阻断（agent: Codex）

- **用户指令**：不做额外检查，直接复位；不涉及启动推理。
- **实际命令**：三次执行 `examples/airbot/p7_servo_move_to_joint_target.py`，目标仍为
  `[0,0.647,0,-0.933,0,0,-1.15]`，参数为 `--max-step-rad 0.02 --speed-rad-s 0.55
  --settle-s 0.15 --execute --allow-robot-motion`。前两次使用 `192.168.25.1`，第三次使用同一台
  X5 的管理地址 `172.100.10.159`。
- **结果**：三次均在创建左臂 SDK client 时超时，分别为
  `Timeout connecting to 192.168.25.1:50071` 和
  `Timeout connecting to 172.100.10.159:50071`。失败发生在 acquire/control/move 之前，未向
  任一机械臂发送运动命令，因而本轮没有发生复位或重复动作。
- **影响**：当前 `arm_app` gRPC 服务不可达。考虑到此前出现过板端重复进程，在未核对现有实例
  前没有盲目拉起另一套板端控制应用；推理 supervisor 也没有启动。

## 2026-07-21 09:30 CST - 重试复位仍被左右 arm gRPC 阻断（agent: Codex）

- **目的与命令**：按用户“再尝试复位”指令，继续用同一 servo 小步复位命令，目标为
  `[0,0.647,0,-0.933,0,0,-1.15]`；先尝试有线双臂两次，再尝试无线右臂一次，最后尝试有线
  左臂一次。
- **结果**：第一次双臂 client 创建过程中左臂连接成功、右臂 `192.168.25.1:50072` 超时；
  第二次右臂同样超时。`172.100.10.159:50072` 也超时；最后
  `192.168.25.1:50071` 再次超时。所有失败均发生在 client 初始化阶段，未 acquire control，
  未下发关节运动，左右臂本轮都没有移动。
- **结论**：左右 `arm_app` gRPC 服务当前均不稳定或不可用，无法通过 SDK 完成复位。没有启动
  inference supervisor，也没有在未知进程状态下启动新的板端应用实例。

## 2026-07-21 09:32 CST - 再次复位中左臂进入 UNKNOWN_ERROR（agent: Codex）

- **执行**：再次运行双臂 servo 小步复位，目标
  `[0,0.647,0,-0.933,0,0,-1.15]`，`max-step-rad=0.02`、`speed-rad-s=0.55`、
  `settle-s=0.15`。本次左右 gRPC client 均成功建立。
- **结果**：左臂从
  `[-0.1058,0.8283,-0.2119,-0.5223,-2.8603,-0.7731,1.1855]` 开始，共规划 144 个
  servo waypoint；第 1 至 91 步返回 True，第 92 步返回 False，随后状态为
  `UNKNOWN_ERROR/csp/valid`。程序释放左臂 lease 后退出，右臂尚未开始移动。
- **停止清理**：执行 `ROBOT_HOST=192.168.25.1 bash scripts/cmds/stop_openpi_p7_inference.sh`。
  左臂 `clear_error=True`，但 EEF/arm 切 idle RPC 被当前 `UNKNOWN_ERROR` 拒绝；最终左臂为
  `UNKNOWN_ERROR/idle/valid`，左 EEF 为 idle。右臂及右 EEF 均为 idle。所有 lease 已释放，
  没有继续复位或启动推理。
- **结论**：本次发生了部分左臂复位运动，但未完成目标；左臂错误无法由当前 SDK placeholder
  clear_error 清除，需要板端或硬件侧恢复后再复位。

## 2026-07-21 09:45 CST - 整理手动启动 OpenPI 真机推理环境（agent: Codex）

- **目的**：为手动启动提供可复制的环境分工、启动顺序和命令，避免再次把板端控制进程、策略服务
  与 ROS2 客户端混在同一环境或重复启动。
- **文档更新**：在 `scripts/README.md` 增加环境表：X5 root 终端负责 `arm_app`/`robot_app`；
  GPU 工作站终端 1 运行策略服务（wrapper 内部 `uv run`/`.venv`）；GPU 工作站终端 2 运行
  推理客户端（wrapper 内部 `.venv-p7-ros/bin/python`）。推理示例显式设置
  `ROS_DOMAIN_ID=0`、`RMW_IMPLEMENTATION=rmw_fastrtps_cpp`，并明确使用 `--capture-mode ros2`。
- **运行态核对**：本次被用户中断后的复位进程已不存在；策略服务 PID `119852` 仍监听 `:8000`；
  没有 `openpi_p7_unlimited_recovery` 或 `openpi_p7_persistent_loop` 残留。该核对未启动、停止或
  控制任何机器人进程。

## 2026-07-21 10:42 CST - 空格回初始位被 1.5rad 关节差保护拒绝（agent: Codex）

- **目的**：定位用户运行 `openpi_p7_unlimited_recovery.sh` 后出现
  `pre-inference joint reset failed rc=1`、`space-key return failed` 的原因。
- **检查命令**（只读，未连接或控制机器人）：

  ```bash
  sed -n '1,240p' logs/openpi_p7_recovery_20260721_103816.log
  tail -n 80 logs/openpi_p7_recovery_20260721_103816.log
  rg -n -- '-1\.15|0\.647|-0\.933|max-joint-delta' scripts examples docs
  ```

- **首次复位证据**：10:38:16 双臂均为 `IDLE/idle/valid`。右臂当前关节为
  `[0.471343,0.183609,0.739228,-0.468440,2.153254,0.399962,1.180806]`，到标准目标
  `[0,0.647,0,-0.933,0,0,-1.15]` 的 joint5/joint7 差值分别约 `-2.153254/-2.330806rad`。
  `move_p7_to_ready_joint_pose.sh` 固定传入 `--max-joint-delta-rad 1.5`，因此本地脚本在获取控制权
  和下发 PTP 前主动报 `FAIL: right: max joint delta exceeds guard 1.500000 rad`。这不是 policy
  WebSocket、ROS2 相机或 P7 controller 故障。
- **控制流证据**：首次复位失败后 quick recovery 只确认左右臂仍为 `IDLE/idle/valid`，supervisor
  随即在 10:38:24 输出 `skipping reset and resuming from the current pose` 并启动 attempt 2。
  因而当前实现会在“复位因关节差保护被拒绝”时仍从非初始姿态开始推理，和“首次必须复位成功”
  的预期不一致。
- **空格复位证据**：10:38:38 按空格后推理进程正常清理并释放控制权。10:38:49 再次复位时，
  左臂当前 joint5/joint7 到目标的差值约 `2.345577/-2.076860rad`，再次超过同一 `1.5rad` 保护，
  所以输出 `space-key return failed; inference remains stopped`。此路径按设计没有继续推理。
- **结论与影响**：报错的直接原因是当前姿态离 ready 目标超过固定保护阈值，而不是控制器未就绪。
  在确认工作空间和大角度回位路径安全前，不应简单删除或全局放宽保护。应先用受控的小关节步进
  回到 ready 附近，或另行确认并显式提高仅本次回位的阈值。另需修正 supervisor：首次复位失败
  不应因为 quick recovery 健康就跳过复位启动策略。

## 2026-07-21 10:44 CST - 用户确认后将 ready 回位关节差阈值提高到 3.0rad（agent: Codex）

- **用户确认**：用户明确确认增大回位脚本的本地安全阈值是安全的。
- **修改**：`scripts/cmds/move_p7_to_ready_joint_pose.sh` 的
  `--max-joint-delta-rad` 从 `1.5` 改为 `3.0`。标准目标
  `[0,0.647,0,-0.933,0,0,-1.15]`、planning PTP、速度/加速度缩放和夹爪参数均未改变。
  `3.0rad` 覆盖 10:38 日志中的最大关节差 `2.345577rad`。
- **离线验证**（未连接机器人、未下发动作）：

  ```bash
  bash -n scripts/cmds/move_p7_to_ready_joint_pose.sh
  SDK_PYTHON=/bin/echo P7_HOST=example.invalid P7_SIDE=both \
    bash scripts/cmds/move_p7_to_ready_joint_pose.sh
  git diff --check -- scripts/cmds/move_p7_to_ready_joint_pose.sh
  ```

  语法和 diff 检查通过；参数展开明确包含 `--max-joint-delta-rad 3.0`、`--execute` 和
  `--allow-robot-motion`。验证用 `/bin/echo` 替代 SDK Python，因此没有建立 P7 连接或执行运动。
- **影响**：下一次 recovery 首次复位或空格回位时，本地 guard 不再拒绝最大单关节差不超过
  `3.0rad` 的 ready PTP；SDK 关节限位、规划器和控制器自身检查仍然生效。

## 2026-07-21 10:56 CST - 强制停止残留 ready PTP 与板端 trajectory 状态（agent: Codex）

- **目的**：用户反馈当前脚本未被杀死，要求停止。
- **本地进程证据**：supervisor 和 persistent loop 已不存在，但仍有独立进程组 PID/PGID `15867`
  运行 `p7_move_to_joint_target.py ... --max-joint-delta-rad 3.0 --execute`。仓库
  `stop_openpi_p7_inference.sh` 只匹配 supervisor/persistent loop，不匹配该 ready PTP 子进程。
- **停止动作**：向进程组 `-15867` 发送 `SIGTERM`，进程立即消失，未使用 `SIGKILL`。但该 Python
  程序没有 SIGTERM 清理 handler；信号发生在 blocking PTP 内时，板端 trajectory 和 60 秒 lease
  不会随本地进程同步取消。
- **控制器收尾**：首次 idle 清理因旧 lease 返回 `RESOURCE_EXHAUSTED/controller already held`。
  lease 超时后左臂成功回到 `IDLE/idle`；右臂持续为 `PLANNING_CONTROL/csp`，切 idle 被拒绝并明确
  返回 `switch out of PLANNING_CONTROL is rejected while trajectory is executing`。
- **急停**：SDK 无普通 cancel trajectory API，因此对右臂 50072 获取新 lease 后调用
  `set_arm_emergency_stop(True)`，成功进入 `EMERGENCY_STOPPED/csp` 并中止持续 trajectory；随后按
  SDK 示例调用 `set_arm_emergency_stop(False)`，状态转为 `UNKNOWN_ERROR/csp`。`clear_error()` 返回
  True，但状态未清除，`switch_controller(idle)` 被当前 FSM 拒绝；最后释放 lease。
- **最后已知状态**：所有本地 recovery、persistent loop 和 ready PTP 进程均已停止；左臂为
  `IDLE/idle`，右臂运动已被急停中止，但最后回读为 `UNKNOWN_ERROR/csp/valid`，需要板端/硬件侧
  恢复后才能重新进入 idle。未重启或停止 X5 的 `arm_app`/`robot_app`。
- **实现影响**：ready PTP 需要显式处理 SIGTERM，并在停止时调用能取消板端 trajectory 的接口；
  当前 SDK 未暴露普通 cancel API，仅依靠 `finally` 切 idle 无法覆盖客户端在 blocking RPC 中被终止
  的场景。

## 2026-07-21 11:30 CST - production ready 回位改为 SDK blocking servo（agent: Codex）

- **用户约束**：禁止 production 回位使用 planning；全部改用高级 SDK servo。不得在客户端实现
  闭环或拆分 waypoint，必须使用 SDK `blocking=True`，等待 SDK 内部闭环完成后返回。
- **SDK 依据**：只读核对 SDK 自带 `airbot_example_move_joint_SERVO.py`，标准流程为
  `acquire_control()`、`switch_controller(Controller.servo_control)`、`set_arm_speed()`，随后单次
  `move_joint(final_target, JointMoveOptions(eff=..., blocking=True))`，最后切 idle 并关闭 client。
- **实现修改**：
  - `examples/airbot/p7_move_to_joint_target.py` 删除 planning 的 `motion_type=ptp`、velocity/
    acceleration scaling 和 planning time；改为每侧 `servo_control`、`set_arm_speed([0.55]*7)`，
    仅调用一次最终目标 `move_joint()`，`JointMoveOptions(eff=[8]*7, blocking=True)`。
  - 保留 SDK 关节限位、用户确认的 `3.0rad` 本地最大关节差、左右顺序执行、双夹爪打开和只读
    trajectory 采样；采样线程不生成命令、不参与闭环。
  - `move_p7_to_ready_joint_pose.sh` 改传 `P7_ARM_SPEED_RAD_S`/`P7_ARM_EFFORT`；recovery 改用
    `RESET_ARM_SPEED_RAD_S=0.55`/`RESET_ARM_EFFORT=8`，删除 reset planning scaling 参数。
  - production 推理仍按用户启动参数使用 `--controller servo --no-servo-blocking` 流式 action；
    本次只把 ready 回位改成 blocking servo。独立 planning precision probe 是历史诊断工具，
    不在 production recovery 调用链中。
- **离线验证**（未连接机器人、未下发动作）：

  ```bash
  python -m py_compile examples/airbot/p7_move_to_joint_target.py
  bash -n scripts/cmds/move_p7_to_ready_joint_pose.sh scripts/cmds/openpi_p7_unlimited_recovery.sh
  SDK_PYTHON=/bin/echo P7_HOST=example.invalid P7_SIDE=both \
    bash scripts/cmds/move_p7_to_ready_joint_pose.sh
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    PYTHONPATH=.venv-p7-sdk/lib/python3.11/site-packages \
    .venv/bin/pytest -q examples/airbot/p7_move_to_joint_target_test.py
  .venv/bin/ruff check examples/airbot/p7_move_to_joint_target.py \
    examples/airbot/p7_move_to_joint_target_test.py
  ```

  参数展开只包含 `--speed-rad-s 0.55 --effort 8 --max-joint-delta-rad 3.0`，无 planning 参数。
  mock 单测 `1 passed`，逐臂断言 controller 顺序仅为 `servo_control -> idle`、最终目标只提交一次、
  `blocking is True`、effort 为 `[8]*7` 且 lease 已释放。Ruff、Python 编译、shell 语法和 diff
  whitespace 检查通过。
- **环境说明**：`.venv-p7-sdk` 没有安装 pytest/ruff；测试使用仓库 `.venv` 的测试工具，并通过
  `PYTHONPATH` 只读加载 `.venv-p7-sdk` 中已验证的私有 SDK。禁用 pytest 自动插件加载以避开工作站
  ROS Jazzy 插件的无关 `lark` 缺失。没有安装或修改依赖。
