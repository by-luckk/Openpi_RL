# AIRRTM 转换层历史记录（代码已退役）

日期：2026-06-30；更新：2026-07-23 14:17 CST；检查人：agent/Codex。
目的：在不开始实现、不下发真机控制命令的前提下，确认飞书遥操作链路里的 `arm_servo_json`
是否能作为当前 OpenPI relpose action 到 AIRBOT 真机的第一版转换层。

## 1. 历史结论与退役状态

> 2026-07-23 更新：当前生产路线已经固定为 Arm-P7 SDK gRPC。仓库中的 AIRRTM publisher、
> message builder 和测试已按用户确认删除；本文件只保留过去的现场实验、协议和风险证据，以下
> 命令不再是当前仓库可运行入口。当前运行方式见
> [`scripts/README.md`](../scripts/README.md) 和
> [`p7-sdk-grpc-current-state.md`](p7-sdk-grpc-current-state.md)。

2026-07-01 用户曾确认“机械臂摇操控制机械臂”的链路打通。当时 AIRRTM 被评估为
“模型伪主臂”的第一版接入层：保留 `airbot-rtm-sender` 和 X5 侧 `robot_app`，
停止真实 `airbot-driver` 主臂发布端，改由本仓库模型 publisher 在同一个 ZMQ topic 上发布
`arm_servo_json` / `servo_pose` 消息。

2026-07-02 16:10 CST 重启后实测更新：清空本机代理环境变量后，`airbot-rtm-sender` 可稳定 join room、P2P connected、data channel open；`sequence=61` 已确认经 sender 发送到 X5，并让左右臂进入 `SERVO_CONTROL`。但实际 TCP 从重启后的约 left `[0.3521,0.0019,0.3362]`、right `[0.3497,-0.0017,0.3255]` 跳到共同的 servo/teleop neutral 附近 `[0.3492,0,0.3302]`，不是期望的 `0.05mm` 小步；随后 `sequence=62 remote_control off` 已送达但 FSM 仍停留在 `SERVO_CONTROL`。因此当前只证明**传输链路已打到 FSM**，尚未证明 `servo_pose` 运动语义可直接接 policy chunk。

2026-07-02 21:57 CST 重连后实测更新：20:10 整套重启后 X5 只剩单套 `robot_app`：`18919 remote`、`19010 left_arm`、`19160 right_arm`；20:17 双臂 no-motion 已通过；20:21 sender 只连接不发布通过且 `total_sent=0`。20:41 用户要求至少 10 帧连续位移后，agent 发布 10 帧 `servo_pose`（sequence `90-99`，每帧累计 0.05mm，左 +X/右 -X，夹爪 100），sender 确认 `[Send]` 10 次并停止于 `sender stopped total_sent=10 errors=0`。这证明 AIRRTM 通道和 X5 控制入口能够收到电脑发出的连续控制帧；但运动语义仍未对齐。20:45 回读过程中出现过远超 0.5mm 构造值的异常 TCP 读数和 FSM 状态变化，不应把这些瞬时读数直接当作肉眼稳定最终位移。21:22 安全检查显示右臂曾为 `UNKNOWN_ERROR raw=-3`、`iq current too large`、`arm_motor_state error=[0,0,0,0,0,0,0,3]`，G2P 温度约 59；用户现场检查后，21:28 只读复查显示双臂恢复 `IDLE raw=0`、motor error 全 0、hardware status none，右侧 G2P 温度约 52。21:31 发布 20 帧 `servo_pose`（sequence `301-320`，累计构造目标 5mm，左 +X/右 -X，夹爪保持 100）后，sender 确认 `total_sent=20 errors=0`，但回读左约 +4.5cm、右约 +3.5cm。复盘确认该轮手写 publisher 错在把 AIRRTM payload zero 覆盖成 current TCP，等价于再次发送 actual TCP payload；X5 receiver 期望的是 `slave_initial + delta`，所以该轮不应再作为 payload frame 的反证。21:55 只读确认当前 X5 没有 `50071/50051/50052` 监听，不能走 SDK gRPC `move_end_pose`；仍是旧三进程 `remote/left_arm/right_arm`，因此继续走 AIRRTM `servo_pose`。21:56 使用默认 `slave_initial` payload zero，并显式传上一轮进入 SERVO 时的 servo-start pose，发布 20 帧 corrected `servo_pose`（sequence `401-420`，双臂从当前 TCP local +X 前进 5cm，姿态不变，夹爪 100），sender 停止日志 `sender stopped total_sent=20 errors=0`。21:57 回读显示左臂从 `[0.3973,-0.0033,0.3409]` 到 `[0.4443,-0.0004,0.3345]`，主方向 `+X=47.0mm`，约为指令的 94%；右臂从 `[0.3832,0.0034,0.3636]` 到 `[0.4337,0.0010,0.3443]`，主方向 `+X=50.5mm`，约为指令的 101%。两臂 motor error 全 0、hardware status none。当前结论：修正 payload frame 后，AIRRTM `servo_pose` 的主方向平移可以接近指令量；但姿态回读被拉到近单位四元数，造成 Y/Z 耦合（左 `dy≈+2.9mm,dz≈-6.4mm`；右 `dy≈-2.4mm,dz≈-19.3mm`），因此不能直接接 policy chunk，下一步要标定/修正姿态保持和坐标轴。

2026-07-07 17:48-17:52 CST 重连后只读/只连接更新：X5 可 SSH，三进程 `robot_app` 正常运行（remote PID `2452`、left PID `2523`、right PID `2680`），双臂均为 `IDLE raw=0`、motor error 全 0、controller IDLE、hardware status none，TCP 可读。当前 X5 `/opt/robot_app/configs/remote/airrtm_config.json` 使用 `room_id=rtm_sender_room_1`、`user_id=airrtc_robot`、`data_channel_label=rtm_sender`；而本机原始 `/home/discover/airbot_teleop/config/sender/airrtc_e2.yaml` 仍是 `room_id=rtm_sender_room`。用原始 room 启动 sender 只能 `joined room room=rtm_sender_room`，随后 `p2p connection timeout after 60000ms`；X5 remote 同期 `AIRRTM stats ... p2p=0 dc_open=0`。把本机 sender 临时配置改成 `rtm_sender_room_1` 后，只连接不发布测试通过：`remote user joined user=airrtc_robot`、`p2p established`、`data channel state=open`、`remote data channel received ... state=open`，停止时 `sender stopped total_sent=0 errors=0`。因此当前控制通道本身可用，但启动 sender 时必须使用与 X5 一致的 `rtm_sender_room_1` 配置；旧的 `rtm_sender_room` 记录只作为历史配置。19:01 用当时读到的 live TCP 只做过本地 no-publish 转换验证：

2026-07-07 18:04-18:08 CST 双臂同步 10cm / 500 帧慢速实测更新：在用户确认工作空间清空后，用 `rtm_sender_room_1` 启动 sender，并以 50Hz、每方向 500 帧 ramp 到 10cm、再 500 帧返回基准的方式同时控制左右臂。实际只完成 `+X` 与 `-X` 两个方向：`+X` 目标处左臂主轴 `+98.1mm`、串轴 `15.4mm`，右臂主轴 `+99.5mm`、串轴 `8.0mm`；回基准后左/右误差分别约 `24.4mm` / `13.4mm`。`-X` 目标处左臂主轴 `108.9mm`、串轴 `55.2mm`，右臂主轴 `100.7mm`、串轴 `20.6mm`；随后左臂回读窗口内 `fsm_cartesian_state` 多帧为空，脚本停止，未继续 `+Y/-Y/+Z/-Z`。sender 停止日志为 `sender stopped total_sent=2050 errors=0`，收尾只读检查显示本机无 sender/publisher 残留、`6000` 未监听；X5 双臂仍在 `SERVO_CONTROL/CSP` hold，TCP 稳定约 `[0.3492,0,0.3301]`，motor error 全 0、hardware status none。当前结论修正为：AIRRTM `servo_pose` 的 X 主轴比例基本可控，但串轴、姿态/坐标耦合、返回基准和状态回读稳定性仍未解决；不能直接接 policy chunk，也不应继续扩大六方向测试，下一步应先修正姿态保持/回基准策略和 `fsm_cartesian_state` 读数容错。

```bash
uv run python examples/airbot/policy_to_airrtm_bridge.py \
  --action-source mock \
  --left-current-pose 0.3521,-0.0017,0.3362,0.0054,-0.0026,0.0010,1.0000 \
  --right-current-pose 0.3497,-0.0010,0.3251,-0.0006,0.0109,-0.0004,0.9999 \
  --assume-servo-start-current \
  --sequence 70 \
  --mock-step-m 0.00005 \
  --gripper-unit model_0_100
```

输出 `action_chunk_shape=[50,32]`、`selected_action_first14=[5e-05,...,100,-5e-05,...,100]`、`payload.command=servo_pose`、`publish=false`。这只证明转换器能基于 live TCP 生成 `arm_servo_json`，未发送控制帧，也不解除“双 robot_app”阻塞。


模型到从臂的转换链路：

1. policy 仍只负责三路 RGB 图像 + prompt + dummy state → 输出 relpose action。
2. 转换层把每步有效 action 前 14 维拆成左右臂 `Δpos(3)+Δrotvec(3)+gripper(1)`。
3. 对每臂用当前从臂末端/TCP pose 积分得到模型期望的 actual TCP target；模型输出的每一行都相对本次观测
   的 current TCP，不把 chunk 内第 i 行链式叠到第 i-1 行。
4. AIRRTM `servo_pose` payload 不能直接发 actual TCP target。真实 `airbot_driver` 以
   `slave_arm_initial_pose` 为 payload 零点，发送 `slave_initial + delta`；X5 receiver 进入
   `SERVO_CONTROL` 后会把这个 delta 叠到 servo-start actual TCP 上。因此 OpenPI publisher 要发：
   `payload_pose = slave_initial_pose + (desired_actual_tcp - servo_start_actual_tcp)`，四元数同理用
   `payload_q = (desired_q * inv(servo_start_q)) * slave_initial_q`。
5. ZMQ topic=`servo` → `airbot-rtm-sender` → X5 `airrtm_config.json` 的 `arm_servo` 接收端。

这条路的价值是：第一版复用已打通的摇操控制通道，不必先生成/编译 `arm_msgs`，也不必自己处理
裸 DDS 类型。Arm-P7 SDK gRPC 仍保留为 current TCP pose 读取、no-motion smoke、受保护直控和
故障排查的通道；直连 DDS 仍然成立，但更像第二条更底层、更低延迟的路线。

## 2. 用户补充的坐标系约束

用户补充的截图里有 `cam2tcp` 和 `cam2imu` 两个矩阵，但本次记录不把它们作为默认输入：

- 当前工作假设：SDK/AIRRTM `servo_pose` 控制坐标系已经是夹爪末端/TCP 坐标系。
- 因此第一版转换层默认直接生成 TCP/夹爪末端目标 pose，不额外套用截图中的 `cam2tcp` 或 `cam2imu`。
- 如果后续选择“用 VIO 相机 pose 作为执行参考”的路线，再单独确认数据集 frame、SDK frame 和手眼外参；
  不能把截图矩阵未经验证地硬编码进转换层。

## 3. 飞书文档证据

只读拉取飞书文档 `SeXHd79NvoX2Ysxow2DczjmCnde` 关键词
`airrtm_config|servo_input_mode|arm_servo_json|data_sources|publish_to_arm|queue_mode`。

关键片段：

```json
{
  "rtm": {
    "channel_name": "rtm_sender_room",
    "data_sources": ["arm_servo"],
    "arm_mode": "both",
    "servo_input_mode": "cartesian_pose",
    "arm_servo_min_interval_ms": 5,
    "queue_mode": "latest",
    "publish_to_arm": true
  }
}
```

含义：X5 接收端已支持 `arm_servo` 数据源，输入模式是笛卡尔 pose，队列取最新命令，并可直接发布到机械臂。

飞书同文档的数采接口片段还确认：

- action 数采接口是 `rt/arm/<left|right>/control/control_command`，类型
  `arm_msgs::msg::dds_::ControlCommand_`。
- state 是 `rt/arm/<left|right>/control/joint_states`，类型
  `sensor_msgs::msg::dds_::JointState_`。
- H264 图像来自 6 路 `rt/camera/<cam>/image_rect/video_encoded`。
- G2P 夹爪行程是 `0.0` 到 `0.096` m。

这些数采接口仍是关节空间记录，不等于当前 checkpoint 的 relpose action；本文件关注的是
`arm_servo_json`/`servo_pose` 这条执行通道。

## 4. 本地 airbot_driver 证据

只读检查：

```bash
rg -n "make_servo_pose_payload|pose_to_payload_array|custom_type|arm_servo_json|ZmqJsonPublisher"   /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver
sed -n '1,120p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/common/message_schema.py
sed -n '260,290p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/apps/publish_airbot_e2_pose.py
sed -n '1,90p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/common/zmq_publisher.py
rg -n "endpoint|topic|channel|custom_type" /home/discover/airbot_teleop/config
```

确认结果：

```python
make_servo_pose_payload(
    left_pose=[x, y, z, qx, qy, qz, qw],
    right_pose=[x, y, z, qx, qy, qz, qw],
    left_gripper=float,
    right_gripper=float,
)
```

外层消息：

```python
make_sender_message(payload, channel="airrtc", custom_type="arm_servo_json", ...)
```

ZMQ 发布格式：

```text
servo {"channel":"airrtc","custom_type":"arm_servo_json","payload":{...},"metadata":{...}}
```

本地配置：

```yaml
# driver/airbot_e2_pose.yaml
endpoint: "tcp://0.0.0.0:6000"
topic: "servo"
channel: "airrtc"
custom_type: "arm_servo_json"

# sender/input/airrtc_e2.yaml
endpoint: "tcp://127.0.0.1:6000"
topic: "servo"
```

2026-07-02 11:28 CST 复查：`/usr/bin/airbot-rtm-sender` 存在；`/home/discover/airbot_teleop/config/sender/airrtc_e2.yaml` 的 AIRRTC `server_url=https://8.138.229.216:7210`、`room_id=rtm_sender_room`、`data_channel_label=rtm_sender`，输入配置 `sender/input/airrtc_e2.yaml` 订阅 `tcp://127.0.0.1:6000`、topic=`servo`。因此下一步只需启动 sender，不需要启动原 `airbot-driver`。

## 5. 模型替代主臂的接入方案

实际替换点是 **ZMQ publisher**，不是 CAN、不是 `airbot-arm`，也不是旧的关节空间
`play_operator.send_action()`：

| 原摇操链路 | 模型伪主臂链路 |
|---|---|
| `airbot-arm` 通过 CAN 读 E2 主臂 | 不需要 CAN，不启动 `airbot-arm` 主臂服务 |
| `airbot-driver` 读主臂 pose 并发布 `servo_pose` | OpenPI publisher 从 policy action 生成同样的 `servo_pose` |
| `airbot-rtm-sender` 订阅 `tcp://127.0.0.1:6000` topic=`servo` | 保持不变 |
| X5 `robot_app` 接收 `arm_servo_json` 并控制从臂 | 保持不变 |

启动时应只保留一个 `servo` publisher：

```bash
# 只启动 sender，不启动 airbot-driver；避免真实主臂和模型同时发同一个 topic。
# 本机若有 http_proxy/ALL_PROXY 等代理变量，必须清空；否则 sender 可能 join room 失败。
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  airbot-rtm-sender ~/airbot_teleop/config/sender/airrtc_e2.yaml

# dry-run publisher 绑定同一个 endpoint/topic：
# endpoint=tcp://0.0.0.0:6000, topic=servo, channel=airrtc, custom_type=arm_servo_json
```

模型 publisher 每个控制周期做：

1. 从 policy server 取 `actions`，shape 已实测为 `(50, 32)`。
2. 只取当前执行步 `actions[i, :14]`，拆成左右臂 7 维；不要一次把 50 行完整 chunk 全部打到从臂。
3. 用当前从臂 TCP pose 调 `convert_action_step()` 得到 `DualArmTcpTarget`。
4. 做 per-step 限幅和状态 guard；第一版建议只允许毫米级以下平移、很小旋转，超限直接拒绝。
5. 打包为：

```python
payload = make_servo_pose_payload(
    left_pose=target.left.pose.as_xyz_xyzw().tolist(),
    right_pose=target.right.pose.as_xyz_xyzw().tolist(),
    left_gripper=target.left.gripper.ratio_0_1,
    right_gripper=target.right.gripper.ratio_0_1,
)
message = make_sender_message(
    payload,
    channel="airrtc",
    custom_type="arm_servo_json",
    source="openpi_policy",
    sequence=sequence,
)
pub.publish(message, topic="servo")
```

2026-07-02 已落地 dry-run-first 实现：

| 文件 | 作用 |
|---|---|
| `src/openpi/shared/airbot_airrtm_servo.py` | 纯 Python AIRRTM `servo_pose` message builder；不依赖 `airbot_driver`；`pyzmq` 只在显式发布时 runtime import |
| `src/openpi/shared/airbot_airrtm_servo_test.py` | 覆盖消息 schema、topic wire format、平移/旋转 guard、夹爪单位切换 |
| `examples/airbot/airrtm_servo_dryrun.py` | CLI；默认只打印单帧 JSON，不发布；发布必须同时传 `--publish --allow-robot-motion`，且必须显式提供 live current pose（`--left-current-pose/--right-current-pose`、`--left-sdk/--right-sdk` 或 `--fsm-monitor-host`）；默认 `teleop_initial_delta` 下还必须提供 `--left/right-servo-start-pose`，或在确认 receiver 尚未进入 `SERVO_CONTROL` 时显式传 `--assume-servo-start-current`；`--remote-control off|on` 可单独 dry-run AIRRTM 遥操开关命令，不读取 TCP pose |

已验证命令：

```bash
uv run ruff check   src/openpi/shared/airbot_airrtm_servo.py   src/openpi/shared/airbot_airrtm_servo_test.py   examples/airbot/airrtm_servo_dryrun.py

uv run pytest   src/openpi/shared/airbot_relpose_test.py   src/openpi/shared/airbot_p7_adapter_test.py   src/openpi/shared/airbot_airrtm_servo_test.py

uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 42
```

验证结果：`ruff` 通过；相关共享层测试 `16 passed`；dry-run 输出 `channel=airrtc`、
`custom_type=arm_servo_json`、`payload.command=servo_pose`，左臂默认 `x+0.0002m`、右臂默认
`x-0.0002m`，夹爪按 0-1 比例输出 `1.0`。该 dry-run 命令未带 `--publish`，不会发送 ZMQ 消息。

2026-07-02 11:01 CST 安全补丁追加验证：`uv run python examples/airbot/airrtm_servo_dryrun.py --publish --allow-robot-motion` 在未提供 current pose 时直接拒绝，输出 `--publish requires explicit current poses...`，因此不会用内置示例 pose 发布到机械臂。

2026-07-02 11:21 CST 已把 X5 原生 `fsm_monitor` 加入 dry-run current TCP pose 来源：`--fsm-monitor-host root@192.168.25.1` 会分别执行 `fsm_monitor --arm-side l/r`，解析最后一条 `[fsm_cartesian_state] translation=[...] orientation=[...]`，再生成 `servo_pose`。现场只读验证命令：

```bash
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 45 --fsm-monitor-host root@192.168.25.1 --mock-step-m 0.0002
```

关键输出：`left_pose=[0.349399999996, -3.999999960000001e-08, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995]`，`right_pose=[0.349000000004, 3.999999960000001e-08, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995]`，左右夹爪均为 `1.0`。命令未带 `--publish`，没有发送 ZMQ 或机械臂控制消息。

同轮只读现场核对：本机没有 `airbot-driver` / `airbot-rtm-sender` / `robot_app` 实际进程，`6000/50071/50051/50052` 未监听；X5 有三个旧栈 `robot_app` 进程（left PID `3411`、remote PID `7605`、right PID `7771`），remote `airrtm_config.json` 仍是 `data_sources=["arm_servo"]`、`servo_input_mode="cartesian_pose"`、`queue_mode="latest"`、`publish_to_arm=true`；X5 当前没有 `50071/50051/50052/6000` 监听，所以 Arm-P7 SDK gRPC 路线此刻不在线，第一版 AIRRTM dry-run 使用 `fsm_monitor` 读 current TCP。

夹爪说明：模型夹爪约定是 `0` 闭合、`100` 最大张开；本地 `airbot_relpose.py` 已能同时给出
`model_0_100`、`ratio_0_1`、`g2p_m`、`p7_mm`。当前 E2 示例里的 `left_gripper/right_gripper`
来自 `e2_gripper_to_percent()`，即 0-1 归一化比例，所以 AIRRTM 第一版 publisher 应优先发
`ratio_0_1`。如果实测 X5 接收端要求 G2P 米或 0-100，再只替换这个打包字段，不改模型语义。

仍需在首次真机闭环前确认：

1. 当前 TCP pose 来源：当前现场可用的是 X5 `/opt/robot_app/bin/fsm_monitor --arm-side l/r`；CLI 已支持 `--fsm-monitor-host root@192.168.25.1` 自动读取。Arm-P7 SDK gRPC `get_end_pose()` 仍是更干净的程序化接口，但 2026-07-02 11:21 CST 现场 `50071` 未监听，暂不可用。后续若能编译/安装 `arm_msgs`，也可改为直接订阅 ROS2/DDS `cartesian_state`。
2. AIRRTM payload frame 已在 2026-07-02 12:07 CST 收敛：payload 以 `slave_arm_initial_pose` 为零点，表示相对 servo-start actual TCP 的 delta，不是 live actual TCP 绝对值。
3. 安全退出/idle/stop 的当前结论见 §8 和 §10：`plan_zero` 会触发规划运动，不能当无运动 stop；`remote_control false` 已实测可经 AIRRTM 送达，但未让 FSM 从 `SERVO_CONTROL` 回到 IDLE；`/arm/<side>/fsm/stop_command` 语义更像 normal stop，但当前 shell 缺 `arm_msgs` package，不能直接用 `ros2 topic pub` 构造。
4. 下一轮不能直接跑 policy chunk，也不应继续扩大六方向测试。2026-07-02 21:56 CST corrected `servo_pose` 5cm 测试证明主方向平移接近指令量（左 94%，右 101%）；2026-07-07 18:04-18:08 CST 双臂 10cm/500 帧实测进一步确认 X 主轴比例大致可控（`+X` 左 98.1mm、右 99.5mm；`-X` 左 108.9mm、右 100.7mm），但串轴仍明显（左 `-X` 串轴约 55.2mm、右 `-X` 串轴约 20.6mm），回基准后会落到 servo neutral 附近而非原始基准，且左臂一度读不到 `fsm_cartesian_state`。下一步应先修正姿态保持、回基准策略和状态读数容错，再做 Y/Z 方向或 policy 闭环。

## 6. 2026-07-02 单帧真机测试结果：通道打通，但不能继续扩大

日期：2026-07-02 11:48 CST；检查人：agent。

执行步骤：

1. 发布前检查本机无 `airbot-driver` / `airbot-arm` / `robot_app` / 旧 `airbot-rtm-sender`，`6000/50071/50051/50052` 未监听。
2. X5 仍为旧栈三进程：left PID `3411`、remote PID `7605`、right PID `7771`。
3. dry-run 使用 `--fsm-monitor-host root@192.168.25.1` 生成 0.1mm 测试 JSON，未发布。
4. 启动 sender：`airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml`。sender 成功加入 `rtm_sender_room`，看到 `airrtc_robot`，P2P connected，data channel open，并订阅 `tcp://127.0.0.1:6000` topic `servo`。
5. 发布一帧极小命令：

```bash
uv run python examples/airbot/airrtm_servo_dryrun.py \
  --sequence 47 \
  --fsm-monitor-host root@192.168.25.1 \
  --mock-step-m 0.00005 \
  --left-gripper 0 \
  --right-gripper 0 \
  --publish \
  --allow-robot-motion
```

实际发送 payload：

```json
{
  "command": "servo_pose",
  "left_pose": [0.349249999999, -9.999999900000002e-09, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995],
  "right_pose": [0.349150000001, 9.999999900000002e-09, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995],
  "left_gripper": 0.0,
  "right_gripper": 0.0
}
```

结果：

- sender 日志确认收到并转发：`[Send] ... total_sent=1 ... custom_type=arm_servo_json ... sequence=47`。
- 随后已停止 sender，日志：`sender stopped total_sent=1 errors=0`。
- X5 双臂 `robot_app` 进程仍在，无残留 `fsm_send_command` / smoke test 进程。
- 左臂/右臂 FSM 均进入 `SERVO_CONTROL`，active 分别为 `rtm_switch_servo_left/right`；电机 `error=[0,0,0,0,0,0,0,0]`。
- 关键异常：发送目标本应是相对 pre-read current TCP 的 `0.05mm` 小步，但发布后 `fsm_cartesian_state` 回读不是目标附近，而是约：
  - left: `translation=[0.3895, -0.0000, 0.3353]`
  - right: `translation=[0.3894, -0.0000, 0.3353]`
  发布前 dry-run/current TCP 约为 `translation=[0.3492, -0.0000, 0.3302]`。2026-07-02 12:07 CST 已修正结论：该偏移主要来自 payload frame 误用。AIRRTM `servo_pose` payload 应是 `slave_initial_pose + (desired_actual_tcp - servo_start_actual_tcp)`，不是 live actual TCP 绝对值。
- 曾尝试只读查看 `/opt/robot_app/bin/fsm_send_command --help`，但该二进制没有打印帮助，反而启动了 `fsm_arm_control_smoke_test`；已立即 Ctrl-C 中断，未用它恢复状态。

结论：**AIRRTM 通信和控制通道已真实打通，但不能继续扩大到连续控制或 policy chunk。** 坐标 frame 已在 §7 收敛：后续只允许在明确 `servo_start_actual_tcp` 后发 `slave_initial_pose + 极小 delta`，或先让 receiver 回到已知非 `SERVO_CONTROL` 状态再用 `--assume-servo-start-current`。在此之前不要再用 `fsm_monitor` current TCP 直接生成 AIRRTM 绝对 payload。

当前收尾状态：本机 sender 已停，没有本机 ZMQ publisher；X5 双臂仍显示 `SERVO_CONTROL` hold，电机 error 为 0。12:53 CST 已确认 `plan_zero` 会触发规划运动，不能作为无运动恢复命令；本轮没有再发任何控制帧。


## 7. 2026-07-02 payload frame 修正：`servo_pose` 以 slave initial 为零点

日期：2026-07-02 12:07 CST；检查人：agent。

目的：解释 11:48 单帧测试为什么把 0.05mm 小步放大成约 40mm 偏移，并修正本仓库 AIRRTM 转换层。

只读证据：本地真实摇操 publisher 配置包含：

```yaml
# /home/discover/airbot_teleop/config/driver/airbot_e2_pose.yaml
master_arm_initial_pose: "0.05092698708176613,-0.6010147333145142,0.5575265288352966,-1.660753846168518,1.437972068786621,1.6237506866455078"
slave_arm_initial_pose: "0.3089256671,-0.0000498008,0.3245732613,-0.0000000007,-0.000002347,-0.0001426536,0.9999999898"
```

真实 `airbot_driver/apps/publish_airbot_e2_pose.py` 的逻辑是：

```python
left_delta_pose = make_pose_delta_from_initial(left_sample.pose, teleop_state.left_reference)
left_pose = make_slave_absolute_pose(left_delta_pose, args.slave_arm_initial_pose)
payload = make_servo_pose_payload(left_pose=pose_to_payload_array(left_pose), ...)
```

其中 `make_slave_absolute_pose()` 对平移做 `slave_initial_pose.translation + delta_pose.translation`，对旋转做 `delta_quaternion * slave_initial_quaternion`。这说明 AIRRTM payload 里的 `left_pose/right_pose` 是“以 follower/slave 初始 pose 为零点的 teleop 目标”，不是当前从臂 actual TCP 的绝对值。

X5 日志也说明 receiver 对第一帧 `servo_pose` 会先切模式再回放缓存命令：

```text
2026-07-02 11:38:49.435 [ArmServo] Joint follow OFF, auto enabling before servo_pose
2026-07-02 11:38:49.435 [ArmServo] Dispatching command: remote_control, enable=1, control_mode=servo
2026-07-02 11:38:49.442 [ArmServo] [left] EEF CSP switch accepted for req=airrtc_47
2026-07-02 11:38:49.446 [ArmServo] [right] EEF CSP switch accepted for req=airrtc_47
2026-07-02 11:38:49.448 [fsm_service_node#left] Replay cached servo pose command after servo startup
2026-07-02 11:38:49.452 [fsm_service_node#right] Replay cached servo pose command after servo startup
```

数学核对：11:48 测试时发布前 current TCP 约 `x=0.3492,z=0.3302`，local config 的 `slave_initial` 是 `x=0.3089256671,z=0.3245732613`，我们错误发送的 payload 是 `x=0.349249999999,z=0.3302`。按 `actual ≈ servo_start + (payload - slave_initial)` 预测：

```text
x = 0.3492 + (0.349249999999 - 0.3089256671) = 0.389524332899
z = 0.3302 + (0.3302 - 0.3245732613) = 0.3358267387
```

实测回读约 `left=[0.3895, -0.0000, 0.3353]`、`right=[0.3894, -0.0000, 0.3353]`，量级吻合。因此 11:48 的异常不是模型问题，而是我们当时把 AIRRTM payload frame 当成了 actual TCP frame。

本仓库修正：

- `src/openpi/shared/airbot_airrtm_servo.py` 新增 `payload_pose_mode`，默认 `teleop_initial_delta`；保留 `actual_tcp` 作为显式调试模式。
- 默认 `left/right_payload_zero_pose` 使用本地 `airbot_e2_pose.yaml` 的 `slave_arm_initial_pose`。
- 新增 `servo_start_tcp_poses` 参数：actual target 仍由模型 relpose + current TCP 算出，但发布 payload 改成 `slave_initial + (actual_target - servo_start)`；四元数使用同样的 delta 组合。
- `examples/airbot/airrtm_servo_dryrun.py` 新增 `--payload-pose-mode`、`--left/right-payload-zero-pose`、`--left/right-servo-start-pose`、`--assume-servo-start-current`。在默认 `teleop_initial_delta` 模式下，带 `--publish` 时如果没有显式 servo-start 或确认 current 即 servo-start，会直接拒绝发布。

验证命令：

```bash
uv run ruff check examples/airbot/airrtm_servo_dryrun.py src/openpi/shared/airbot_airrtm_servo.py src/openpi/shared/airbot_airrtm_servo_test.py
uv run pytest src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_p7_adapter_test.py src/openpi/shared/airbot_airrtm_servo_test.py
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 48 --fsm-monitor-host root@192.168.25.1 --mock-step-m 0.00005
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 49 --fsm-monitor-host root@192.168.25.1 --mock-step-m 0.00005 --publish --allow-robot-motion
```

关键输出：

```text
All checks passed!
18 passed in 0.05s
warning: using current TCP as servo-start TCP for dry-run only
left_pose=[0.3089756671, -4.98008e-05, 0.3245732613, ...]
right_pose=[0.308875667101, -4.98008e-05, 0.3245732712999999, ...]
--publish in teleop_initial_delta mode requires --left-servo-start-pose/--right-servo-start-pose, or --assume-servo-start-current after confirming the receiver has not already entered SERVO_CONTROL.
```

结论：下一次单帧真机验证的 payload 应接近 `slave_initial_pose ± 小 delta`，而不是 `fsm_monitor` 当前 TCP 附近的 `0.349/0.389`。当前仍不允许连续控制；必须先让 receiver 回到已知非 SERVO_CONTROL 状态，或显式记录本次 SERVO_CONTROL 的 `servo_start_tcp` 后再发单帧。

## 8. 2026-07-02 安全退出/remote_control 只读排查与 dry-run 能力

日期：2026-07-02 12:53 CST；检查人：agent。

目的：在不继续发送 `servo_pose` 的前提下，确认 X5 当前状态、`remote_control false` / `plan_zero` / `stop_command` 的语义，并把“停止遥操”做成可复现 dry-run 命令。

只读检查命令：

```bash
pgrep -af 'airbot-rtm-sender|airbot-driver|airbot-arm|airrtm_servo_dryrun|robot_app'
ss -lntp | rg ':6000|:50071|:50051|:50052'
ssh -o ConnectTimeout=3 root@192.168.25.1 "ps -eo pid,cmd | grep robot_app | grep -v grep"
ssh -o ConnectTimeout=3 root@192.168.25.1 "timeout 4 /opt/robot_app/bin/fsm_monitor --arm-side l"
ssh -o ConnectTimeout=3 root@192.168.25.1 "timeout 4 /opt/robot_app/bin/fsm_monitor --arm-side r"
sed -n '600,650p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/apps/publish_airbot_e2_pose.py
ssh -o ConnectTimeout=3 root@192.168.25.1 "grep -RIn 'remote_control, enable=0\|plan_zero\|Joint follow: OFF\|PLANNING_CONTROL' /userdata/storage 2>/dev/null | tail -120"
ssh -o ConnectTimeout=3 root@192.168.25.1 "source /opt/ros/humble/setup.bash && ros2 topic info -v /arm/left/fsm/stop_command"
ssh -o ConnectTimeout=3 root@192.168.25.1 "source /opt/ros/humble/setup.bash && ros2 interface show arm_msgs/msg/FsmStopCommand"
```

关键输出：

```text
# 本机：无 airbot-rtm-sender / airbot-driver / airrtm_servo_dryrun / robot_app；6000/50071/50051/50052 无监听
3411 ./bin/robot_app ./configs/left_arm/project_config.json
7605 ./bin/robot_app ./configs/remote/project_config.json
7771 ./bin/robot_app ./configs/right_arm/project_config.json
[fsm_state] state=SERVO_CONTROL raw=3 active=rtm_switch_servo_left/right
[fsm_cartesian_state] translation=[0.3895, -0.0000, 0.3353]
motor error=[0,0,0,0,0,0,0,0]
```

本地 `publish_airbot_e2_pose.py` 快捷键语义：

```text
p -> make_remote_control_payload(False)  # 停止遥操
l -> make_remote_control_payload(False)  # 安全退出
z/m -> make_plan_zero_payload(...)       # 回零/规划，不是无运动 stop
```

X5 历史日志语义：

```text
Dispatching command: remote_control, enable=0, control_mode=servo
Joint follow: OFF
Dispatching command: plan_zero, req=...
FSM state light updated ... state=PLANNING_CONTROL
```

ROS2 endpoint 现状：`/arm/<left|right>/fsm/stop_command` 存在，类型显示为 `arm_msgs/msg/FsmStopCommand`，订阅方为 1；`switch_control_state_command` 也存在。但当前 X5 shell 执行 `ros2 interface show arm_msgs/msg/FsmStopCommand` 返回 `Unknown package 'arm_msgs'`，`/opt/robot_app/share/arm_msgs` 也不存在。因此 ROS2 CLI 虽能看到 DDS endpoint，当前不能直接构造/发布 `FsmStopCommand` 或 `FsmSwitchControlStateCommand`。

本仓库新增能力：

- `src/openpi/shared/airbot_airrtm_servo.py` 新增 `make_remote_control_payload(enable=...)`，输出 `{"command":"remote_control","enable":false|true}`。
- `examples/airbot/airrtm_servo_dryrun.py` 新增 `--remote-control off|on`。该模式只构造 AIRRTM 遥操开关消息，不解析 current TCP pose，不走 relpose/servo target 转换；如带 `--publish` 仍必须显式加 `--allow-robot-motion`。

验证命令与结果：

```bash
uv run ruff check src/openpi/shared/airbot_airrtm_servo.py examples/airbot/airrtm_servo_dryrun.py src/openpi/shared/airbot_airrtm_servo_test.py
# All checks passed!

uv run pytest src/openpi/shared/airbot_airrtm_servo_test.py
# 8 passed in 0.04s

uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 51 --remote-control off
# payload={"command":"remote_control","enable":false}
```

结论：本轮没有发送新的 ZMQ/AIRRTM 控制帧。`plan_zero` 会进入规划控制，不能当安全 stop；`remote_control false` 是官方摇操端的停止遥操命令，预计会关闭 joint follow，但是否让 FSM 退出当前 `SERVO_CONTROL` 仍需一次受控发布后观察；`stop_command` 语义更接近 normal stop/IDLE，但在没有可用 `arm_msgs` 类型或官方 CLI 前不能盲发。

2026-07-02 15:13 CST 后续更新：X5 `robot_app` 已重启，双臂随后回读为 `IDLE raw=0`，所以“先发一帧 `remote_control off` 清理当前 `SERVO_CONTROL`”这个下一步前提已经过期；当前下一步应先处理后续 `UNKNOWN_ERROR` / AIRRTC 断链问题，不能继续发运动命令。

## 9. 2026-07-02 15:13 CST - sequence 55 单帧发布未确认送达

目的：在双臂回到 `IDLE` 后，用 0.05mm 单帧 `servo_pose` 验证本仓库 publisher 到 X5 remote 的端到端链路。

发送前状态：本机无 sender / dry-run 残留；X5 `robot_app` 为 PIDs `2648/2729/2911`；8s `fsm_monitor` 回读左右臂均为 `IDLE raw=0`，motor error 全 0，TCP 约 left `[0.3521,-0.0008,0.3357]`、right `[0.3490,-0.0021,0.3122]`。

先执行 dry-run：

```bash
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 54 \
  --left-current-pose 0.3521,-0.0008,0.3357,0.0004,-0.0015,-0.0010,1.0000 \
  --right-current-pose 0.3490,-0.0021,0.3122,-0.0016,0.0422,-0.0025,0.9991 \
  --mock-step-m 0.00005 --assume-servo-start-current
# payload.command=servo_pose, custom_type=arm_servo_json, left/right gripper=1.0, 未 publish
```

随后启动 sender 并尝试实际发布 sequence 55：

```bash
airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 55 \
  --left-current-pose 0.3521,-0.0008,0.3357,0.0004,-0.0015,-0.0010,1.0000 \
  --right-current-pose 0.3490,-0.0021,0.3122,-0.0016,0.0422,-0.0025,0.9991 \
  --mock-step-m 0.00005 --assume-servo-start-current --publish --allow-robot-motion
# 本地 publisher 打印 servo {... sequence=55 ...}
```

关键结果：sender 已成功加入房间并一度显示 data channel open，但在实际发送前后 data channel 关闭，日志出现 `data channel is not open` / `send failed ... sequence=55`。因此本轮只能确认本地 ZMQ publisher 执行过，不能确认 AIRRTC 已送达 X5，也不能确认机械臂执行了该帧。

收尾状态：本机无 sender / dry-run 残留，`6000` 无监听。X5 后续 `fsm_monitor` 显示 `UNKNOWN_ERROR raw=-3`，hardware status 有 `ARM_STATE` / `ARM_FULL_STATE loss`，但对应时间戳约 `15:16:28` / `15:16:33`，早于 sequence 55 实际发送尝试，因此不能把异常直接归因于 sequence 55。当前安全结论是不再发送任何运动命令，只做只读诊断，直到 FSM 恢复 `IDLE` 且 AIRRTC data channel 稳定。

## 10. 2026-07-02 16:15 CST - 重启后 AIRRTM 送达成功但运动语义仍不安全

目的：用户重启机械臂后，继续打通 OpenPI publisher -> ZMQ `servo` -> `airbot-rtm-sender` -> AIRRTC -> X5 `robot_app` -> FSM 的链路，并判断是否可以直接接 policy chunk。

发送前只读检查命令：

```bash
pgrep -af 'airbot-rtm-sender|airrtm_servo_dryrun|robot_app'
ss -lntp
ssh root@192.168.25.1 "ps -eo pid,cmd | grep robot_app | grep -v grep"
ssh root@192.168.25.1 "timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side l"
ssh root@192.168.25.1 "timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side r"
```

关键状态：本机没有 sender/publisher 残留，相关端口无 `6000/50071/50051/50052` 监听；X5 重启后为 remote/left/right 三个 `robot_app`，PIDs `5710/5767/5920`。左右臂均为 `IDLE raw=0`，motor error 全 0；TCP 约 left `[0.3521,0.0019,0.3362]`、right `[0.3497,-0.0017,0.3255]`。

网络诊断：直接运行 sender 失败，日志为 `join room failed error=-2`、`Invalid room or user`、`WebSocket connection failed`。`nc -vz -w 3 8.138.229.216 7210` 可达，`curl --noproxy '*' 'http://8.138.229.216:7210/socket.io/?EIO=4&transport=polling'` 返回 200；问题是本机 `http_proxy/https_proxy/ALL_PROXY=http://127.0.0.1:7897` 影响 sender。可用启动命令：

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml
```

清空代理后，sender 日志显示 WebSocket `101 Switching Protocols`、joined room `rtm_sender_room`、remote user `airrtc_robot` joined、P2P connected、data channel open，并订阅 `tcp://127.0.0.1:6000` topic `servo`。如果 sender 打开后空闲约 25 秒不发布，data channel 会 closing/closed；受控测试必须在 channel open 后立即发布。

实际发布命令：

```bash
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 61 --left-current-pose 0.3521,0.0019,0.3362,0.0001,-0.0025,0.0025,1.0000 --right-current-pose 0.3497,-0.0017,0.3255,-0.0006,0.0098,-0.0025,0.9999 --mock-step-m 0.00005 --assume-servo-start-current --publish --allow-robot-motion
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 62 --remote-control off --publish --allow-robot-motion
```

结果：sequence 61 的 sender 日志确认 `[Send] ... total_sent=1 ... "sequence":61`，左右臂进入 `SERVO_CONTROL raw=3 active=rtm_switch_servo_left/right`，arm/eef controller 为 `CSP`，motor error 全 0。但 TCP 并未执行期望的 `0.05mm` 小步，而是从重启后读数移动到约 left `[0.3492,0,0.3302]`、right `[0.3491,0,0.3302]`，姿态接近单位四元数。该帧默认夹爪为 `1.0`，对应模型夹爪 100 最大张开；这符合用户确认的“100 开、0 闭”，但不是本轮运动语义问题的根因。

sequence 62 `remote_control off` 也被 sender 确认送达：`[Send] ... total_sent=1 ... "command":"remote_control","enable":false ... "sequence":62`。后续 `fsm_monitor` 仍显示左右臂为 `SERVO_CONTROL`，pose 约 `[0.3492,0,0.3302]`，motor error 全 0；因此 `remote_control off` 在当前 setup 中不能当作退出 SERVO/回 IDLE 命令。

收尾检查：本机 `pgrep -af 'airbot-rtm-sender|airrtm_servo_dryrun'` 无输出，`ss -lntp` 无 `6000/50071/50051/50052` 监听。

结论：AIRRTM 传输链路已真实打通到 X5 FSM，但当前 `servo_pose`/servo-start 语义仍未对齐，且 `remote_control off` 不能恢复 IDLE。禁止继续发送 policy chunk 或连续 servo 命令；下一步只允许只读分析 X5 receiver 语义、确认官方 stop/IDLE 流程，或由用户/官方 UI 恢复 IDLE 后再做单帧小步验证。

## 11. 飞书记录状态

已定位飞书 VIO 文件夹：`https://w79rvfxw83.feishu.cn/drive/folder/IGY1fkfZ3ltQMIdWHZvcZcPznne`。

2026-06-30 17:12 CST 首次尝试创建飞书记录时被审批策略拦截；随后用户明确回复“允许写入飞书 VIO 文件夹”。
在该授权后，已创建飞书文档：https://w79rvfxw83.feishu.cn/docx/Uc7GdKUSmoYYHOxZPCPcHADRnMI（document_id `Uc7GdKUSmoYYHOxZPCPcHADRnMI`）。


2026-07-02 13:29 CST 补充：已同步飞书 VIO 文档 P0 checkbox 到 revision 150，记录 sender 连接预演成功、实际发布命令被审批拒绝、sender total_sent=0、未发送控制帧。

2026-07-02 15:46 CST 补充：已同步飞书 VIO 文档到 revision 159，覆盖当前现场核对、AIRRTM 表格当前状态/下一步、模型推理与机械臂通信环境边界、控制下发表格、P0/P1 checkbox 和证据来源；记录 sequence 55 本地 ZMQ 已发布但 AIRRTC sender send failed，未确认 X5 收到，后续 fsm_monitor 为 UNKNOWN_ERROR，当前禁止继续发运动命令。

2026-07-02 16:41 CST 补充：已同步飞书 VIO 文档到 revision 167，覆盖当前现场核对、AIRRTM 表格当前状态/下一步、控制下发表格、P0/P1 checkbox 和证据来源；记录代理环境导致 sender join fail、清空代理后 sequence=61 送达并触发 SERVO_CONTROL、pose 落到 neutral、sequence=62 remote_control off 已送达但未退出 SERVO，当前禁止 policy chunk。
