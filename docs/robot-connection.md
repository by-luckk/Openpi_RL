# 连接机器人 `192.168.25.1` / `172.100.10.159` 与实时数据源

> 维护约定见 [../AGENTS.md](../AGENTS.md) §0。最近核对：2026-07-02 21:57 CST。
> 这台机器是 AIRBOT 机器人的板载 SoC：Horizon/Hobot **aarch64**，**ROS2 Humble**，`rmw_fastrtps_cpp`，`ROS_DOMAIN_ID=0`。
> 我们要的是**实时读取**——板上没有可读视频文件，相机/机械臂都是实时 **ROS2 话题**。

---

## 1. 怎么连上去（SSH）

```
有线 / DDS 推荐链路：192.168.25.1       用户：root     本工作站已装 SSH 公钥，免密；密码 root 仅 fallback
无线 / 管理备用链路：172.100.10.159     用户：root     2026-06-30 已验证免密；密码 root 仅 fallback
```

```bash
ssh root@192.168.25.1          # 有线 / DDS 推荐链路；网络可达时使用同一 root 公钥免密
ssh root@172.100.10.159        # 无线 wlan0；已验证免密，只建议 SSH/管理备用，不建议 DDS/ROS2 多播
```

当前工作站已把 `~/.ssh/id_ed25519.pub` 追加到机器人 `/root/.ssh/authorized_keys`，正常不需要 `sshpass` 或输密码。若换机器、key 丢失、或需要 fallback 非交互登录，再用 `SSH_ASKPASS` 传密码：

```bash
cat > /tmp/askpass.sh <<'EOF'
#!/bin/sh
echo "root"
EOF
chmod +x /tmp/askpass.sh

SSH_ASKPASS=/tmp/askpass.sh SSH_ASKPASS_REQUIRE=force setsid -w \
  ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password \
      -o PubkeyAuthentication=no root@192.168.25.1 '<command>'
```

> 2026-06-30 17:44 CST 已完成：本机 `~/.ssh/id_ed25519.pub` 已追加到机器人 root 的 `authorized_keys`；`ssh -i ~/.ssh/id_ed25519 root@172.100.10.159` 返回 `key_login_ok`。
> 板上 ssh 监听 `0.0.0.0:22`（已确认）。

## 2. 网络拓扑（为什么能直连 DDS）

| 端 | 接口 | IP |
|---|---|---|
| 工作站 | `enp108s0` | 历史可用时为 `192.168.25.132/24`；2026-06-30 17:54 CST 当前为 `DOWN` |
| 机器人 | `eth0` | `192.168.25.1/24` |

- 历史状态：两端在**同一根有线 /24**，`ping 192.168.25.1` 通 → 同子网，FastDDS 多播发现可直接跨机生效。
- 历史现场（2026-06-30 17:54 CST）：工作站 `enp108s0 DOWN`，`ping 192.168.25.1` 失败；X5 `eth0 192.168.25.1/24` 仍为 UP。当时只能通过 Wi-Fi `172.100.10.159` SSH 管理，不能认为工作站直连 DDS 已就绪。
- 当前现场（2026-07-02 16:09 CST）：有线链路已恢复，`ip route get 8.138.229.216` 走 `via 192.168.25.1 dev enp108s0 src 192.168.25.132`；AIRRTC server `8.138.229.216:7210` TCP 可达。注意本机代理环境会干扰 `airbot-rtm-sender`，启动 sender 时需清空 `http_proxy/https_proxy/ALL_PROXY` 等变量。
- 当前现场（2026-07-02 18:53 CST）：`ssh root@192.168.25.1 date` 返回 `Thu Jul  2 18:53:15 CST 2026`，说明有线 SSH 管理链路已恢复。本机 `pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|serve_policy.py|robot_app'` 无输出，即本机没有残留 sender/bridge/policy/robot_app 控制源。
- 机器人另有 `wlan0 172.100.10.159`（无线，另一网段，可用于 SSH/管理备用，别用来走 DDS）。
- 机器人侧 `rmw_fastrtps_cpp` + `ROS_DOMAIN_ID=0`；板上有 `rclpy` + `cv_bridge`。工作站无 `/opt/ros` 系统 ROS，但 2026-06-30 已装系统级 Miniconda 环境 `/opt/miniconda3/envs/ros2-topic`，可用 `mamba` 本地直接订阅标准 ROS2 topic。

## 3. 相机：三路左目（实时 ROS2 话题）

每个立体相机取**左目**，三路对应 repo 的三个相机名：

| repo 相机名 | ROS2 话题（原始图像） | 编码 / 分辨率 / 帧率 |
|---|---|---|
| `base_0_rgb` | `/camera/head_left/image_rect` | `sensor_msgs/Image`，**nv12**，**640×352**，~19–20Hz |
| `left_wrist_0_rgb` | `/camera/left_arm_left/image_rect` | 同上 |
| `right_wrist_0_rgb` | `/camera/right_arm_left/image_rect` | 同上 |

每路相机还有：
- `/camera/<cam>/image_rect/video_encoded` — `foxglove_msgs/CompressedVideo`（**H264**，低带宽，需解码）
- `/camera/<cam>/image_rect/camera_info`、`/camera/<cam>/request_idr`、`/camera/<cam>/set_bitrate`

板上共 6 路（`head_left/right`、`left_arm_left/right`、`right_arm_left/right`），我们只用 `*_left` 三路。

2026-07-08 14:06 CST mixed runtime 复查：本机已有 `/opt/ros/jazzy/bin/ros2`，`ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic list` 能看到 6 路 `image_rect` topic；但当时实际 publisher 只有 `left_arm_left/left_arm_right` 两路。`/camera/head_left/image_rect` 与 `/camera/right_arm_left/image_rect` 8 秒内 `ros2 topic echo --once --field encoding` 收不到帧，`robot_app remote` 日志显示 head/right-arm 相机 `attach_to_vin failed`。这说明 mixed runtime 下不能把临时双相机替代输入当作正式模型输入。

2026-07-08 17:07 CST 旧脚本复查：用户改用旧 `bash start-robot-app-3arm.sh` 完整启动 X5 `/opt/robot_app` 三进程后，本机 ROS2 三路正式左目均可收到帧：`/camera/head_left/image_rect`、`/camera/left_arm_left/image_rect`、`/camera/right_arm_left/image_rect` 的 `encoding` 均为 `nv12`。`examples/airbot/capture_ros2_openpi_observation.py` 成功导出 `base_0_rgb`、`left_wrist_0_rgb`、`right_wrist_0_rgb` 三个 `352x640x3 uint8` RGB 图像，随后 `request_policy_from_observation_npz.py` 请求 OpenPI policy 返回 `actions` 形状 `(50,32)`。本次没有下发机械臂运动。


### 3.1 video_encoded 实时视频流确认

日期：2026-06-30；检查人：agent。
目的：回答“是否有 video”，确认相机是实时图像/视频流而不是板上文件。

结论：**有实时 video topic**。每路相机同时发布原始图像和 H264 编码视频：

| 类型 | topic 模式 | 消息类型 | 用法 |
|---|---|---|---|
| 原始图像 | `/camera/<cam>/image_rect` | `sensor_msgs/Image` | nv12 640×352，约 19–20Hz；本地处理要转 RGB |
| 编码视频 | `/camera/<cam>/image_rect/video_encoded` | `foxglove_msgs/CompressedVideo` | H264，适合跨机传输；客户端需解码 |

六路都有：`head_left/head_right/left_arm_left/left_arm_right/right_arm_left/right_arm_right`。当前推理取三路左目：

```bash
/camera/head_left/image_rect/video_encoded
/camera/left_arm_left/image_rect/video_encoded
/camera/right_arm_left/image_rect/video_encoded
```

复现命令（机器人侧）：

```bash
source /opt/ros/humble/setup.bash
ros2 topic info /camera/head_left/image_rect/video_encoded
ros2 topic hz /camera/head_left/image_rect/video_encoded
ros2 topic echo --once /camera/head_left/image_rect/video_encoded --field format
```

验证命令（在机器人上）：
```bash
source /opt/ros/humble/setup.bash
ros2 topic list | grep image_rect
ros2 topic info /camera/head_left/image_rect
ros2 topic hz   /camera/head_left/image_rect          # 实测 ~19.5Hz
ros2 topic echo --once --field encoding /camera/head_left/image_rect   # nv12
```

> ⚠️ 注意：图像是 **nv12**（YUV420），不是 RGB/BGR。桥接时要用 `cv_bridge`/手动转成 RGB；repo `play_operator.capture_observation()` 默认做的是 BGR→RGB，对接前要对齐颜色空间和 640×352 vs 640×480 分辨率差异。

## 4. 机械臂：连接与读写（实时 ROS2 话题）

机器人侧跑着三个 `robot_app` 进程（`remote` / `left_arm` / `right_arm` 的 `project_config.json`），双臂控制全部走 ROS2，共 ~185 个话题。命名规则 `/arm/{left,right}/...`。

**读关节状态（做观测用）：**

| 话题 | 类型 | 内容 |
|---|---|---|
| `/arm/left/fsm/joint_state` | `sensor_msgs/JointState` | names `['joint1'..'joint6','joint7','G2P']`，position 为对应数组 |
| `/arm/right/fsm/joint_state` | `sensor_msgs/JointState` | 同上 |
| `/arm/{left,right}/control/joint_states` | `sensor_msgs/JointState` | 控制层关节反馈 |
| `/arm/{left,right}/fsm/eef_motor_state` | `arm_msgs/MotorState` | 末端/夹爪电机状态 |

> **⚠️ 这套关节 topic ≠ 当前 checkpoint 的 action I/O**：机器人每臂 `joint_state` 是 8 个（`joint1..joint7 + G2P`，`G2P` effort≈-8.45 是夹爪）。当前 checkpoint 输出的是 relpose action，不是关节角。训练数据 state=16 曾来自相机位姿+夹爪，但当前 PI05 checkpoint 推理不消费真实 state 数值；policy 请求可用 dummy state。这里的 `joint_state` 更适合执行侧 FK/限幅/夹爪反馈，或采关节空间数据集。模型真实契约见 [model-io-contract.md](model-io-contract.md)，relpose 部署链路见 [vio-relpose-deployment.md](vio-relpose-deployment.md)。

**下发动作（驱动机械臂）——伺服控制相关话题：**
- `/arm/{left,right}/servo/command`、`/arm/{left,right}/servo/state`
- `/arm/{left,right}/fsm/servo_joint_command`、`/arm/{left,right}/fsm/joint_position_control_command`
- 状态机：`/arm/{left,right}/fsm/state`、`switch_control_state_command`、`stop_command`、`emergency_stop_command`
- 末端模式 RPC：`/rpc/arm/{left,right}/fsm/get_eef_mode/{request,response}`

> ⚠️ 与 repo 原生路径的差异：`airbot_inference_*.py` → `play_operator.py` 是用 **`airbot_play` gRPC（端口 50051/50053）** 下发动作的，板上**没有**这个 gRPC，只有上面的 ROS2 伺服话题。真机闭环要么改 operator 走 ROS2 servo command，要么在板上架一个 gRPC↔ROS2 适配。下发动作前务必先在安全状态/低速验证。

### 4.1 当前 TCP pose：X5 `fsm_monitor` 只读可用

日期：2026-07-02 11:21 CST；检查人：agent。
目的：在 Arm-P7 SDK gRPC `50071` 当前不在线时，确认是否能从 X5 旧栈读取左右臂 current TCP pose，作为 AIRRTM `servo_pose` 转换的当前位姿输入。

只读命令：

```bash
ssh -o ConnectTimeout=3 root@192.168.25.1 "ps -eo pid,cmd | grep robot_app | grep -v grep"
ssh -o ConnectTimeout=3 root@192.168.25.1 "ss -lntp | grep -E '50071|50051|50052|6000' || true"
ssh -o ConnectTimeout=3 root@192.168.25.1 "sed -n '1,220p' /opt/robot_app/configs/remote/airrtm_config.json"
ssh -o ConnectTimeout=3 root@192.168.25.1 "timeout 4 /opt/robot_app/bin/fsm_monitor --arm-side l"
ssh -o ConnectTimeout=3 root@192.168.25.1 "timeout 4 /opt/robot_app/bin/fsm_monitor --arm-side r"
```

关键输出：

```text
3411 ./bin/robot_app ./configs/left_arm/project_config.json
7605 ./bin/robot_app ./configs/remote/project_config.json
7771 ./bin/robot_app ./configs/right_arm/project_config.json

# ss 对 50071/50051/50052/6000 无输出

[fsm_state] state=PLANNING_CONTROL raw=1 substate=idle_hold
[arm_controller_state] arm_id=2(CSP) eef_id=2(CSP) manager_state=0 arm_name=csp eef_name=csp traj_running=false
[fsm_cartesian_state] translation=[0.3492, -0.0000, 0.3302] orientation=[-0.0000, 0.0000, -0.0001, 1.0000]
```

结论：X5 当前仍是旧的 `remote + left_arm + right_arm` 三进程结构，remote AIRRTM 配置保持 `arm_servo` / `cartesian_pose` / `publish_to_arm=true`；`50071` gRPC route 此刻不在线。`fsm_monitor --arm-side l/r` 能稳定读到 `translation[3] + orientation[4]`，可作为 AIRRTM 转换器的一版 current TCP pose 来源。该命令只读 DDS/FSM 状态，不发送控制命令。

2026-07-02 11:48 CST 单帧 AIRRTM 真机发布后补充：`fsm_monitor` 可读到发布后双臂进入 `SERVO_CONTROL`，电机 error 仍为 0；但回读 pose 从发布前约 `translation=[0.3492, -0.0000, 0.3302]` 变为约 `left=[0.3895, -0.0000, 0.3353]`、`right=[0.3894, -0.0000, 0.3353]`，与 0.05mm 测试目标不一致。因此在查清 AIRRTM receiver 的 pose frame/初始偏置前，不能把 `fsm_monitor` 的 PLANNING 态 current TCP 直接当作 `servo_pose` 绝对目标继续发连续控制。

2026-07-02 12:07 CST 修正：本地真实 `airbot_driver` 证明 AIRRTM `servo_pose` payload 以 `slave_arm_initial_pose=[0.3089256671,-0.0000498008,0.3245732613,-0.0000000007,-0.000002347,-0.0001426536,0.9999999898]` 为零点，X5 receiver 进入 `SERVO_CONTROL` 后近似执行 `actual_target = servo_start_actual + (payload - slave_initial)`。11:48 的 0.3895m 回读与该公式吻合。后续不能把 `fsm_monitor` current TCP 直接放进 payload；应先记录 servo-start actual TCP，再发 `slave_initial + desired_delta_from_servo_start`。

2026-07-02 12:53 CST 补充：本机无 AIRRTM sender/publisher/robot_app 残留，X5 三个 `robot_app` 仍在，双臂 `fsm_monitor` 仍显示 `SERVO_CONTROL`、`translation≈[0.3895, 0, 0.3353]`、电机 `error=[0,...,0]`。本地真实摇操脚本里 `p/l` 都发布 `remote_control false`，X5 日志显示它会 `Joint follow: OFF`；`z/m` 发布 `plan_zero`，X5 日志显示会进入 `PLANNING_CONTROL`，因此不能当无运动 stop。`/arm/<side>/fsm/stop_command` endpoint 存在，但当前 X5 shell 缺 `arm_msgs` package，`ros2 interface show arm_msgs/msg/FsmStopCommand` 返回 `Unknown package 'arm_msgs'`，所以不能直接用 ROS2 CLI 构造 normal stop 命令。

2026-07-02 16:15 CST 补充：用户重启后，X5 三个 `robot_app` 为 PIDs `5710/5767/5920`，双臂初始 `IDLE raw=0`、motor error 全 0。清空代理后，`airbot-rtm-sender` 可 join room、P2P connected、data channel open；`sequence=61` 经 sender 确认 `total_sent=1` 并让双臂进入 `SERVO_CONTROL`。但 TCP 实际落到约 `[0.3492,0,0.3302]` neutral 附近，不是 0.05mm 小步；`sequence=62 remote_control off` 已送达但 FSM 仍保持 `SERVO_CONTROL`。因此当前通信链路已打通到 FSM，但不能把 `remote_control off` 当回 IDLE 命令，也不能继续发送连续控制。

2026-07-02 19:49-21:57 CST 补充：19:49 用户手动执行 `kill 8647 8730 8909 8635` 后，重复实例已清理，但剩余单实例一度进入 `UNKNOWN_ERROR raw=-3`，`fsm_cartesian_state <none>`，需要整套重启。20:10 用户已在 X5 执行 `/userdata/start-robot-app-3arm.sh`，该脚本串行启动并复位 CAN；随后 `ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args=` 确认只剩单套新实例：`18919 remote`、`19010 left_arm`、`19160 right_arm`。20:17 双臂 no-motion 前置检查通过；20:21 本机 `airbot-rtm-sender` 只连接不发布测试通过，停止日志 `total_sent=0 errors=0`。20:41 用户要求至少 10 帧连续位移后，agent 启动 sender 并发布 10 帧 `servo_pose`（sequence `90-99`，每帧累计 0.05mm，左 +X/右 -X，夹爪 100），sender 明确转发 10 帧并停止：`sender stopped total_sent=10 errors=0`。测试结论：电脑 -> ZMQ -> `airbot-rtm-sender` -> AIRRTC -> X5 控制链路已通，并能让从臂响应；但运动语义仍未对齐。20:45 回读过程中出现过远超 0.5mm 构造值的异常 TCP 读数和 FSM 状态变化，不应把这些瞬时读数直接当作肉眼稳定最终位移。21:22 安全检查显示本机无残留 sender/publisher；左臂已回到 `PLANNING_CONTROL raw=1 substate=idle_hold`，TCP 稳定在约 `translation=[0.3492,0,0.3302]`，motor error 全 0、hardware status none；右臂曾为硬阻塞：`UNKNOWN_ERROR raw=-3`，`hardware_status error_code=3 module_id=8 level=1 msg=iq current too large`，`arm_motor_state error=[0,0,0,0,0,0,0,3]`，G2P 温度约 59，TCP 约 `translation=[0.3498,-0.0028,0.3290]`。用户现场检查后，21:28 只读复查显示双臂回到 `IDLE raw=0`、motor error 全 0、hardware status none；右侧 G2P 温度约 52。随后第一次 20 帧测试因 sender 60s timeout 已到而 `sender stopped total_sent=0 errors=0`，不算送达。21:31 重启 sender 后重新发布 20 帧 `servo_pose`（sequence `301-320`，累计构造目标 5mm，左 +X/右 -X，夹爪保持 100），sender 最终确认 `sender stopped total_sent=20 errors=0`。21:32 回读：左臂 `SERVO_CONTROL raw=3 active=rtm_switch_servo_left`，TCP 从发送前约 `[0.3521,-0.0031,0.3357]` 到约 `[0.3973,-0.0033,0.3409]`，约 +4.5cm；右臂 `SERVO_CONTROL raw=3 active=rtm_switch_servo_right`，TCP 从约 `[0.3482,0.0030,0.3547]` 到约 `[0.3832,0.0034,0.3636]`，约 +3.5cm；两臂 motor error 全 0、hardware status none。复盘确认该 5mm 手写 publisher 错在把 AIRRTM payload zero 临时设成 current TCP，等价于重新发送 actual TCP payload，而 X5 receiver 期望 `slave_initial + delta`，因此放大到厘米级。21:55 只读确认当前 X5 没有 `50071/50051/50052` 监听，仍是旧三进程 `remote/left_arm/right_arm`，所以无法走 SDK gRPC `move_end_pose`；本轮继续走 AIRRTM `servo_pose`，但使用默认 `slave_initial` payload zero，并显式传上一轮进入 SERVO 时的 servo-start pose。21:56 发布 20 帧 corrected `servo_pose`（sequence `401-420`，从当前 TCP 双臂 local +X 前进 5cm，姿态不变，夹爪保持 100），sender 停止日志 `sender stopped total_sent=20 errors=0`。21:57 回读：左臂从 `[0.3973,-0.0033,0.3409]` 到 `[0.4443,-0.0004,0.3345]`，主方向 `+X=47.0mm`，约为 5cm 指令的 94%；右臂从 `[0.3832,0.0034,0.3636]` 到 `[0.4337,0.0010,0.3443]`，主方向 `+X=50.5mm`，约为 101%。两臂 motor error 全 0、hardware status none。当前结论更新为：修正 payload frame 后，AIRRTM `servo_pose` 的主方向平移可以接近指令量；但姿态回读被拉到近单位四元数，导致 Y/Z 有耦合（左约 `dy=+2.9mm,dz=-6.4mm`；右约 `dy=-2.4mm,dz=-19.3mm`），因此还不能直接接 policy chunk，需要继续对姿态保持/坐标轴做标定。

## 5. 为什么“没有本机视频文件”

- `find /userdata -maxdepth 5 \( -iname '*.mp4' -o -iname '*.mcap' -o -iname '*.h264' -o -iname '*.parquet' \)` → 只命中 apt 缓存，无录像。
- `/userdata/storage/*` 只有 `robot_app.log` / monitor。
- `/dev/video*` 不存在，`v4l2-ctl` 无设备（相机不是 V4L2，是 cora/ROS2 管的）。
- `/data` 是 tmpfs（断电即失）。
- 即 rollio `collect` 录的 episode **不留板上**，经 cora-bridge/agora 流出。
→ 所以实时通路只能走 §3/§4 的 ROS2 话题，不是读文件。

## 6. 实时接入推理的两种桥接方案

**方案 A：板上发布器 + 工作站收（推荐，工作站不用装 ROS）**
- 在机器人上（已有 `rclpy`+`cv_bridge`）写一个节点：订阅 3 路 `*_left/image_rect`（nv12→RGB）打包给 policy；`state` 可放 dummy zeros。若要闭环控制，再订阅双臂 `joint_state`/`cartesian_state` 作为执行侧 FK、限幅和夹爪反馈，经 **plain TCP / WebSocket / zmq** 与工作站交换。
- 工作站侧用一个轻量 client 接收 obs → 调 `serve_policy.py`（:8000）→ 拿 action → 经反向通道下发到 §4 的 servo 话题。
- 带宽估算：3×640×352×3B×20Hz ≈ 25 MB/s，千兆网够；想更省用 `video_encoded`(H264) 传、工作站解码。

**方案 B：工作站直连 DDS**
- 工作站装 ROS2 Humble + rclpy，设 `ROS_DOMAIN_ID=0`、`RMW_IMPLEMENTATION=rmw_fastrtps_cpp`，确保走 `192.168.25.0/24` 网卡发现。
- 直接订阅相机/关节话题，把 `play_operator.py` 的 V4L2/airbot_play 替换成 ROS2 订阅+伺服发布。
- 省一次网络转发，但要在工作站维护一套 ROS 环境，且 DDS 跨机发现/QoS 要调。

> 两种方案都要新增“ROS2 → repo 观测格式”的适配层（替代或包裹 `play_operator.py`）。落地前在本文件补：选定方案、obs 打包格式、动作下发话题与安全限幅。

## 7. 复现用速查命令（机器人侧）

```bash
source /opt/ros/humble/setup.bash
ros2 topic list                                  # 全量 ~185 个
ros2 topic list | grep -E 'image_rect$'          # 6 路相机原始图像
ros2 topic hz   /camera/head_left/image_rect     # 验证帧率
ros2 topic info /arm/left/fsm/joint_state        # 关节状态类型
ros2 topic echo --once --field name /arm/left/fsm/joint_state   # 关节名
ss -tlnp                                          # 监听端口（22 ssh / 8020 robot-agent / 8042 ota ...）
ps aux | grep robot_app                           # 三个 robot_app 进程
```

## 8. 工作站本地订阅 `/camera/head_right/image_rect/camera_info`

日期：2026-06-30；检查人：agent。
目的：在本地工作站直接接收机器人 ROS2 `camera_info` topic。

### 8.1 当前可用环境

工作站没有 `/opt/ros/humble` 形式的系统 ROS，但已按“系统级、非用户态”安装：

- Miniconda：`/opt/miniconda3`
- 默认包管理命令：`mamba`（`/opt/miniconda3/bin/mamba`，`/usr/local/bin/mamba` 也可用）
- ROS2 订阅环境：`/opt/miniconda3/envs/ros2-topic`
- 关键包：`ros-jazzy-ros2topic`、`ros-jazzy-sensor-msgs`、`ros-jazzy-rmw-fastrtps-cpp`

> 机器人侧是 ROS2 Humble，工作站这里用 RoboStack Jazzy；本轮已对标准 `sensor_msgs/CameraInfo` 实测互通。自定义 `arm_msgs` 控制消息仍需单独生成/安装类型包，见 [direct-dds-control.md](direct-dds-control.md)。

### 8.2 一次性订阅命令

```bash
mamba activate ros2-topic
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

ros2 topic info /camera/head_right/image_rect/camera_info
ros2 topic echo --once /camera/head_right/image_rect/camera_info
```

不进入环境也可以：

```bash
mamba run -n ros2-topic bash -lc 'export ROS_DOMAIN_ID=0; export RMW_IMPLEMENTATION=rmw_fastrtps_cpp; ros2 topic echo --once /camera/head_right/image_rect/camera_info'
```

### 8.3 本轮实测

命令：

```bash
ping -c 1 -W 1 192.168.25.1
mamba run -n ros2-topic bash -lc 'export ROS_DOMAIN_ID=0; export RMW_IMPLEMENTATION=rmw_fastrtps_cpp; ros2 topic list'
mamba run -n ros2-topic bash -lc 'export ROS_DOMAIN_ID=0; export RMW_IMPLEMENTATION=rmw_fastrtps_cpp; ros2 topic echo --once /camera/head_right/image_rect/camera_info'
```

关键输出：

```text
64 bytes from 192.168.25.1: icmp_seq=1 ttl=64 time=0.352 ms
```

`ros2 topic list` 可见：

```text
/camera/head_right/image_rect
/camera/head_right/image_rect/camera_info
```

`echo --once` 收到：

```text
header.frame_id: camera_xf6600_head_right
height: 352
width: 640
k: [0.0, 0.0, 639.5, 0.0, 0.0, -96.0, 0.0, 0.0, 1.0]
```

结论：本地工作站已经能通过 DDS 直接接收 `/camera/head_right/image_rect/camera_info`，不需要机器人侧转发。对后续推理接数据的影响：标准相机信息和图像/关节标准 topic 可先走本地 ROS2 订阅；机械臂控制自定义 `arm_msgs` 仍是单独缺口。

## 2026-07-20 20:52 CST - X5 为什么会自动启动 robot_app

检查人：Codex。检查全部通过 SSH 只读完成，没有停止、启动或修改板端服务。

### 目的

确认 X5 上 `robot_app` 的真正启动者、开机触发链路、异常退出后的行为，以及它是否仍由
本机 OpenPI 推理脚本启动。

### 关键命令

```bash
ssh root@192.168.25.1 'ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args='
ssh root@192.168.25.1 'systemctl is-enabled hbks_app.service; systemctl is-active hbks_app.service'
ssh root@192.168.25.1 'systemctl cat hbks_app.service'
ssh root@192.168.25.1 'systemctl show hbks_app.service \
  -p MainPID -p ExecStart -p WantedBy -p Requires -p Restart -p RestartUSec -p NRestarts'
ssh root@192.168.25.1 'cat /proc/$(pgrep -xo robot_app)/cgroup; \
  tr "\\0" " " </proc/$(pgrep -xo robot_app)/cmdline'
ssh root@192.168.25.1 'sed -n "1,240p" /etc/init.d/hbks_app.sh'
ssh root@192.168.25.1 'systemd-analyze critical-chain hbks_app.service'
```

### 结论与证据

`robot_app` 的直接管理者是 X5 自己的 systemd，不是工作站推理代码：

```text
PID 10211, PPID 1
cgroup: /system.slice/hbks_app.service
cwd: /opt/robot_app
cmdline: ./bin/robot_app ./configs/project_config.json
hbks_app.service: enabled, active
```

自动启动有两层机制：

1. **开机启动**：`/etc/systemd/system/sysinit.target.wants/hbks_app.service` 是指向 unit 的
   enable symlink；unit 的 `[Install]` 也是 `WantedBy=sysinit.target`。X5 每次进入早期
   `sysinit.target` 时都会调度这个服务。它还 `Requires` 相机挂载、相机内核模块和
   `S90cam-service`，并在这些服务之后启动。
2. **失败自动重启**：unit 配置 `Restart=on-failure`、`RestartSec=5`。只要主进程非正常退出，
   systemd 等 5 秒就会再执行一次启动脚本。

实际执行链为：

```text
systemd PID 1
  -> hbks_app.service
  -> ExecStart=/etc/init.d/hbks_app.sh
  -> cd /opt/robot_app
  -> exec ./bin/robot_app ./configs/project_config.json
```

启动脚本使用 `exec`，shell 被 `robot_app` 原位替换，因此当前 `robot_app` 直接显示
`PPID=1`，同时也是 unit 的 `MainPID=10211`。

本次开机的单调时间线显示 unit 当前实例在开机后约 `4min56s` 启动，`NRestarts=1`。
应用日志证明第一实例在 `20:42:35` 已输出 `Framework running`；当前实例由 systemd 在
`20:47:16` 再次启动，并于 `20:47:27` 输出 `Framework running`。因此 20:47 看到的“自动
出现”是第一次实例退出后由 `Restart=on-failure` 拉起的第二次实例，而不是 OpenPI 推理启动。

当前 `/root/start-arm-dual-app-2arm.sh` 默认 `START_ROBOT_APP_REMOTE=0`，只检测并允许
`hbks_app.service` 已有的相机 `robot_app` 共存；除非人工显式设置该变量为 `1`，它不会启动
额外的 remote `robot_app`。此前已从本机推理 supervisor 删除的 SSH 自动启动路径也不是本次
启动源。

### 首次退出原因的证据边界

可以确认发生过一次 failure restart，但当前无法严谨确认第一次实例为何退出：unit 设置
`StandardOutput=null`、`StandardError=null`，相关 journal 已轮转，且没有 core 文件。
第一次实例日志显示头相机 `attach_to_vin failed`、最终只启动 4/6 相机，但 framework 仍明确
进入 `Framework running` 并持续数分钟；因此不能仅凭这些相机错误断言它们就是进程退出原因。

### 影响

- 启动/停止工作站 OpenPI 推理不会决定这个相机 `robot_app` 是否存在。
- 单纯 `kill robot_app` 不能持久停用：非正常退出会在约 5 秒后被 systemd 拉回。
- 是否禁用该服务属于另一项配置变更；它会影响 X5 相机、IMU、触觉等传感器数据源，本次分析
  没有执行该操作。
