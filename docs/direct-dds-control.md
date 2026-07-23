# 直连 DDS 控制 X5/P7 双臂（不经 CAN / 不经 AIRRTM 的底层路线）

> 维护约定见 [../AGENTS.md](../AGENTS.md) §0。最近核对：2026-06-30。
> 适用场景：**我们要让模型/程序直接发指令**（不是人扳示教臂遥操作）。
> 2026-06-30 20:27 CST 更新：当前主线已改为 **Arm-P7 SDK gRPC**，见 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)。本文件只保留直连 DDS / 裸 FSM topic 的历史调研和底层备选资料，不作为当前执行方案。
>
> 历史结论：直连 DDS 本身不需要 CAN；当前 X5 曾确认有裸 DDS/FSM topic 订阅者。但按用户最新要求，不继续推进 DDS Route 或裸 DDS publisher。

---

## 0. 为什么不需要 CAN（先澄清概念）

飞书遥操作链路里 CAN 只干一件事：**读 E2 示教臂（主臂）的关节位姿**（`airbot-arm -i can0`）。
即 **CAN = 动作的来源（人扳主臂）**，不是“传输到 X5 的通道”。

我们的动作来源是**模型输出**，没有物理主臂要读 → **CAN 完全不需要**。

后续有三条执行通道：

1. **DDS Route RPC**：飞书 wiki《二代臂 DDS Route 开发指南》给出的推荐 facade，带 `acquire_control/renew_control/release_control` lease 流程和 `get_cartesian_pose` / `call_servo_pose_command` 接口；但当前 X5 版本未部署。
2. **裸 DDS/FSM topic**：工作站直接往 X5 的命令 topic 发 DDS 消息；本文件原本描述这条底层路线。
3. **AIRRTM `arm_servo_json`**：复用已经装好的 `airbot-driver`/`airbot-rtm-sender` 消息通道，把模型动作转换成 `servo_pose` payload；这条路线见 [airrtm-conversion-layer.md](airrtm-conversion-layer.md)。

因此，`airbot-driver`、`airbot-rtm-sender`、AIRRTM 对直连 DDS 不是必需项，但不能再把它们排除为“不可用路径”。当前主线不再推进 DDS Route 或裸 `FsmServoPoseCommand` 发布；如未来用户明确切回 DDS，再按本文档重新评估。

## 0.1 DDS Route 文档与当前 X5 的差异（2026-06-30 17:54 CST）

用户提供的飞书 wiki：《二代臂 DDS Route 开发指南》（document_id `TqNMdmC1nosChixvzvWcFtaenKg`，revision `128`）定义了更高层接口：

- 服务前缀：`rt/arm/dds_route/`、`rt/arm/left/dds_route/`、`rt/arm/right/dds_route/`。
- 权威 IDL：`cora/dds/msg/arm_msgs/msg/FsmDdsRoute.idl`。
- 控制权：`acquire_control -> renew_control -> 控制命令携带 client_id/lease_id -> release_control`。
- 当前模型最需要：`get_cartesian_pose` 返回 `[x,y,z,qx,qy,qz,qw]`；`call_servo_pose_command` 发送 `[x,y,z,qx,qy,qz,qw]`；`call_end_effector_position_control` 发送夹爪位置数组。

但当前 X5 现场只读检查结果：

```text
/opt/robot_app/include/version.hpp:
#define AIRBOT_MOTION_VERSION "0.1.1.dev90+g24fec8a"

ros2 topic list | grep dds_route       # 无输出
find /opt -name "FsmDdsRoute*.idl"     # 无输出
ps -ef | grep -E 'dds_route|control_authority|arm-dds-route'  # 无输出
```

而 wiki 明确注明 DDS Route 需要 `robot_app 0.3.3+` 和 `arm_p7_sdk 1.1.0.dev50+`。所以当前 X5 不能按 DDS Route 文档直接调用。该文档现在仅作为**历史接口资料和反证**；当前目标接口契约见 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)。

## 1. 为什么直连可行（已实测）

| 事实 | 证据 |
|---|---|
| 命令 topic 有 robot_app 在订阅 | `ros2 topic info -v /arm/left/control/control_command` → `Subscription count: 1`，节点 `_CREATED_BY_BARE_DDS_APP_`（robot_app 用裸 DDS 收发） |
| 同子网可达 | 历史曾在工作站 `enp108s0 192.168.25.132/24` ↔ X5 `eth0 192.168.25.1/24` 下 ping 通；**2026-06-30 17:54 CST 当前现场 `enp108s0 DOWN`，`ping 192.168.25.1` 不通**（见 [robot-connection.md](robot-connection.md)） |
| 中间件同源可互通 | X5 cora 框架用 **FastDDS 2.6.10**（`libfastrtps.so.2.6.10`），**domain_id=0**（`/opt/robot_app/configs/remote/framework_config.json`）。ROS2 Humble 默认 `rmw_fastrtps_cpp` 同源，跨机发现/通信可行 |

> ⚠️ 但“可行”有前提（§5）：robot_app 是**裸 DDS app**（不是标准 ROS2 节点），消息是 cora 自带的 `arm_msgs` IDL，
> **不在 `/opt/ros`、`ros2 interface list` 里查不到**。工作站要发，必须用**与 X5 完全一致的 IDL 生成的类型**，且 topic 名/QoS 对齐。


### 1.1 机械臂回传与控制入口实测（2026-06-30）

检查人：agent。所有命令均为**只读订阅/查询**，没有发布任何控制命令。

**机械臂有高频回传数据：**

| topic | 类型 | 实测结果 | 用途 |
|---|---|---|---|
| `/arm/{left,right}/control/joint_states` | `sensor_msgs/JointState` | 左臂约 **245Hz**；`name=[joint1..joint7,G2P]`；含 `position/velocity/effort` | 推荐作为当前关节状态；标准 ROS 可直接订阅 |
| `/arm/{left,right}/fsm/joint_state` | `sensor_msgs/JointState` | 左臂约 **123Hz**；同样 `joint1..joint7,G2P` | FSM 层关节反馈；标准 ROS 可直接订阅 |
| `/arm/{left,right}/control/imu`、`/fsm/imu` | `sensor_msgs/Imu` | topic 存在；本轮 4s 内未收到帧，配置里 `imu_hz=0` | 默认不可依赖 |
| `/arm/{left,right}/fsm/state` | `arm_msgs/FsmState` | pub=1，但当前 `/opt/ros/humble` 无 `arm_msgs`，`ros2 topic echo` 失败 | 需生成 `arm_msgs` 后用于状态/错误监控 |
| `/arm/{left,right}/fsm/cartesian_state` | `arm_msgs/CartesianState` | pub=1，但同样需 `arm_msgs` 类型 | FK 末端位姿反馈 |

实测关节样例（左臂 `/control/joint_states`）：`position` 前 7 位是 7 关节 rad，第 8 位 `G2P=0.0`；`effort` 末位约 `-8.448`，对应夹爪力。

**控制入口都有 robot_app 订阅者，QoS 为 RELIABLE + VOLATILE：**

| 控制入口 | 类型 | 订阅者 | 说明 |
|---|---|---|---|
| `/arm/<side>/fsm/switch_control_state_command` | `arm_msgs/FsmSwitchControlStateCommand` | 1 | 切到 `FSM_SERVO_CONTROL=3` 的必要入口 |
| `/arm/<side>/fsm/servo_pose_command` | `arm_msgs/FsmServoPoseCommand` | 1 | 发送末端目标位姿；X5 内部做 servo/IK，**本地不必自己解 IK** |
| `/arm/<side>/fsm/servo_joint_command` | `arm_msgs/FsmServoJointCommand` | 1 | 发送 7 关节目标；需要已有 joint target 或先调 IK |
| `/arm/<side>/fsm/end_effector_position_control_command` | `arm_msgs/FsmEndEffectorPosControlCommand` | 1 | 发送 G2P 夹爪位置，行程 0.0–0.096m |
| `/arm/<side>/control/control_command` | `arm_msgs/ControlCommand` | 1 | 更底层 joint command；不建议作为第一条控制路径 |

**类型文件位置：**

```bash
/opt/cora/include/cora/dds/idl/arm_msgs/msg/{ArmControl,Servo,FiniteStateMachine}.idl
/opt/cora/include/cora/dds/idl/kdl_msgs/msg/kdl_msgs.idl
/opt/cora/include/cora/dds/idl/rpc_msgs/msg/rpc_msgs.idl
```

`ros2 interface list | grep arm_msgs` 为空，所以工作站/ROS2 CLI 不能直接发布这些控制消息；必须先用 IDL 生成 ROS2/FastDDS 类型，或直接使用 Cora/FastDDS SDK。

**机械臂模型与节拍：**

- 本体：P7C，7 轴 `joint1..joint7`。
- 夹爪：`G2P`，行程 `0.0–0.096m`。
- `servo_engine_update_period_us=4000`，即 250Hz 内部 tick。
- `servo_engine_incoming_command_timeout_ms=1000`，命令断流超过约 1s 会超时。
- `fsm_state_publish_period_ms=8`，FSM 层状态/控制拉取约 125Hz。

复现命令：

```bash
source /opt/ros/humble/setup.bash
ros2 topic echo --once /arm/left/control/joint_states
ros2 topic hz /arm/left/control/joint_states
ros2 topic hz /arm/left/fsm/joint_state
ros2 topic info -v /arm/left/fsm/servo_pose_command
ros2 topic info -v /arm/left/fsm/switch_control_state_command
ros2 interface list | grep arm_msgs || true
```

## 2. 控制时序（FSM 状态机，必须按顺序）

X5 双臂由 FSM 管控。命令分状态，**发 servo 命令前必须先把 FSM 切到 `SERVO_CONTROL`**，否则命令被拒。
权威定义来自 X5 的 `arm_msgs/msg/FiniteStateMachine.idl`（`SwitchableFsmState`）：

```
0 FSM_IDLE
1 FSM_PLANNING_CONTROL
2 FSM_GRAVITY_COMPENSATION
3 FSM_SERVO_CONTROL        ← 流式伺服控制，我们要的状态
4 FSM_POSITION_CONTROL
5 FSM_FORCE_CONTROL
```

**标准上电→受控流程：**

```
1. 订阅 /arm/<l|r>/fsm/state (FsmState)            # 读当前状态，监控 + 错误检测
2. 发 /arm/<l|r>/fsm/switch_control_state_command  # FsmSwitchControlStateCommand, target=3 (SERVO_CONTROL)
     - mode = 1 (CARTESIAN_POSE)  ← relpose 模型走这条；或 mode=0 (JOINT) 走关节流
     - auto_run = true
     - has_initial_joint = true, initial_joint[7] = 当前关节（从 joint_state 读）
     - blocking = true, blocking_timeout_ms = 2000
3. 等 /arm/<l|r>/fsm/ack (FsmAck)                  # accepted=true 且 state 到 3 才算切成功
4. 按伺服节拍流式发命令：
     - mode=1: /arm/<l|r>/fsm/servo_pose_command   (FsmServoPoseCommand)
     - mode=0: /arm/<l|r>/fsm/servo_joint_command  (FsmServoJointCommand)
5. 夹爪: /arm/<l|r>/fsm/end_effector_position_control_command (FsmEndEffectorPosControlCommand)
6. 收尾: 理论上应发 `/arm/<l|r>/fsm/stop_command`（`FsmStopCommand`）或切回 IDLE；但 2026-07-02 12:53 CST 现场确认当前 shell 缺 `arm_msgs` package，不能直接用 `ros2 topic pub` 构造 stop/switch 消息。
```

**急停/异常**：`/arm/<l|r>/fsm/emergency_stop_command`（`FsmEmergencyStopCommand`），复位用 `emergency_reset_command`。
`FsmState.state` 出现负值（-1 急停 / -2 碰撞 / -3 未知）要立即停发命令。

2026-07-02 12:53 CST 现场补充：`ros2 topic info -v /arm/left/fsm/stop_command` 能看到类型 `arm_msgs/msg/FsmStopCommand`、订阅方 1、QoS `RELIABLE/VOLATILE`；`switch_control_state_command` 也能看到 endpoint。但 `ros2 interface show arm_msgs/msg/FsmStopCommand` 返回 `Unknown package 'arm_msgs'`，且未发现 `/opt/robot_app/share/arm_msgs`，因此“能发现 DDS endpoint”不等于“当前 ROS2 CLI 能发该命令”。

## 3. 关键消息字段（来自 X5 IDL，权威）

> 来源：`/opt/cora/include/cora/dds/idl/arm_msgs/msg/{ArmControl,Servo,FiniteStateMachine}.idl`。
> **本体是 7-DOF**：几乎所有数组都是 `[7]`。

### 切状态：`FsmSwitchControlStateCommand` → `/arm/<l|r>/fsm/switch_control_state_command`
```
Header header
string  request_id
uint8   target              # 3 = SERVO_CONTROL
boolean blocking
int32   blocking_timeout_ms
# 以下仅 target==SERVO_CONTROL 时有意义：
uint8   mode                # 0 JOINT, 1 CARTESIAN_POSE, 2 CARTESIAN_TWIST
uint8   feedback_mode       # 0 FOLLOW, 1 SIM
boolean has_initial_joint
double  initial_joint[7]
boolean has_scale
double  scale[3]            # linear, rotational, joint
int32   period_ms
int32   timeout_ms
double  epsilon
double  sim_alpha
boolean auto_run
boolean auto_pause_on_exit
```

### 笛卡尔伺服（relpose 模型用）：`FsmServoPoseCommand` → `/arm/<l|r>/fsm/servo_pose_command`
```
Header header
string  request_id
double  translation[3]      # 末端目标位置 xyz (m)
double  orientation[4]      # 末端目标姿态四元数
boolean has_velocity
double  velocity[7]
boolean has_current_threshold
double  current_threshold[7]
int64   timestamp_ns
boolean blocking            # 流式伺服时设 false
int32   blocking_timeout_ms
double  blocking_joint_tolerance_rad
uint32  blocking_settle_cycles
```
> ⚠️ `orientation[4]` 的四元数顺序（wxyz vs xyzw）IDL 未注明，**上真机前必须用一帧已知姿态实测确认**。

### 关节伺服（关节流方案用）：`FsmServoJointCommand` → `/arm/<l|r>/fsm/servo_joint_command`
```
Header header
string  request_id
double  pos[7]              # 7 关节目标位置 (rad)
double  vel[7]
double  acc[7]
boolean has_current_threshold
double  current_threshold[7]
int64   timestamp_ns
...（blocking 同上）
```

### 夹爪：`FsmEndEffectorPosControlCommand` → `/arm/<l|r>/fsm/end_effector_position_control_command`
```
Header header
string  request_id
sequence<double> position   # G2P 行程 0.0~0.096 m（见 teleop-and-data-collection.md §3）
sequence<double> velocity
sequence<double> current_threshold
...（blocking 同上）
```

### 状态反馈（订阅）
- `/arm/<l|r>/fsm/state` → `FsmState { uint8 state; string active_request_id; string last_error; }`
- `/arm/<l|r>/fsm/ack` → `FsmAck { string request_id; string command_name; boolean accepted; uint8 state; string message; }`
- `/arm/<l|r>/fsm/cartesian_state` → `CartesianState { double translation[3]; double orientation[4]; }`（FK 末端位姿）
- `/arm/<l|r>/control/joint_states` → `sensor_msgs/JointState`（`[joint1..joint7, G2P]`，读当前关节，切状态时填 `initial_joint`）

## 4. QoS（必须与 X5 对齐才能匹配）

实测 X5 命令 topic 的 endpoint QoS（`ros2 topic info -v`）：

```
Reliability: RELIABLE
Durability:  VOLATILE
History:     KEEP_LAST（depth 未知，按默认）
Liveliness:  AUTOMATIC
```

工作站发布端必须用 **RELIABLE + VOLATILE**，否则 DDS 匹配失败、消息发不进去。

## 5. 落地前必须解决的前提（按优先级）

1. **P0 — arm_msgs 类型可用性**：robot_app 是裸 DDS，消息是 cora 的 `arm_msgs` IDL（`/opt/cora/include/cora/dds/idl/arm_msgs/`，依赖 `std_msgs`、`rpc_msgs`、`Planning.idl`）。2026-07-02 12:53 CST 现场确认 X5 的 ROS2 CLI 不能 `interface show arm_msgs/msg/FsmStopCommand`，所以 stop/switch/servo DDS 直发仍必须先解决类型包/IDL 生成问题。
   工作站要发，二选一：
   - (a) 把这些 IDL 拷到工作站，用 `rosidl`/`fastddsgen` 生成类型，建一个 ROS2/FastDDS 包；
   - (b) 直接用 cora SDK（若有 python binding）在工作站侧发布。
   **没有正确的类型定义，直连无从谈起。**
2. **P0 — 动作语义对齐**：现有 checkpoint 输出 **relpose action**（见 [vio-relpose-deployment.md](vio-relpose-deployment.md)）。当前 policy 推理不消费真实 state，但输出仍要转换成机械臂命令：默认 TCP→TCP 路线需要当前 TCP pose，直接积分成“末端目标位姿”后填 `FsmServoPoseCommand.translation/orientation`。固定 **手眼外参 `T_eef_cam`** 只在使用相机 frame 参考/控制转换时需要。
3. **P1 — FSM 切换实测**：在 X5 上确认切到 `SERVO_CONTROL` 的完整参数组合（mode/auto_run/scale）与 ack 行为；先用**单臂、低速、SIM feedback_mode** 验证不动真电机。
4. **P1 — 四元数顺序 / 单位**：`orientation[4]` 顺序、`current_threshold` 默认值、夹爪 position 方向，逐一实测。
5. **P2 — 伺服节拍**：servo engine `period_us=4000`（250Hz）、`incoming_command_timeout_ms=1000`。命令流要稳定（断流超 1s 会触发超时），但不必硬怼 250Hz；relpose 模型按 30Hz 节拍消费 chunk（见 vio-relpose-deployment.md §7）。

## 6. 三种执行/采集路径对比

| | 直连 DDS（本文档） | AIRRTM `arm_servo_json`（airrtm-conversion-layer.md） | E2 遥操作采集（teleop-and-data-collection.md） |
|---|---|---|---|
| 动作来源 | 模型/程序 | 模型/程序转换成 `servo_pose` payload | E2 示教臂（人扳，需 CAN） |
| 传输 | 工作站→X5 直发 DDS（同有线网） | ZMQ→`airbot-rtm-sender`→X5 `arm_servo` | ZMQ→sender→AIRRTM→X5 |
| 需要 CAN | 否 | 否 | 是（读主臂） |
| 需要 sender/driver | 否 | 是，复用其消息通道 | 是 |
| 主要前提 | `arm_msgs` 类型 + ROS2/DDS 环境 + FSM/servo 语义 | 当前 TCP pose、夹爪量纲、`remote_control`/安全流程确认 | CAN 硬件 + 主臂 + config |
| 适合 | 更底层、低延迟、长期控制链路 | 最快打通第一版模型闭环 | 人工遥操作和关节空间数采 |

→ 当前结论：**当前主线不是 DDS**。CAN 不在 Arm-P7 SDK gRPC 路线里；若目标是最快让模型动作跑到机械臂，先推进 `arm_p7_sdk` 安装、`50071` gRPC 服务连通和 SDK control adapter。

## 7. 复现命令

```bash
# 在 X5 (192.168.25.1) 上抓 IDL（直连方案的核心契约）
ls  /opt/cora/include/cora/dds/idl/arm_msgs/msg/
cat /opt/cora/include/cora/dds/idl/arm_msgs/msg/FiniteStateMachine.idl   # FSM/servo 命令
cat /opt/cora/include/cora/dds/idl/arm_msgs/msg/Servo.idl                # ServoCommand
cat /opt/cora/include/cora/dds/idl/arm_msgs/msg/ArmControl.idl           # JointCommand/ControlCommand

# 确认订阅方 + QoS
source /opt/ros/humble/setup.bash
ros2 topic info -v /arm/left/fsm/servo_pose_command
ros2 topic info -v /arm/left/fsm/switch_control_state_command

# 确认 DDS 实现与 domain
ls /opt/robot_app/lib | grep -i fastrtps                                 # FastDDS 2.6.10
grep domain_id /opt/robot_app/configs/remote/framework_config.json       # 0
```

## 8. 下一步建议

1. 从 X5 拷出 `arm_msgs` + 依赖 IDL（`std_msgs`/`rpc_msgs`/`Planning.idl`），在工作站建类型包（P0-1）。
2. 工作站装 ROS2 Humble + FastDDS，`ROS_DOMAIN_ID=0`、`RMW_IMPLEMENTATION=rmw_fastrtps_cpp`，走 25 网段验证能 `ros2 topic echo` 到 X5 的 `fsm/state`。
3. 写一个最小测试节点：切 SERVO_CONTROL（SIM feedback、单臂）→ 收 ack → 发一条 `FsmServoPoseCommand`（小幅、当前位姿附近）→ 看 `cartesian_state` 是否响应。**全程低速、随时急停。**
4. 确认当前 TCP pose 来源和 `servo_pose_command` 的 base/world frame，把 relpose 输出接到 `servo_pose_command`（P0-2）；只有改走相机 pose 路线时才标定/录入手眼外参 `T_eef_cam`。
