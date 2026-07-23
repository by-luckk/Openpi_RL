# 小推车遥操作 + 数采接口（飞书文档落地）

> 维护约定见 [../AGENTS.md](../AGENTS.md) §0。最近核对：2026-06-30。
> 来源飞书文档：《小推车遥操作使用文档》v0.1.1（doc id `SeXHd79NvoX2Ysxow2DczjmCnde`）。
> 这份文档讲的是 **E2 示教臂 → PC → X5 接收端 → P7 双臂** 的遥操作链路，以及在 X5 侧
> **采集训练数据**要订阅哪些 topic。它和 [inference-architecture.md](inference-architecture.md)
> 的“推理”是两条独立链路。⚠️ 注意：这里的数采接口是**关节空间**（`joint_states`/`control_command`），
> 与当前 checkpoint 的 relpose action 语义不同；当前 PI05 policy 推理不消费真实 state 数值，
> 但执行 relpose action 时仍可能用关节/FK/外参取得参考 pose。直接对接关系见 §3 和
> [vio-relpose-deployment.md](vio-relpose-deployment.md)。

---

## 1. 系统拓扑（遥操作）

```
E2 示教臂 ×2 (主臂)              PC 发送端 (笔记本)                  X5 接收端 = 192.168.25.1
┌──────────────┐  CAN can0/can1  ┌────────────────────────┐  AIRRTM   ┌────────────────────────┐
│ 人手操作主臂  │ ──────────────> │ airbot-arm (50051/50052)│ ───DC──> │ robot_app (remote)      │
│              │                 │ airbot-driver (按键 O/P)│  图传RTC  │ robot_app (left/right)  │
│              │                 │ airbot-rtm-sender       │ <──────  │ P7 双臂 + 自研相机 ×6   │
└──────────────┘                 └────────────────────────┘          └────────────────────────┘
```

- **PC 发送端**：把 E2 主臂的位姿经 AIRRTM DataChannel 发给 X5。需要 `airbot-arm`（机械臂控制服务）+ `arm-sdk`（Python 二次开发）+ `airbot-driver`（遥操作驱动/按键）+ `airbot-rtm-sender`（RTM 发送）。
- **X5 接收端 = `192.168.25.1`**：跑 3 个 `robot_app`（`remote` 图传+遥操接收、`left_arm`、`right_arm`），驱动 P7 双臂并发布相机/关节 topic。**这正是我们 §robot-connection 里探到的那台机器。**
- 按键（在启动 driver 的终端）：`O` 开启遥操 / `P` 暂停 / `Z` 从臂回零 / `M` 主从臂回零 / `L` 主臂移到安全退出位姿（停止前务必先按 L，否则回零可能碰撞）。
- 网络现状：x5 与 PC **必须有线**；无线 RTM 抖动（峰值 150ms）、RTC 图传 200–300ms，均未达标（目标 <130ms）。

## 2. 数采接口：最小 topic 集合（关节空间数采用）

> 文档里 topic 带 `rt/` 前缀（DDS 原生名）；在 X5 上用 `ros2 topic list` 看到的是去掉 `rt/` 的 `/...`，二者是同一 topic（已实测对应）。
> ⚠️ 这套是**关节空间**接口，用于采关节数据集 / 作底层动作通道；不能直接当作当前 relpose checkpoint 的 action/state 表示（见 §3）。

| 类别 | 对象 | topic（DDS `rt/` 名） | ROS2 名 | 类型 |
|---|---|---|---|---|
| action | 左臂 arm+夹爪 | `rt/arm/left/control/control_command` | `/arm/left/control/control_command` | `arm_msgs/ControlCommand` |
| action | 右臂 arm+夹爪 | `rt/arm/right/control/control_command` | `/arm/right/control/control_command` | `arm_msgs/ControlCommand` |
| state | 左臂 arm+夹爪 | `rt/arm/left/control/joint_states` | `/arm/left/control/joint_states` | `sensor_msgs/JointState` |
| state | 右臂 arm+夹爪 | `rt/arm/right/control/joint_states` | `/arm/right/control/joint_states` | `sensor_msgs/JointState` |
| image | 6 路相机 | `rt/camera/<cam>/image_rect/video_encoded` | `/camera/<cam>/image_rect/video_encoded` | `foxglove_msgs/CompressedVideo`（**H264**） |

6 路相机：`head_left/head_right`、`left_arm_left/left_arm_right`、`right_arm_left/right_arm_right`。我们推理取**三路左目** `head_left`/`left_arm_left`/`right_arm_left`。

> ⚠️ 数采文档推荐用 **`/control/...`**（`arm_control` 底层）做 action/state 对齐源，而我们 §robot-connection 之前记的是 `/fsm/joint_state`（FSM 高层）。采**关节空间数据集**时**以 `/control/joint_states` 为准`（文档明示这是“实际进入 arm_control 的主控制命令/硬件反馈”）。（注意：当前 checkpoint 的 policy 请求不把关节 topic 当 state；但执行 relpose action 时可用关节/FK/夹爪反馈，见 §3。）

## 3. ★关节维度：文档一锤定音（机器人侧 = 关节空间）

机器人（X5/P7）侧 `joint_states` / `control_command` 是**关节空间**，文档明确：

- **arm 本体是 7 轴**：`joint1..joint7`，单位 rad。
- **夹爪 G2P 是第 8 个关节**：单位 **m**，行程 `0.0 ~ 0.096`（来自 `arm_models.json`）。
- `joint_states` 顺序固定：`[joint1..joint7, G2P]`（识别到夹爪时在 7 个 arm 关节后追加 G2P）。
- action（`control_command`）：arm 命令 `joint_names` 含 7 个，夹爪命令单独一条只含 `G2P`（复用同一 topic，按 `joint_names` 区分）。

**因此机器人关节空间每臂 = 7 关节 + 1 夹爪 = 8，双臂 = 16。**

### ⚠️ 重要：这套关节 topic ≠ 当前 checkpoint 的 I/O（不要直接对接）

之前一版本文件曾把“14 维模型 vs 16 维机器人”写成“本体自由度 P0 硬冲突”，**那是误判，已纠正**。真相见权威文档 [vio-relpose-deployment.md](vio-relpose-deployment.md)（对照真实训练转换器 `docs/VIO_Test/.../vio_preview_converter.py` 核对）：

- 当前 checkpoint `pi05_vio_plant_collection` **不是关节空间模型，而是 relpose action 模型**：
  - 训练数据 **state 16 维** = 每臂相机 VIO 位姿 `[pos(3) + quat(4)]` + 左右夹爪各 1 = 7+7+2。**不是关节角**。但当前 PI05 配置 `discrete_state_input=False`，policy 推理不消费这些 state 数值。
  - **action 14 维** = 每臂 `[Δpos(3) + Δrotvec(3) + 夹爪(1)]`。那个“6”是 **6-DOF 位姿增量**，不是 6 个关节。
- 所以“6 vs 7”是**位姿表示 vs 关节计数**的差异，根本不是自由度对不上。本体维度**不构成** P0 阻塞。

**两条数据表示是不同 pipeline：**

| | 当前 checkpoint（relpose） | 本飞书文档数采接口（关节空间） |
|---|---|---|
| state | 训练数据 state 是 pose 字段；当前按 TCP pose 语义处理，policy 可用 dummy state | 关节角 `joint_states`（`/arm/*/control/joint_states`） |
| action | 当前按 TCP 局部系 `Δpos+Δrotvec`+夹爪处理 | 关节 `control_command`（position rad / G2P m） |
| 用途 | 训练标签语义 / relpose 动作重构参考；当前 policy 推理可用 dummy state | 采**关节空间训练数据** / 或驱动臂的底层接口 |

> 含义：本飞书文档的 `joint_states`/`control_command` 适合**采关节空间数据集**或作为**历史底层通道资料**，但**不能直接当作现有 relpose checkpoint 的 action**。当前 policy 推理请求是三路图像 + prompt + dummy state；真正的 P0 在执行侧已改为 Arm-P7 SDK gRPC：安装/确认 `arm_p7_sdk`、连通 50071 服务、用 `get_end_pose()` 取当前 TCP pose、用 `move_end_pose()` / `move_eef()` 下发目标。手眼外参只在相机 pose 备选路线需要。

## 4. 消息格式速查（来自文档 IDL/示例）

**`arm_msgs/ControlCommand`**（action）：`header` + `joint_names: string[]` + `commands: JointCommand[]`（下标一一对应）。
`JointCommand` 字段：`position`(arm rad / G2P m)、`velocity`、`kp`、`kd`、`torque_ff`、`max_torque`(Nm)。

**`sensor_msgs/JointState`**（state）：`header` + `name[]` + `position[]` + `velocity[]` + `effort[]`，四数组按下标对应。G2P 的 effort 是夹持力（我们之前实测恒 -8.45 即此）。

**FSM 模式** `rt/arm/<l|r>/fsm/state`（`arm_msgs/FsmState`）：`state` uint8 → `0 IDLE / 1 PLANNING / 2 GRAVITY_COMP / 3 SERVO_CONTROL / 4 POSITION_CONTROL / 5 FORCE_CONTROL`，负值为错误（-1 急停 / -2 碰撞 / -3 未知）。底层控制器模式看 `rt/arm/<l|r>/control/controller_state`（`csp`/`mit`/`trajectory`）。

## 5. H264 图像

X5 的 `remote/framework_config.json` 起了 6 个 camera 实例 + 1 个 codec 节点；每路相机启用 VPU H264 encode，codec 节点发布 `foxglove_msgs/CompressedVideo`，`format=h264`。
→ 桥接取图有两条路：① 订阅 `/camera/<cam>/image_rect`（原始 **nv12** 640×352，带宽大）；② 订阅 `.../video_encoded`（H264，省带宽，需解码）。数采文档推荐 H264 链路。

## 6. 软件安装清单与现状（2026-06-30 实测 → 已补装）

飞书文档要求 **PC 发送端**装 4 类包。**2026-06-30 已全部补齐**（介质来自 `~/Downloads`）。

| 组件 | 文档要求 | 工作站现状 |
|---|---|---|
| `airbot-arm` 主程序 deb | 必装（机械臂控制服务，5.2.3） | ✅ 已装 `5.2.3`（`/usr/bin/airbot-arm`） |
| `airbot-rtm-sender` deb | 必装（RTM 发送） | ✅ 已装 `0.1.0`（`/usr/bin/airbot-rtm-sender`） |
| `arm-sdk` Python whl | 必装（Python 二次开发 + `arm-sdk` CLI） | ✅ **已装** `5.2.3` 到独立 venv（见下） |
| `airbot_driver` whl | 必装（遥操作驱动 + 按键 O/P/Z/M/L） | ✅ **已装** `0.1.0` 到同一 venv，`airbot-driver --check-config` / `--dry-run` 通过 |
| `config.zip`（sender/driver/receiver 配置） | 必需（启动要 `CONFIG_ROOT`） | ✅ **已解压**到 `~/airbot_teleop/config/` |

**安装位置（重要）**：为不污染推理用的 `.venv`（jax/openpi），遥操作软件装在**独立 venv**：

```
~/airbot_teleop/
  venv/                     # uv venv, python 3.12；arm-sdk 5.2.3 + airbot-driver 0.1.0
  config/                   # 解压自 config.zip
    driver/airbot_e2_pose.yaml
    sender/airrtc_e2.yaml  (+ input/airrtc_e2.yaml)
    receivers/airrtc.yaml  (在 X5 端用)
```

- `airbot-driver` 依赖 **`arm-sdk>=5.2.3`**（不是 `arm-p7-sdk`），故发送端只装 `arm_sdk-5.2.3`，**未装** `arm_p7_sdk`（那是另一条 P7 gRPC SDK，driver 不引用）。
- 用 `uv venv --python 3.12` + `uv pip install <两个 whl>`，依赖（grpcio/protobuf/pynput/pyzmq/loguru/typer 等共 19 包）一并装好。
- CLI 路径：`~/airbot_teleop/venv/bin/{arm-sdk,airbot-driver}`。

**仍需注意的硬件/环境前提（软件已就绪，但这些不归安装解决）：**
- **无 CAN 接口**：本机 `ip link` 无 `can0/can1`。E2 主臂走 CAN，**没有 CAN 卡就接不了 E2 示教臂**，`airbot-arm -i can0/can1` 起不来。`can-utils` 已装（`candump`/`cansend`）。→ **这是把本机当发送端的当前唯一硬阻塞。**
- 网络：发送端 sender 配置连 AIRRTC 信令 `https://8.138.229.216:7210`；**sender room 必须和 X5 接收端一致**。2026-07-07 17:52 CST 实测 X5 remote 是 `rtm_sender_room_1`，而本机原始 `airrtc_e2.yaml` 仍是 `rtm_sender_room`，原始配置会 P2P timeout；启动 sender 前要用匹配 room 的临时配置或同步修改 sender 配置。

### 结论（这台工作站当前能做什么）
- 作为**推理 GPU 服务端**：就绪（见 inference-architecture.md，serve 已验证）。
- 作为**遥操作 PC 发送端**：**软件已就绪**（arm-sdk + airbot-driver + sender 全装、config 已解压、driver 配置校验通过）。**唯一缺口 = CAN 硬件**：接上 E2 主臂用的 CAN 卡后即可起完整链路（见 §8）。
- 作为**数采/推理的数据读取端**：网络可达 X5（同子网，见 robot-connection.md），但缺 ROS2/DDS 订阅环境与 H264 解码；topic 契约已由本文件 §2~§5 明确。

## 7. 待办 / 下一步（按优先级）

1. **模型伪主臂 publisher**：用户已打通真实摇操控制链路。2026-07-02 已新增 dry-run-first publisher（`src/openpi/shared/airbot_airrtm_servo.py`、`examples/airbot/airrtm_servo_dryrun.py`）。闭环时不需要 CAN；停止 `airbot-driver`，只保留 `airbot-rtm-sender`，由 OpenPI publisher 绑定 `tcp://0.0.0.0:6000`、topic=`servo`，发布同样的 `arm_servo_json` / `servo_pose` 消息。
2. **P0 执行侧对齐（当前 checkpoint relpose action）**：按 [airrtm-conversion-layer.md](airrtm-conversion-layer.md) §5 把 `actions[i, :14]` 通过当前 TCP pose 积分成从臂绝对 `servo_pose`，并确认 base/world frame、夹爪 0-1 打包、`remote_control` 门禁和单步 safety guard；`T_eef_cam` 只在相机 pose 路线需要。
3. **真实 E2 遥操作发送端**：如果还要继续用物理主臂示教，才需要 CAN 硬件；软件已装好，接上 CAN 卡后可按 §8 启动。
4. 若只做数据读取/推理桥接：在读取端装 ROS2+rclpy（或在 X5 上发布器推流）、补 H264 解码（ffmpeg / pyav），按 §2 topic 订阅。

## 8. 遥操作发送端启动序列（软件已装，待 CAN 硬件到位后执行）

```bash
# 变量
TELE=~/airbot_teleop
VENV=$TELE/venv
CONFIG_ROOT=$TELE/config

# 终端1：左臂服务（接上 CAN 后；can 速率配置见飞书文档 X5 节）
sudo airbot-arm -i can0 -t airbot_play_e2 --address 0.0.0.0:50051
# 终端2：右臂服务
sudo airbot-arm -i can1 -t airbot_play_e2 --address 0.0.0.0:50052

# 终端3：Sender（ZMQ 6000 → AIRRTC 信令 → X5）
airbot-rtm-sender "$CONFIG_ROOT/sender/airrtc_e2.yaml"

# 终端4：Driver（读 E2 主臂位姿 → ZMQ pub 6000；按键在此终端）
$VENV/bin/airbot-driver --config "$CONFIG_ROOT/driver/airbot_e2_pose.yaml"
```

数据流：`airbot-driver`（读主臂，发 ZMQ `tcp://*:6000` topic=`servo`）→ `airbot-rtm-sender`（SUB 6000）→ AIRRTC room `rtm_sender_room` → X5 接收端 `robot_app`。
按键（在 driver 终端）：`O` 开 / `P` 停 / `Z` 从臂回零 / `M` 主从回零 / `L` 主臂到安全退出位姿（停前先按 L）。

> 验证（无硬件也能跑）：`$VENV/bin/airbot-driver --check-config $CONFIG_ROOT/driver/airbot_e2_pose.yaml`（已通过，输出 `config OK`）；`--dry-run` 可打印解析后的完整 app 命令。

## 9. ★模型伪主臂接入：不需要 CAN；复用 AIRRTM sender

容易混淆，这里讲清楚 CAN / AIRRTM / 直连 DDS / Arm-P7 SDK gRPC 在当前飞书链路里各自只管什么。
2026-07-01 用户已确认“机械臂摇操控制机械臂”的链路打通，因此第一版模型闭环可以直接替换
真实主臂发布端：让模型输出生成和 `airbot-driver` 一样的 `arm_servo_json` / `servo_pose`，继续走
`airbot-rtm-sender` → X5 `robot_app`。

- **CAN 只负责“读 E2 主臂”**：`airbot-arm -i can0/can1` 把物理示教臂经 CAN 读进来，人手扳动主臂产生动作。模型作为动作来源时，没有 E2 主臂要读，**不需要 CAN**，也不需要启动 `airbot-arm` 主臂服务。
- **不要让 `airbot-driver` 和模型 publisher 同时跑**：二者都会往 `tcp://*:6000` topic=`servo` 发从臂命令；同时存在会出现命令竞争。模型闭环时应停止真实 `airbot-driver`，只保留 `airbot-rtm-sender`。
- **AIRRTM 是当前最快接入点**：飞书文档里的 X5 `airrtm_config.json` 已有 `data_sources=["arm_servo"]`、`servo_input_mode="cartesian_pose"`、`queue_mode="latest"`、`publish_to_arm=true`。本地 `airbot_driver` 已确认 `servo_pose` payload 是 `left_pose/right_pose=[x,y,z,qx,qy,qz,qw]` 加左右夹爪值，经 ZMQ `tcp://*:6000` topic=`servo` 送给 `airbot-rtm-sender`。
- **Arm-P7 SDK gRPC 仍保留，但不是这条链路的输出端**：SDK adapter 已验证 no-motion smoke，可继续用 `get_end_pose()` 取 current TCP pose、做 dry-run/guard、排查 50071 服务；若改走 SDK 直控，则由 `GuardedP7ArmAdapter` 调 `move_end_pose()`，但这和“替代主臂输出”是两条执行通道。
- **直连 DDS 只保留为历史/底层资料**：工作站与 X5 在同一根有线 /24、X5 跑 FastDDS domain 0 时，直接发 ROS2/DDS topic 在底层条件上可行；但当前不优先推进裸 DDS publisher。

当前选择：**不需要 CAN** 是定论；模型替代主臂的第一版路线是 OpenPI publisher → ZMQ `servo` → `airbot-rtm-sender` → X5 `arm_servo`。详见 [airrtm-conversion-layer.md](airrtm-conversion-layer.md) §5；SDK gRPC 的状态和 safety adapter 见 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)。

### 已验证（2026-06-30，X5 上 `ros2 topic info -v`）
X5 的命令 topic **都有 `robot_app` 在订阅**（`Subscription count: 1`，节点为 `_CREATED_BY_BARE_DDS_APP_`，
即 robot_app 用裸 DDS 收发，不是 rclpy 节点）：

| topic | 类型 | 订阅方 |
|---|---|---|
| `/arm/left/control/control_command` | `arm_msgs/ControlCommand` | robot_app ✅ |
| `/arm/left/servo/command` | `arm_msgs/ServoCommandRequest` | robot_app ✅ |
| `/arm/left/fsm/servo_pose_command` | `arm_msgs/FsmServoPoseCommand` | robot_app ✅ |

→ 历史结论：**从工作站直接发这些 topic，X5 能收**，直连 DDS 在底层条件上成立；但 2026-07-01 当前第一版模型伪主臂路线优先复用已打通的 AIRRTM sender，不按裸 DDS 路线启动真机。

### 但直连有前提（落地前必须解决）
1. **自定义消息定义**：这些是 `arm_msgs/*`（`ControlCommand`/`ServoCommandRequest`/`FsmServoPoseCommand`…），
   **不是 ROS 标准消息**。工作站要发，必须拿到 `arm_msgs` 的 IDL/msg 定义并编译（来源：X5 的
   `framework/dds/msg/arm_msgs`，或 `airbot_arm_release.tar.gz`）。
2. **工作站要有 DDS/ROS2**：本机无系统 ROS。需装 ROS2 Humble + FastDDS（或纯 CycloneDDS/FastDDS +
   编译好的 arm_msgs），设 `ROS_DOMAIN_ID=0`、`RMW_IMPLEMENTATION=rmw_fastrtps_cpp`，走
   `192.168.25.0/24` 网卡做发现（见 [robot-connection.md](robot-connection.md) §2）。
3. **FSM 状态门禁**：发 servo 命令前，X5 侧 FSM 要处于接受该控制的状态（`SERVO_CONTROL` 等，
   见 §4 状态表）。需确认怎么把 FSM 切到 servo，以及命令的关节/位姿语义与单位。
4. **动作表示对齐**：当前 checkpoint 输出 relpose action；policy 推理不需要真实 state，但执行时要用当前 TCP pose 换成末端目标，
   再决定走哪个命令 topic（关节 `control_command` vs 位姿 `servo_pose_command`）。手眼外参只在相机 pose 路线需要；见
   [vio-relpose-deployment.md](vio-relpose-deployment.md)。

> 一句话：**CAN 不需要**；AIRRTM `arm_servo_json` 可作为较快的第一版转换层；直连 DDS 是更底层路线，
> 已证明对面在订阅，但需要“工作站装 DDS + 编 arm_msgs + 对齐 FSM/动作语义”。
