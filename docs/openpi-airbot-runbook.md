# OpenPI -> AIRBOT 真机运行手册

更新时间：2026-07-09 21:19 CST
维护人：agent/Codex

本文保留历史路线，但当前推荐的正式启动方式已经改为 **统一混合 runtime**：用新版 `/opt/arm_dual_app` 控制左右臂，同时只启动旧 `/opt/robot_app` 的 `remote` 进程提供相机/remote DDS topic。

- **当前推荐路线**：X5 `/root/start-arm-dual-app-2arm.sh` 一次启动 `arm_dual_app left_arm`、`arm_dual_app right_arm` 和 `robot_app remote only`。控制走 SDK gRPC，左臂 `50071`、右臂 `50072`；相机走 `robot_app remote` 发布的 ROS2/DDS topic；三者统一到 DDS domain `0`。
- **旧 AIRRTM 路线**：本机 OpenPI / AIRRTM sender -> 远端 X5 `/opt/robot_app` 三进程 -> 左右机械臂。只在需要复现旧摇操/AIRRTM 链路时使用。
- **纯新版 SDK gRPC 路线**：只启动 `/opt/arm_dual_app` 左右臂，不启动 `robot_app remote`。这能控制臂，但没有完整相机 topic，不适合作为 OpenPI 实机推理入口。

当前不要走裸 DDS，也不要让旧 `/opt/robot_app` 的 `left_arm/right_arm` 与新版 `/opt/arm_dual_app` 同时接 CAN。

## 0. 当前链路和边界

旧 AIRRTM 控制链路：

```text
OpenPI policy server, or JSON/mock action
  -> examples/airbot/policy_to_airrtm_bridge.py / airrtm_servo_dryrun.py
  -> local ZMQ PUB tcp://0.0.0.0:6000 topic=servo
  -> airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml
  -> AIRRTC room rtm_sender_room_1（以 X5 当前 /opt/robot_app/configs/remote/airrtm_config.json 为准）
  -> X5 robot_app remote
  -> left_arm/right_arm
```

当前 action 语义：

```text
action[0:7]   = left  dx,dy,dz, drot_x,drot_y,drot_z, gripper
action[7:14]  = right dx,dy,dz, drot_x,drot_y,drot_z, gripper
单位：dx/dy/dz 为米，drot 为 rotvec 弧度，gripper 为模型约定 0-100（0 闭合，100 最大打开）
```

当前 OpenPI 到机械臂的边界：

- `policy_to_airrtm_bridge.py --action-source policy` 可以请求 OpenPI policy server，拿到 `actions`，并把其中一行转换成 AIRRTM `servo_pose`。
- `examples/airbot/policy_to_p7_sdk_bridge.py` 可以在 `.venv-p7-sdk` 中读取 action JSON、读取当前双臂 TCP、把 relpose action 转成 Arm-P7 SDK target；默认 dry-run，显式 `--execute --allow-robot-motion` 才会运动。2026-07-08 已完成一次真实单步 servo。
- `examples/airbot/capture_ros2_openpi_observation.py` 可以在 ROS2 环境订阅图像并导出 OpenPI observation `.npz`；`examples/airbot/request_policy_from_observation_npz.py` 可以在 OpenPI/uv 环境读取 `.npz` 请求 policy 并导出 action JSON。
- 单帧 **real camera observation -> policy** dry-run 已完成：2026-07-08 17:07 CST，用户用旧 `bash start-robot-app-3arm.sh` 启动 X5 `/opt/robot_app` 三进程后，本机 ROS2 成功收到正式三路左目 `head_left/left_arm_left/right_arm_left` 的 `nv12 640x352` 图像，并请求 OpenPI policy 返回 `actions` 形状 `(50, 32)`。
- 单帧 **real camera observation -> policy -> P7 SDK servo control** 完整 smoke 已完成：2026-07-08 18:44 CST，在统一 runtime 下抓三路相机，OpenPI 返回 `(50,32)` action chunk，`policy_to_p7_sdk_bridge.py` 先 dry-run 通过，再以 `--max-translation-step-m 0.005 --max-rotation-step-rad 0.02 --execute --allow-robot-motion` 执行 action index 0。实际只发送 TCP pose，不控制夹爪；左臂移动约 `0.000483m`，右臂约 `0.001373m`，最终左右臂均回到 `IDLE/idle/valid`。
- 多轮 **closed-loop 脚本** 已落地并验证：2026-07-08 18:51 CST 新增 `scripts/cmds/openpi_p7_closed_loop.sh`，默认 dry-run，按顺序编排 ROS2 相机抓帧、OpenPI policy 请求和 P7 SDK bridge。2 轮 dry-run 成功，随后 1 轮 `--execute --allow-robot-motion` 成功；左臂移动约 `0.000822m`，右臂约 `0.001108m`，最终左右臂均回到 `IDLE/idle/valid`。
- **夹爪控制已补到 P7 SDK bridge 和低频 closed-loop wrapper，并完成真实 smoke**：2026-07-09 11:53 CST，`examples/airbot/policy_to_p7_sdk_bridge.py` 与 `scripts/cmds/openpi_p7_closed_loop.sh` 增加 `--enable-gripper`。默认仍不控制夹爪；只有同时给出 `--enable-gripper --execute --allow-robot-motion` 时才会进入 `EEFControlMode.csp` 并调用 `move_eef()`。模型夹爪值沿用训练定义 `0=闭合、100=最大打开`，执行到 P7 SDK 时转换为 mm 并默认 clamp 到 `[0,95]mm`。2026-07-09 13:46 CST 已真实执行 open->close->open，左右夹爪 `move_eef()` 均返回 `ok=True`，方向确认正确。
- **常驻 OpenPI -> P7 控制循环已补入口并完成 dry-run 与真实执行**：2026-07-09 11:53 CST 新增 `examples/airbot/openpi_p7_persistent_loop.py` 和 `scripts/cmds/openpi_p7_persistent_loop.sh`。它在 P7 SDK Python 里保持双臂 `AirbotClient`、控制权、controller mode 和可选 EEF mode 常驻；相机抓帧仍调用 `/usr/bin/python3` 的 ROS2 脚本，policy 请求仍调用 `uv run python`。2026-07-09 12:42 CST 已完成 1 轮相机 -> policy -> P7 SDK dry-run；13:48 CST 已完成 20 秒真实闭环 smoke；15:49 CST 在用户确认实验场景清空、物体在相机视野内后完成 60 秒真实闭环，31 次 action 执行，TCP 与夹爪均返回成功，最终释放控制并回到 `IDLE/idle/valid`。
- 左臂姿态对齐右臂已做一次现场辅助：2026-07-08 19:09 CST 新增 `examples/airbot/p7_align_left_orientation_to_right.py`，使用 P7 SDK 只调整左臂 TCP orientation。左/右姿态差从约 `0.162rad / 9.3deg` 降到稳定复查约 `0.026rad / 1.5deg`。继续追 0 度会引入厘米级 TCP 位置耦合，不建议在未加位置恢复/规划约束前继续硬推。
- P7 SDK 连续 servo smoke 已完成：2026-07-08 20:04 CST 新增 `examples/airbot/p7_continuous_servo_smoke.py`，默认 dry-run，真实执行需 `--execute --allow-robot-motion`。最终成功参数为 `--duration-s 25 --rate-hz 5 --radius-m 0.008 --arm-speed-rad-s 0.55`，使用非阻塞 `move_end_pose()`；实测 126 帧、`26.21s`，左/右最大 TCP 偏离约 `0.0091m/0.0100m`，最终回起点误差约 `0.00019m/0.00031m`，双臂回到 `IDLE/idle/valid`。
- 现场左右映射注意：2026-07-08 22:40 CST 用户现场观察表明，SDK 逻辑名/配置名可能和物理左右相反：`50071`（配置名 left_arm）实际驱动了用户看到的右臂；`50072`（配置名 right_arm）更像物理左臂。该路重启后 motor4 曾为 `73°C`，10 秒后仍为 `66°C`。后续现场命令应同时写清 SDK 端口和物理侧，不要只按 `left/right` 字面理解。
- 注意区分运行方式：2026-07-08 14:06 CST 的 mixed runtime 下只看到 `left_arm_left/left_arm_right` 两路相机 publisher，`head_*` 和 `right_arm_*` 初始化 `attach_to_vin failed`；17:07 CST 旧 `/opt/robot_app` 三进程完整启动后，正式三路相机已恢复。

新版 SDK planning 控制链路：

```text
本机 .venv-p7-sdk / arm_p7_sdk 1.1.2
  -> AirbotClient(host=192.168.25.1, port=50071, backend="grpc")  # left
  -> AirbotClient(host=192.168.25.1, port=50072, backend="grpc")  # right
  -> X5 /opt/arm_dual_app left_arm/right_arm
  -> Controller.servo_control + move_end_pose(...) 或 Controller.planning_control + move_end_pose_linear(...)
```

### 0.1 2026-07-06 新版软件包状态

已解包 `~/Downloads/AIRBOT-ARM-P7-SW-2026-07-06-11-28-30.tar.gz`，其中和当前路线相关的内容是：

- `components/sdk_client/arm_p7_sdk-1.1.2-py3-none-any.whl`
- `components/sdk_client/sdk-board-bundle-arm_p7_sdk-1.1.2-py3-none-any-20260626114111.tar.gz`
- `components/arm_p7/arm_dual_app_0.3.7_20260703145313_arm64.deb`
- 固件包也在压缩包里，但本轮没有刷 sensor hub 或 motor board 固件。

本机已更新独立 SDK 环境：

```bash
uv pip install --python .venv-p7-sdk/bin/python --reinstall --no-deps \
  /tmp/airbot_p7_sw_20260706/AIRBOT-ARM-P7-SW-2026-07-06-11-28-30/components/sdk_client/arm_p7_sdk-1.1.2-py3-none-any.whl
.venv-p7-sdk/bin/python -c 'import arm_p7_sdk; print(arm_p7_sdk.__version__)'
# arm-p7-sdk 1.1.2
```

X5 已安装新版包：

```bash
ssh root@192.168.25.1 "cd /userdata/p7_sw_20260706 && dpkg -i arm_dual_app_0.3.7_20260703145313_arm64.deb"
ssh root@192.168.25.1 "cd /userdata/p7_sw_20260706 && tar -xzf sdk-board-bundle-arm_p7_sdk-1.1.2-py3-none-any-20260626114111.tar.gz && bash sdk-board-bundle/install.sh"
```

关键输出：X5 `arm_dual_app 0.3.7` 已安装到 `/opt/arm_dual_app`；board bundle smoke test 显示 `cora version: 1.2.2+20260626085518`、`arm-p7-sdk version: 1.1.2`、`smoke test ok`。安装时出现过 `colcon-core` 与 `setuptools 82.0.1` 的版本告警，但 SDK smoke 通过；后续如果要在 X5 上跑 colcon，再单独处理这个 Python 包版本问题。

2026-07-08 18:28 CST 更新：X5 `/root/start-arm-dual-app-2arm.sh` 已改为统一入口。它会先确保 `/opt/arm_dual_app/configs/{left_arm,right_arm}/framework_config.json` 的 `dds.domain_id=0`，再启动 left=`arm_dual_app/can0/50071`、right=`arm_dual_app/can1/50072`，最后启动 `/opt/robot_app/configs/remote/project_config.json`。实测当前后台进程为 `arm_dual_app` 两个和 `robot_app remote` 一个；本机能在 `ROS_DOMAIN_ID=0` 下看到三路相机和左右臂 `/arm/*/fsm/joint_state`，SDK no-motion dry-run 通过。



## 0.2 一次完整 OpenPI 抓取放置测试流程（现场照抄版）

适用场景：机械臂已上电、实验物体已摆好、工作空间已清空，需要从本机启动 OpenPI policy，读取机械臂三路相机，保存视频，并把模型输出实时下发到 P7 SDK 控制机械臂。当前推荐使用 `/root/start-arm-dual-app-2arm.sh`，不要用旧 `start-robot-app-3arm.sh` 做正式 OpenPI 闭环。

### 终端 A：启动 X5 侧统一 runtime

在 X5 上运行，保持这个终端不要关闭：

```bash
ssh root@192.168.25.1
bash /root/start-arm-dual-app-2arm.sh
```

期望只启动三个进程：`arm_dual_app left_arm`、`arm_dual_app right_arm`、`robot_app remote`。不要同时启动旧 `robot_app left_arm/right_arm`。

### 终端 B：本机做启动前检查

```bash
cd /home/discover/Desktop/Openpi_RL

pgrep -af 'openpi_p7_persistent_loop|serve_policy.py|record_openpi_cameras|capture_ros2_openpi_observation' || true
ss -lntp 'sport = :8000' || true

ssh root@192.168.25.1 "ps -ww -C arm_dual_app -o pid,ppid,lstart,etime,stat,args=; ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="
```

三路相机和左右臂 topic 检查：

```bash
for t in \
  /camera/head_left/image_rect \
  /camera/left_arm_left/image_rect \
  /camera/right_arm_left/image_rect \
  /arm/left/fsm/joint_state \
  /arm/right/fsm/joint_state
do
  ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v "$t"
done
```

双臂 SDK 状态只读检查：

```bash
.venv-p7-sdk/bin/python - <<'PY'
from arm_p7_sdk import AirbotClient

for name, port in [('left', 50071), ('right', 50072)]:
    c = AirbotClient(host='192.168.25.1', port=port, backend='grpc')
    try:
        st = c.get_service_state()
        js = c.get_arm_joint_state()
        es = c.get_eef_joint_state()
        em = c.get_eef_mode()
        pose = c.get_end_pose()
        print(name, st)
        print('  joints', ['%.4f' % x for x in js.angles] if js else None)
        print('  eef_state', es)
        print('  eef_mode', em)
        print('  pose_xyz', ['%.4f' % x for x in pose.position] if pose else None)
    finally:
        c.close()
PY
```

正式双臂实验前，左右臂都应是 `IDLE/idle/valid`。如果某一侧是 `UNKNOWN_ERROR`，不要继续双臂运动；先重启机械臂和终端 A 的脚本，或只用 `--active-sides right/left` 做健康侧单臂验证。

### 终端 C：启动 OpenPI policy server

```bash
cd /home/discover/Desktop/Openpi_RL
bash scripts/cmds/serve_policy.sh
```

等到看到 policy server 监听 `0.0.0.0:8000` 后保持终端不要关闭。

### 终端 D：启动三路相机录像

```bash
cd /home/discover/Desktop/Openpi_RL
mkdir -p /tmp/openpi_camera_records
STAMP=$(date +%Y%m%d_%H%M%S)

ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  /usr/bin/python3 examples/airbot/record_openpi_cameras.py \
  --duration-s 420 \
  --fps 15 \
  --output-prefix /tmp/openpi_camera_records/${STAMP}_openpi_task
```

该脚本只录像，不控制机械臂。输出包括：

```text
/tmp/openpi_camera_records/${STAMP}_openpi_task_triptych.mp4
/tmp/openpi_camera_records/${STAMP}_openpi_task_base_0_rgb.mp4
/tmp/openpi_camera_records/${STAMP}_openpi_task_left_wrist_0_rgb.mp4
/tmp/openpi_camera_records/${STAMP}_openpi_task_right_wrist_0_rgb.mp4
/tmp/openpi_camera_records/${STAMP}_openpi_task_metadata.json
```

### 终端 E：先跑一次 OpenPI dry-run

dry-run 会抓相机、请求 policy、生成 action 和 summary，但不会 acquire 控制权，也不会发 `move_end_pose()` / `move_eef()`：

```bash
cd /home/discover/Desktop/Openpi_RL

bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --iterations 2 \
  --period-s 1.0 \
  --controller servo \
  --chunk-steps 1 \
  --max-step-translation-m 0.005 \
  --max-step-rotation-rad 0.02 \
  --max-envelope-m 0.05 \
  --prompt 'pick up the plant with the gripper, lift it, move it to the collection box, and release it' \
  --enable-gripper
```

期望看到三路相机均 captured、policy 返回 `action_shape=[50,32]`，并且最终输出 `DRY_RUN`。

### 终端 E：正式执行抓取放置闭环

当前“纯模型输出、无强制夹爪、关闭三项 motion guard”的现场测试命令如下。夹爪只遵循模型输出：`0=闭合`、`100=最大打开`；不要加任何 `--force-gripper-*` 参数。

```bash
cd /home/discover/Desktop/Openpi_RL

bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 300 \
  --period-s 0.5 \
  --controller servo \
  --chunk-steps 5 \
  --max-step-translation-m 0 \
  --max-step-rotation-rad 0 \
  --max-envelope-m 0 \
  --prompt 'pick up the plant with the gripper, lift it, move it to the collection box, and release it' \
  --enable-gripper \
  --eef-speed-mm-s 80 \
  --execute \
  --allow-robot-motion
```

如果只想控制健康的一侧，例如右臂，追加：

```bash
  --active-sides right
```

如果想先跑保守安全版，把正式命令中的三项 guard 改回小步参数，并把 `chunk-steps` 改成 1：

```bash
  --chunk-steps 1 \
  --max-step-translation-m 0.005 \
  --max-step-rotation-rad 0.02 \
  --max-envelope-m 0.05
```

### 收尾和结果检查

正常结束或按 Ctrl+C 后，`openpi_p7_persistent_loop.py` 会尝试 `switch_eef_idle`、`switch_idle` 和 `release_control`。随后在本机检查最终状态：

```bash
.venv-p7-sdk/bin/python - <<'PY'
from arm_p7_sdk import AirbotClient

for name, port in [('left', 50071), ('right', 50072)]:
    c = AirbotClient(host='192.168.25.1', port=port, backend='grpc')
    try:
        print(name, c.get_service_state())
        js = c.get_arm_joint_state()
        es = c.get_eef_joint_state()
        pose = c.get_end_pose()
        print('  joints', ['%.4f' % x for x in js.angles] if js else None)
        print('  eef', es)
        print('  pose_xyz', ['%.4f' % x for x in pose.position] if pose else None)
    finally:
        c.close()
PY
```

解析最近一轮 summary：

```bash
python3 - <<'PY'
import json, math
from pathlib import Path

p = sorted(Path('/tmp/openpi_p7_persistent_loop').glob('summary_*.jsonl'))[-1]
rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
print('summary', p)
print('rows', len(rows), 'first_iter', rows[0].get('iteration'), 'last_iter', rows[-1].get('iteration'))
for side in ['left', 'right']:
    ss = [r.get('sides', {}).get(side, {}) for r in rows if side in r.get('sides', {})]
    if not ss:
        continue
    pts = [tuple(float(v) for v in s['measured_xyz']) for s in ss if s.get('measured_xyz')]
    vals = [float(s['gripper_p7_mm_command']) for s in ss if s.get('gripper_p7_mm_command') is not None]
    print(side, 'active_count', sum(bool(s.get('active')) for s in ss))
    if pts:
        p0 = pts[0]
        print('  max_tcp_envelope_m', max(math.dist(p0, p) for p in pts))
        print('  last_delta_m', tuple(pts[-1][i] - p0[i] for i in range(3)))
    if vals:
        print('  gripper_mm_minmax', min(vals), max(vals))
    print('  forced_gripper_count', sum(1 for s in ss if s.get('gripper_forced')))
PY
```

停止顺序：先让终端 E 的闭环结束；终端 D 录像可等到自然结束，也可 Ctrl+C；终端 C policy server Ctrl+C；最后终端 A 的 X5 启动脚本 Ctrl+C。若最终任一侧为 `UNKNOWN_ERROR`，下一轮正式测试前先重启机械臂和 `/root/start-arm-dual-app-2arm.sh`。

## 1. 启动机械臂侧 robot_app（旧 AIRRTM 路线）

在本机确认能 SSH 到 X5：

```bash
ssh root@192.168.25.1
```

在 X5 上启动三进程 robot_app，并保持这个终端不要关闭：

```bash
cd /userdata
bash start-robot-app-3arm.sh
```

期望看到类似输出：

```text
启动 remote ...
启动 left_arm ...
启动 right_arm ...
全部启动完成（3/3），按 Ctrl+C 停止
```

另开一个本机终端，检查 X5 进程：

```bash
ssh root@192.168.25.1 "ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="
```

期望至少有三行：

```text
./bin/robot_app /opt/robot_app/configs/remote/project_config.json
./bin/robot_app /opt/robot_app/configs/left_arm/project_config.json
./bin/robot_app /opt/robot_app/configs/right_arm/project_config.json
```

检查当前这条主线是否仍然是 AIRRTM 而不是 SDK gRPC：

```bash
ssh root@192.168.25.1 "ss -lntp | grep -E '50071|50051|50052' || true"
```

如果没有输出，说明当前不是 SDK gRPC `move_end_pose()` 路线，继续按本文 AIRRTM 路线操作。

## 1A. 启动统一 runtime（SDK gRPC 控制 + remote 相机）

这是当前推荐路线。它允许 `arm_dual_app` 左右臂进程与 `robot_app remote` 共存，但不允许旧 `robot_app left_arm/right_arm` 与 `arm_dual_app` 同时接 CAN。

先确认没有旧进程残留：

```bash
ssh root@192.168.25.1 "ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args=; ps -ww -C arm_dual_app -o pid,ppid,lstart,etime,stat,args="
```

如果已有任何 `robot_app` 或 `arm_dual_app` 残留，先用原启动脚本的 Ctrl+C 停掉，或者人工确认后再清理。不要在不清楚父脚本的情况下直接杀进程。

在 X5 上启动统一脚本，并保持终端不要关闭：

```bash
ssh root@192.168.25.1
bash /root/start-arm-dual-app-2arm.sh
```

期望输出：

```text
DDS domain 已是 0: /opt/arm_dual_app/configs/left_arm/framework_config.json
DDS domain 已是 0: /opt/arm_dual_app/configs/right_arm/framework_config.json
启动 left_arm ... /opt/arm_dual_app/configs/left_arm/project_config.json
启动 right_arm ... /opt/arm_dual_app/configs/right_arm/project_config.json
启动 robot_app remote ... /opt/robot_app/configs/remote/project_config.json
全部启动完成（3/3），按 Ctrl+C 停止
```

脚本会自动处理：

- `/opt/arm_dual_app` 左右臂 DDS domain 确认为 `0`，不对时先备份再修改。
- 新版 CAN 映射：left=`can0`、right=`can1`。
- 启动 `robot_app remote only`，不启动旧 `robot_app left_arm/right_arm`。
- Ctrl+C 时一起停止三个由该脚本启动的进程。

另开本机终端确认端口：

```bash
ssh root@192.168.25.1 "ss -lntp | grep -E ':50071|:50072|:8091|:8092'"
```

期望：left gRPC `50071`、right gRPC `50072`；log proxy 通常是 left `8091`、right `8092`。

确认 X5 进程形态：

```bash
ssh root@192.168.25.1 "ps -ww -C arm_dual_app -o pid,ppid,lstart,etime,stat,args=; ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="
```

期望只有：

```text
./bin/arm_dual_app /opt/arm_dual_app/configs/left_arm/project_config.json
./bin/arm_dual_app /opt/arm_dual_app/configs/right_arm/project_config.json
./bin/robot_app /opt/robot_app/configs/remote/project_config.json
```

确认 domain 0 下同时能看到相机和臂 topic：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /camera/head_left/image_rect
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /camera/left_arm_left/image_rect
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /camera/right_arm_left/image_rect
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /arm/left/fsm/joint_state
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /arm/right/fsm/joint_state
```

先做 no-motion dry-run，不会 `acquire_control()`，不会切控制器，也不会发运动：

```bash
cd /home/discover/Desktop/Openpi_RL
.venv-p7-sdk/bin/python examples/airbot/p7_dual_planning_precision_probe.py --step-m 0.08
```

确认 `left state_before` / `right state_before` 都是 `IDLE/idle/valid`，且输出 `DRY_RUN` target 后，再清空工作空间并真实执行 `+X,+Y,+Z` 各 8cm planning 测试：

```bash
cd /home/discover/Desktop/Openpi_RL
.venv-p7-sdk/bin/python examples/airbot/p7_dual_planning_precision_probe.py \
  --axes x,y,z \
  --step-m 0.08 \
  --execute
```

脚本默认每个方向完成后回到该方向开始前的 pose，并打印每只臂的：

```text
commanded_m, delta_m=(dx,dy,dz), axis_error_m, cross_axis_m, total_error_m, return_error_m
```

如果只想做单臂 SDK servo 小步 smoke，可以用旧 guarded 脚本，但注意右臂端口改成 `50072`：

```bash
# left, dry-run by default
.venv-p7-sdk/bin/python examples/airbot/p7_guarded_servo_step.py --host 192.168.25.1 --port 50071

# right, dry-run by default
.venv-p7-sdk/bin/python examples/airbot/p7_guarded_servo_step.py --host 192.168.25.1 --port 50072
```

当前推荐本机走 gRPC 控制。DDS domain 统一为 `0` 是为了本机 ROS2 同时看到 `robot_app remote` 相机 topic 和 `arm_dual_app` 臂状态 topic；SDK 控制本身仍走 gRPC `50071/50072`。

2026-07-09 10:39 CST 10cm 六方向实测结论：

- 端口/物理侧仍按现场修正理解：SDK `left` / `50071` 很可能是物理右臂，SDK `right` / `50072` 很可能是物理左臂。下面结果先按 SDK 名和端口记录。
- planning 模式在当前姿态下不是六方向都可达。`+X/+Y/+Z/-Y` 的主轴误差和串轴误差均为毫米内；`-X` 在 `50071` 上 TRAC-IK 失败，`-Z` 在两侧失败（`50071` TRAC-IK 失败，`50072` 触发 joint velocity limit）。
- servo 模式能走完整个 `+X/+Y/+Z/-X/-Y/-Z` 测试并回基准，但 `-X/-Z` 有明显串轴耦合。正向和 `-Y` 基本为毫米内；`50071 -X` 总误差约 `39.1mm`，`50071 -Z` 总误差约 `14.9mm`，`50072 -Z` 总误差约 `39.9mm`。
- 因此当前可作为 OpenPI 小步闭环入口的是“短步长、低速、带 per-step guard 的 servo”，不是直接把 policy 输出扩大成 10cm 大步；planning 可用于明确可达目标和回零/复位，但不能假设所有方向 10cm 都能从当前姿态规划成功。


## 1A.2. P7 SDK 连续 servo smoke

用于现场前确认 PC -> X5 gRPC -> 双臂 servo 的连续小步控制链路。脚本默认 dry-run，不会 acquire 控制权，也不会发运动；真实执行必须显式加 `--execute --allow-robot-motion`。

推荐先跑 dry-run：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_continuous_servo_smoke.py \
  --duration-s 25 --rate-hz 5 --radius-m 0.008 \
  --max-envelope-m 0.05 --arm-speed-rad-s 0.55
```

确认双臂均为 `IDLE/idle/valid` 后，再跑真实小幅连续运动：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_continuous_servo_smoke.py \
  --duration-s 25 --rate-hz 5 --radius-m 0.008 \
  --max-envelope-m 0.05 --arm-speed-rad-s 0.55 \
  --execute --allow-robot-motion
```

2026-07-08 20:04 CST 实测结果：`blocking=False` 的 servo 流式语义可连续执行，126 帧、`26.21s`，指令包络 `0.00894m`，左/右实测最大偏离 `0.00906m/0.01001m`，最终回起点误差 `0.00019m/0.00031m`，双臂最终均为 `IDLE/idle/valid`。

注意：不要用 `blocking=True` 反复调用 `move_end_pose()` 来模拟连续流式控制。实测 `blocking=True` 会在多帧连续调用中出现 `move_end_pose returned False`，虽然脚本能释放控制并回到 idle，但这不是后续 OpenPI 实时控制应采用的方式。

## 1B. 运行 OpenPI -> P7 SDK closed-loop 脚本

当前脚本：

```bash
scripts/cmds/openpi_p7_closed_loop.sh
```

它不是单一 Python runtime，而是显式编排三个环境：

```text
/usr/bin/python3 examples/airbot/capture_ros2_openpi_observation.py   # ROS2/rclpy
uv run python examples/airbot/request_policy_from_observation_npz.py  # OpenPI policy client
.venv-p7-sdk/bin/python examples/airbot/policy_to_p7_sdk_bridge.py     # Arm-P7 SDK
```

默认 dry-run，不会控制机械臂：

```bash
# 先单独启动 policy server
bash scripts/cmds/serve_policy.sh

# 另开终端跑 2 轮 dry-run
bash scripts/cmds/openpi_p7_closed_loop.sh \
  --iterations 2 \
  --max-translation-step-m 0.005 \
  --max-rotation-step-rad 0.02
```

真实小步执行必须显式加两个开关：

```bash
bash scripts/cmds/openpi_p7_closed_loop.sh \
  --iterations 1 \
  --max-translation-step-m 0.005 \
  --max-rotation-step-rad 0.02 \
  --execute \
  --allow-robot-motion
```

脚本会把每轮产物写到 `/tmp/openpi_p7_closed_loop/`，包括 observation npz、action JSON、bridge log 和 `summary_*.jsonl`。2026-07-08 18:51 CST 已验证：2 轮 dry-run 成功，1 轮 execute 成功；默认只发送 TCP pose，不控制夹爪，最终左右臂均为 `IDLE/idle/valid`。如果要让这个低频 wrapper 同时控制夹爪，追加 `--enable-gripper --eef-min-mm 0 --eef-max-mm 95 --eef-speed-mm-s 100 --eef-effort 5`；模型夹爪值 `0=闭合、100=最大打开`，P7 SDK 执行目标默认 clamp 到 `[0,95]mm`。

这仍是低频闭环编排：每轮都会重新启动一次 P7 bridge 进程，不适合长时间任务执行。长时间任务优先使用下一节的常驻循环。

## 1C. 运行 OpenPI -> P7 SDK 常驻控制循环

当前脚本：

```bash
scripts/cmds/openpi_p7_persistent_loop.sh
```

它仍然尊重三套环境边界，但 P7 SDK 控制端是常驻的：

```text
/usr/bin/python3 examples/airbot/capture_ros2_openpi_observation.py   # ROS2/rclpy，相机抓一帧
uv run python examples/airbot/request_policy_from_observation_npz.py  # OpenPI policy client，请求 action chunk
.venv-p7-sdk/bin/python examples/airbot/openpi_p7_persistent_loop.py  # 常驻 P7 SDK clients/control
```

默认 dry-run，不 acquire 控制权，不发 `move_end_pose()`，也不发 `move_eef()`：

```bash
# 先单独启动 policy server
bash scripts/cmds/serve_policy.sh

# 另开终端跑 2 轮 dry-run
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --iterations 2 \
  --period-s 1.0 \
  --controller servo \
  --chunk-steps 1 \
  --max-step-translation-m 0.005 \
  --max-step-rotation-rad 0.02 \
  --max-envelope-m 0.05
```

真实 60 秒小步 servo 执行示例：

```bash
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 60 \
  --period-s 1.0 \
  --controller servo \
  --chunk-steps 1 \
  --max-step-translation-m 0.005 \
  --max-step-rotation-rad 0.02 \
  --max-envelope-m 0.05 \
  --execute \
  --allow-robot-motion
```

如果要同时让模型输出控制夹爪，在上述命令中追加：

```bash
  --enable-gripper \
  --eef-min-mm 0 \
  --eef-max-mm 95 \
  --eef-speed-mm-s 100 \
  --eef-effort 5
```

夹爪语义和训练一致：模型输出 `0` 表示闭合，`100` 表示最大打开。脚本执行时把模型值线性转换成 P7 `move_eef()` 的 mm 目标，并默认限制在 `[0,95]mm`，避免把 `0.096m` 理论值直接发成超出 SDK 文档 G2P 上限的目标。

常驻循环的关键保护：

- `--max-step-translation-m` / `--max-step-rotation-rad` 限制相邻目标步长。
- `--max-envelope-m` 限制目标相对脚本启动时 TCP 的最大空间包络。
- `--execute` 必须和 `--allow-robot-motion` 同时出现，否则拒绝运动。
- `--enable-gripper` 默认关闭；不加时即使模型输出夹爪值，也只记录目标，不实际调用 `move_eef()`。
- `--active-sides` 默认 `left,right`；可设为 `right` 或 `left`，只对指定侧 acquire/switch/move，未激活侧仍只读 TCP pose 作为 observation/context。该参数用于一侧进入 `UNKNOWN_ERROR` 后继续验证另一侧闭环，不是常规双臂任务的默认用法。
- 每轮产物写入 `/tmp/openpi_p7_persistent_loop/summary_*.jsonl`，包括 observation/action 文件路径、每侧目标、实测 TCP、误差和夹爪目标。

当前状态：2026-07-09 11:53 CST 已通过 `.venv-p7-sdk/bin/python -m py_compile`、`--help` 和非法参数 `REFUSE` 校验；2026-07-09 12:42 CST 已完成 1 轮完整 dry-run：三路相机均抓到 `nv12 640x352`，policy 返回 `[50,32]`，P7 SDK 双臂均为 `IDLE/idle/valid`，动作和夹爪目标均在 guard 内。2026-07-09 13:48 CST 已完成 20 秒真实闭环 smoke：15 次 action 执行，双臂和夹爪均返回 `ok=True`，最终释放控制并回到 `IDLE/idle/valid`。2026-07-09 15:49 CST 已完成 60 秒真实闭环：`summary=/tmp/openpi_p7_persistent_loop/summary_20260709_154920.jsonl`，31 次迭代；left/right 最大 target error 分别约 `1.61mm` / `2.12mm`，相对首帧实测运动包络约 `18.1mm` / `42.8mm`，均在 `--max-envelope-m 0.05` 内；夹爪命令范围 left `94.18~95.00mm`、right `90.46~95.00mm`；最终双臂与 EEF 均回到 `IDLE/idle`，临时 policy server 已停止，`ss -lntp 'sport = :8000'` 无监听。2026-07-09 16:01 CST 第一轮正式实验在同一保守参数下启动，成功执行 35 轮；第 36 轮右臂目标 envelope `0.050677m` 超过 `0.050000m` guard，被脚本在下发前拒绝并安全收尾，最终双臂与 EEF 仍为 `IDLE/idle/valid`。本轮还为 request 脚本增加 `--skip-policy-port-check`，常驻 loop 默认使用它，避免每轮裸 TCP 探活在 WebSocket server 里刷 handshake error。


2026-07-09 21:12 CST 更新：在左臂因上一轮双臂测试进入 `UNKNOWN_ERROR` 后，新增并验证 `--active-sides right` 单侧执行模式。右臂单臂纯模型闭环运行 `185.26s`，summary=`/tmp/openpi_p7_persistent_loop/summary_20260709_210408.jsonl`，共 `433` 条已成功动作记录；三路相机、policy、右臂 servo 和夹爪 `move_eef()` 均持续工作。右臂相对首帧最大 TCP 包络约 `0.2859m`，末帧相对首帧约 `(+0.0477,+0.2035,+0.0392)m`；右夹爪命令范围 `5.80~95.00mm`，`forced_gripper_count=0`，即夹爪完全遵循模型输出。停止原因是第 87 轮后续一个右臂 `move_end_pose` 由 SDK 返回 `False`，不是相机或 policy 断链。右臂最终 `IDLE/idle/valid`；左臂仍为 `UNKNOWN_ERROR/idle/valid`，需要重启或显式清错后才能重新参与双臂运动。

## 2. 发送前安全检查（旧 AIRRTM 路线）

每次真机发布前都先检查本机没有残留发送进程：

```bash
pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|airrtm_servo_dryrun|serve_policy.py' || true
ss -lntp | grep ':6000' || true
```

如果已有 `airbot-rtm-sender` 或某个 publisher 正在运行，先确认它是不是你当前要用的那个进程。不要让两个 publisher 同时绑定 `6000`。

检查左臂状态：

```bash
ssh root@192.168.25.1 \
  "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
```

检查右臂状态：

```bash
ssh root@192.168.25.1 \
  "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
```

允许继续的最低条件：

- `arm_motor_state error=[0,0,0,0,0,0,0,0]`
- `arm_hardware_status <none>`
- `fsm_cartesian_state` 能读到 `translation=[x,y,z] orientation=[qx,qy,qz,qw]`
- 现场确认机械臂周围没有人手、线缆、桌面边缘或其他障碍物

如果出现 `UNKNOWN_ERROR`、`iq current too large`、motor error 非 0、hardware status 有错误，不要发运动指令。

## 3. 启动 AIRRTM sender

先核对 X5 当前 room。2026-07-07 17:52 CST 实测，X5 remote 使用的是 `rtm_sender_room_1`，而本机原始 `/home/discover/airbot_teleop/config/sender/airrtc_e2.yaml` 仍是 `rtm_sender_room`；room 不一致会导致 sender 只 `joined room`，随后 `p2p connection timeout`。

```bash
ssh root@192.168.25.1 "grep -RInE 'room_id|user_id|data_channel_label' /opt/robot_app/configs/remote/airrtm_config.json"
```

当前建议先生成一个临时 sender 配置，不改原始文件：

```bash
python3 - <<'PY'
from pathlib import Path
src = Path('/home/discover/airbot_teleop/config/sender/airrtc_e2.yaml')
dst = Path('/tmp/airrtc_e2_room1.yaml')
text = src.read_text()
text = text.replace('room_id: "rtm_sender_room"', 'room_id: "rtm_sender_room_1"')
text = text.replace('log_dir: "logs/sdk/airrtc/airrtc_e2"', 'log_dir: "logs/sdk/airrtc/airrtc_e2_room1"')
text = text.replace('config: "input/airrtc_e2.yaml"', 'config: "/home/discover/airbot_teleop/config/sender/input/airrtc_e2.yaml"')
dst.write_text(text)
print(dst)
PY
```

在本机开一个单独终端启动 sender：

```bash
cd /home/discover/Desktop/Openpi_RL
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  airbot-rtm-sender /tmp/airrtc_e2_room1.yaml
```

这个终端需要保持运行。期望看到：

```text
joined room room=rtm_sender_room_1 user=airrtc_sender
remote user joined user=airrtc_robot
p2p established peer=airrtc_robot
data channel state=open
initialized socket_type=sub endpoint=tcp://127.0.0.1:6000 mode=connect topic='servo'
```

如果 sender 停止时打印：

```text
sender stopped total_sent=0 errors=0
```

说明本次没有真正转发任何控制帧。

## 4. 手动发送一帧小位移

最简单的手动通路是 `airrtm_servo_dryrun.py`。它可以通过 X5 上的 `fsm_monitor` 自动读取当前 TCP pose。

先做 no-publish 预览，不会发给机械臂：

```bash
cd /home/discover/Desktop/Openpi_RL
uv run python examples/airbot/airrtm_servo_dryrun.py \
  --fsm-monitor-host root@192.168.25.1 \
  --assume-servo-start-current \
  --mock-step-m 0.001 \
  --max-translation-step-m 0.002 \
  --max-rotation-step-rad 0.02 \
  --gripper-unit model_0_100 \
  --sequence 1
```

确认输出里的 `payload.command` 是 `servo_pose`，`publish` 为 `false`。

确认安全后，真正发布同样的一帧：

```bash
cd /home/discover/Desktop/Openpi_RL
uv run python examples/airbot/airrtm_servo_dryrun.py \
  --fsm-monitor-host root@192.168.25.1 \
  --assume-servo-start-current \
  --mock-step-m 0.001 \
  --max-translation-step-m 0.002 \
  --max-rotation-step-rad 0.02 \
  --gripper-unit model_0_100 \
  --sequence 1 \
  --publish \
  --allow-robot-motion
```

注意：

- `--publish --allow-robot-motion` 必须同时出现才会真实发给 sender。
- `--assume-servo-start-current` 只适合 receiver 还没进入 `SERVO_CONTROL`、你确认 servo-start 就是当前 TCP 的情况。
- 如果机械臂已经处在 `SERVO_CONTROL`，不要再用 `--assume-servo-start-current`；需要显式传入当初进入 servo 时的 `--left-servo-start-pose` 和 `--right-servo-start-pose`。
- `airrtm_servo_dryrun.py` 的 mock action 默认是左臂 `+X`、右臂 `-X`。如果要精确指定左右臂方向，用下一节 JSON action。

发布后回读双臂状态：

```bash
ssh root@192.168.25.1 \
  "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
ssh root@192.168.25.1 \
  "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
```

## 5. 用 JSON action 明确控制左右臂

如果要自己指定模型 action，可以生成一个 JSON action。下面例子表示左右臂都沿 action 的 `+X` 方向走 `1cm`，夹爪保持 `100`。

```bash
python3 - <<'PY'
import json

action = [0.0] * 32
action[0] = 0.01      # left dx, meter
action[6] = 100.0     # left gripper, model 0-100
action[7] = 0.01      # right dx, meter
action[13] = 100.0    # right gripper, model 0-100

with open("/tmp/airbot_action_forward_1cm.json", "w") as f:
    json.dump(action, f)
PY
```

先从 `fsm_monitor` 复制当前 TCP pose。格式必须是：

```text
x,y,z,qx,qy,qz,qw
```

例如：

```text
0.3521,-0.0014,0.3362,0.0051,-0.0026,0.0012,1.0000
```

no-publish 预览：

```bash
cd /home/discover/Desktop/Openpi_RL
uv run python examples/airbot/policy_to_airrtm_bridge.py \
  --action-source json \
  --action-json /tmp/airbot_action_forward_1cm.json \
  --left-current-pose <left_x,left_y,left_z,left_qx,left_qy,left_qz,left_qw> \
  --right-current-pose <right_x,right_y,right_z,right_qx,right_qy,right_qz,right_qw> \
  --assume-servo-start-current \
  --max-translation-step-m 0.011 \
  --max-rotation-step-rad 0.02 \
  --gripper-unit model_0_100 \
  --sequence 10
```

真实发布：

```bash
cd /home/discover/Desktop/Openpi_RL
uv run python examples/airbot/policy_to_airrtm_bridge.py \
  --action-source json \
  --action-json /tmp/airbot_action_forward_1cm.json \
  --left-current-pose <left_x,left_y,left_z,left_qx,left_qy,left_qz,left_qw> \
  --right-current-pose <right_x,right_y,right_z,right_qx,right_qy,right_qz,right_qw> \
  --assume-servo-start-current \
  --max-translation-step-m 0.011 \
  --max-rotation-step-rad 0.02 \
  --gripper-unit model_0_100 \
  --sequence 10 \
  --publish \
  --allow-robot-motion
```

这仍然是一帧 guarded command，不是完整轨迹播放器。不要用 shell loop 盲目重复同一个 current pose；每一帧都应该基于正确的 current pose / servo-start pose 构造，否则会重新引入比例和坐标系错误。

## 6. 启动 OpenPI policy server

在本机单独开一个终端：

```bash
cd /home/discover/Desktop/Openpi_RL
bash scripts/cmds/serve_policy.sh
```

当前脚本使用：

```text
config=pi05_vio_plant_collection
checkpoint=checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000
port=8000
```

保持这个终端运行。桥接脚本默认从 `127.0.0.1:8000` 请求 policy。

## 7. OpenPI inference result -> AIRRTM no-publish

先不发给机械臂，只确认 policy server 可以返回 action chunk，且 bridge 能转换成 `servo_pose`：

```bash
cd /home/discover/Desktop/Openpi_RL
ACTION_SOURCE=policy \
POLICY_HOST=127.0.0.1 \
POLICY_PORT=8000 \
PROMPT="put the plant into the collection box" \
bash scripts/cmds/airrtm_bridge_dryrun.sh
```

期望看到：

```text
action_chunk_shape=[50,32]
selected_action_first14=...
payload.command=servo_pose
publish=false
```

如果报：

```text
policy server is not reachable
```

先回到上一节确认 `serve_policy.sh` 还在运行。

## 8. 发送 OpenPI 的一行推理结果给机械臂

前提：

- 第 1-3 节已经完成：X5 robot_app 运行、状态安全、AIRRTM sender data channel open。
- 第 6 节 OpenPI policy server 正在运行。
- 你已经从 `fsm_monitor` 复制了左右臂当前 TCP pose。
- 如果 receiver 已经进入过 `SERVO_CONTROL`，你知道 servo-start pose；否则只在确认 fresh start 时使用 `--assume-servo-start-current`。

no-publish 预览：

```bash
cd /home/discover/Desktop/Openpi_RL
uv run python examples/airbot/policy_to_airrtm_bridge.py \
  --action-source policy \
  --policy-host 127.0.0.1 \
  --policy-port 8000 \
  --prompt "put the plant into the collection box" \
  --left-current-pose <left_x,left_y,left_z,left_qx,left_qy,left_qz,left_qw> \
  --right-current-pose <right_x,right_y,right_z,right_qx,right_qy,right_qz,right_qw> \
  --assume-servo-start-current \
  --action-index 0 \
  --max-translation-step-m 0.01 \
  --max-rotation-step-rad 0.02 \
  --gripper-unit model_0_100 \
  --sequence 100
```

真实发布：

```bash
cd /home/discover/Desktop/Openpi_RL
uv run python examples/airbot/policy_to_airrtm_bridge.py \
  --action-source policy \
  --policy-host 127.0.0.1 \
  --policy-port 8000 \
  --prompt "put the plant into the collection box" \
  --left-current-pose <left_x,left_y,left_z,left_qx,left_qy,left_qz,left_qw> \
  --right-current-pose <right_x,right_y,right_z,right_qx,right_qy,right_qz,right_qw> \
  --assume-servo-start-current \
  --action-index 0 \
  --max-translation-step-m 0.01 \
  --max-rotation-step-rad 0.02 \
  --gripper-unit model_0_100 \
  --sequence 100 \
  --publish \
  --allow-robot-motion
```

这一步只发布 OpenPI 返回 action chunk 中的第 `--action-index` 行。不要一次性把 50 行 chunk 全部连续发给机械臂；当前还没有完成姿态/YZ 耦合标定，也没有完整的闭环观测和停止恢复策略。

## 9. 停止和恢复

停止本机发送：

- 在 `airbot-rtm-sender` 终端按 `Ctrl+C`。
- 确认无残留进程：

```bash
pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|airrtm_servo_dryrun|serve_policy.py' || true
ss -lntp | grep ':6000' || true
```

停止 OpenPI policy server：

- 在 `serve_policy.sh` 终端按 `Ctrl+C`。

停止 X5 robot_app：

- 在 X5 `start-robot-app-3arm.sh` 终端按 `Ctrl+C`。

停止后再次做双臂 `fsm_monitor` 检查。如果状态不是 `IDLE` 或出现 hardware/motor error，先现场恢复，不要继续发下一条指令。

## 10. 常见问题

`sender stopped total_sent=0 errors=0`：

sender 没收到本机 ZMQ publisher 的消息。常见原因是 publisher 没运行、sender 启动还没到 data channel open、或者 publisher 绑定 `6000` 和 sender 订阅窗口错过。

`policy server is not reachable`：

`scripts/cmds/serve_policy.sh` 没启动，或者端口不是 `8000`。

`--publish requires --allow-robot-motion`：

这是故意的安全门。真实运动必须显式加两个参数。

`--publish requires --left-current-pose and --right-current-pose`：

`policy_to_airrtm_bridge.py` 不会自动 SSH 读取当前 TCP；先用 `fsm_monitor` 复制左右臂 pose，或者先用 `airrtm_servo_dryrun.py --fsm-monitor-host` 做手动链路测试。

已经进入 `SERVO_CONTROL` 后还能不能用 `--assume-servo-start-current`：

不要用。`teleop_initial_delta` payload 需要知道 receiver 进入 servo 时的起点。已经进过 `SERVO_CONTROL` 时，应传显式 `--left-servo-start-pose` / `--right-servo-start-pose`，或者重启 robot_app 回到一个明确 fresh 状态。

旧 AIRRTM 路线为什么不直接用 SDK pose 接口：

旧三进程 `/opt/robot_app` runtime 没有暴露 SDK gRPC pose 服务，所以这一路线继续用已验证可转发和驱动真机的 AIRRTM 通道。新版 `/opt/arm_dual_app` 已安装后可以提供 SDK gRPC route，但必须先停止旧 `robot_app` 并按 §1A 启动新版 app；left=`50071`、right=`50072`。

## 11. 已知限制和正式任务注意事项

- 三路实时相机、OpenPI policy、P7 SDK 双臂 TCP 控制、夹爪 `move_eef()` 和常驻控制循环已经打通，并通过 20 秒和 60 秒真实闭环验证；这部分不再是未完成项。
- 当前正式组合方式是 `/root/start-arm-dual-app-2arm.sh`：启动两条 `/opt/arm_dual_app` 臂进程，并只启动 `/opt/robot_app` 的 `remote` 相机/话题进程。不要让旧 `robot_app left/right` 与新版 `arm_dual_app` 同时接 CAN。
- 现场观察过 SDK 逻辑名和物理左右可能相反：`50071/config left_arm` 曾对应用户看到的右臂，`50072/config right_arm` 曾对应用户看到的左臂。正式任务记录和排障时同时写端口、配置名、物理侧。
- 正式抓取/放置任务可以开始，但第一轮仍应保留小步 guard：`--max-step-translation-m 0.005 --max-step-rotation-rad 0.02 --max-envelope-m 0.05 --period-s 1.0 --chunk-steps 1`。不要一次性连续播放 policy 的 50 步 chunk，也不要直接放大到 20cm envelope，除非现场重新确认工作空间和异常停机策略。
- 脚本日志能证明“相机 -> policy -> P7 SDK 控制链路完成并且最终状态正常”，但不能自动判断任务语义是否成功抓取/放置。物体是否被正确抓取、放置仍需现场肉眼或后续视觉评估确认。

## 12. 相关文档

- [airrtm-conversion-layer.md](airrtm-conversion-layer.md)
- [robot-connection.md](robot-connection.md)
- [vio-relpose-deployment.md](vio-relpose-deployment.md)
- [training-robot-io-alignment.md](training-robot-io-alignment.md)
- [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)
