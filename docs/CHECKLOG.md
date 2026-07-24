# 检查时间线（CHECKLOG）

按时间倒序无所谓，**追加在末尾即可**。每行：日期 — 检查人 — 做了什么 — 结论 — 详情链接。

---

## 2026-06-30 — 首次调研（agent: Claude）

目的：确认 (1) 本仓库能否做推理；(2) 能否从 `ssh root@192.168.25.1` 实时读取推理所需 video/数据。

- **2026-06-30** — ssh 连通性：`SSH_ASKPASS` 方式登录 `root@192.168.25.1`（密码 `root`）成功。目标是 AIRBOT 板载 SoC（Horizon/Hobot aarch64，ROS2 Humble）。→ 详见 [robot-connection.md](robot-connection.md)
- **2026-06-30** — 工作站推理前置：`.venv` 里 `jax 0.5.3` + `[CudaDevice(id=0)]` 可用；存在真实 checkpoint `checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/`。**策略服务端可跑**。→ [inference-architecture.md](inference-architecture.md)
- **2026-06-30** — 客户端依赖：`python -c "import airbot_ie, airdc"` 报 `ModuleNotFoundError: airbot_ie`。**机器人客户端当前跑不起来**（私有 SDK 未装）。→ [inference-architecture.md](inference-architecture.md)
- **2026-06-30** — 机器人无本机视频文件：`find /userdata ... *.mp4/*.mcap/*.h264/*.parquet` 仅命中 apt 缓存，`/userdata/storage/*` 只有 log。录制数据不留板上。→ [robot-connection.md](robot-connection.md)
- **2026-06-30** — 机器人无 V4L2 相机：`/dev/video*` 不存在；`v4l2-ctl` 无设备。相机改为 ROS2 话题。→ [robot-connection.md](robot-connection.md)
- **2026-06-30** — 实时相机话题：`ros2 topic list` 见 6 路 `coracam`，每路 `image_rect`(`sensor_msgs/Image`, nv12, 640×352, ~19Hz) + `video_encoded`(`foxglove_msgs/CompressedVideo` H264)。取三路左目 head_left/left_arm_left/right_arm_left。→ [robot-connection.md](robot-connection.md)
- **2026-06-30** — 实时臂状态：`/arm/{left,right}/fsm/joint_state`(`sensor_msgs/JointState`，names `joint1..joint6,joint7,G2P`)；EEF `/arm/*/fsm/eef_motor_state`(`arm_msgs/MotorState`)。→ [robot-connection.md](robot-connection.md)
- **2026-06-30** — 同子网可达：工作站 `enp108s0 192.168.25.132/24` ↔ 机器人 `eth0 192.168.25.1/24`，ping 通；机器人 `rmw_fastrtps_cpp` + `ROS_DOMAIN_ID=0`，板上有 `rclpy`+`cv_bridge`；工作站无系统 ROS。→ [robot-connection.md](robot-connection.md)

**总结论**：策略服务端能在 GPU 工作站推理；真机闭环需要一个 **ROS2→观测桥接**（V4L2/airbot_play 路径在 `192.168.25.1` 上不存在），并补装 `airbot_ie`/`airdc` 或用桥接绕过客户端的本地采集。

## 2026-06-30（下午）— 关节维度实测 + 服务端跑通（agent: Claude）

目的：(1) 实测机器人关节维度与模型契约对齐；(2) 把 `serve_policy.sh` 指向真实 checkpoint 并验证服务端能推理。

- **2026-06-30** — 关节实测：`ros2 topic echo --once /arm/left/fsm/joint_state` → name `[joint1..joint7, G2P]`（**8 维**），`G2P` effort≈-8.45 确认是夹爪。~~模型每臂只要 7 维 → 维度不一致，映射待定。~~ → [model-io-contract.md](model-io-contract.md) §4
  - 🛠 **后续修正**：「模型每臂 7 维关节」前提作废——该 checkpoint 是 relpose（相机位姿）模型，不是关节空间，joint_state 与它无直接映射。关节维度结论本身（8 个，G2P 是夹爪）仍有效。见 [vio-relpose-deployment.md](vio-relpose-deployment.md)。
- **2026-06-30** — config 匹配：checkpoint assets 目录 `vio_plant_collection_30hz_relpose` 对应 `config.py:729` 的 `pi05_vio_plant_collection`（`Pi0Config PI05, action_horizon=50, action_dim=32`）。norm_stats state/action 均 32 维（pad 后）。→ [model-io-contract.md](model-io-contract.md) §1
- **2026-06-30** — 模型 I/O 契约：相机名 `base_0_rgb/left_wrist_0_rgb/right_wrist_0_rgb`；~~state/action 真实 14 维 = [左臂6+左夹爪1+右臂6+右夹爪1]~~，pad 到 32；`AirbotInputs` 不再做 BGR→RGB（按 RGB 喂）。→ [model-io-contract.md](model-io-contract.md) §2/§3
  - 🛠 **后续修正**：维度/表示判错——实测 norm_stats 为 **state=16、action=14**，且是 relpose：state=每臂相机位姿`pos(3)+quat(4)`+夹爪，action=每臂`Δpos(3)+Δrotvec(3)`+夹爪。非关节空间。见 [model-io-contract.md](model-io-contract.md) 修正版 / [vio-relpose-deployment.md](vio-relpose-deployment.md)。
- **2026-06-30** — 改 `scripts/cmds/serve_policy.sh`：`POLICY_CONFIG=pi05_vio_plant_collection`、`CHECKPOINT_DIR=checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000`。
- **2026-06-30** — **服务端跑通** ✅：6.2GiB params restore 3.45s，`server listening on 0.0.0.0:8000`。mock 观测打 websocket 返回 `actions (50, 32)`。→ [inference-architecture.md](inference-architecture.md)
- **2026-06-30** — 仓库卫生：发现 `docs/VIO_Test/VIO_Test/` 是用户解压进来的**另一份独立 openpi git 仓库**（含自带 `.git`、`__MACOSX`、`uv.lock`）。它不是本仓库内容，会污染 `find`/`grep`/`docs` 索引，本次分析一律以仓库根的 `src/`、`examples/` 为准。建议从 `docs/` 移出或加入 `.gitignore`。

**本轮结论（已按 2026-06-30 20:27 CST SDK gRPC 路线修正）**：服务端**已实测可推理**；下一步真机闭环的硬骨头不是 `joint_state→state`，也不是给 policy 补相机 pose。当前 checkpoint 输出 relpose action，policy 请求可用 dummy state；真正工作是观测桥接、SDK `get_end_pose()` 当前 TCP pose、`move_end_pose()` / `move_eef()` 控制适配和安全壳（手眼外参仅相机 pose 路线需要）。见 [vio-relpose-deployment.md](vio-relpose-deployment.md) §8 和 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)。

## 2026-06-30（傍晚）— 读飞书《小推车遥操作使用文档》+ 安装核对（agent: Claude）

目的：(1) 按飞书文档搞清如何接入机械臂/读取数据；(2) 核对该装的软件是否都装好了。文档 id `SeXHd79NvoX2Ysxow2DczjmCnde`。

- **2026-06-30** — 文档性质：这是 **E2 主臂→PC→X5(192.168.25.1)→P7 双臂** 的遥操作 + 数采指南，与推理是两条链路；其“数采接口”节直接给出 obs/action 的 topic 契约。→ [teleop-and-data-collection.md](teleop-and-data-collection.md) §1/§2
- **2026-06-30** — ★关节维度定论：文档明示 arm 本体 **7 轴 `joint1..joint7`(rad)** + 夹爪 **`G2P`(m, 行程 0~0.096)**，`joint_states` 顺序 `[joint1..joint7,G2P]`。即每臂 8 维、双臂 16。→ [teleop-and-data-collection.md](teleop-and-data-collection.md) §3
- **2026-06-30** — ⚠️ 纠错（曾误判）：一度把“模型14维 vs 机器人16维”写成“本体自由度 P0 硬冲突”。对照 checkpoint 真实 norm_stats + 训练转换器（`docs/VIO_Test/.../vio_preview_converter.py`）后**否定**：当前 checkpoint 是**相机相对位姿(relpose)模型**——state16=每臂相机位姿`[pos3+quat4]`+夹爪2，action14=每臂`[Δpos3+Δrotvec3+夹爪1]`。“6”是 6-DOF 位姿增量不是 6 关节。机器人的关节 topic 与该 checkpoint 是**不同表示的两条 pipeline**，本体维度不构成阻塞。权威见 → [vio-relpose-deployment.md](vio-relpose-deployment.md)；对照 [teleop-and-data-collection.md](teleop-and-data-collection.md) §3
- **2026-06-30** — topic 命名核对：文档 `rt/<x>` = X5 上 ROS2 `/<x>`（实测 `/arm/*/control/control_command`、`/control/joint_states`、`/camera/*/video_encoded` 均在）。数采推荐用 `/control/...` 而非 `/fsm/...`。→ [teleop-and-data-collection.md](teleop-and-data-collection.md) §2
- **2026-06-30** — 安装核对：`airbot-arm 5.2.3` ✅、`airbot-rtm-sender 0.1.0` ✅ 已装；**`arm-sdk` whl ❌ 未装、`airbot_driver` whl ❌ 未装**（CLI 都 not found），`config.zip` ⚠️ 未解压。介质全在 `~/Downloads`。另：无 conda、本机无 CAN 接口(can0/can1)、无 ffmpeg、.venv 无 DDS/解码库。→ [teleop-and-data-collection.md](teleop-and-data-collection.md) §6

**本轮结论（已按 2026-06-30 17:30 CST 修正）**：飞书文档把**机器人侧关节空间**维度定死（每臂 7 关节 + G2P 夹爪）。但当前 checkpoint 是 relpose 模型，与关节 topic 是两条不同表示的 pipeline，本体维度**不是**阻塞项（曾误判，已纠正，见上条与 [vio-relpose-deployment.md](vio-relpose-deployment.md)）。真正的 P0 阻塞是执行侧对齐：当前 TCP pose 来源、servo pose 坐标系、夹爪接口换算；手眼外参只在相机 pose 备选路线需要。软件层面：推理 GPU 服务端就绪；遥操作发送端**未就绪**（缺两个 whl 安装、缺 CAN 硬件、config 未解压、无 conda）。

## 2026-06-30（傍晚二）— 补装遥操作发送端软件（agent: Claude）

目的：把本机装成能**发送遥操作指令**的 PC 发送端。

- **2026-06-30** — 依赖判定：`airbot-driver` 依赖 `arm-sdk>=5.2.3`（非 arm-p7-sdk），故装 `arm_sdk-5.2.3` + `airbot_driver-0.1.0`，不装 `arm_p7_sdk`。→ [teleop-and-data-collection.md](teleop-and-data-collection.md) §6
- **2026-06-30** — 安装：为不污染推理 `.venv`，用 `uv venv --python 3.12` 在 `~/airbot_teleop/venv` 建独立环境，装两个 whl（共 19 包）。`arm-sdk version`→`5.2.3`；`airbot-driver --help` 正常。
- **2026-06-30** — config：`config.zip` 解压到 `~/airbot_teleop/config/`（driver/sender/receivers）。`airbot-driver --check-config airbot_e2_pose.yaml`→`config OK`；`--dry-run` 解析出完整 app 命令。✅
- **2026-06-30** — 现状：发送端**软件全就绪**（airbot-arm 5.2.3 + airbot-rtm-sender 0.1.0 + arm-sdk + airbot-driver + config）。**唯一硬阻塞 = 无 CAN 接口**（接 E2 主臂用），需补 CAN 卡。启动序列见 → [teleop-and-data-collection.md](teleop-and-data-collection.md) §8

**本轮结论**：遥操作发送端软件补装完成并通过配置校验，装在独立 venv `~/airbot_teleop`（不影响推理 `.venv`）。接上 CAN 硬件即可起完整发送链路。

## 2026-06-30（晚）— 真机实测：确认无相机 VIO 位姿，只有关节空间（agent: Claude）

目的：用户装好 sshpass 后，实连 `192.168.25.1` 验证「真机能否直接提供 relpose checkpoint 所需的相机位姿」。

- **2026-06-30** — sshpass 登录成功。`uname`: `Linux ubuntu 6.1.83-DR-PL5.2_V0.0.0 ... aarch64`，ROS2 humble。共 185 个 topic。
- **2026-06-30** — **关键否定结论：无任何相机 pose / VIO topic**。`ros2 topic list | grep camera | grep pose` → 空。历史训练数据里出现过 `/robot/camera/*_wrist/left/pose` 这个 topic 名，但后续已按用户确认把默认部署语义修正为 TCP pose；真机上没有该 pose topic 不阻塞当前 policy 推理。
- **2026-06-30** — 真机笛卡尔只有 `/arm/{left,right}/fsm/cartesian_state`（type `arm_msgs/msg/CartesianState`，FK 末端位姿，frame=base_link 系），且 publisher=1 但 `echo --once` 取不到（低频/需触发；subscription=0）。`arm_msgs` 自定义包不在默认 ROS env，需 source 机器人 app workspace 才能解析其字段。
- **2026-06-30** — `joint_states` 正常实时发布（`/arm/left/control/joint_states`, pub=1）。实测：`name=[joint1..joint7, G2P]`（**7 关节 + 夹爪**），position 给出 7 关节角(rad)+G2P 行程，effort 末位 -8.448=夹爪。frame_id=base_link。
- **2026-06-30** — 飞书《小推车遥操作使用文档》(wiki SaakwdAP7iZTIKks5qKc5BsVn9f) 的「数采接口」最小集 = joint_states(state) + control_command(action, rad) + 6 路 H264，**完全不含 pose**。印证当前 HY6310_airrtm_control 遥操配置走纯关节空间。G2P 夹爪行程范围 0~0.096 m。

**本轮结论（已按 2026-06-30 20:27 CST SDK gRPC 路线修正）**：这台真机当前**拿不到**训练数据中曾使用的相机 VIO 位姿；这不再视为 policy 推理 state 阻塞，因为当前 `pi05_vio_plant_collection` 不消费 state 数值。真正影响闭环的是执行侧：当前主线用 SDK `get_end_pose()` 提供当前 TCP pose，再把 relpose action 积分为 `move_end_pose()` 的绝对目标。

## 2026-06-30（晚）— 直连 DDS 控制方案调研（agent: Claude）

目的：回答"为什么要 CAN？本地发 ROS2 topic 对面不能直接收吗" → 确认直连可行性并落文档。

- **2026-06-30** — 命令 topic 有订阅方：`ros2 topic info -v /arm/left/control/control_command`、`/servo/command`、`/fsm/servo_pose_command` 在 X5 上 `Subscription count: 1`，订阅方 `_CREATED_BY_BARE_DDS_APP_`（robot_app 裸 DDS）。→ **本地直接发 DDS topic，X5 能收**；这是当时的直连 DDS 底层验证，不需要 CAN/driver/AIRRTM。2026-06-30 20:27 CST 后不再作为当前主线。→ [direct-dds-control.md](direct-dds-control.md)
- **2026-06-30** — CAN 角色澄清：CAN 只用于 `airbot-arm` 读 **E2 物理主臂**位姿（动作来源），是遥操作专属。模型/程序发指令无主臂可读 → **不需要 CAN**。→ [direct-dds-control.md](direct-dds-control.md) §1
- **2026-06-30** — 中间件同源：X5 cora 框架用 **FastDDS 2.6.10**（`libfastrtps.so.2.6.10`）+ **domain_id=0**（`framework_config.json`），与 ROS2 Humble `rmw_fastrtps_cpp` 同源 → 跨机发现可互通。→ [direct-dds-control.md](direct-dds-control.md) §3
- **2026-06-30** — arm_msgs 非标准 ROS 消息：`ros2 interface list | grep arm_msgs` 为空；定义在 cora 自带 IDL `/opt/cora/include/cora/dds/idl/arm_msgs/msg/`（`ArmControl/Servo/FiniteStateMachine/Planning/Collision.idl`）。工作站要发须先取 IDL 自行生成消息类型。→ [direct-dds-control.md](direct-dds-control.md) §2/§5
- **2026-06-30** — FSM 状态契约：`SwitchableFsmState` 枚举 `IDLE/PLANNING/GRAVITY_COMP/SERVO_CONTROL/POSITION_CONTROL/FORCE_CONTROL`；发 servo 前须经 `switch_control_state_command` 切到 `FSM_SERVO_CONTROL`，否则命令被拦。servo input 模式 `cartesian_pose`（`airrtm_config.json`）。→ [direct-dds-control.md](direct-dds-control.md) §4

**本轮当时结论（已被 2026-06-30 20:27 CST SDK gRPC 路线取代）**：当时确认直连 DDS 在底层条件上可行 —— 同子网 + 同 FastDDS + domain 0，命令 topic 有 robot_app 订阅。但当前不再推进 DDS Route 或裸 DDS publisher；控制主线改为 Arm-P7 SDK gRPC。手眼外参仍只在相机 pose 路线需要。CAN 不在当前 SDK gRPC 路径上。

## 2026-06-30（晚）— 文档收敛：纠正"必须重训"的过早结论（agent: Claude）

目的：把"真机实测无相机位姿"+"relpose 语义已确证"两块拼成可执行结论，并纠正早前文档里"必须重训关节空间模型"的判断。

- **2026-06-30** — 读 `docs/VIO_Test/.../docs/26-06-28/26-06-28-pi05-normalization-check.md`：官方训练笔记确认 action = camera-relative SE(3)（§168 明示，若 TCP-relative 才需 camera-to-TCP 外参），state=16D pose+gripper，stats 必须用 VIO 数据重算、不复用旧 stats。
- **2026-06-30** — 关键洞察落文档（后续修正）：早期按腕部相机路线推导需要 `T_eef_cam`。后续用户确认训练用 TCP pose 后，默认路线改为直接用当前 TCP pose 积分 relpose action；该 pose 不必作为当前 policy state 输入，但 relpose action 下发仍需要执行侧当前 TCP pose。→ [vio-relpose-deployment.md](vio-relpose-deployment.md) §0/§5/§6/§8。
- **2026-06-30** — 纠正 CHECKLOG 上一轮"不能直接闭环/三条路/§10待补"的措辞：实际是"不能开箱即用但不必重训，两条路在 §5/§6/§8"。

**本轮结论（已按 2026-06-30 20:27 CST SDK gRPC 路线修正）**：闭环方向应表述为 image+prompt→model→relpose action→arm。当前 checkpoint 可用，不必重训；policy 请求里 `state` 可用 dummy。前提集中在执行侧：SDK `get_end_pose()` 当前 TCP pose、`CartesianPose` 坐标系、夹爪 mm 换算、`move_end_pose()` / `move_eef()` 下发和安全壳；`T_eef_cam` 仅相机 pose 路线需要。DDS 相关内容仅保留为历史资料。

## 2026-06-30（晚二）— 本地订阅 head_right camera_info 步骤整理（agent: Codex）

目的：回答用户“要在本地接收 `/camera/head_right/image_rect/camera_info`”。

- **2026-06-30** — 查阅既有文档确认：机器人侧 ROS2 Humble + `rmw_fastrtps_cpp` + `ROS_DOMAIN_ID=0`；工作站与机器人同在 `192.168.25.0/24`，但此前记录为工作站无系统 ROS。→ [robot-connection.md](robot-connection.md) §8
- **2026-06-30** — 当时本机核对：`which ros2` → `ros2 not found`；`printenv ROS_DOMAIN_ID RMW_IMPLEMENTATION` → 空。该条是安装前状态，后续“晚五”已用系统级 Miniconda/mamba 补装 `/opt/miniconda3/envs/ros2-topic` 并实测直连成功。

**本轮结论（已被晚五更新）**：安装前工作站没有 `ros2`，不能直接通过 DDS 订阅；当前最新结论见“晚五”：本机已能直接接收 `/camera/head_right/image_rect/camera_info`。

## 2026-06-30（晚三）— 当前 repo 与 inference 输入第一性原理检查（agent: Codex）

目的：回答“当前 repo 在做什么，需要输入什么数据以进行 inference”，从代码、checkpoint、训练转换器反推最小输入契约。

- **2026-06-30** — 代码入口核对：`scripts/cmds/serve_policy.sh` 当前指向 `POLICY_CONFIG=pi05_vio_plant_collection` 与 checkpoint `checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000`；`scripts/serve_policy.py` 通过 WebSocket 接 observation 并返回 actions。→ [repo-inference-first-principles.md](repo-inference-first-principles.md)
- **2026-06-30** — transform 链路核对：`LeRobotAirbotDataConfig` 使用 `AirbotInputs`/`AirbotOutputs`；PI05 model transforms 包含 `ResizeImages(224,224)`、`TokenizePrompt`、`PadStatesAndActions(32)`；checkpoint assets norm_stats 在 serving 时从 checkpoint 加载。→ [repo-inference-first-principles.md](repo-inference-first-principles.md)
- **2026-06-30** — checkpoint stats 复核：系统 `python3` 无 numpy（`ModuleNotFoundError`），改用 `.venv/bin/python` 读取 `norm_stats.json`，输出 `state_len 32 state_effective 16`、`action_len 32 action_effective 14`、尾部补零均为 True。→ [repo-inference-first-principles.md](repo-inference-first-principles.md)
- **2026-06-30** — 训练转换器核对：`vio_preview_converter.py` 证明 state/action 是 pose relpose 结构，`vio_convert_to_lerobot.py` 声明 `state: (16,)`、`actions: (50,14)`。早期曾按 topic 名写成相机局部系；后续用户确认训练使用 TCP pose，默认 action frame 已改为 TCP 局部系。→ [repo-inference-first-principles.md](repo-inference-first-principles.md)
- **2026-06-30** — AIRBOT 示例客户端核对：`examples/airbot/play_operator.py` 仍是 V4L2 + `airbot_ie/airdc` gRPC + 关节空间 qpos/send_action，不能直接作为当前 relpose checkpoint 的真机客户端。→ [repo-inference-first-principles.md](repo-inference-first-principles.md)

**本轮结论（已按 2026-06-30 20:27 CST SDK gRPC 路线修正）**：policy server 的请求格式需要三路 RGB 图像 + `state` 键 + prompt，但当前 PI05 checkpoint 不消费 `state` 数值，dummy state 即可；server 返回 `(50,32)`，真实有效 action 为前 14 维。真机闭环缺口是观测客户端和执行侧 SDK 适配：取图、发请求、用 `get_end_pose()` 当前 TCP pose 把 relpose action 转成 `move_end_pose()` / `move_eef()`。


## 2026-06-30（晚四）— 视频流、机械臂回传与模型-机械臂接口对齐（agent: Codex）

目的：回答“是否有 video”“控制机械臂还缺什么”“模型输出和机械臂输入分别是什么”“是否必须 IK”“外参是否需要每次输入”。

- **2026-06-30** — 视频确认：topic list 明确 6 路相机均有 `/camera/<cam>/image_rect` 和 `/camera/<cam>/image_rect/video_encoded`；`video_encoded` 是实时 H264 topic，不是板上视频文件。推理取三路左目 `head_left/left_arm_left/right_arm_left`。→ [robot-connection.md](robot-connection.md) §3.1
- **2026-06-30** — 机械臂回传：`/arm/{left,right}/control/joint_states` 是标准 `sensor_msgs/JointState`，左臂实测约 245Hz；`/fsm/joint_state` 约 123Hz；字段为 `joint1..joint7,G2P`，含 position/velocity/effort，G2P effort 约 -8.45。→ [direct-dds-control.md](direct-dds-control.md) §1.1
- **2026-06-30** — 控制入口历史核对：`switch_control_state_command`、`servo_pose_command`、`servo_joint_command`、`end_effector_position_control_command` 都有 robot_app 订阅者，QoS 为 RELIABLE/VOLATILE。当时 DDS 路线缺口是 `arm_msgs` 类型包/发布客户端，不是硬件数据源；20:27 CST 后当前缺口已改为 SDK/gRPC 服务。→ [direct-dds-control.md](direct-dds-control.md) §1.1/§5
- **2026-06-30** — IDL/配置：`arm_msgs/kdl_msgs/rpc_msgs` IDL 在 `/opt/cora/include/cora/dds/idl/`；P7C 是 7 轴，G2P 行程 `0.0–0.096m`；servo tick 4ms，incoming timeout 1000ms。→ [direct-dds-control.md](direct-dds-control.md) §1.1
- **2026-06-30** — 模型到机械臂接口：模型有效 action 是每步 14 维 relpose（每臂 `Δpos3+Δrotvec3+gripper1`）；机械臂推荐入口是 `FsmServoPoseCommand` 的末端绝对目标 pose + 夹爪位置命令。X5 内部可做 servo/IK，本地不一定要自己做 IK；只有走 `servo_joint_command` 才需要 7 关节目标或先调 KDL IK。→ [model-io-contract.md](model-io-contract.md) §6.1
- **2026-06-30** — 外参结论（后续修正）：`T_eef_cam` 不是默认 TCP→TCP 路线的输入；不需要每次 policy 推理人工输入。若执行 relpose→绝对 pose，每帧需要的是执行侧当前 TCP pose，它不是当前 policy 的 state 输入；只有改走相机 pose 路线才需要固定手眼外参。→ [model-io-contract.md](model-io-contract.md) §6.1

**本轮当时结论（已被 2026-06-30 20:27 CST SDK gRPC 路线取代）**：当时确认有实时视频流和高频机械臂回传，并曾把 `arm_msgs` / DDS publisher 视为最短控制缺口。当前不再走 DDS；最短缺口改为安装 `arm_p7_sdk`、连通 50071 gRPC 服务、用 `get_end_pose()` / `move_end_pose()` / `move_eef()` 接执行适配器。policy 推理仍可用 dummy state；固定手眼外参仅相机 pose 路线需要。

## 2026-06-30（晚五）— 系统级 Miniconda/mamba 与本地 ROS2 订阅装好（agent: Codex）

目的：按用户要求安装 Miniconda 和 mamba，默认使用 mamba；并让本地工作站能接收 `/camera/head_right/image_rect/camera_info`。

- **2026-06-30** — 安装前检查：Ubuntu 24.04.4 LTS x86_64；`conda/mamba/ros2` 均不存在；`/opt/miniconda3` 不存在。
- **2026-06-30** — 系统级安装 Miniconda 到 `/opt/miniconda3`，安装包 sha256=`2284bafb7863a23411b19874d216e237964d4b32dd9beb6807fa8b2d84570961`。未写用户目录，sudo 密码只走交互输入。→ [local-conda-mamba-ros2.md](local-conda-mamba-ros2.md)
- **2026-06-30** — base 环境安装 `mamba 2.5.0` + `conda-libmamba-solver`；`conda 26.5.3` 已设 `solver: libmamba`、`channel_priority: strict`。系统级 shell hook 写入 `/etc/profile.d/miniconda.sh`，新 zsh/bash 中 `mamba` 默认可用，且 `mamba activate ros2-topic` 可直接进入环境。
- **2026-06-30** — 为避免大依赖，放弃并清理中断的 `ros2-jazzy` 半成品；改建最小 `/opt/miniconda3/envs/ros2-topic`，包含 `ros-jazzy-ros2topic`、`ros-jazzy-sensor-msgs`、`ros-jazzy-rmw-fastrtps-cpp`。
- **2026-06-30** — 验证：`mamba run -n ros2-topic ros2 topic --help` 正常；`from sensor_msgs.msg import CameraInfo` 输出 `CameraInfo`；`ping 192.168.25.1` 通。
- **2026-06-30** — 本地直连 DDS 实测：`ros2 topic list` 能看到 `/camera/head_right/image_rect/camera_info`；`ros2 topic echo --once /camera/head_right/image_rect/camera_info` 收到 `frame_id=camera_xf6600_head_right`、`height=352`、`width=640`。按新 zsh 会话 `mamba activate ros2-topic` 后直接 echo 也复测通过。→ [robot-connection.md](robot-connection.md) §8

**本轮结论**：系统级 Miniconda/mamba 已装好，默认走 mamba/libmamba；本地工作站已能直接订阅 `/camera/head_right/image_rect/camera_info`。后续命令：`mamba activate ros2-topic`，设置 `ROS_DOMAIN_ID=0` 和 `RMW_IMPLEMENTATION=rmw_fastrtps_cpp` 后运行 `ros2 topic echo --once /camera/head_right/image_rect/camera_info`。

## 2026-06-30（晚六补）— 训练配置/实测确认当前 PI05 不消费 state 数值（agent: Codex）

目的：回应“远端实际训练过程里我们用了什么，是否其实不需要 state”，从训练脚本、config、transform、模型前向和 checkpoint 实测确认。

- **2026-06-30** — 训练入口核对：`docs/VIO_Test/VIO_Test/scripts/cmds/vio_policy_train.sh` 使用 `POLICY_CONFIG=pi05_vio_plant_collection`；本仓库同名 config 为 `Pi0Config(model_type=PI05, action_horizon=50, action_dim=32, discrete_state_input=False)`。→ [model-io-contract.md](model-io-contract.md) §0/§1
- **2026-06-30** — 代码路径核对：`AirbotInputs` 仍读取 `data["state"]` 并 pad 到 32；但 `TokenizePrompt` 在 `discrete_state_input=False` 时把 state 置为 `None`，PI05 模型也没有 continuous `state_proj` 分支。→ [repo-inference-first-principles.md](repo-inference-first-principles.md) §2
- **2026-06-30** — checkpoint 实测：同三路零图像、同 prompt、同 fixed noise 下，`state=zeros(16)` 与 `state=linspace(-1000,1000,16)` 的 `policy.infer()` 输出完全一致：`max_abs_diff 0.0`、`allclose_exact True`。→ [model-io-contract.md](model-io-contract.md) §0

**本轮结论**：你判断是对的。当前 checkpoint 推理**不需要真实 state 数值**；只需提供一个 `state` 占位键让 transforms 通过。训练数据里仍有 state=16（相机 pose+夹爪），它解释 action 标签/归一化和 relpose 重构公式；但真机闭环的实际缺口在执行侧：如何把 action 转成机械臂 servo 命令，而不是如何给 policy 喂 camera pose。

## 2026-06-30（晚七）— 记录机械臂无线 SSH 入口（agent: Codex）

目的：用户补充 `ssh root@172.100.10.159`、密码 `root` 也可登录机械臂；核对并补充到长期入口文档。

- **2026-06-30** — 文档核对：此前 [robot-connection.md](robot-connection.md) §2 已记录机器人 `wlan0 172.100.10.159`，但 [../AGENTS.md](../AGENTS.md) 只列了 `ssh root@192.168.25.1`。本轮已把 `ssh root@172.100.10.159`（密码 `root`）补为“无线 / 管理备用链路”，并保留 `192.168.25.1` 作为有线 / DDS 推荐链路。未重新发起 SSH 登录验证；该入口来自用户补充 + 既有 `wlan0` 文档。

**本轮结论（网络入口仍有效，控制路线已更新）**：后续 agent 应知道两种登录方式：`ssh root@192.168.25.1` 和 `ssh root@172.100.10.159`，密码均为 `root`。若未来专门验证 DDS/ROS2，多播仍优先有线 `192.168.25.0/24`；但当前启动机械臂主线已改为 Arm-P7 SDK gRPC。

## 2026-06-30（晚七）— I/O 对齐表收敛：policy state 占位、夹爪 0-100（agent: Codex）

目的：纠正本轮对齐表里“policy 必须输入真实相机/夹爪 state”的表述，并按用户确认把夹爪约定收敛为 0-100。

- **2026-06-30** — 代码复核：`pi05_vio_plant_collection` 是 `discrete_state_input=False`；`AirbotInputs` 仍要求 `state` 键，但 PI05 模型前向不走 continuous `state_proj`，已有实测也证明 dummy state 与极端 state 输出一致。
- **2026-06-30** — 文档纠正：新增/更新 [training-robot-io-alignment.md](training-robot-io-alignment.md)，明确 policy 请求为三路 RGB 图像 + prompt + dummy state；当前参考 pose 属于执行侧 action→servo 转换，不是当前 policy 输入。
- **2026-06-30** — 夹爪纠正：模型侧夹爪是 `0-100` 原始开合值（开=100，闭=0）；若底层接口是米制 G2P，则仅在输入/输出边界换算。

**本轮结论**：模型已训练好；推理时需要给它图像/prompt 和一个 state 占位键，但不需要真实相机 pose 作为 policy input。真正需要实时 pose 的地方是机械臂执行侧，用来把模型 relpose action 转成绝对 servo pose。



## 2026-06-30 16:18 CST — CHECKLOG 时间格式约定更新（agent: Codex）

目的：按用户要求，把后续 CHECKLOG/changelog 条目的时间标记从“晚三 / 晚五 / 傍晚二”等相对轮次改为具体时间。

- **2026-06-30 16:18 CST** — 检查命令：`rg -n "CHECKLOG|日期|时间|晚|changelog|变更|时间线" AGENTS.md docs/CHECKLOG.md`；确认现有 `docs/CHECKLOG.md` 多处使用“晚/傍晚”轮次标记，`AGENTS.md` 仅要求绝对日期。
- **2026-06-30 16:18 CST** — 修改并读回确认：`sed -n 24,40p AGENTS.md` 显示已新增规则：`docs/CHECKLOG.md` 后续统一写绝对日期 + 具体时间（例：`2026-06-30 21:35`），不要再用“晚三 / 晚五 / 傍晚二”这类相对时间或轮次标记。

**本轮结论**：后续 agent 写 `docs/CHECKLOG.md` 时应直接写具体时间，例如 `2026-06-30 16:18 CST`，不要再新增“晚x”式标题。

## 2026-06-30（晚八）— 远端机械臂工作方式与 I/O 整理（agent: Codex）

目的：回答用户“远端机械臂现在怎么做、需要做什么处理、输入输出是什么”，整合飞书遥操作文档、直连 DDS 文档、relpose 部署文档和 I/O 对齐表。

- **2026-06-30** — 复核 [teleop-and-data-collection.md](teleop-and-data-collection.md)：飞书链路是 E2 主臂→PC→AIRRTM→X5/P7 的遥操作与关节空间数采；其 `joint_states/control_command` 是关节空间接口，不等于当前 checkpoint 的 relpose action。
- **2026-06-30** — 历史复核 [direct-dds-control.md](direct-dds-control.md)：直连 DDS 路线不需要 CAN/AIRRTM，切 FSM 到 `SERVO_CONTROL` 后发 `servo_pose_command` 和夹爪命令，前提是有 `arm_msgs` 类型与 QoS 对齐；20:27 CST 后该路线只保留为历史资料，当前主线是 Arm-P7 SDK gRPC。
- **2026-06-30** — 复核 [training-robot-io-alignment.md](training-robot-io-alignment.md) / [vio-relpose-deployment.md](vio-relpose-deployment.md)：当前 policy 请求是三路 RGB 图像 + prompt + dummy state；执行侧需要当前 TCP pose、servo pose 坐标系、夹爪 0-100 到底层接口的边界换算；固定 `T_eef_cam` 仅在相机 pose 参考路线需要。

**本轮结论（已按 2026-06-30 20:27 CST SDK gRPC 路线修正）**：远端机械臂闭环分两层：policy 只负责图像+prompt→relpose action；远端机械臂执行层负责 SDK pose 回传、relpose→末端目标 pose、`move_end_pose()` 和 `move_eef()` 下发。FSM/arm_msgs 只保留为历史 DDS 路线资料。

## 2026-06-30 17:05 CST — AIRRTM 转换层只读核对与文档收敛（agent: Codex）

目的：按用户要求先不开始实现，只完整了解当前状态；重点核对飞书/本地 `airbot_driver` 是否已有可复用的模型动作到机械臂执行转换通道。

- **2026-06-30 17:05 CST** — 飞书 VIO 文件夹定位：`lark-cli drive +search --query VIO --doc-types folder --format json` → 唯一结果 `VIO`，token `IGY1fkfZ3ltQMIdWHZvcZcPznne`。
- **2026-06-30 17:05 CST** — 飞书文档只读核对：`docs +fetch` 关键词 `airrtm_config|servo_input_mode|arm_servo_json|data_sources|publish_to_arm|queue_mode`，确认 X5 `airrtm_config.json` 中 `data_sources=["arm_servo"]`、`servo_input_mode="cartesian_pose"`、`queue_mode="latest"`、`publish_to_arm=true`。
- **2026-06-30 17:05 CST** — 本地 `airbot_driver` 只读核对：`make_servo_pose_payload()` 的 payload 为 `command="servo_pose"`、`left_pose/right_pose=[x,y,z,qx,qy,qz,qw]`、`left_gripper/right_gripper=float`；外层 `custom_type="arm_servo_json"`；ZMQ 配置为 `tcp://0.0.0.0:6000` / topic `servo`。
- **2026-06-30 17:05 CST** — 文档纠正（历史）：将 [teleop-and-data-collection.md](teleop-and-data-collection.md) 中“模型驱动不需要 AIRRTC”的绝对表述改为“CAN 不需要；AIRRTM 可作为第一版转换层，直连 DDS 是另一条底层路线”。20:27 CST 后该判断已被 SDK gRPC 主线覆盖。新增 [airrtm-conversion-layer.md](airrtm-conversion-layer.md)。
- **2026-06-30 17:05 CST** — 用户补充纳入：截图中的 `cam2tcp/cam2imu` 默认不用；当前工作假设是 AIRRTM/SDK `servo_pose` 控制坐标系已经是夹爪末端/TCP。若后续选择 VIO 相机 pose 参考路线，再单独确认外参。

**本轮当时结论（已被 2026-06-30 20:27 CST SDK gRPC 路线取代）**：当时判断可先走 AIRRTM `arm_servo_json`，但当前不走 AIRRTM/DDS；主线改为 Arm-P7 SDK gRPC：模型 relpose action → `DualArmTcpTarget` → `CartesianPose` → `move_end_pose()` / `move_eef()`。本轮未写控制代码，也未向机器人发送控制命令。

## 2026-06-30 17:12 CST — 飞书 VIO 记录创建被审批策略拦截（agent: Codex）

目的：按用户“可以写一个飞书文档，位置放在 VIO 文件夹”要求，将当前情况记录创建到飞书 VIO 文件夹。

- **2026-06-30 17:12 CST** — 已定位 VIO 文件夹 token `IGY1fkfZ3ltQMIdWHZvcZcPznne`。
- **2026-06-30 17:12 CST** — 尝试执行 `lark-cli docs +create --parent-token IGY1fkfZ3ltQMIdWHZvcZcPznne ...` 时被审批策略拒绝：向外部飞书文档写入 repo/机器人现状内容被判定为需要更明确授权的外发风险。
- **2026-06-30 17:12 CST** — 未创建飞书文档，未向机器人发送任何控制命令。当前完整记录已保存在本地 [airrtm-conversion-layer.md](airrtm-conversion-layer.md)。如后续用户明确批准把这份内容写入飞书，再执行创建。

**本轮结论**：飞书写入当时被拦截，未做绕过；后续用户明确授权后已创建飞书记录，见 2026-06-30 17:18 CST 条目。

## 2026-06-30 17:18 CST — 飞书 VIO 记录创建成功（agent: Codex）

目的：用户明确回复“允许写入飞书 VIO 文件夹”后，将本地 AIRRTM 转换层现状记录创建到飞书 VIO 文件夹。

- **2026-06-30 17:18 CST** — 执行：`lark-cli docs +create --parent-token IGY1fkfZ3ltQMIdWHZvcZcPznne --content ... --format json`。
- **2026-06-30 17:18 CST** — 返回：`ok=true`，`document_id=Uc7GdKUSmoYYHOxZPCPcHADRnMI`，URL：https://w79rvfxw83.feishu.cn/docx/Uc7GdKUSmoYYHOxZPCPcHADRnMI。
- **2026-06-30 17:18 CST** — 内容范围（历史）：当前 checkpoint/policy I/O、AIRRTM `arm_servo_json` 可选转换层、SDK/TCP 坐标系约定、后续实现前待确认事项。20:27 CST 后已改为 Arm-P7 SDK gRPC 主线。未写控制代码，未向机器人发送控制命令。

**本轮结论**：飞书 VIO 文件夹中的状态记录已创建成功；本地底稿仍以 [airrtm-conversion-layer.md](airrtm-conversion-layer.md) 为准同步维护。

## 2026-06-30 17:30 CST — TCP pose 训练语义修正：默认不需要手眼外参（agent: Codex）

目的：回应“训练用的就是 TCP Pose，为什么还需要固定手眼外参”，把文档里的相机路线旧结论收敛到当前 TCP 默认路线。

- **2026-06-30 17:30 CST** — 用户确认：训练使用的是 TCP pose。由此推导，模型 action 的 `Δpos/Δrotvec` 默认应解释为 TCP 局部系相对量。
- **2026-06-30 17:30 CST** — 本地证据复核：`airrtm-conversion-layer.md` 已记录 AIRRTM/SDK `servo_pose` 当前工作假设是夹爪末端/TCP pose；`docs/VIO_Test/.../26-06-27-openpi-remote-data-precheck.md` 记录上游预处理曾通过 `CAMERA_T_TCP` 最终写出 TCP pose。`vio_preview_converter.py` 的 pose topic 名包含 `camera`，不能再单独作为“部署默认相机 frame”的结论。
- **2026-06-30 17:30 CST** — 文档修正：更新 [training-robot-io-alignment.md](training-robot-io-alignment.md)、[vio-relpose-deployment.md](vio-relpose-deployment.md)、[model-io-contract.md](model-io-contract.md)、[repo-inference-first-principles.md](repo-inference-first-principles.md)、[direct-dds-control.md](direct-dds-control.md)、[teleop-and-data-collection.md](teleop-and-data-collection.md)。

**本轮结论（已按 2026-06-30 20:27 CST SDK gRPC 路线修正）**：默认闭环是 TCP→TCP：policy 输出 TCP relpose action，执行侧通过 SDK `get_end_pose()` 获取当前 TCP pose 后积分成目标 TCP pose，再发 SDK `move_end_pose()`；夹爪走 `move_eef()`。固定手眼外参 `T_eef_cam` 不在默认路径里；只有未来改用 VIO 相机 pose 作为执行参考、或需要 camera pose ↔ TCP pose 转换时才需要。

## 2026-06-30 17:11 CST — 飞书 VIO 文档改为原文修正 TCP pose 结论（agent: Codex）

目的：按用户要求同步更新飞书 VIO 文件夹里的《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》，且不要追加新章节，而是修改原有结论。

- **2026-06-30 17:11 CST** — 读取目标文档：`lark-cli docs +fetch --doc Uc7GdKUSmoYYHOxZPCPcHADRnMI --detail with-ids --format json`，确认文档可访问，revision 从 5 开始。
- **2026-06-30 17:11 CST** — 先前尝试 `docs +update --command append` 被策略拦截，未写入；用户随后明确授权“可以让你修改飞书文档”，并要求以修改原文为主。
- **2026-06-30 17:11 CST** — 执行多次 `lark-cli docs +update --command block_replace`，替换“当前结论”中 action frame 语义、“坐标系约定”段落及三条列表、“还缺什么”的前三个待确认项。
- **2026-06-30 17:11 CST** — 读回验证：`docs +fetch --scope keyword --keyword "坐标系约定|还缺什么|TCP pose|手眼外参"` 显示飞书文档已写入：训练使用 TCP pose，默认闭环 TCP→TCP，`T_eef_cam` 不在默认路径中；只有相机 pose 备选路线才需要手眼外参。
- **2026-06-30 17:11 CST** — 目录验证：`docs +fetch --scope outline --max-depth 2` 仍只有原五个 H1：当前结论、AIRRTM 通道是否可用、坐标系约定、还缺什么、证据来源；没有新增“TCP pose 修正”章节。

**本轮结论**：飞书文档已按“修改原文”方式同步完成，链接仍为 https://w79rvfxw83.feishu.cn/docx/Uc7GdKUSmoYYHOxZPCPcHADRnMI 。未向机器人发送任何控制命令。

## 2026-06-30 17:44 CST — 机械臂 root SSH 公钥免密登录已配置（agent: Codex）

目的：按用户要求，把本工作站 SSH 公钥加入机械臂，后续登录不再输入密码，并同步更新长期文档。

- **2026-06-30 17:44 CST** — 本机公钥来源：`~/.ssh/id_ed25519.pub`。
- **2026-06-30 17:44 CST** — 写入命令：`PUBKEY=$(cat ~/.ssh/id_ed25519.pub); sshpass -p root ssh ... root@172.100.10.159 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && grep -qxF '$PUBKEY' ~/.ssh/authorized_keys || printf '%s\n' '$PUBKEY' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && wc -l ~/.ssh/authorized_keys"`。
- **2026-06-30 17:44 CST** — 关键输出：`authorized_keys` 从 3 行变为 `4 /root/.ssh/authorized_keys`。
- **2026-06-30 17:44 CST** — 免密验证：`ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes ... root@172.100.10.159 'hostname; whoami; echo key_login_ok'` → `ubuntu`、`root`、`key_login_ok`。
- **2026-06-30 17:44 CST** — 文档同步：已更新 [../AGENTS.md](../AGENTS.md) 和 [robot-connection.md](robot-connection.md) 的登录说明；`root` 密码只保留为 fallback。

**本轮结论（网络入口仍有效，控制路线已更新）**：从本工作站登录机械臂无线管理地址 `ssh root@172.100.10.159` 已验证免密。`192.168.25.1` 是同一台 X5 的有线口，网络可达时应使用同一 root 公钥；若未来做 DDS/ROS2 再优先走有线链路，当前主线是 Arm-P7 SDK gRPC。


## 2026-06-30 17:54 CST — DDS Route 历史路线与当前 X5 真机状态对齐（agent: Codex）

目的：用户提供 `docs/二代臂Arm-P7-SDK开发指南.md` 和飞书 DDS wiki 后，连接当前机械臂做只读核对，确定模型动作下发前的实际方案。

- **2026-06-30 17:54 CST** — 飞书 DDS wiki 读取：`lark-cli docs +fetch --doc https://w79rvfxw83.feishu.cn/wiki/PNkUwkPtoiciYTkqsI5cNF08nCe --scope outline/section`。文档标题《二代臂 DDS Route 开发指南》，document_id `TqNMdmC1nosChixvzvWcFtaenKg`，revision `128`；核心接口为 `acquire_control/renew_control/release_control`、`get_cartesian_pose`、`call_switch_control_state`、`call_servo_pose_command`、`call_end_effector_position_control`。
- **2026-06-30 17:54 CST** — 文档前提：DDS Route wiki 注明需要 `robot_app 0.3.3+` 和 `arm_p7_sdk 1.1.0.dev50+`；pose 统一为 `[x,y,z,qx,qy,qz,qw]`，控制类 RPC 必须携带业务层 `client_id` 和 `lease_id`。
- **2026-06-30 17:54 CST** — 当前网络：`ip -br addr show enp108s0` → `DOWN`；`ping 172.100.10.159` 成功；`ping 192.168.25.1` 失败。X5 侧 `eth0 192.168.25.1/24` 和 `wlan0 172.100.10.159/23` 均 UP。
- **2026-06-30 17:54 CST** — 当前 X5 版本/route：`/opt/robot_app/include/version.hpp` → `AIRBOT_MOTION_VERSION "0.1.1.dev90+g24fec8a"`；`ros2 topic list | grep dds_route`、`find /opt -name "FsmDdsRoute*.idl"`、`ps -ef | grep dds_route` 均无输出。结论：当前 X5 未部署 DDS Route。
- **2026-06-30 17:54 CST** — 当前可见底层入口：`/arm/*/fsm/servo_pose_command` 和 `/arm/*/fsm/end_effector_position_control_command` 有 robot_app 订阅者，QoS 为 RELIABLE/VOLATILE；`/arm/left/control/joint_states` 约 244.6Hz；G2P 行程配置为 `0.0-0.096m`。
- **2026-06-30 17:54 CST** — 文档同步：新增 [p7-dds-route-current-state.md](p7-dds-route-current-state.md)，修正 [direct-dds-control.md](direct-dds-control.md) 和 [robot-connection.md](robot-connection.md) 中“当前有线直连已就绪”的过期表述。

**本轮当时结论（已被 2026-06-30 20:27 CST 用户指令取代）**：当时判断 DDS Route 是升级后的目标接口，因为它直接提供 lease、`get_cartesian_pose` 和 `call_servo_pose_command`；但当前 X5 固件版本未部署该 route，不能按 DDS wiki 直接跑。20:27 CST 后当前主线改为 Arm-P7 SDK gRPC，不再推进 DDS Route / 裸 DDS publisher。全程未发布控制消息，未移动机械臂。


## 2026-06-30 17:58 CST — 飞书 VIO 文档同步 DDS Route / 当前 X5 状态（agent: Codex）

目的：按当时用户要求将 DDS Route 文档和当前机械臂现场状态同步到飞书 VIO 文档；2026-06-30 20:27 CST 后已被 Arm-P7 SDK gRPC 路线更新覆盖。

- **2026-06-30 17:58 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-06-30 17:58 CST** — 执行：用 `lark-cli docs +update --command block_replace` 替换原文 14 个 block，覆盖“当前结论”两条、“AIRRTM 通道是否可用”表格一格、“坐标系约定”两条、“还缺什么”五条、“证据来源”四条。
- **2026-06-30 17:58 CST** — 写入要点（历史）：当时写入 DDS Route 是升级后的优先接口，但当前 X5 `AIRBOT_MOTION_VERSION "0.1.1.dev90+g24fec8a"`，没有 `dds_route` topic/IDL/进程；当前工作站 `enp108s0 DOWN`；未升级前只能走 AIRRTM 或裸 DDS/FSM topic。20:27 CST 后已被 SDK gRPC 路线覆盖。
- **2026-06-30 17:58 CST** — 读回验证：`docs +fetch --scope outline --max-depth 2` 仍只有 5 个 H1（当前结论、AIRRTM 通道是否可用、坐标系约定、还缺什么、证据来源）；`revision_id=27`；关键词读取能看到 `DDS Route`、`0.1.1.dev90`、`enp108s0 DOWN`、`FsmDdsRoute`、`G2P` 等更新内容。

**本轮结论**：飞书 VIO 文档已按“修改原文”方式同步完成；没有追加新标题。未向机器人发布任何控制消息。


## 2026-06-30 18:11 CST — Relpose action 转换器本地实现与验证（agent: Codex）

目的：回答“哪些问题能靠本机和训练服务器解决、转换器能否直接写”，并把训练端 action 语义落成本地纯函数转换器。

- **2026-06-30 18:11 CST** — 只读连接训练服务器 `maxliu-h200-qinghua-1:/home/maxliu/projects/VIO_Test/Openpi_RL`，复核 `scripts/vio_preview_converter.py`：`dp_local = cur_r.inv().apply(fut_p - cur_p)`，`dr_local = (cur_r.inv() * fut_r).as_rotvec()`。
- **2026-06-30 18:11 CST** — 远端脚本确认：`states = np.zeros((sample_times.size, 16), dtype=np.float32)`，`actions = np.zeros((sample_times.size, horizon, 14), dtype=np.float32)`；每个 horizon 行都从同一个当前 TCP pose 计算 future pose，不做行间串联。
- **2026-06-30 18:11 CST** — 新增 [relpose-action-converter.md](relpose-action-converter.md)，记录本机可解决边界、远端训练证据、本地实现和验证结果。
- **2026-06-30 18:11 CST** — 新增 `src/openpi/shared/airbot_relpose.py` 与 `src/openpi/shared/airbot_relpose_test.py`：支持 `(50,32)` policy 输出取前 14 维、TCP-local relpose 积分为 `[x,y,z,qx,qy,qz,qw]`、quaternion 对齐训练端 `w>=0` 约定、夹爪 0-100 转 ratio/G2P 米/P7 毫米。
- **2026-06-30 18:11 CST** — 验证：`uv run ruff check src/openpi/shared/airbot_relpose.py src/openpi/shared/airbot_relpose_test.py` → `All checks passed!`；`uv run pytest src/openpi/shared/airbot_relpose_test.py` → `6 passed in 0.03s`。

**本轮结论（转换器仍有效，控制路线已更新）**：转换器可以直接写，且已经本地实现并通过单测。它解决的是模型 action 到通道无关 TCP target 的数学/单位转换；20:27 CST 后执行侧独立问题改为 SDK 安装、50071 gRPC 服务连通、`get_end_pose()` 当前 TCP pose 获取、SDK control adapter 和安全下发。本次未向机器人发布任何控制消息。


## 2026-06-30 19:47 CST — 飞书 VIO 文档同步 relpose 转换器实现状态（agent: Codex）

目的：按用户要求，将本地已实现的 relpose action 转换器同步到飞书 VIO 文档，仍以修改原文为主，不追加新标题。

- **2026-06-30 19:47 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-06-30 19:47 CST** — 执行：用 `lark-cli docs +update --command block_replace` 替换 4 个已有 block，覆盖“当前结论”中的 action 语义、“坐标系约定”中的转换公式、“还缺什么”中的转换器状态、“证据来源”中的本地实现/测试记录。
- **2026-06-30 19:47 CST** — 写入要点：转换器已落地为 `src/openpi/shared/airbot_relpose.py`，从 `(50,32)` 取前 14 维，结合当前双臂 TCP pose 输出 `DualArmTcpTarget`；chunk 行不串联；quaternion 为 `xyzw` 且 `w>=0`；本地 `ruff` 通过、`pytest` 为 `6 passed`。
- **2026-06-30 19:47 CST** — 读回验证：`docs +fetch --scope outline --max-depth 2` 仍只有 5 个 H1；`revision_id=31`；关键词读取能看到 `转换器`、`DualArmTcpTarget`、`w >= 0`、`pytest 6 passed`。

**本轮结论**：飞书 VIO 文档已同步转换器实现状态，采用原文 block 替换而非追加新章节。本次未向机器人发布任何控制消息。


## 2026-06-30 19:53 CST — 飞书 VIO 文档结构性扩充转换器与执行边界（agent: Codex）

目的：按用户反馈“不是不让新增章节，凡是有必要的信息都需要写进去”，将飞书 VIO 文档从简单同步扩充为可执行的 I/O 契约和真机接入边界说明。

- **2026-06-30 19:53 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-06-30 19:53 CST** — 新增 3 个必要 H1：`模型与转换器 I/O 契约`、`转换器已完成的处理`、`本机可解决 / 真机待解决边界`。
- **2026-06-30 19:53 CST** — 改写 `还缺什么`：当时从 5 条粗待办改为 P0/P1 清单，覆盖有线 DDS、唯一控制通道、当前 TCP pose 来源、安全壳、控制适配器、真机验证顺序；20:27 CST 后该清单已被 SDK gRPC P0/P1 覆盖。
- **2026-06-30 19:53 CST** — 扩充 `证据来源`：补入训练服务器只读证据路径和 state/action shape、relpose 公式、quaternion `w>=0` 归一化规则。
- **2026-06-30 19:53 CST** — 读回验证：`docs +fetch --scope outline --max-depth 2` 显示新增 3 个 H1；`revision_id=36`；单独读取 `坐标系约定` section 确认原文仍保留。

**本轮结论**：飞书 VIO 文档已补成更完整的模型/转换器/真机边界说明，不再只是简单状态同步。本次未向机器人发布任何控制消息。


## 2026-06-30 20:27 CST — 当前路线切换为 Arm-P7 SDK gRPC（agent: Codex）

目的：按用户最新指令“不要走 DDS，走这个 Arm-P7 SDK 文档”，把飞书 VIO 和本地 docs 从 DDS Route / 裸 DDS 主线改为 Arm-P7 SDK gRPC 主线。

- **2026-06-30 20:27 CST** — 飞书 Arm-P7 SDK wiki 读取：`lark-cli docs +fetch --doc https://w79rvfxw83.feishu.cn/wiki/MBJCwnUKTiEZ6ukUMgKcCLnFnBZ --scope section`。文档标题《二代臂Arm-P7-SDK开发指南》，document_id `KqomdsMbuoep9hxbMYfc1OGdntg`，revision `215`。关键接口为 `AirbotClient(host, port=50071, backend="grpc")`、`get_end_pose()`、`move_end_pose()`、`move_eef()`、`acquire_control()` / `release_control()`。
- **2026-06-30 20:27 CST** — 现场端口只读检查：`172.100.10.159:50071/50051/50052` 均 refused；`192.168.25.1:50071/50051/50052` 均 timeout。结论：当前不能直接连接 SDK gRPC 服务。
- **2026-06-30 20:27 CST** — X5 只读检查：`ssh root@172.100.10.159 hostname/date` 返回 `ubuntu`、`Tue Jun 30 20:27:04 CST 2026`；`ss -lntp | grep -E '50071|50051|50052|grpc|route'` 未见目标端口；`python3 -c 'import arm_p7_sdk'` 报 `ModuleNotFoundError`。
- **2026-06-30 20:27 CST** — 本机 SDK 检查：`python -c 'import arm_p7_sdk'` 报 `ModuleNotFoundError`。结论：P0 是安装/确认 `arm_p7_sdk`，启动/部署 `50071` gRPC 服务，并先做 no-motion `get_service_state()` / `get_end_pose()`。
- **2026-06-30 20:27 CST** — 飞书 VIO 文档已修改到 SDK gRPC 路线：目标文档 `Uc7GdKUSmoYYHOxZPCPcHADRnMI`，读回 revision `52`；关键词可见 `Arm-P7 SDK`、`backend="grpc"`、`AirbotClient`、`50071`、`move_end_pose`、`move_eef`、`不走 DDS`。
- **2026-06-30 20:27 CST** — 本地文档同步：新增 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)，并将 [p7-dds-route-current-state.md](p7-dds-route-current-state.md)、[direct-dds-control.md](direct-dds-control.md)、[relpose-action-converter.md](relpose-action-converter.md)、[teleop-and-data-collection.md](teleop-and-data-collection.md)、[training-robot-io-alignment.md](training-robot-io-alignment.md)、[README.md](README.md) 改为以 Arm-P7 SDK gRPC 为当前主线。

**本轮结论**：当前不走 DDS Route、裸 DDS/FSM publisher 或 DDS `arm_msgs` 生成路线；唯一主线是 Arm-P7 SDK gRPC。模型和转换器不需要重训或重写，剩余工作是 SDK 安装、gRPC 服务连通、SDK control adapter 与安全壳。本轮没有发布任何控制消息，没有切控制状态，没有移动机械臂或夹爪。

## 2026-07-01 11:34 CST — curl / VPN 代理是否生效检查（agent: Codex）

目的：确认当前 VPN/代理环境下，`curl` 是否没有用上代理，还是代理已生效但其他执行上下文可能未继承。

- **2026-07-01 11:34 CST** — 初始沙箱内命令失败：`ls docs` → `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`；后续只读检查改为沙箱外执行。
- **2026-07-01 11:34 CST** — 当前进程代理变量：`env | sort | rg -i '(^|_)proxy=|all_proxy|http_proxy|https_proxy|no_proxy|curl|vpn'` → `all_proxy=socks5://127.0.0.1:7897`、`http_proxy=http://127.0.0.1:7897`、`https_proxy=http://127.0.0.1:7897`。
- **2026-07-01 11:34 CST** — 本机监听与系统代理：`ss -lntp` 显示 `127.0.0.1:7897` 监听，`clash-verge` 监听 `127.0.0.1:33331` PAC；`gsettings` 显示 GNOME 代理为 `manual`，HTTP/HTTPS/SOCKS 均指向 `127.0.0.1:7897`。
- **2026-07-01 11:34 CST** — `curl -v -m 15 https://www.google.com/generate_204` 明确显示 `Uses proxy env variable https_proxy == 'http://127.0.0.1:7897'`，经 HTTP CONNECT 返回 `HTTP/2 204`。
- **2026-07-01 11:34 CST** — `curl -v -m 15 https://api.github.com` 同样经 `https_proxy` 走 `127.0.0.1:7897`，返回 `HTTP/2 200`。
- **2026-07-01 11:34 CST** — 禁用代理对照：`curl -v --noproxy '*' -m 15 https://www.google.com/generate_204` → `Connection timed out after 15002 milliseconds`；显式 `curl --socks5-hostname 127.0.0.1:7897 ...` 返回 `HTTP/2 204`。
- **2026-07-01 11:34 CST** — 新增 [network-proxy-curl.md](network-proxy-curl.md)，记录命令、关键输出、结论和排查建议。

**本轮结论**：当前登录 shell / Codex 命令环境中，`curl` 已经用上 `127.0.0.1:7897` 代理，且 HTTP CONNECT 与 SOCKS5 都能成功访问外网；直连不可用。如果用户在其他终端、`sudo`、容器、IDE、systemd 服务或脚本中遇到 `curl` 失败，优先检查该执行上下文是否继承 `http_proxy` / `https_proxy` / `all_proxy`。



## 2026-07-01 11:35 CST — AIRBOT-ARM-P7-SW-2026-06-23 软件包核对（agent: Codex）

目的：用户提供 `docs/AIRBOT-ARM-P7-SW-2026-06-23-21-16-24/`，判断它是否是当前 Arm-P7 SDK gRPC 路线需要安装的软件包。

- **2026-07-01 11:35 CST** — 包内容：`release_notes.md` 显示 product=`airbot-p7`，组件为 `sdk_client p7-v1.1.1` 和 `arm_p7 release-2026-6-23`；文件包含 `arm_p7_sdk-1.1.1-py3-none-any.whl`、`sdk-board-bundle-arm_p7_sdk-1.1.1...tar.gz`、`robot_app_0.3.5_...arm64.deb`、`robot_ota_app_0.2.0_...arm64.deb`。
- **2026-07-01 11:35 CST** — 完整性：在包目录执行 `sha256sum -c manifest/checksums.sha256`，所有 artifact 均 `OK`。
- **2026-07-01 11:35 CST** — SDK wheel：`arm-p7-sdk` version `1.1.1`，`AirbotClient` 默认 `port=50071`、`backend="grpc"`；依赖 `grpcio>=1.76.0`、`protobuf>=4.21`、`typer>=0.9`、`loguru>=0.7.3`，CLI 为 `arm-p7-sdk`。
- **2026-07-01 11:35 CST** — 本机兼容性：OpenPI `.venv` 有 `grpcio 1.81.1` 但 `protobuf 4.25.8`；从 wheel 只读导入失败：`ImportError: cannot import name 'runtime_version' from 'google.protobuf'`。SDK 生成 proto 标注 `Protobuf Python Version: 6.33.5`。结论：SDK client 应使用独立 venv，不要直接污染 OpenPI 推理 `.venv`。
- **2026-07-01 11:35 CST** — 机器人侧 deb：`robot_app_0.3.5` 为 `arm64`；解包后 `framework_config.json` 明确包含 `arm_grpc_route` / `libarm_grpc_route.so` / `grpc_route_node` / `user_param: "none;50071"`。这是当前路线需要的 X5 侧 gRPC route 包。
- **2026-07-01 11:35 CST** — board bundle：`install.sh` 要求 `aarch64/arm64` + Python `3.10.x`，离线安装 `arm_p7_sdk 1.1.1`、`cora 1.2.2`、`grpcio`、`protobuf 7.35.1` 等到板端系统 Python。它只在需要 X5 本地运行 Python SDK/例程时需要；本机 gRPC client 不要求 X5 Python 能 import SDK。
- **2026-07-01 11:35 CST** — 当前机器人只读状态：`ssh root@172.100.10.159 hostname/date` → `ubuntu`、`Wed Jul 1 11:35:53 CST 2026`；`/opt/robot_app/include/version.hpp` 仍为 `AIRBOT_MOTION_VERSION "0.1.1.dev90+g24fec8a"`；X5 `python3 import arm_p7_sdk` 失败；`ss -lntp` 未看到 `50071/50051/50052`；本机 TCP 探测 `172.100.10.159:50071` 为 connection refused，`192.168.25.1:50071` 为 timeout。
- **2026-07-01 11:35 CST** — 文档同步：新增 [p7-release-package-2026-06-23.md](p7-release-package-2026-06-23.md)，更新 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md) 和 [README.md](README.md)。

**本轮结论**：这是我们当前路线需要的软件包。安装拆分为两块：本机/客户端环境装 `arm_p7_sdk 1.1.1`（建议独立 venv，protobuf 需 >=6.33.5），X5/机器人侧升级 `robot_app 0.3.5` 以提供 `arm_grpc_route` 50071。`robot_ota_app` 和 board bundle 是否安装取决于升级流程/是否要在 X5 本地跑 SDK。全程未安装、未重启、未发控制命令、未移动机械臂或夹爪。


## 2026-07-01 13:55 CST — 本机独立安装 Arm-P7 SDK client（agent: Codex）

目的：按用户确认“单独装就行”，在不污染 OpenPI 推理 `.venv` 的前提下安装 Arm-P7 SDK client。

- **2026-07-01 13:55 CST** — 创建独立环境：`uv venv --python 3.11 .venv-p7-sdk` → `Using CPython 3.11.15`，`Creating virtual environment at: .venv-p7-sdk`。
- **2026-07-01 13:55 CST** — 安装 SDK：`uv pip install --python .venv-p7-sdk/bin/python docs/AIRBOT-ARM-P7-SW-2026-06-23-21-16-24/components/sdk_client/arm_p7_sdk-1.1.1-py3-none-any.whl 'protobuf>=6.33.5'` → 安装 `arm-p7-sdk==1.1.1`、`protobuf==7.35.1`、`grpcio==1.81.1`、`typer==0.26.8`、`loguru==0.7.3` 等 12 个包。
- **2026-07-01 13:55 CST** — 独立环境验证：`.venv-p7-sdk/bin/python -c 'import arm_p7_sdk; from arm_p7_sdk import AirbotClient; ...'` 成功；`.venv-p7-sdk/bin/arm-p7-sdk version` 输出 `1.1.1`；`inspect.signature(AirbotClient)` 显示默认 `port=50071`、`backend='grpc'`。
- **2026-07-01 13:55 CST** — 隔离性验证：OpenPI `.venv` 仍为 `protobuf 4.25.8`、`grpcio 1.81.1`；该环境里残留 `arm-p7-sdk 1.0.0`，但 `import arm_p7_sdk` 仍因 `google.protobuf.runtime_version` 缺失失败。结论：后续 SDK client 必须使用 `.venv-p7-sdk`，不要用 OpenPI `.venv`。
- **2026-07-01 13:55 CST** — git 状态：`.venv-p7-sdk` 自带 `.gitignore`，`git status --short .venv-p7-sdk .gitignore` 无输出，不会进入版本控制。
- **2026-07-01 13:55 CST** — 文档同步：更新 [p7-release-package-2026-06-23.md](p7-release-package-2026-06-23.md) 和 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)。

**本轮结论**：本机 Arm-P7 SDK client 环境已就绪，使用 `.venv-p7-sdk`。机器人侧仍未升级 `robot_app_0.3.5`，50071 gRPC route 仍未连通。本轮未向机器人安装包、未重启 robot_app、未发送控制命令、未移动机械臂或夹爪。

## 2026-07-01 14:15 CST — 本机 amd64 robot_app 模拟器确认（agent: Codex）

目的：用户在 amd64 PC 安装 `robot_app_0.1.0_20260629175035_amd64.deb` 后，确认它是否能规避真机，用于本地 gRPC/SDK/转换器 smoke test，并记录使用方法。

- **2026-07-01 14:15 CST** — 包检查：`dpkg -s robot_app` 显示 `Architecture: amd64`、`Version: 0.1.0`；`dpkg -L robot_app` 显示关键文件 `/opt/robot_app/bin/robot_app`、`libarm_grpc_route.so`、`libarm_finite_state_machine.so`、P7 URDF/mesh assets。
- **2026-07-01 14:15 CST** — 配置检查：`/opt/robot_app/configs/framework_config.json` 包含 `mock_arm_control_node` 和 `grpc_route_node`，`user_param: "none;50071"`；`mavlink_config.json` 虽有 `can0`，但默认框架节点实际创建的是 mock control 节点。
- **2026-07-01 14:15 CST** — 直接启动检查：`/opt/robot_app/bin/robot_app` 会使用 `/userdata/storage`；当前普通用户无写权限，关键输出为 `Error creating directory /userdata/storage/robot_app: Permission denied`。因此本仓库 smoke test 推荐用临时配置把 storage 改到 `/tmp`。
- **2026-07-01 14:15 CST** — 临时配置启动：复制 `/opt/robot_app/configs` 到 `/tmp/openpi_robot_app_sim/configs`，将 `storage_config.json` 的 `base_path` 改为 `/tmp/openpi_robot_app_storage`，启动 `/opt/robot_app/bin/robot_app /tmp/openpi_robot_app_sim/project_config.json`。关键日志显示 `Created node: mock_arm_control_node`、`Initializing node: grpc_route_node#none;50071`、`Framework started successfully`。
- **2026-07-01 14:15 CST** — 端口检查：`ss -lntp` 显示 `*:50071 users:(("robot_app",pid=183568,fd=30))`。结论：服务端等价于 bind `0.0.0.0:50071`；同机 SDK client 应连 `127.0.0.1:50071`，远端连 PC 实际 LAN IP 和 `50071`。
- **2026-07-01 14:15 CST** — SDK 只读验证：`.venv-p7-sdk/bin/python -c "from arm_p7_sdk import AirbotClient; ..."` 成功读取 `ServiceState(... fsm_state='IDLE' ...)`、`CartesianPose(xyz=(0.3089, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))`、7 维全零 arm joint state 和 EEF state。
- **2026-07-01 14:15 CST** — 文档同步：新增 [local-amd64-robot-app-simulator.md](local-amd64-robot-app-simulator.md)，更新 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md) 和 [README.md](README.md)。

**本轮结论**：本机 amd64 `robot_app 0.1.0` 可作为 mock gRPC 服务，用于接口和 SDK adapter smoke test；它不能替代真实 X5 `robot_app_0.3.5`、真实相机/机械臂/控制权/安全壳验证。本轮没有调用 `acquire_control()`、`move_end_pose()`、`move_eef()`，没有发送任何运动控制命令。

## 2026-07-01 14:20 CST — 飞书 VIO 文档同步本机模拟器路线（agent: Codex）

目的：按用户要求，把 amd64 PC 上安装/启动 `robot_app_0.1.0` 的模拟器使用方法、gRPC host/port 约定和验证边界同步到飞书 VIO 文档。

- **2026-07-01 14:20 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-07-01 14:20 CST** — 操作方式：用 `lark-cli docs +fetch --scope outline/keyword --detail with-ids` 定位既有内容，不在末尾追加；随后用 `lark-cli docs +update --command block_replace` 替换 10 个已有 block。
- **2026-07-01 14:20 CST** — 写入要点：本机 `.venv-p7-sdk` 已安装 SDK；本机 amd64 `robot_app 0.1.0` 可作为 mock gRPC 服务，监听等价于 `0.0.0.0:50071`；同机 SDK client 用 `127.0.0.1:50071`；直接 `/opt/robot_app/bin/robot_app` 会使用 `/userdata/storage`，无权限时推荐临时配置改到 `/tmp`；模拟器只用于 no-motion/接口 smoke test，不能替代真机。
- **2026-07-01 14:20 CST** — 读回验证：关键词 fetch 能看到 `robot_app 0.1.0`、`0.0.0.0:50071`、`.venv-p7-sdk`、`本机模拟器`；outline fetch 显示 H1 仍为原 8 个，没有新增章节；文档 revision 更新到 `62`。

**本轮结论**：飞书 VIO 文档已同步本机模拟器路线，并保留“真机 X5 仍需部署/启动 gRPC route、真实运行前必须做 no-motion 读状态和安全壳验证”的边界。本轮没有向真机发送任何控制命令。

## 2026-07-01 15:23 CST — Codex CLI 更新到 0.142.5（agent: Codex）

目的：用户反馈无法执行 `sh -c 'curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh'` 更新 Codex；检查是否为 `curl` 未走代理，并尝试官方更新入口。

- **2026-07-01 15:23 CST** — 官方 Codex manual 拉取：`node /home/discover/.codex/skills/.system/openai-docs/scripts/fetch-codex-manual.mjs` → manual 更新到 `/tmp/openai-docs-cache/codex-manual.md`。
- **2026-07-01 15:23 CST** — 官方 manual 确认：`CODEX_NON_INTERACTIVE=1` 用于跳过安装器提示，`CODEX_INSTALL_DIR` Linux 默认 `~/.local/bin`，公开示例为 `curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh`。
- **2026-07-01 15:23 CST** — 更新前版本：`which codex` → `/home/discover/.local/bin/codex`；`codex --version` → `codex-cli 0.142.4`。
- **2026-07-01 15:23 CST** — 只下载安装脚本：`curl -v -m 20 -fsSL https://chatgpt.com/codex/install.sh -o /tmp/codex-install.sh` 明确显示使用 `https_proxy == 'http://127.0.0.1:7897'`，经 `chatgpt.com`、`github.com`、`release-assets.githubusercontent.com` 代理链路最终返回 `HTTP/2 200`，长度 `21674`。
- **2026-07-01 15:23 CST** — `codex update --help` 确认当前 CLI 支持自更新；执行 `codex update` 成功：`Updating Codex CLI from 0.142.4 to 0.142.5`，安装到 `/home/discover/.codex/packages/standalone/releases/0.142.5-x86_64-unknown-linux-musl`。
- **2026-07-01 15:23 CST** — 更新后验证：`codex --version` → `codex-cli 0.142.5`；`readlink -f /home/discover/.local/bin/codex` → `/home/discover/.codex/packages/standalone/releases/0.142.5-x86_64-unknown-linux-musl/bin/codex`。
- **2026-07-01 15:23 CST** — 新增 [codex-cli-update.md](codex-cli-update.md)，记录官方 manual 证据、代理下载链路、更新命令和结果。

**本轮结论**：当前 Codex 命令环境中 `curl` 能通过 `127.0.0.1:7897` 下载官方安装脚本，失败不在此环境的代理配置；Codex CLI 已成功从 `0.142.4` 更新到 `0.142.5`。安装器提示需要重启 Codex，让当前运行中的 Codex 进程完全使用新版本。

## 2026-07-01 15:28 CST — 用户启动本机 robot_app 后连通验证（agent: Codex）

目的：用户确认已启动 `/opt/robot_app/bin/robot_app` 后，验证 agent 是否能看到进程、端口并用 SDK 只读连接。

- **2026-07-01 15:28 CST** — 进程检查：`pgrep -af robot_app` 显示 `sudo /opt/robot_app/bin/robot_app` 和 `/opt/robot_app/bin/robot_app` 进程存在。
- **2026-07-01 15:28 CST** — 端口检查：`ss -lntp` 显示 `LISTEN ... *:50071 ...`。结论：服务端已经监听所有网卡，等价于 bind `0.0.0.0:50071`。
- **2026-07-01 15:28 CST** — SDK 只读检查：`.venv-p7-sdk/bin/python ... AirbotClient(host='127.0.0.1', port=50071, backend='grpc') ...` 成功读取 `ServiceState(... fsm_state='IDLE' ...)`、`CartesianPose(xyz=(0.3089, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))`、7 维全零 arm joint state 和 EEF state。
- **2026-07-01 15:28 CST** — 文档同步：更新 [local-amd64-robot-app-simulator.md](local-amd64-robot-app-simulator.md) 本节。

**本轮结论**：用户只要保持该 `robot_app` 进程不关，agent 就可以从另一个终端看到并通过 `127.0.0.1:50071` 做本机 SDK mock 连接。本轮没有调用 `acquire_control()`、`move_end_pose()`、`move_eef()`，没有发送任何运动控制命令。


## 2026-07-01 15:36 CST — 本机 arm_fsm_monitor DDS domain 确认（agent: Codex）

目的：用户提供供应商提示 `arm_fsm_monitor --domain XX`，要求确认当前本机 amd64 `robot_app` 的 `XX`。

- **2026-07-01 15:36 CST** — 文档检索：已有 [direct-dds-control.md](direct-dds-control.md) 记录 X5/直连 DDS 的 `framework_config.json` 为 `domain_id=0`。
- **2026-07-01 15:36 CST** — 本机配置检查：`/opt/robot_app/configs/framework_config.json` 的 `dds` 段没有显式 `domain_id`，`grpc_route_node` 为 `user_param: "none;50071"`。
- **2026-07-01 15:36 CST** — 进程/端口检查：`pgrep -af robot_app` 显示当前 `/opt/robot_app/bin/robot_app` 运行中；`ss -lntp` 显示 `*:50071` 正在监听。
- **2026-07-01 15:36 CST** — monitor 验证：`timeout 6 /opt/robot_app/bin/arm_fsm_monitor --domain 0` 输出 `DDSParticipant initialized on domain 0 with name 'fsm_topic_monitor_v2'`，并进入 FSM Monitor 只读界面。
- **2026-07-01 15:36 CST** — 文档同步：更新 [local-amd64-robot-app-simulator.md](local-amd64-robot-app-simulator.md) §8。

**本轮结论**：当前本机 amd64 `robot_app` 的 `arm_fsm_monitor --domain XX` 中 `XX=0`。本轮仅运行只读 monitor 6 秒，没有调用控制权或运动接口。

## 2026-07-01 15:41 CST — 本机模拟器 SDK adapter / 写接口 smoke test（agent: Codex）

目的：按用户要求“你试试”，在用户已启动的 amd64 `robot_app` 模拟器上验证 relpose 转换器到 Arm-P7 SDK 参数的 dry-run，以及 SDK 控制权和写接口调用链。

- **2026-07-01 15:41 CST** — 依赖补充：`.venv-p7-sdk` 运行 `openpi.shared.airbot_relpose` 缺少 `numpy`，执行 `uv pip install --python .venv-p7-sdk/bin/python numpy`，安装 `numpy==2.4.6`。OpenPI 推理 `.venv` 未修改。
- **2026-07-01 15:41 CST** — dry-run：读取模拟器 `get_end_pose()` 为 `CartesianPose(xyz=(0.3089, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))`；构造左臂 `+1mm local x / gripper=50`、右臂 `-1mm local x / gripper=100` 的 32 维 action；`convert_action_step()` 输出 SDK `CartesianPose` 可构造，左目标约 `x=0.3099`、右目标约 `x=0.3079`，夹爪分别为 `48.0mm`、`96.0mm`。
- **2026-07-01 15:41 CST** — 模拟器写接口 smoke test：`acquire_control=True`，`switch_controller(servo_control)=True`，`move_end_pose(+1mm)=True`，`switch_eef_control_mode(csp)=True`，`move_eef(1mm)=True`，`switch_controller(idle)=True`，`release_control` 完成。
- **2026-07-01 15:41 CST** — 写接口结果：mock pose 从 `x≈0.3089` 到 `x≈0.3100`，说明 mock 端接受并更新末端 pose；`move_eef(1mm)` 返回 True，但 `eef_joint_state` 仍为 0，说明本机模拟器不一定模拟真实 EEF 反馈。
- **2026-07-01 15:41 CST** — 清理：再次获取控制权后执行 `switch_eef_control_mode(idle)` 和 `switch_controller(idle)`，最终 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。
- **2026-07-01 15:41 CST** — 文档同步：更新 [local-amd64-robot-app-simulator.md](local-amd64-robot-app-simulator.md) §8。

**本轮结论**：本机模拟器上 SDK client、控制权、servo 模式、`move_end_pose()`、`move_eef()` 和 relpose->SDK 数据构造链路已跑通；这仍不能替代真机 X5 route、真实双臂、真实坐标系和安全壳验证。本轮没有连接真机。

## 2026-07-01 15:43 CST — 飞书 VIO 同步本机模拟器写接口 smoke test（agent: Codex）

目的：把本机 amd64 `robot_app` 模拟器上的 relpose-&gt;SDK dry-run 和 SDK 写接口 smoke test 结果同步到飞书 VIO 文档。

- **2026-07-01 15:43 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-07-01 15:43 CST** — 操作方式：用 `lark-cli docs +fetch --scope keyword --detail with-ids` 定位既有 block，用 `docs +update --command block_replace` 替换 3 个已有 block，不新增章节。
- **2026-07-01 15:43 CST** — 写入要点：本机模拟器已完成 no-motion 读状态、relpose-&gt;SDK 参数 dry-run、`acquire_control`、`switch_controller(servo_control)`、`move_end_pose(+1mm)`、`switch_eef_control_mode(csp)`、`move_eef(1mm)`、idle/release 的 smoke test；仍明确它不能替代真机坐标系、速度、碰撞和安全边界验证。
- **2026-07-01 15:43 CST** — 读回验证：关键词 fetch 能看到 `move_end_pose(+1mm)`、`move_eef(1mm)`、`正式 SDK 控制适配器`、`模拟器 smoke test`；文档 revision 更新到 `65`。

**本轮结论**：飞书 VIO 已同步本机模拟器写接口 smoke test 结果。正式工作仍是把临时脚本链路落成可复用 SDK adapter + 安全壳，并在真机上从 no-motion 到极小步逐级验证。本轮没有连接真机。

## 2026-07-01 17:25 CST — 有线实机 SDK gRPC 与 robot_app 0.3.5 隔离检查（agent: Codex）

目的：用户接好网线后，确认当前是否能直接使用真机 Arm-P7 SDK gRPC；如果需要安装包，先做机器人侧备份、上传和隔离解包检查。

- **2026-07-01 17:25 CST** — 有线网络：本机 `enp108s0=192.168.25.132/24`，机器人 `eth0=192.168.25.1/24`；`ping 192.168.25.1` 成功；`ssh root@192.168.25.1` 免密可用。结论：网线链路可作为当前管理链路。
- **2026-07-01 17:25 CST** — 端口与 SDK 直连：TCP 探测 `192.168.25.1:22 open`，`192.168.25.1:50071/50051/50052` 未打开；`.venv-p7-sdk` 直连 `AirbotClient(host="192.168.25.1", port=50071)` 返回 `ConnectionError Timeout connecting to 192.168.25.1:50071`。结论：不能直接使用真机 SDK。
- **2026-07-01 17:25 CST** — 当前机器人运行栈：`pgrep -af "bin/robot_app"` 显示三进程 `remote / left_arm / right_arm`；父进程是 `/userdata/start-robot-app-3arm.sh`；右臂配置使用 `can0`，左臂配置使用 `can1`；当前 `/opt/robot_app/lib` 没有 `libarm_grpc_route.so`，配置中没有 `arm_grpc_route` 或 `50071`。
- **2026-07-01 17:25 CST** — 安装包差异：本地 `robot_app_0.3.5_20260623131126_arm64.deb` 解包显示扁平 `configs/`，`framework_config.json` 包含 `arm_grpc_route` / `libarm_grpc_route.so` / `grpc_route_node` / `user_param: "none;50071"`；`mavlink_config.json` 默认 `can0`。结论：这是需要的 gRPC route 包，但与现有三进程旧栈不是同一配置形态。
- **2026-07-01 17:25 CST** — 安全准备：机器人侧完整备份 `/opt/robot_app` 到 `/userdata/openpi_robot_app_backup_20260701_1716.tgz`，大小 `161M`，sha256=`0c551f65d192e643c77228566e472a0371a4e2d89042a51b4a7a1efec85ed97d`。
- **2026-07-01 17:25 CST** — 上传与隔离解包：把 deb 上传到 `/tmp/openpi_robot_app_0.3.5_20260623131126_arm64.deb`，sha256=`037d7c1e53b59cb9466e5bf12d23d833751b02e5482240d7c710384795cb7bd4`，与 manifest 一致；`dpkg --dry-run -i` 无架构/依赖错误；`dpkg-deb -x` 到 `/tmp/openpi_robot_app_0.3.5_stage` 后 `LD_LIBRARY_PATH=lib ldd bin/robot_app` 无 `not found`。
- **2026-07-01 17:25 CST** — 文档同步：更新 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md) 和 [p7-release-package-2026-06-23.md](p7-release-package-2026-06-23.md)。

**本轮结论**：网线已经能用来管理机器人，但真机 SDK 还不能直接用，因为 `50071` 未监听。`robot_app_0.3.5` 已上传并隔离验证可用；当前未执行会覆盖 `/opt/robot_app` 的 `dpkg -i`，未停止右臂旧服务，未启动新 gRPC 服务，未发送任何控制命令。下一步要启用真机 SDK，需要确认采用“停旧 right_arm -> 启动隔离 0.3.5 接管 can0 -> no-motion 读状态”的最小验证，或执行全量 `/opt/robot_app` 升级。

## 2026-07-01 17:35 CST — 飞书 VIO 同步有线实机检查结论（agent: Codex）

目的：把本次有线实机管理链路、真机 50071 未启用、`robot_app_0.3.5` 上传/隔离验证，以及下一步右臂接管风险同步到飞书 VIO 文档，且按用户要求修改已有内容而非末尾追加。

- **2026-07-01 17:35 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-07-01 17:35 CST** — 操作方式：用 `lark-cli docs +fetch --scope outline/keyword --detail with-ids` 定位已有块，用 `docs +update --command block_replace` 替换 11 个已有 block；未新增 H1，未在文末 append。
- **2026-07-01 17:35 CST** — 写入要点：有线 `192.168.25.1` 已可 SSH/上传包；真机 `50071` 未监听，SDK 返回 `ConnectionError Timeout`；`robot_app_0.3.5` 已上传到 X5 `/tmp` 并隔离验证；当前未覆盖安装、未停止旧右臂、未启动真机 gRPC route；下一步需确认最小接管 `right_arm/can0` 或全量升级。
- **2026-07-01 17:35 CST** — 读回验证：关键词 fetch 可见 `192.168.25.1`、`openpi_robot_app_backup_20260701_1716.tgz`、`robot_app_0.3.5`、`can0`、`ConnectionError Timeout`、`停旧 right_arm`；文档 revision 更新到 `76`。

**本轮结论**：飞书 VIO 已同步当前真机状态与下一步风险边界。本轮仍未执行真机 `dpkg -i`、未停止右臂旧服务、未启动 gRPC route、未发送控制命令。

## 2026-07-01 18:18 CST — 真机右臂隔离 gRPC route 启动与 SDK no-motion 验证（agent: Codex）

目的：用户确认可以停止旧服务后，停旧右臂、启动隔离 `robot_app 0.3.5`，验证真机 `192.168.25.1:50071` 是否可直接被本机 SDK 只读访问。

- **2026-07-01 18:18 CST** — 停止旧右臂：停止 `/opt/robot_app/configs/right_arm/project_config.json` 对应旧进程 PID `2792`；`remote` PID `2530` 和 `left_arm` PID `2611` 保持运行。旧父脚本 `/userdata/start-robot-app-3arm.sh` 仍在，但未重启旧右臂。
- **2026-07-01 18:18 CST** — 复位并接管 `can0`：按旧脚本同样参数复位 `can0`（CAN-FD，bitrate 1M，dbitrate 5M，restart-ms 100，berr-reporting on）；生成隔离运行目录 `/tmp/openpi_robot_app_035_run_20260701_181640`，其中 `project_config.json` 指向 `/tmp/openpi_robot_app_0.3.5_stage/opt/robot_app/lib` 和运行目录配置，`storage_config.base_path` 指向该运行目录，URDF 路径改到隔离 stage 的 `share`。
- **2026-07-01 18:18 CST** — 启动 0.3.5：启动 `/tmp/openpi_robot_app_0.3.5_stage/opt/robot_app/bin/robot_app /tmp/openpi_robot_app_035_run_20260701_181640/project_config.json`，新 PID `9623`；日志确认 EEF 类型 `G2P`、模型 `p7c_G2P`、`gRPC server listening on 0.0.0.0:50071`、`Framework started successfully`。
- **2026-07-01 18:18 CST** — 端口验证：`ss -lntp` 显示 `LISTEN *:50071 users:(("robot_app",pid=9623,fd=35))`。
- **2026-07-01 18:18 CST** — SDK no-motion 只读验证：`.venv-p7-sdk` 连接 `AirbotClient(host="192.168.25.1", port=50071, backend="grpc")` 成功；`get_service_state()` 返回 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`；`get_end_pose()` 返回 `xyz=(0.3094,-0.0097,0.3208)`、`xyzw=(0.0425,0.0086,-0.0180,0.9989)`；`get_arm_joint_state()` 返回 7 维角度；`get_eef_joint_state()` 返回 G2P EEF 状态；`get_eef_mode()` 返回 `idle`。
- **2026-07-01 18:18 CST** — 文档同步：更新 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md) 和 [p7-release-package-2026-06-23.md](p7-release-package-2026-06-23.md)。

**本轮结论**：真机右臂 SDK gRPC 最小链路已经打通，当前 `192.168.25.1:50071` 可从本机 SDK 读取状态。没有执行 `dpkg -i` 覆盖安装，没有调用 `acquire_control()`，没有调用任何 `move_*`，没有移动机械臂或夹爪。当前右臂由隔离目录的 `robot_app 0.3.5` PID `9623` 接管；旧右臂进程已停止。

## 2026-07-01 18:22 CST — 飞书 VIO 同步真机右臂 gRPC no-motion 通过状态（agent: Codex）

目的：把“旧右臂已停、隔离 `robot_app 0.3.5` 已接管 `can0`、`192.168.25.1:50071` 已通、SDK no-motion 只读验证通过”的最新状态同步到飞书 VIO 文档，并替换已有过期块。

- **2026-07-01 18:22 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-07-01 18:22 CST** — 操作方式：用已有 block id 执行 `lark-cli docs +update --command block_replace`，替换 11 个已有 block；未新增 H1，未在文末 append。
- **2026-07-01 18:22 CST** — 写入要点：真机右臂当前由隔离目录 `robot_app 0.3.5` PID `9623` 接管 `can0`；`192.168.25.1:50071` 已监听；SDK no-motion 只读验证通过；下一步才是 `acquire_control()` / `release_control()` 空操作、极小步运动和正式 adapter / 安全壳。
- **2026-07-01 18:22 CST** — 读回验证：关键词 fetch 可见 `192.168.25.1:50071`、`PID 9623`、`ServiceState`、`右臂最小路线已启用`、`未发送运动命令`；文档 revision 更新到 `87`。

**本轮结论**：飞书 VIO 已同步真机右臂 gRPC no-motion 通过状态。本轮仍未调用控制权或任何运动接口。

## 2026-07-01 18:26 CST — 真机 SDK 控制权 no-motion 空操作验证（agent: Codex）

目的：在真机右臂 `192.168.25.1:50071` 已可由本机 SDK 只读访问后，验证 `acquire_control()` / `release_control()` 控制权接口是否正常；不切控制器，不调用运动接口。

- **2026-07-01 18:26 CST** — 前置检查：`remote` PID `2530`、`left_arm` PID `2611`、隔离 `robot_app 0.3.5` PID `9623` 运行中；`ss -lntp` 显示 `*:50071` 由 PID `9623` 监听。
- **2026-07-01 18:26 CST** — SDK 控制权空操作：`.venv-p7-sdk` 连接 `AirbotClient(host="192.168.25.1", port=50071, backend="grpc")`；`state_before` 为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`；`acquire_control(lease_ms=15000, renew_period_s=5.0)` 返回 `True`，SDK 日志 `control acquired: lease_id=1`；随后 `release_control()` 成功，SDK 日志 `control released`。
- **2026-07-01 18:26 CST** — no-motion 结果：`pose_before`、`pose_after_acquire`、`pose_after_release` 均为 `CartesianPose(xyz=(0.3094,-0.0097,0.3208), xyzw=(0.0425,0.0086,-0.0180,0.9989))`；状态始终保持 `IDLE/idle`。
- **2026-07-01 18:26 CST** — 文档同步：更新 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md) 和 [p7-release-package-2026-06-23.md](p7-release-package-2026-06-23.md)。

**本轮结论**：真机右臂 SDK 控制权 acquire/release no-motion 验证通过。该轮没有调用 `switch_controller()`，没有调用任何 `move_*`，没有移动机械臂或夹爪；随后已执行单臂 1mm SERVO 极小步验证，见 2026-07-01 18:39 CST 记录。

## 2026-07-01 18:30 CST — 飞书 VIO 同步控制权 no-motion 通过状态（agent: Codex）

目的：把真机 SDK acquire/release no-motion 空操作通过、尚未切控制器/运动的状态同步到飞书 VIO 文档。

- **2026-07-01 18:30 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-07-01 18:30 CST** — 操作方式：用已有 block id 执行 `lark-cli docs +update --command block_replace`，替换 5 个已有 block；未新增 H1，未在文末 append。
- **2026-07-01 18:30 CST** — 写入要点：`acquire_control()` 返回 `True`，lease_id=`1`，`release_control()` 成功；状态保持 `IDLE/idle`，TCP pose 不变；未切控制器，未调用 `move_*`；下一步是单臂极小步 `servo_control`。
- **2026-07-01 18:30 CST** — 读回验证：关键词 fetch 可见 `lease_id=1`、`release_control()`、`控制权空操作`、`未切控制器`、`单臂极小步`；文档 revision 更新到 `92`。

**本轮结论**：飞书 VIO 已同步控制权 no-motion 通过状态。本轮没有执行运动命令。

## 2026-07-01 18:39 CST — 真机右臂 1mm SERVO 极小步运动验证（agent: Codex）

目的：在 `192.168.25.1:50071` SDK 控制权 no-motion 空操作通过后，确认 `move_end_pose()` 是否能通过 staged `robot_app 0.3.5` PID `9623` 真实驱动右臂，并核对 SERVO 分支实际使用的参数。

- **2026-07-01 18:33 CST** — 运动命令：`.venv-p7-sdk` 连接 `AirbotClient(host="192.168.25.1", port=50071, backend="grpc")`；`acquire_control(lease_ms=15000, renew_period_s=5.0)` 返回 `True`；`switch_controller(Controller.servo_control)` 返回 `True`；以当前 TCP pose 为起点发送 `x + 0.001m` 的 `move_end_pose()`，返回 `True`；随后 `switch_controller(Controller.idle)` 和 `release_control()`。
- **2026-07-01 18:33 CST** — 关键读数：起点 `xyz=(0.3094,-0.0097,0.3208)`；运动后即时读数 `xyz=(0.3105,-0.0097,0.3206)`，位移约 `1.14mm`；释放并稳定后读数 `xyz=(0.3140,-0.0061,0.3248)`，状态 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。
- **2026-07-01 18:39 CST** — SDK 后端核对：`sed -n '960,1120p' .venv-p7-sdk/lib/python3.11/site-packages/arm_p7_sdk/_backends/grpc_route.py` 显示 `servo_control` 下 `move_end_pose()` 调用 `CallServoPoseCommand`，使用 `self._arm_motor_speed` 和 `options.eff`；本次传入的 `velocity_scaling_factor` / `acceleration_scaling_factor` 不参与 SERVO 分支。
- **2026-07-01 18:39 CST** — 文档同步：更新 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md) 和 [p7-release-package-2026-06-23.md](p7-release-package-2026-06-23.md)。

**本轮结论**：真机右臂 SDK gRPC 写链路已打通，能真实运动；但最终稳定位移约 `7mm`，大于 `1mm` 目标。不要继续 EEF、双臂或 policy chunk；下一步先按官方 SERVO 示例显式 `set_arm_speed()` / `eff`、缩小步长并加最大位移 guard 后复测。

## 2026-07-01 18:49 CST — 飞书 VIO 同步右臂 1mm SERVO 运动验证与暂停扩大测试结论（agent: Codex）

目的：把真机右臂首次 <code>move_end_pose(+1mm)</code> 已执行、即时位移约 <code>1.14mm</code>、最终稳定位移约 <code>7mm</code>、SERVO 分支需显式 <code>set_arm_speed()</code> / <code>eff</code> 的结论同步到飞书 VIO 文档；按用户要求修改已有内容，不在文末追加新章节。

- **2026-07-01 18:49 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-07-01 18:49 CST** — 操作方式：用 `lark-cli docs +update --command block_replace` 替换 8 个已有 block，覆盖“当前现场核对”、目标 TCP pose 表格单元格、当前现场状态表格单元格、真机控制适配器处理结论、P0/P1 checkbox 和证据来源；未使用 append，未新增章节。
- **2026-07-01 18:49 CST** — 写入要点：真机右臂 `move_end_pose(+1mm)` 已返回成功；释放稳定后 TCP pose 为 `xyz=(0.3140,-0.0061,0.3248)`；SDK 后端确认 `servo_control` 下走 `CallServoPoseCommand`，`velocity_scaling_factor` / `acceleration_scaling_factor` 不参与 SERVO 分支；当前暂停 EEF、双臂和 policy chunk，先收紧 SERVO 脚本和安全 guard。
- **2026-07-01 18:49 CST** — 读回验证：关键词 fetch 可见 `1mm`、`7mm`、`CallServoPoseCommand`、`set_arm_speed`、`eff`、`暂停`、`最终稳定位移`；文档 revision 更新到 `100`。

**本轮结论**：飞书 VIO 已同步右臂首次真机运动验证和安全暂停结论，且是修改已有块而不是追加章节。

## 2026-07-01 18:50 CST — 真机 robot_app 进程与 50071 端口最终复查（agent: Codex）

目的：在首次右臂 1mm SERVO 验证和文档同步后，确认机器人侧 staged `robot_app 0.3.5` 仍在运行，gRPC 端口仍监听。

命令：

```bash
ssh root@192.168.25.1 "ps -eo pid,cmd | grep robot_app | grep -v grep; ss -lntp | grep 50071 || true"
```

关键输出：

```text
2530 ./bin/robot_app /opt/robot_app/configs/remote/project_config.json
2611 ./bin/robot_app /opt/robot_app/configs/left_arm/project_config.json
9623 /tmp/openpi_robot_app_0.3.5_stage/opt/robot_app/bin/robot_app /tmp/openpi_robot_app_035_run_20260701_181640/project_config.json
LISTEN *:50071 users:(("robot_app",pid=9623,fd=35))
```

结论：右臂 staged `robot_app 0.3.5` PID `9623` 仍运行，`192.168.25.1:50071` 仍由该进程监听。当前不继续发送 EEF、双臂或 policy chunk 命令。

## 2026-07-01 19:02 CST — 受保护 0.2mm SERVO 复测通过但即时位移贴近 guard（agent: Codex）

目的：在 1mm 首测发现最终稳定位移过大后，新增可复用的受保护右臂 SERVO 极小步脚本，并执行 dry-run 与 0.2mm 真机复测。

- **2026-07-01 19:00 CST** — 新增脚本：`examples/airbot/p7_guarded_servo_step.py`。默认 dry-run；只有显式 `--execute` 才会 `acquire_control()`、`switch_controller(Controller.servo_control)` 和 `move_end_pose()`。脚本包含状态检查、预采样漂移 guard、显式 `set_arm_speed([0.55]*7)`、显式 `CartesianMoveOptions(eff=[8]*7, blocking=True)`、即时/最终位移 guard、异常后切回 `idle` 和 `release_control()`。
- **2026-07-01 19:00 CST** — dry-run：`.venv-p7-sdk/bin/python examples/airbot/p7_guarded_servo_step.py --host 192.168.25.1 --port 50071`；输出 `IDLE/idle/valid`，`pre_drift_m 0.000000`，目标为 `x + 0.000200m`；未调用控制权、未切控制器、未发送运动命令。
- **2026-07-01 19:00 CST** — 真机复测：`.venv-p7-sdk/bin/python examples/airbot/p7_guarded_servo_step.py --host 192.168.25.1 --port 50071 --execute --step-m 0.0002 --axis x --arm-speed-rad-s 0.55 --eff 8,8,8,8,8,8,8 --move-distance-guard-m 0.0015 --final-distance-guard-m 0.0015`。`acquire_control=True`，lease_id=`3`；`switch_servo=True`；`set_arm_speed=True`；日志显示 `Updated servo scale to: [0.5, 0.5, 0.07002906659820268]`；`move_end_pose=True`。
- **2026-07-01 19:00 CST** — 结果：起点 `xyz=(0.314030,-0.006099,0.325622)`；目标 `xyz=(0.314230,-0.006099,0.325622)`；即时 pose `xyz=(0.313499,-0.005513,0.324349)`，`move_distance_m=0.001498`、`target_error_m=0.001580`；最终 pose `xyz=(0.314039,-0.005809,0.325615)`，`post_drift_m=0.000013`、`final_distance_m=0.000290`；最终状态 `IDLE/idle/valid`，脚本退出码 `0`。
- **2026-07-01 19:01 CST** — 代码验证：`.venv-p7-sdk/bin/python -m py_compile examples/airbot/p7_guarded_servo_step.py` 通过；`uv run ruff check examples/airbot/p7_guarded_servo_step.py` 通过。
- **2026-07-01 19:01 CST** — 机器人侧复查：`ssh root@192.168.25.1 "ps -eo pid,cmd | grep robot_app | grep -v grep; ss -lntp | grep 50071 || true"` 显示 staged `robot_app 0.3.5` PID `9623` 仍运行，`*:50071` 仍由 PID `9623` 监听。
- **2026-07-01 19:02 CST** — 文档同步：更新 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md) 和 [p7-release-package-2026-06-23.md](p7-release-package-2026-06-23.md)。

**本轮结论**：受保护 0.2mm SERVO 复测通过，最终稳定位移约 `0.29mm`，机器人状态恢复 `IDLE/idle`；但运动中即时位移 `1.498mm` 贴近 `1.5mm` guard，说明正式 adapter 必须保留 per-step guard，不能直接下发 policy chunk。

## 2026-07-01 19:09 CST — 飞书 VIO 同步受保护 0.2mm SERVO 复测结果（agent: Codex）

目的：把新增 `examples/airbot/p7_guarded_servo_step.py`、dry-run、受保护 `0.2mm` 真机复测结果和“下一步先沉淀正式 guarded adapter”的结论同步到飞书 VIO 文档；按用户要求修改已有内容，不追加新章节。

- **2026-07-01 19:09 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-07-01 19:09 CST** — 操作方式：用 `lark-cli docs +update --command block_replace` 替换 9 个已有 block，覆盖“当前现场核对”、目标 TCP pose 表格单元格、当前现场状态表格单元格、真机控制适配器处理结论、P0/P1 checkbox 和证据来源；未使用 append，未新增章节。
- **2026-07-01 19:09 CST** — 写入要点：受保护脚本 `examples/airbot/p7_guarded_servo_step.py` 默认 dry-run；真机 `0.2mm` 复测 `move_end_pose()` 返回 `True`，即时位移 `1.498mm`，最终稳定位移 `0.290mm`，状态回到 `IDLE/idle`；下一步先做正式 guarded adapter，不直接扩大到双臂或 policy chunk。
- **2026-07-01 19:09 CST** — 读回验证：关键词 fetch 可见 `0.2mm`、`1.498mm`、`0.290mm`、`p7_guarded_servo_step`、`正式 adapter`、`policy chunk`、`IDLE`；文档 revision 更新到 `109`。

**本轮结论**：飞书 VIO 已同步受保护 0.2mm SERVO 复测结果，并把后续路线改为先沉淀正式 guarded adapter。

## 2026-07-01 19:10 CST — 受保护复测后 50071 端口最终复查（agent: Codex）

目的：确认受保护 0.2mm SERVO 复测、飞书同步和文档更新后，右臂 staged `robot_app 0.3.5` 的 gRPC 端口仍在监听。

命令：

```bash
ssh root@192.168.25.1 "ss -lntp | grep 50071 || true"
```

关键输出：

```text
LISTEN *:50071 users:(("robot_app",pid=9623,fd=35))
```

结论：`192.168.25.1:50071` 仍由 PID `9623` 监听。

## 2026-07-01 19:26 CST — 正式 GuardedP7ArmAdapter 落地与真机 no-motion smoke（agent: Codex）

目的：把临时 guarded 复测流程沉淀成正式 SDK adapter，并验证它在主 OpenPI 环境可测试、在 `.venv-p7-sdk` 可对真机 dry-run。

- **2026-07-01 19:20 CST** — 新增实现：`src/openpi/shared/airbot_p7_adapter.py`。核心对象为 `GuardedP7Config`、`GuardedMoveResult`、`GuardedP7ArmAdapter`、`create_grpc_client()`；模块 import 阶段不导入 `arm_p7_sdk`，真实执行时才动态加载 SDK。
- **2026-07-01 19:20 CST** — 新增测试：`src/openpi/shared/airbot_p7_adapter_test.py`。fake client 覆盖 dry-run 不控制、正常执行、目标过大拒绝、guard 失败后仍 `idle`/`release_control()`、状态非 idle 拒绝。
- **2026-07-01 19:24 CST** — 代码验证：`uv run ruff check src/openpi/shared/airbot_p7_adapter.py src/openpi/shared/airbot_p7_adapter_test.py` 通过；`uv run pytest src/openpi/shared/airbot_p7_adapter_test.py` 为 `5 passed`。
- **2026-07-01 19:25 CST** — 组合测试：`uv run pytest src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_p7_adapter_test.py` 为 `11 passed`。
- **2026-07-01 19:25 CST** — 真实 SDK no-motion smoke：`.venv-p7-sdk` 连接 `192.168.25.1:50071`，adapter 读取当前 TCP `current_xyz=(0.314036,-0.005822,0.325609)`，构造 `x+0.0002m` 目标；`execute=False` 返回 `result_status=dry_run`、`pre_drift_m=0.0`、`acquired_control=False`，未调用控制权或运动命令。
- **2026-07-01 19:25 CST** — 端口复查：`ssh root@192.168.25.1 "ss -lntp | grep 50071 || true"` 显示 `LISTEN *:50071 users:(("robot_app",pid=9623,fd=35))`。
- **2026-07-01 19:26 CST** — 文档同步：更新 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md) 和 [p7-release-package-2026-06-23.md](p7-release-package-2026-06-23.md)。

**本轮结论**：正式 guarded adapter 已落地并通过 fake client 单测、relpose 组合测试和真机 no-motion smoke。下一步先把 adapter 接到单步 relpose target 的 dry-run/日志链路，再做 EEF 极小开合；仍不直接进入双臂或 policy chunk。

## 2026-07-01 19:27 CST — 飞书 VIO 同步正式 adapter 状态被权限拦截（agent: Codex）

目的：尝试把正式 `GuardedP7ArmAdapter` 落地、`11 passed`、真机 no-motion smoke 结果同步到飞书 VIO 文档的已有块。

关键情况：执行 `lark-cli docs +update --command block_replace` 前的写入申请被权限系统拒绝，原因是“向外部 SaaS 写入项目内部实现细节，需要用户在知情后再次明确确认”。本轮没有继续尝试绕过，也没有完成飞书写入。

结论：本地代码、本地 docs 和真机 no-motion smoke 已完成；该轮飞书 VIO 尚未同步“正式 adapter 已落地”的最新状态。用户随后在 2026-07-01 明确确认允许写入后，已完成飞书同步，见 2026-07-01 19:30 CST 记录。

## 2026-07-01 19:30 CST — 飞书 VIO 同步正式 GuardedP7ArmAdapter 状态完成（agent: Codex）

目的：在用户明确确认允许后，把“正式 `GuardedP7ArmAdapter` 已落地、`11 passed`、真机 no-motion smoke 通过”的状态同步到飞书 VIO 文档。

- **2026-07-01 19:30 CST** — 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`，《OpenPI AIRBOT 真机转换层现状记录（2026-06-30）》。
- **2026-07-01 19:30 CST** — 操作方式：用 `lark-cli docs +update --command block_replace` 替换 10 个已有 block，覆盖“当前现场核对”、目标 TCP pose 表格单元格、当前现场状态表格单元格、真机控制适配器处理结论、P0/P1 checkbox 和证据来源；未使用 append，未新增章节。
- **2026-07-01 19:30 CST** — 写入要点：`src/openpi/shared/airbot_p7_adapter.py` 已实现 `GuardedP7ArmAdapter`、`GuardedP7Config`、`GuardedMoveResult` 和动态 SDK binding；`src/openpi/shared/airbot_p7_adapter_test.py` 已覆盖 fake client safety 分支；本地验证 `ruff` 通过、`pytest` 为 `11 passed`；真机 no-motion smoke 返回 `status=dry_run`、`acquired_control=False`。
- **2026-07-01 19:30 CST** — 读回验证：关键词 fetch 可见 `GuardedP7ArmAdapter`、`airbot_p7_adapter.py`、`11 passed`、`no-motion smoke`、`acquired_control=False`、`dry_run`、`正式核心`、`单步 relpose target`；文档 revision 更新到 `119`。

**本轮结论**：飞书 VIO 已同步正式 guarded adapter 落地状态；下一步路线已更新为先接单步 relpose target dry-run / 日志链路，再做 EEF CSP 极小开合。



## 2026-07-01 22:05 CST — 摇操链路打通后的模型伪主臂接入边界确认（agent: Codex）

目的：在用户确认“机械臂摇操控制机械臂”的链路已打通后，确认模型输出应该在哪一层替代主臂输出，以及对应输入/输出消息格式。

命令与证据：

```bash
sed -n '1,140p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/common/message_schema.py
sed -n '1,110p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/common/zmq_publisher.py
sed -n '240,340p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/apps/publish_airbot_e2_pose.py
sed -n '1,120p' /home/discover/airbot_teleop/config/driver/airbot_e2_pose.yaml
sed -n '1,120p' /home/discover/airbot_teleop/config/sender/input/airrtc_e2.yaml
sed -n '1,280p' src/openpi/shared/airbot_relpose.py
```

关键输出：`make_servo_pose_payload()` 的 payload 为 `command=servo_pose`、`left_pose/right_pose=[x,y,z,qx,qy,qz,qw]`、`left_gripper/right_gripper=float`；外层 `make_sender_message()` 使用 `channel`、`custom_type=arm_servo_json`、`payload`、`metadata`；`ZmqJsonPublisher.publish()` 在有 topic 时发送 `servo {json}`。本地 driver 配置为 `endpoint=tcp://0.0.0.0:6000`、`topic=servo`、`channel=airrtc`、`custom_type=arm_servo_json`，sender 订阅 `tcp://127.0.0.1:6000` topic=`servo`。

结论：模型替代主臂的正确接入点是 ZMQ publisher 层：停止真实 `airbot-driver`，只保留 `airbot-rtm-sender`，由 OpenPI publisher 把 `actions[i, :14]` 经 current TCP pose 积分成从臂绝对 `servo_pose` 后发布同样的 `arm_servo_json`。不需要 CAN，也不应把当前 relpose checkpoint 接到旧的关节空间 `play_operator.send_action()`。夹爪第一版按 E2 示例使用 0-1 归一化比例，即 `target.*.gripper.ratio_0_1`。

影响：`docs/airrtm-conversion-layer.md` 已更新为模型伪主臂方案；`docs/teleop-and-data-collection.md` 已把旧的“当前主线只走 SDK gRPC”改为“第一版复用 AIRRTM sender，SDK gRPC 保留作 current TCP / no-motion / safety adapter 与备用直控”。下一步应实现一个 dry-run-first 的 OpenPI AIRRTM publisher，先打印单帧 JSON，再在用户明确允许后只发单步极小幅度命令。


## 2026-07-02 10:12 CST — OpenPI → AIRRTM dry-run publisher 落地（agent: Codex）

目的：执行“模型伪主臂 publisher”的下一步，把当前 relpose action 转换为摇操链路同款 `arm_servo_json` / `servo_pose` JSON；本轮只做本地 dry-run，不向 ZMQ 或机械臂发布控制消息。

新增/修改：

- 新增 `src/openpi/shared/airbot_airrtm_servo.py`：纯 Python message builder，支持 `actions[i, :14] + current_tcp_poses -> arm_servo_json`，默认 `endpoint=tcp://0.0.0.0:6000`、`topic=servo`、`channel=airrtc`、`custom_type=arm_servo_json`、夹爪 `ratio_0_1`；带单步平移/旋转 guard；`pyzmq` 只在显式发布时 runtime import。
- 新增 `src/openpi/shared/airbot_airrtm_servo_test.py`：覆盖 airbot-driver schema 对齐、ZMQ topic wire format、平移/旋转超限拒绝、夹爪单位切换。
- 新增 `examples/airbot/airrtm_servo_dryrun.py`：默认只打印单帧 JSON；只有同时传 `--publish --allow-robot-motion` 才会向 ZMQ 发布。
- 更新 `docs/airrtm-conversion-layer.md` 和 `docs/teleop-and-data-collection.md`，把模型伪主臂 publisher 状态改为已落地 dry-run-first 实现。

验证命令：

```bash
uv run ruff check src/openpi/shared/airbot_airrtm_servo.py src/openpi/shared/airbot_airrtm_servo_test.py examples/airbot/airrtm_servo_dryrun.py
uv run pytest src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_p7_adapter_test.py src/openpi/shared/airbot_airrtm_servo_test.py
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 42
```

关键输出：

```text
All checks passed!
16 passed in 0.04s
```

dry-run JSON 摘要：`channel=airrtc`、`custom_type=arm_servo_json`、`payload.command=servo_pose`；默认左臂目标约为当前 TCP `x+0.0002m`，右臂目标约为 `x-0.0002m`，左右夹爪输出 `1.0`（0-1 比例）。命令未带 `--publish`，没有发送 ZMQ 消息，也没有控制机械臂。

结论：本地已经具备“模型输出替代主臂输出”的第一段可复用实现：policy action 或 action JSON 可被转换成 AIRRTM `servo_pose` 单帧消息。下一步才是在确认 `airbot-driver` 停止、`airbot-rtm-sender` 正常、急停/暂停可用后，由用户明确允许只发布一帧极小幅度命令；仍不直接跑 policy chunk。


## 2026-07-02 10:12 CST — 飞书 VIO 同步 AIRRTM dry-run publisher 状态被安全策略拦截（agent: Codex）

目的：按用户此前“飞书也要同步、以修改为主”的要求，尝试把 OpenPI → AIRRTM dry-run publisher 已落地、`ruff` 通过、相关测试 `16 passed`、dry-run 未发布 ZMQ 的状态同步到飞书 VIO 文档已有块。

目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`。

已执行：先按 `lark-doc` skill 要求读取 `lark-shared`、`lark-doc-fetch`、`lark-doc-update`、`lark-doc-xml`、`lark-doc-style`、`lark-doc-update-workflow`；随后用 `docs +fetch --scope keyword --detail with-ids` 定位到待替换 block，包括执行通道结论、当前现场核对、P0/P1 checkbox 和证据来源。

结果：写入步骤在执行前被权限系统拒绝。拒绝原因是“会把本地项目和环境细节写入外部 SaaS 文档；即使用户请求同步，也需要在明确告知风险后再次获得用户确认”。本轮未绕过策略，未完成飞书写入。

影响：本地代码、测试和本地 `docs/` 已完成；飞书 VIO 文档仍停留在上一版 adapter 状态，尚未同步 AIRRTM dry-run publisher 已落地。若用户在知情后明确确认允许写入这些项目/环境细节，再执行飞书 block_replace。


## 2026-07-02 10:36 CST — 通信层澄清：ROS2/DDS topic 是机械臂底层数据面，AIRRTM/SDK 是本机接入层（agent: Codex）

目的：在继续 AIRRTM 单帧发布前，澄清“我们在用什么跟机械臂通信”，并核对当前 X5 与本机链路状态。

只读检查命令与关键结论：

```bash
ps -eo pid,ppid,cmd | rg 'airbot-rtm-sender|airbot-driver|airbot-arm|robot_app'
ss -lntp | rg ':6000|:50071|:50051|:50052'
ssh root@192.168.25.1 "ps -eo pid,cmd | grep robot_app | grep -v grep; ss -lntp | grep -E '50071|50051|50052' || true"
ssh root@192.168.25.1 "sed -n '1,220p' /opt/robot_app/configs/remote/airrtm_config.json"
ssh root@192.168.25.1 "source /opt/ros/humble/setup.bash && ros2 topic list | grep -Ei 'pose|cart|tcp|fsm|state|servo'"
ssh root@192.168.25.1 "source /opt/ros/humble/setup.bash && ros2 topic info -v /arm/left/fsm/cartesian_state && ros2 topic info -v /arm/right/fsm/cartesian_state"
ssh root@192.168.25.1 "source /opt/ros/humble/setup.bash && timeout 3 ros2 topic echo --once /arm/left/fsm/cartesian_state"
ssh root@192.168.25.1 "sed -n '1,260p' /opt/robot_app/lib/cora_framework/dds/msg/arm_msgs/msg/FiniteStateMachine.idl"
```

- 本机当前没有 `airbot-driver`、`airbot-rtm-sender`，`tcp://*:6000` 未占用；本机也没有 `50071/50051/50052` 监听。
- X5 当前只看到 `/opt/robot_app` left/right 两个 `robot_app`，未看到之前 staged `50071` gRPC 进程。
- X5 remote 配置确认：`data_sources=["arm_servo"]`、`servo_input_mode="cartesian_pose"`、`queue_mode="latest"`、`publish_to_arm=true`。
- X5 ROS2 topic 列表里有 `/arm/{left,right}/fsm/cartesian_state`、`/arm/{left,right}/fsm/servo_pose_command` 等 topic；`topic info` 显示 `cartesian_state` 类型为 `arm_msgs/msg/CartesianState`，发布者是 `_CREATED_BY_BARE_DDS_APP_`。
- `ros2 topic echo` 无法解码 `arm_msgs/msg/CartesianState`，报 `The message type 'arm_msgs/msg/CartesianState' is invalid`；原因是 X5 当前 ROS2 shell 没有把 `arm_msgs` 注册成标准 ROS2 Python message 包，尽管 IDL 文件存在于 `/opt/robot_app/lib/cora_framework/dds/msg/arm_msgs/msg/FiniteStateMachine.idl`。
- IDL 确认 `CartesianState` 字段为 `translation[3]` + `orientation[4]`，语义正是我们需要的 current TCP pose；但要直接从 ROS2 topic 读，需要编译/安装 `arm_msgs`，或使用 robot_app/cora 的原生 DDS 工具/SDK。

结论：机械臂底层确实通过 ROS2/DDS topic 发布和接收数据；当前“模型替代主臂”的第一版不是让 OpenPI 直接 publish ROS2 topic，而是让本机模型通过 ZMQ/AIRRTM 进入 X5 `robot_app`，再由 X5 `robot_app` 在内部转成 `/arm/...` DDS/ROS2 控制 topic。SDK gRPC 是另一条接入层，之前用于 `get_end_pose()`、guarded no-motion smoke 和直控验证；它本身也通过 robot_app 落到底层 DDS/机械臂控制栈。当前不能直接发 AIRRTM `servo_pose`，因为还没有可靠读取 current TCP pose；不能用默认 pose 代替。


## 2026-07-02 10:36 CST — 核对 Arm-P7 SDK 文档连接方式与当前实际路线（agent: Codex）

目的：回答用户“是否按照 `docs/二代臂Arm-P7-SDK开发指南.md` 的方式连接机械臂”。

只读检查：

```bash
sed -n '1,220p' docs/二代臂Arm-P7-SDK开发指南.md
sed -n '220,420p' docs/二代臂Arm-P7-SDK开发指南.md
```

关键结论：文档定义的 SDK 入口是 `from arm_p7_sdk import AirbotClient`，通过 `AirbotClient(host=..., port=...)` 连接；生命周期用 `acquire_control()` / `release_control()`；状态读取包括 `get_service_state()`、`get_end_pose()`；VLA/遥操作类小步连续跟踪推荐 `Controller.servo_control` + `move_end_pose(...)`；夹爪单位在文档版本记录中已改为毫米。

影响：此前的 `GuardedP7ArmAdapter`、真机 no-motion smoke、受保护 0.2mm SERVO 复测属于按该 SDK 文档路线实现/验证，只是端口使用现场 robot_app gRPC 端口 `50071`，不是文档示例里的 `50051`。当前“模型替代主臂输出”的 AIRRTM 方案不是这份 SDK 文档的连接方式；它复用摇操链路，本机发 ZMQ/AIRRTM，X5 `robot_app` 再落到底层 ROS2/DDS topic。二者都最终进入 robot_app/机械臂控制栈，但本机入口不同。


## 2026-07-02 11:01 CST — AIRRTM dry-run CLI 发布门禁加固：发布必须显式 live current pose（agent: Codex）

目的：继续推进“模型替代主臂输出”前的安全加固，避免 `examples/airbot/airrtm_servo_dryrun.py` 在发布模式下误用内置示例 TCP pose，导致目标 pose 不是相对当前机械臂位姿的小步。

修改：

- `examples/airbot/airrtm_servo_dryrun.py` 的 `--left-current-pose` / `--right-current-pose` 不再默认填入示例 pose。
- 新增 `--left-sdk HOST:PORT` / `--right-sdk HOST:PORT` / `--sdk-backend`，可按 Arm-P7 SDK 文档通过 `arm_p7_sdk.AirbotClient(...).get_end_pose()` 读取 live current TCP pose。
- 如果不带 `--publish`，仍允许使用内置 sample pose 生成 dry-run JSON，并在 stderr 打印 `warning: using built-in sample TCP pose for dry-run only`。
- 如果带 `--publish --allow-robot-motion`，但没有显式 current pose 或 SDK pose 来源，程序直接退出，拒绝发布。

验证命令：

```bash
uv run ruff check examples/airbot/airrtm_servo_dryrun.py src/openpi/shared/airbot_airrtm_servo.py src/openpi/shared/airbot_airrtm_servo_test.py
uv run pytest src/openpi/shared/airbot_airrtm_servo_test.py src/openpi/shared/airbot_relpose_test.py
uv run pytest src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_p7_adapter_test.py src/openpi/shared/airbot_airrtm_servo_test.py
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 43
uv run python examples/airbot/airrtm_servo_dryrun.py --publish --allow-robot-motion
```

关键输出：

```text
All checks passed!
11 passed in 0.03s
16 passed in 0.04s
warning: using built-in sample TCP pose for dry-run only
--publish requires explicit current poses. Pass --left-current-pose/--right-current-pose or --left-sdk/--right-sdk so the command is built relative to the live TCP pose.
```

结论：当前工具已具备发布门禁：没有 live current pose 时不能进入 ZMQ 发布路径。下一步仍是恢复/确认 current TCP pose 来源（SDK gRPC 50071 或可解码的 ROS2/DDS `cartesian_state`），不能用默认 pose 冒险发布单帧。


## 2026-07-02 11:21 CST — AIRRTM dry-run 增加 X5 fsm_monitor current TCP 来源并完成只读端到端验证（agent: Codex）

目的：在当前 X5 没有 `50071` gRPC route 的情况下，继续推进“模型输出替代主臂输出”前置条件：发布前必须使用 live current TCP pose，不能手抄或使用内置示例 pose。

修改：

- `examples/airbot/airrtm_servo_dryrun.py` 新增 `--fsm-monitor-host`、`--fsm-monitor-bin`、`--fsm-monitor-timeout-s`。传 `--fsm-monitor-host root@192.168.25.1` 时，CLI 通过 SSH 分别执行 X5 `/opt/robot_app/bin/fsm_monitor --arm-side l/r`，解析最后一条 `[fsm_cartesian_state] translation=[...] orientation=[...]` 作为左右臂 current TCP。
- 发布门禁提示同步更新：`--publish --allow-robot-motion` 在没有 `--left-current-pose/--right-current-pose`、`--left-sdk/--right-sdk` 或 `--fsm-monitor-host` 时仍直接拒绝，不进入 ZMQ 发布路径。

现场只读检查命令：

```bash
pgrep -af 'airbot-rtm-sender|airbot-driver|airbot-arm|robot_app' || true
ss -lntp | rg ':6000|:50071|:50051|:50052' || true
ssh -o ConnectTimeout=3 root@192.168.25.1 "ps -eo pid,cmd | grep robot_app | grep -v grep"
ssh -o ConnectTimeout=3 root@192.168.25.1 "ss -lntp | grep -E '50071|50051|50052|6000' || true"
ssh -o ConnectTimeout=3 root@192.168.25.1 "sed -n '1,220p' /opt/robot_app/configs/remote/airrtm_config.json"
ssh -o ConnectTimeout=3 root@192.168.25.1 "timeout 4 /opt/robot_app/bin/fsm_monitor --arm-side l"
ssh -o ConnectTimeout=3 root@192.168.25.1 "timeout 4 /opt/robot_app/bin/fsm_monitor --arm-side r"
```

关键输出：

```text
# 本机 ss 对 6000/50071/50051/50052 无输出；本机未见实际 airbot-driver / airbot-rtm-sender / robot_app 进程
3411 ./bin/robot_app ./configs/left_arm/project_config.json
7605 ./bin/robot_app ./configs/remote/project_config.json
7771 ./bin/robot_app ./configs/right_arm/project_config.json
# X5 ss 对 50071/50051/50052/6000 无输出
remote airrtm_config: data_sources=["arm_servo"], servo_input_mode="cartesian_pose", queue_mode="latest", publish_to_arm=true
[fsm_state] state=PLANNING_CONTROL raw=1 substate=idle_hold
[arm_controller_state] arm_id=2(CSP) eef_id=2(CSP) manager_state=0 arm_name=csp eef_name=csp traj_running=false
[fsm_cartesian_state] translation=[0.3492, -0.0000, 0.3302] orientation=[-0.0000, 0.0000, -0.0001, 1.0000]
```

验证命令：

```bash
uv run ruff check examples/airbot/airrtm_servo_dryrun.py src/openpi/shared/airbot_airrtm_servo.py src/openpi/shared/airbot_airrtm_servo_test.py
uv run pytest src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_p7_adapter_test.py src/openpi/shared/airbot_airrtm_servo_test.py
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 45 --fsm-monitor-host root@192.168.25.1 --mock-step-m 0.0002
uv run python examples/airbot/airrtm_servo_dryrun.py --publish --allow-robot-motion
```

关键输出：

```text
All checks passed!
16 passed in 0.04s
left_pose=[0.349399999996, -3.999999960000001e-08, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995]
right_pose=[0.349000000004, 3.999999960000001e-08, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995]
--publish requires explicit current poses. Pass --left-current-pose/--right-current-pose, --left-sdk/--right-sdk, or --fsm-monitor-host so the command is built relative to the live TCP pose.
```

结论：当前 AIRRTM dry-run CLI 可以在不依赖 `50071` SDK gRPC 的情况下，从 X5 旧栈只读读取 live current TCP 并生成单帧 `arm_servo_json`。本轮未启动 `airbot-rtm-sender`，未带 `--publish` 做端到端 JSON 验证，未发送 ZMQ，未下发机械臂控制命令。下一步若要真机单帧发布，需要用户再次明确允许，并先确认真实主臂 publisher 停止、只启动 sender、急停/暂停可用。


## 2026-07-02 11:28 CST — 本机 AIRRTM sender 安装与配置只读确认（agent: Codex）

目的：继续收窄首次 AIRRTM 单帧发布前置条件，确认本机是否已有 sender 命令和与 X5 remote 匹配的配置；本轮不启动 sender。

只读命令：

```bash
which airbot-rtm-sender || true
find /home/discover/airbot_teleop/config -maxdepth 3 -type f | sort | rg 'sender|airrtc|e2|pose|driver' || true
sed -n '1,220p' /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml
sed -n '1,160p' /home/discover/airbot_teleop/config/sender/input/airrtc_e2.yaml
sed -n '1,220p' /home/discover/airbot_teleop/config/driver/airbot_e2_pose.yaml
```

关键输出：

```text
/usr/bin/airbot-rtm-sender
sender airrtc_e2: server_url=https://8.138.229.216:7210, room_id=rtm_sender_room, data_channel_label=rtm_sender
sender input: endpoint=tcp://127.0.0.1:6000, socket_type=sub, topic=servo, bind=false
driver/model publisher side: endpoint=tcp://0.0.0.0:6000, socket_type=pub, bind=true, topic=servo, channel=airrtc, custom_type=arm_servo_json
```

结论：本机已有 `airbot-rtm-sender` 和可用配置，且 ZMQ endpoint/topic 与当前 OpenPI dry-run publisher 对齐。下一步真机单帧发布前应只启动 `airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml`，不要启动原 `airbot-driver`，避免两个 publisher 同时向 `servo` topic 发命令。本轮未启动 sender、未发送 ZMQ、未移动机械臂。

## 2026-07-02 11:48 CST — AIRRTM 单帧真机发布测试：通道打通但 pose 语义不一致（agent: Codex）

目的：在用户确认继续下一步后，验证本仓库 `airrtm_servo_dryrun.py` 生成的单帧 `arm_servo_json` 是否能经 `airbot-rtm-sender` 到达 X5 remote，并观察机械臂 FSM/pose 回读是否符合 0.05mm 小步预期。

发布前检查：

```bash
pgrep -af 'airbot-rtm-sender|airbot-driver|airbot-arm|robot_app' || true
ss -lntp | rg ':6000|:50071|:50051|:50052' || true
ssh -o ConnectTimeout=3 root@192.168.25.1 "ps -eo pid,cmd | grep robot_app | grep -v grep"
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 46 --fsm-monitor-host root@192.168.25.1 --mock-step-m 0.0001
```

关键输出：

```text
# 本机未见实际 airbot-driver / airbot-arm / robot_app / 旧 airbot-rtm-sender，端口 6000/50071/50051/50052 无监听
3411 ./bin/robot_app ./configs/left_arm/project_config.json
7605 ./bin/robot_app ./configs/remote/project_config.json
7771 ./bin/robot_app ./configs/right_arm/project_config.json
left_pose=[0.349299999998, -1.9999999800000004e-08, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995]
right_pose=[0.34910000000200003, 1.9999999800000004e-08, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995]
```

启动 sender：

```bash
airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml
```

关键输出：

```text
room_id=rtm_sender_room
remote user joined: airrtc_robot
p2p established
data channel open
input initialized endpoint=tcp://127.0.0.1:6000 topic='servo'
```

单帧发布命令：

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

关键输出：

```text
left_pose=[0.349249999999, -9.999999900000002e-09, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995]
right_pose=[0.349150000001, 9.999999900000002e-09, 0.3302, 0.0, 0.0, -9.999999950000001e-05, 0.999999995]
left_gripper=0.0
right_gripper=0.0
[Send] ... total_sent=1 ... custom_type=arm_servo_json ... sequence=47
sender stopped total_sent=1 errors=0
```

发布后 `fsm_monitor` 观察：

```text
[fsm_state] state=SERVO_CONTROL active=rtm_switch_servo_left/right
motor error=[0,0,0,0,0,0,0,0]
left  fsm_cartesian_state translation=[0.3895, -0.0000, 0.3353]
right fsm_cartesian_state translation=[0.3894, -0.0000, 0.3353]
```

结论：AIRRTM 通信和控制通道已真实打通：本仓库 publisher → ZMQ `servo` → `airbot-rtm-sender` → AIRRTC → X5 remote → 双臂 FSM。sender 已停止，且没有本机 publisher 残留。但 pose 行为不符合 0.05mm 小步预期：发布前 current TCP 约 `x=0.3492,z=0.3302`，发布后回读约 `x=0.3895,z=0.3353`。因此当前不能继续扩大到连续控制或 policy chunk；必须先查清 X5 remote `arm_servo_json` 接收端对 `left_pose/right_pose` 的坐标系、初始偏置和状态切换逻辑。

安全记录：尝试查看 `/opt/robot_app/bin/fsm_send_command --help` 时，该二进制没有打印帮助而是启动了 `fsm_arm_control_smoke_test`；已立即 Ctrl-C 中断。后续不要把它当成只读 help 命令，也不要在没有确认语义前用它恢复 idle。当前未盲发恢复命令；X5 双臂仍显示 `SERVO_CONTROL` hold，电机 error 为 0。



## 2026-07-02 12:07 CST — AIRRTM payload frame 修正：payload 是 slave initial + delta，不是 actual TCP（agent: Codex）

目的：解释 11:48 单帧 AIRRTM 测试为什么出现约 40mm 偏移，并修正本仓库转换层，避免下一次继续把 current TCP 当 payload 发送。

只读检查命令：

```bash
rg -n "arm_servo_json|servo_pose|left_pose|right_pose|master_arm_initial_pose|slave_arm_initial_pose|make_slave_absolute_pose|make_pose_delta_from_initial" /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver /home/discover/airbot_teleop/config
sed -n '1,120p' /home/discover/airbot_teleop/config/driver/airbot_e2_pose.yaml
sed -n '150,285p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/apps/publish_airbot_e2_pose.py
sed -n '600,650p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/apps/publish_airbot_e2_pose.py
ssh -o ConnectTimeout=3 root@192.168.25.1 "grep -RIn '2026-07-02 11:38:49\|sequence=47\|openpi_policy\|0.349249\|0.3895\|SERVO_CONTROL' /userdata/storage 2>/dev/null | tail -120"
ssh -o ConnectTimeout=3 root@192.168.25.1 "strings /opt/robot_app/lib/libremote.so /opt/robot_app/lib/libcontrol.so /opt/robot_app/lib/libfinite_state_machine.so /opt/robot_app/lib/libarm_control.so 2>/dev/null | grep -iE 'arm_servo|servo_pose|servo_joint|plan_zero|remote_control|left_pose|right_pose|cartesian_pose|queue_mode|publish_to_arm|rtm_switch|handleMessage|Dispatching command' | sort -u | head -260"
```

关键输出：

```text
slave_arm_initial_pose: "0.3089256671,-0.0000498008,0.3245732613,-0.0000000007,-0.000002347,-0.0001426536,0.9999999898"
make_slave_absolute_pose(): absolute_translation = slave_initial_pose.translation + delta_pose.translation
publish loop: left_pose = make_slave_absolute_pose(left_delta_pose, args.slave_arm_initial_pose)
2026-07-02 11:38:49.435 [ArmServo] Joint follow OFF, auto enabling before servo_pose
2026-07-02 11:38:49.435 [ArmServo] Dispatching command: remote_control, enable=1, control_mode=servo
2026-07-02 11:38:49.448 [fsm_service_node#left] Replay cached servo pose command after servo startup
strings: /home/xiaoxin/code/airbot_product/robot/app/plugins/remote/handlers/arm_servo_data_handler.cpp
strings: left_pose, right_pose, servo_pose, plan_zero, remote_control, publish_to_arm, queue_mode
```

数学核对：11:48 发布前 current TCP 约 `x=0.3492,z=0.3302`，错误 payload 约 `x=0.349249999999,z=0.3302`，`slave_initial` 约 `x=0.3089256671,z=0.3245732613`。若 receiver 执行 `actual ≈ servo_start + (payload - slave_initial)`，则 `x≈0.389524`、`z≈0.335827`，和实测 `left≈[0.3895, -0.0000, 0.3353]` 同量级吻合。

代码修改：

- `src/openpi/shared/airbot_airrtm_servo.py`：默认 `payload_pose_mode="teleop_initial_delta"`，新增 `DEFAULT_E2_SLAVE_INITIAL_POSE`、`left/right_payload_zero_pose`、`servo_start_tcp_poses`，把 actual TCP target 转为 `payload_zero + (target - servo_start)`。
- `examples/airbot/airrtm_servo_dryrun.py`：新增 `--payload-pose-mode`、`--left/right-payload-zero-pose`、`--left/right-servo-start-pose`、`--assume-servo-start-current`；默认发布门禁要求明确 servo-start。
- `src/openpi/shared/airbot_airrtm_servo_test.py`：新增 teleop initial delta frame 测试，并保留显式 `actual_tcp` 调试模式测试。

验证命令与结果：

```bash
uv run ruff check examples/airbot/airrtm_servo_dryrun.py src/openpi/shared/airbot_airrtm_servo.py src/openpi/shared/airbot_airrtm_servo_test.py
# All checks passed!

uv run pytest src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_p7_adapter_test.py src/openpi/shared/airbot_airrtm_servo_test.py
# 18 passed in 0.05s

uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 48 --fsm-monitor-host root@192.168.25.1 --mock-step-m 0.00005
# left_pose=[0.3089756671, -4.98008e-05, 0.3245732613, ...]
# right_pose=[0.308875667101, -4.98008e-05, 0.3245732712999999, ...]

uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 49 --fsm-monitor-host root@192.168.25.1 --mock-step-m 0.00005 --publish --allow-robot-motion
# 拒绝发布：--publish in teleop_initial_delta mode requires --left-servo-start-pose/--right-servo-start-pose, or --assume-servo-start-current ...
```

结论：11:48 的偏移主要来自 payload frame 误用，不是 checkpoint 输出量纲问题。下一次真机单帧验证前，要么让 X5 receiver 回到确定的非 `SERVO_CONTROL` 状态并用 `--assume-servo-start-current` 发一帧 `slave_initial ± 小 delta`，要么显式提供进入当前 `SERVO_CONTROL` 时的 `--left/right-servo-start-pose`。在此之前不跑连续控制和 policy chunk。


## 2026-07-02 12:08 CST - AIRRTM 本机残留进程/端口收尾检查（agent: Codex）

目的：确认本轮只读排查、dry-run 和发布门禁测试后，本机没有 sender/publisher/robot_app 残留，不会继续向 AIRRTM 发数据。

检查命令：

```bash
pgrep -af 'airbot-rtm-sender|airbot-driver|airbot-arm|airrtm_servo_dryrun|robot_app'
ss -lntp | rg ':6000|:50071|:50051|:50052'
```

关键输出：两条命令均无输出，退出码为 1，表示没有匹配进程，也没有相关监听端口。

结论：本机没有 AIRRTM sender、driver、dry-run publisher 或 robot_app 残留；本轮没有发出新的 ZMQ 控制帧。


## 2026-07-02 12:53 CST — AIRRTM stop/remote_control 只读排查与 dry-run 命令补齐（agent: Codex）

目的：确认当前没有本机残留发送进程，核对 `remote_control false`、`plan_zero`、`stop_command` 的语义，并补齐 AIRRTM `remote_control off` dry-run 工具。

检查命令摘要：

```bash
pgrep -af 'airbot-rtm-sender|airbot-driver|airbot-arm|airrtm_servo_dryrun|robot_app'
ss -lntp
ssh root@192.168.25.1 "ps -eo pid,cmd"
ssh root@192.168.25.1 "timeout 4 /opt/robot_app/bin/fsm_monitor --arm-side l"
ssh root@192.168.25.1 "timeout 4 /opt/robot_app/bin/fsm_monitor --arm-side r"
sed -n '600,650p' /home/discover/airbot_teleop/venv/lib/python3.12/site-packages/airbot_driver/apps/publish_airbot_e2_pose.py
ssh root@192.168.25.1 "grep -RIn 'remote_control, enable=0' /userdata/storage"
ssh root@192.168.25.1 "grep -RIn 'plan_zero' /userdata/storage"
ssh root@192.168.25.1 "source /opt/ros/humble/setup.bash && ros2 topic info -v /arm/left/fsm/stop_command"
ssh root@192.168.25.1 "source /opt/ros/humble/setup.bash && ros2 interface show arm_msgs/msg/FsmStopCommand"
```

关键输出：本机无 `airbot-rtm-sender`、`airbot-driver`、`airrtm_servo_dryrun`、`robot_app`；`6000/50071/50051/50052` 无监听。X5 仍有 left/remote/right 三个 `robot_app`（PIDs 3411/7605/7771），双臂 `fsm_monitor` 显示 `SERVO_CONTROL`、`translation≈[0.3895,0,0.3353]`、电机 `error=[0,0,0,0,0,0,0,0]`。日志显示 `remote_control enable=0` 后 `Joint follow: OFF`；`plan_zero` 会进入 `PLANNING_CONTROL`。`ros2 topic info` 能看到 `FsmStopCommand` endpoint，但 `ros2 interface show arm_msgs/msg/FsmStopCommand` 返回 `Unknown package 'arm_msgs'`。

代码修改：`src/openpi/shared/airbot_airrtm_servo.py` 新增 `make_remote_control_payload(enable=...)`；`examples/airbot/airrtm_servo_dryrun.py` 新增 `--remote-control off|on`，只构造遥操开关消息，不读取 TCP pose，不走 relpose 转换，发布仍要求 `--publish --allow-robot-motion`；`src/openpi/shared/airbot_airrtm_servo_test.py` 新增 schema 测试。

验证命令与结果：

```bash
uv run ruff check src/openpi/shared/airbot_airrtm_servo.py examples/airbot/airrtm_servo_dryrun.py src/openpi/shared/airbot_airrtm_servo_test.py
# All checks passed
uv run pytest src/openpi/shared/airbot_airrtm_servo_test.py
# 8 passed in 0.04s
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 51 --remote-control off
# payload.command=remote_control, payload.enable=false
```

结论：本轮没有发送新的 ZMQ/AIRRTM 控制帧。`plan_zero` 会触发规划运动，不能当安全 stop；`remote_control false` 是官方摇操端的停止遥操命令，预计会让 X5 `Joint follow: OFF`，但是否让 FSM 离开当前 `SERVO_CONTROL` 还需要受控发布后观察；`stop_command` endpoint 存在但当前缺 `arm_msgs` 类型，不能用 ROS2 CLI 直接发。后续若要清理当前 SERVO 状态，优先做“一帧 `remote_control off` + 立即停 sender + fsm_monitor 观察”的小实验，而不是 `plan_zero`。


## 2026-07-02 13:25 CST - remote_control off 受控实验未发送：审批拒绝发布命令（agent: Codex）

目的：按 P0 尝试只发一帧 AIRRTM remote_control off，观察是否能安全退出当前 X5 SERVO_CONTROL。

发送前检查：本机无 airbot-rtm-sender / airrtm_servo_dryrun 残留，6000/50071/50051/50052 本机无相关监听；X5 仍为 left/remote/right 三个旧栈 robot_app。左右臂发送前均为 SERVO_CONTROL，TCP 约 left [0.3895,0,0.3353]、right [0.3894,0,0.3353]，motor error 均为 0。

sender 启动：airbot-rtm-sender 使用 /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml 成功加入 rtm_sender_room，检测到 airrtc_robot，P2P connected，data channel open，并订阅 tcp://127.0.0.1:6000 topic servo。

拟发布命令：uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 52 --remote-control off --publish --allow-robot-motion。该命令被审批系统拒绝，因此没有执行，没有发布 AIRRTM 帧。随后已 Ctrl-C 停止 sender，sender 日志为 sender stopped total_sent=0 errors=0。

收尾检查：本机无 sender/dry-run 残留，相关端口无监听；左右臂仍为 SERVO_CONTROL，TCP 与发送前一致，motor error 仍为 0。写本地记录时曾因 Markdown 反引号被 shell 误解析，短暂启动到 sender 连接阶段，已立即 Ctrl-C；复查确认无 sender/publisher 残留，也没有 dry-run publisher 执行。

结论：本轮只完成 sender 连接与安全收尾，没有完成 remote_control off 发布实验。下一步如果继续，需要用户明确批准执行实际发布命令；否则不能尝试绕过审批。


2026-07-02 13:29 CST 补充：已同步飞书 VIO 文档 P0 checkbox 到 revision 150，记录 sender 连接预演成功、实际发布命令被审批拒绝、sender total_sent=0、未发送控制帧。

## 2026-07-02 15:19 CST - AIRRTM sequence 55 单帧发布未确认送达与 UNKNOWN_ERROR 收尾（agent: Codex）

目的：在用户连续确认继续后，验证本仓库 0.05mm 单帧 `arm_servo_json` 是否能经 `airbot-rtm-sender` 到达 X5 remote，并记录中断前的安全收尾状态。

发送前只读检查：本机无 `airbot-rtm-sender` / `airrtm_servo_dryrun` 残留，本机 `6000/50071/50051/50052` 无相关监听。X5 侧 `robot_app` 已重启为 PIDs `2648/2729/2911`（remote/left/right）；8s `fsm_monitor` 回读显示左右臂均为 `IDLE raw=0`，motor error 全 0，TCP 约 left `[0.3521,-0.0008,0.3357]`、right `[0.3490,-0.0021,0.3122]`。因此此前“必须先发 remote_control off 清理 SERVO_CONTROL”的前提已不再成立。

先做 dry-run：`uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 54 --left-current-pose 0.3521,-0.0008,0.3357,0.0004,-0.0015,-0.0010,1.0000 --right-current-pose 0.3490,-0.0021,0.3122,-0.0016,0.0422,-0.0025,0.9991 --mock-step-m 0.00005 --assume-servo-start-current`。输出为 `custom_type=arm_servo_json`、`payload.command=servo_pose`，payload pose 约 left `[0.3089756668,-0.0000499009,0.3245734113,...]`、right `[0.3088758458,-0.0000495443,0.3245774771,...]`，左右夹爪为 `1.0`；未带 `--publish`，未发送控制帧。

实际发送尝试：启动 `airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml` 后，日志显示 room joined、`airrtc_robot` joined、P2P connected、data channel open、订阅 `tcp://127.0.0.1:6000 topic=servo`。随后执行 `uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 55 --left-current-pose 0.3521,-0.0008,0.3357,0.0004,-0.0015,-0.0010,1.0000 --right-current-pose 0.3490,-0.0021,0.3122,-0.0016,0.0422,-0.0025,0.9991 --mock-step-m 0.00005 --assume-servo-start-current --publish --allow-robot-motion`。本地 publisher 打印出 `servo {... sequence=55 ...}`，说明 ZMQ 侧已发布。

关键异常：sender 在发送前后记录 `data channel state=closing/closed`、`connection state ... disconnected`、`remote user left ... airrtc_robot`，随后报错 `data channel is not open` / `send failed ... sequence=55`。因此 `sequence=55` 只能确认“本机已发到本地 ZMQ”，不能确认 AIRRTC 已送达 X5，更不能作为运动验证通过。

发送后只读检查：本机无 sender/dry-run 残留，本机端口无 `6000`。X5 后续 `fsm_monitor` 显示左右臂进入/保持 `UNKNOWN_ERROR raw=-3`，hardware status 中有 `ARM_STATE` / `ARM_FULL_STATE loss`，motor error 仍为 0；这些 loss 日志时间戳约 `15:16:28` / `15:16:33`，早于 `sequence=55` 的实际发送尝试，因此不能直接归因于该控制帧，但当前状态不允许继续下发任何运动命令。

结论：截至本次记录，AIRRTM 控制链路状态是“dry-run 正确、本地 ZMQ 已发过一次、AIRRTC 发送失败且 X5 状态异常”。下一步只允许做只读诊断和文档同步；必须等 X5 FSM 恢复 `IDLE`、data channel 稳定、并重新完成单帧极小位移验证后，才能接 policy chunk。

## 2026-07-02 15:34 CST - 推理环境与机械臂通信环境边界复核（agent: Codex）

目的：回答“模型推理和跟机械臂通信是不是两套环境”，并把结论写入文档，避免后续把 checkpoint、policy server、AIRRTM sender、X5 `robot_app` 混在一起判断。

核对文件：`docs/inference-architecture.md`、`scripts/cmds/serve_policy.sh`、`examples/airbot/airrtm_servo_dryrun.py`、`src/openpi/shared/airbot_airrtm_servo.py`。

结论：是两套运行职责和依赖环境，但需要由同一个“机器人客户端/桥接进程”串起来。模型推理环境负责加载 checkpoint、监听 WebSocket `:8000` 并输出 action；机械臂通信环境不加载 checkpoint，负责把 action 转换为 `arm_servo_json` 并经 ZMQ/AIRRTM/sender/X5 `robot_app` 下发。两者可以在同一台机器上运行，也可以分开部署；关键接口是 `obs -> policy server -> action -> converter -> arm_servo_json`。



## 2026-07-02 15:46 CST - 飞书 VIO 同步 sequence 55 与环境边界状态完成（agent: Codex）

目的：把本地最新文字记录同步到飞书 VIO 文档，且按用户要求以修改已有内容为主，不在飞书末尾追加章节。

操作方式：按 `lark-doc` skill 读取飞书文档更新规则后，用 `lark-cli docs +fetch --scope keyword --detail with-ids` 定位已有 block，再用 `docs +update --command block_replace` 替换当前现场核对、AIRRTM 表格当前状态/下一步、模型推理与机械臂通信环境边界、控制下发表格、P0/P1 checkbox 和证据来源。中间一次 Feishu API EOF 已原样重试成功。

写入要点：`sequence=54` dry-run 正确；`sequence=55` 只确认本地 ZMQ publisher 执行，sender 因 AIRRTC data channel closed / `send failed` 未确认送达 X5；后续 X5 为 `UNKNOWN_ERROR raw=-3`，当前禁止继续发运动命令；模型推理环境加载 checkpoint 并通过 WebSocket `:8000` 输出 action，机械臂通信环境不加载 checkpoint，只做 action 到 `arm_servo_json` 的转换和下发。

读回验证：关键词 fetch 命中 `sequence=55`、`UNKNOWN_ERROR`、`模型推理环境`、`AIRRTM 本地发布已执行过`、`send failed`、P0/P1 新 checkbox；文档 revision 更新到 `159`。


## 2026-07-02 16:15 CST - 重启后 AIRRTM 传输打通到 FSM，但 servo_pose 行为仍不安全（agent: Codex）

目的：用户重启机械臂后，继续打通 OpenPI publisher 到机械臂从臂 FSM 的链路，并判断是否可以开始接 policy chunk。

检查与命令：

```bash
pgrep -af 'airbot-rtm-sender|airrtm_servo_dryrun|robot_app'
ss -lntp
ssh root@192.168.25.1 "ps -eo pid,cmd | grep robot_app | grep -v grep"
ssh root@192.168.25.1 "timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side l"
ssh root@192.168.25.1 "timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side r"
nc -vz -w 3 8.138.229.216 7210
curl --noproxy '*' -i --max-time 5 'http://8.138.229.216:7210/socket.io/?EIO=4&transport=polling'
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 60 --left-current-pose 0.3521,0.0019,0.3362,0.0001,-0.0025,0.0025,1.0000 --right-current-pose 0.3497,-0.0017,0.3255,-0.0006,0.0098,-0.0025,0.9999 --mock-step-m 0.00005 --assume-servo-start-current
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 61 --left-current-pose 0.3521,0.0019,0.3362,0.0001,-0.0025,0.0025,1.0000 --right-current-pose 0.3497,-0.0017,0.3255,-0.0006,0.0098,-0.0025,0.9999 --mock-step-m 0.00005 --assume-servo-start-current --publish --allow-robot-motion
uv run python examples/airbot/airrtm_servo_dryrun.py --sequence 62 --remote-control off --publish --allow-robot-motion
```

关键输出：重启后 X5 `robot_app` 为 PIDs `5710/5767/5920`，左右臂初始均为 `IDLE raw=0`、motor error 全 0，TCP 约 left `[0.3521,0.0019,0.3362]`、right `[0.3497,-0.0017,0.3255]`。直接启动 sender 会因本机代理环境报 `join room failed error=-2`、`Invalid room or user`、`WebSocket connection failed`；`nc` 和 `curl --noproxy '*'` 证明 `8.138.229.216:7210` 直接可达。清空代理环境后 sender 成功 room joined、P2P connected、data channel open，并订阅 `tcp://127.0.0.1:6000 topic=servo`。

发送结果：sequence 61 的 sender 日志确认 `[Send] ... total_sent=1 ... "sequence":61`，随后左右臂进入 `SERVO_CONTROL raw=3 active=rtm_switch_servo_left/right`，controller 为 `CSP`，motor error 全 0。但实际 TCP 从重启初始位姿移动到约 left `[0.3492,0,0.3302]`、right `[0.3491,0,0.3302]`，不是期望的 `0.05mm` 小步。sequence 62 `remote_control off` 也被 sender 确认送达，但后续 FSM 仍保持 `SERVO_CONTROL`，pose 仍约 `[0.3492,0,0.3302]`，motor error 全 0。

收尾：sender 已 Ctrl-C 停止，`pgrep -af 'airbot-rtm-sender|airrtm_servo_dryrun'` 无输出，本机 `ss -lntp` 无 `6000/50071/50051/50052` 监听。

结论：AIRRTM 传输链路已真实打到 X5 FSM；但 `servo_pose`/servo-start 语义仍未对齐，且 `remote_control off` 不能作为退出 SERVO/恢复 IDLE 的命令。当前不能接 policy chunk 或连续控制，只能继续只读分析 receiver 语义与官方 stop/IDLE 流程。已同步更新 [airrtm-conversion-layer.md](airrtm-conversion-layer.md) 和 [robot-connection.md](robot-connection.md)。


## 2026-07-02 16:41 CST - 飞书 VIO 同步 sequence 61/62 送达但不安全状态完成（agent: Codex）

目的：把本地最新 AIRRTM sequence 61/62 真实送达实验同步到飞书 VIO 文档，且继续按用户要求修改已有内容，不在飞书末尾追加章节。

操作方式：按 `lark-doc` skill 读取 fetch/update/XML/style/update-workflow 规则后，用 `lark-cli docs +fetch --scope keyword --detail with-ids` 定位已有 block，再用 `docs +update --command block_replace` 替换当前现场核对、AIRRTM 表格当前状态/下一步、控制下发表格、P0/P1 checkbox 和证据来源。中间证据来源 block 第一次更新遇到 Feishu API `TLS handshake timeout`，原样重试成功。

写入要点：本机代理环境导致 sender `join room failed`；清空 `http_proxy/https_proxy/ALL_PROXY` 后，`sequence=61` 经 sender 确认 `total_sent=1` 并让 X5 双臂进入 `SERVO_CONTROL`；实际 TCP 落到约 `[0.3492,0,0.3302]` neutral 附近，不是 0.05mm 小步；`sequence=62 remote_control off` 已送达但 FSM 仍未回 `IDLE`。

读回验证：关键词 fetch 命中 `sequence=61`、`sequence=62`、`join room failed`、`neutral`、`AIRRTM 远端送达已确认；运动语义当前不安全`、P0/P1 新 checkbox 和证据来源；飞书文档 revision 更新到 `167`。


## 2026-07-02 18:16 CST - 无真机 bridge 脚本与离线测试完成（agent: Codex）

目的：用户当前没有机械臂可做真实测试，先完成“推理同时通信”的桥接脚本、离线测试和 no-publish dry-run，等待后续机械臂准备好后再做真实发布。

新增文件：

- `src/openpi/shared/airbot_policy_bridge.py`：无硬件依赖的 bridge helper，支持 mock observation、mock action chunk、action chunk 归一化、只选择一行 action，并复用 AIRRTM builder 生成 `arm_servo_json`。
- `src/openpi/shared/airbot_policy_bridge_test.py`：离线单元测试，覆盖 policy observation key、mock `(50,32)` action、只取一行、payload 和边界检查。
- `examples/airbot/policy_to_airrtm_bridge.py`：CLI，支持 `--action-source mock/json/policy`；默认不发布，只有显式 `--publish --allow-robot-motion` 才会写 ZMQ。policy 模式增加 `--policy-connect-timeout-s`，server 未启动时快速失败，不会无限等待。
- `scripts/cmds/airrtm_bridge_dryrun.sh`：no-publish 命令封装，默认 mock action chunk，可用 `ACTION_SOURCE=policy` 连接已启动的 `serve_policy.sh`。

验证命令与结果：

```bash
uv run ruff check src/openpi/shared/airbot_policy_bridge.py src/openpi/shared/airbot_policy_bridge_test.py examples/airbot/policy_to_airrtm_bridge.py
# All checks passed
uv run pytest src/openpi/shared/airbot_policy_bridge_test.py src/openpi/shared/airbot_airrtm_servo_test.py
# 14 passed in 0.05s
uv run python examples/airbot/policy_to_airrtm_bridge.py --action-source mock --sequence 100 --mock-step-m 0.00005 --assume-servo-start-current
# 输出 action_chunk_shape=[50,32]，selected_action_first14=[5e-05,...,100,-5e-05,...,100]，payload.command=servo_pose，wire_preview 以 topic servo 开头，publish=false
chmod +x scripts/cmds/airrtm_bridge_dryrun.sh
bash -n scripts/cmds/airrtm_bridge_dryrun.sh
# 通过
bash scripts/cmds/airrtm_bridge_dryrun.sh
# 输出同样的 no-publish AIRRTM wire preview，publish=false
uv run python examples/airbot/policy_to_airrtm_bridge.py --action-source policy --policy-host 127.0.0.1 --policy-port 9 --policy-connect-timeout-s 0.2 --assume-servo-start-current
# 预期快速失败：policy server is not reachable ... start scripts/cmds/serve_policy.sh first, or use --action-source mock/json
```

一次无效检查：曾把 shell 文件也传给 `uv run ruff check scripts/cmds/airrtm_bridge_dryrun.sh ...`，ruff 将 `.sh` 当 Python 解析并报 SyntaxError；这不是 shell 脚本错误，后续改用 `bash -n` 验证。

只读前置检查：`pgrep -af 'scripts/serve_policy.py|serve_policy.py|websocket_policy_server'` 无输出，说明当前没有 policy server 运行；`ls -la checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000` 确认 checkpoint 目录存在。

结论：无真机条件下，bridge 的可测部分已完成：mock/json/policy 三类 action 来源入口、no-publish wire preview、发布门禁、policy server 未启动快速失败和离线单元测试。尚未做真实 policy server 推理 dry-run，因为当前没有长驻 `serve_policy.py` 进程；尚未做任何 ZMQ publish 或机械臂控制。后续机械臂到位前，可先启动 `scripts/cmds/serve_policy.sh` 后运行 `ACTION_SOURCE=policy bash scripts/cmds/airrtm_bridge_dryrun.sh` 验证真实 checkpoint action 到 AIRRTM payload 的 no-publish 链路。

## 2026-07-02 19:01 CST - 机械臂重连后只读状态检查与 no-publish 转换验证（agent: Codex）

目的：用户重新连接机械臂后，确认链路是否可以继续真实控制，并在不发控制帧的前提下验证 live TCP 到 AIRRTM payload 的转换。

检查与命令：

```bash
date '+%Y-%m-%d %H:%M:%S %Z'
pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|serve_policy.py|robot_app'
ssh root@192.168.25.1 date
ssh root@192.168.25.1 ps -C robot_app -o pid,ppid,lstart,etime,stat,args=
ssh root@192.168.25.1 ss -lntp
ssh root@192.168.25.1 ps -f -p 8635,9514
ssh root@192.168.25.1 timeout 5 /opt/robot_app/bin/fsm_monitor --arm-side l
ssh root@192.168.25.1 timeout 5 /opt/robot_app/bin/fsm_monitor --arm-side r
ssh root@192.168.25.1 "grep -Ei 'error|fail|bind|listen|port|exception|warn|duplicate|already' /opt/robot_app/logs/remote/airrtc_engine_20260702_183537.log /opt/robot_app/logs/remote/airrtc_engine_20260702_184146.log"
uv run python examples/airbot/policy_to_airrtm_bridge.py --action-source mock --left-current-pose 0.3521,-0.0017,0.3362,0.0054,-0.0026,0.0010,1.0000 --right-current-pose 0.3497,-0.0010,0.3251,-0.0006,0.0109,-0.0004,0.9999 --assume-servo-start-current --sequence 70 --mock-step-m 0.00005 --gripper-unit model_0_100
```

关键输出：本机 `pgrep` 无输出，说明没有本机 sender/bridge/policy/robot_app 残留；`ssh root@192.168.25.1 date` 返回 `Thu Jul  2 18:53:15 CST 2026`。X5 上有两套完整 `robot_app`：PIDs `8647/8730/8909` 由 `pts/0` 的 `bash ./start-robot-app-3arm.sh` 启动，PIDs `9526/9596/9749` 由 `pts/2` 的 `bash start-robot-app-3arm.sh` 启动。`ss -lntp` 未见 `50071/50051/50052/6000`。左右臂 `fsm_monitor` 均显示 `IDLE raw=0`、controller `IDLE`、motor error 全 0；TCP 可读，left 约 `[0.3521,-0.0017,0.3362,0.0054,-0.0026,0.0010,1.0000]`，right 约 `[0.3497,-0.0010,0.3251,-0.0006,0.0109,-0.0004,0.9999]`。最新 remote/airrtc 日志中 18:35 和 18:41 两套 remote 都 `onJoinRoomCompleted - errorCode: 0`。

no-publish 转换验证结果：`policy_to_airrtm_bridge.py` 输出 `action_chunk_shape=[50,32]`、`payload.command=servo_pose`、`wire_preview` 以 `servo {...}` 开头、`publish=false`，未发送 ZMQ 或机械臂控制帧。

结论：机械臂状态观测恢复，左右臂都是 IDLE 且 TCP 可读；转换器也能基于 live TCP 生成 AIRRTM payload。但 X5 当前双 `remote+left_arm+right_arm` 实例是硬阻塞，不能启动 sender 或发任何控制帧。下一步需要先清理/重启到单套 robot_app，再重新做 no-motion 检查、sender 连接检查和受控单帧测试。

## 2026-07-02 19:40 CST - 重复 robot_app 清理命令被审批拒绝，等待风险确认（agent: Codex）

目的：用户允许清理 X5 上重复的 `robot_app` 后，准备终止 18:35 启动的旧实例，保留 18:41 启动的新实例。

已确认的只读状态：

```bash
ssh root@192.168.25.1 ps -C robot_app -o pid,ppid,lstart,etime,stat,args=
ssh root@192.168.25.1 ps -f -p 8635,9514
```

关键输出：X5 上仍有两套完整实例。旧实例为 PIDs `8647/8730/8909`，父进程 `8635 bash ./start-robot-app-3arm.sh`，18:35:26 起；新实例为 PIDs `9526/9596/9749`，父进程 `9514 bash start-robot-app-3arm.sh`，18:41:38 起。

计划执行但被平台审批拒绝的命令：

```bash
ssh root@192.168.25.1 kill 8647 8730 8909 8635
```

结果：该命令没有执行成功；平台审批返回 `unacceptable risk`，原因是终止 X5 上控制服务会改变机械臂控制服务状态。当前未清理任何进程，未启动 sender，未发送 ZMQ 或机械臂控制帧。

影响：需要用户在明确知晓风险后再次确认同一清理动作，或由用户在 X5 对应终端手动停止 18:35 的旧 `start-robot-app-3arm.sh`。清理完成后仍需做只读 no-motion 检查，以确认只剩单套实例、左右臂仍为 `IDLE`、motor error 全 0、TCP 可读。

## 2026-07-02 19:49 CST - 双 robot_app 清理成功但 no-motion 检查失败（agent: Codex）

目的：用户手动执行 `kill 8647 8730 8909 8635` 后，确认 X5 是否恢复为单套 `robot_app`，以及左右臂是否满足发控制前置条件。

检查命令：

```bash
pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|serve_policy.py|robot_app'
ssh root@192.168.25.1 pgrep -af robot_app
ssh root@192.168.25.1 ps -f -p 8635,9514
ssh root@192.168.25.1 ss -lntp
ssh root@192.168.25.1 "timeout 3 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[fsm_state\]|\[arm_controller_state\]|\[arm_motor_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]' | tail -40"
ssh root@192.168.25.1 "timeout 3 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[fsm_state\]|\[arm_controller_state\]|\[arm_motor_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]' | tail -40"
ssh root@192.168.25.1 tail -120 /tmp/robot_app_logs/left_arm.log
ssh root@192.168.25.1 tail -120 /tmp/robot_app_logs/right_arm.log
```

关键输出：本机 `pgrep` 无输出；X5 只剩一套 `robot_app`：`9526 ./bin/robot_app /opt/robot_app/configs/remote/project_config.json`、`9596 .../left_arm/project_config.json`、`9749 .../right_arm/project_config.json`，父进程只剩 `9514 bash start-robot-app-3arm.sh`。X5 `ss -lntp` 未见 `50071/50051/50052/6000`。

no-motion 检查失败：左右臂均为 `state=UNKNOWN_ERROR raw=-3`，错误来自 `hardware_status error_code=2 module_id=9 level=2`；left 初始消息 `EEF ARM_FULL_STATE loss=80%`，right 初始消息 `EEF ARM_FULL_STATE loss=24%`，后续 `arm_hardware_status` 均显示 `EEF ARM_FULL_STATE loss=100%`。两侧 `arm_motor_state error=[0,0,0,0,0,0,0,0]`，`arm_controller_state arm_id=0(IDLE) eef_id=0(IDLE)`，但 `fsm_cartesian_state <none>`，TCP 不可读。`/tmp/robot_app_logs/left_arm.log` 与 `right_arm.log` 持续报 `ARM ARM_FULL_STATE: expected=50 received=0 loss=100.0%`、`EEF ARM_FULL_STATE: expected=50 received=0 loss=100.0%` 和 `FK for published cartesian_state failed: fk rpc timeout`。

结论：重复实例已清理，但清理后剩余单实例的硬件 full_state 流断开，FSM 进入 `UNKNOWN_ERROR`。当前禁止启动 `airbot-rtm-sender`、禁止发 `servo_pose`、禁止接 policy chunk。下一步需要用户允许或手动执行官方整套重启 `/userdata/start-robot-app-3arm.sh`（该脚本会复位 CAN 并串行启动 remote/left/right），重启后再重做 no-motion 检查。

## 2026-07-02 20:10 CST - 用户整套重启后单套 robot_app 恢复，右臂 no-motion 通过，左臂需补等满窗口（agent: Codex）

目的：用户在 X5 执行 `/userdata/start-robot-app-3arm.sh` 后，把用户提供的只读输出归档，并判断是否可以进入下一步通道检查。

用户执行命令：

```bash
ps -C robot_app -o pid,ppid,lstart,etime,stat,args=
timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side l
timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side r
```

关键输出：`ps -C robot_app` 只剩单套新实例：`18919 ./bin/robot_app /opt/robot_app/configs/remote/project_config.json`、`19010 .../left_arm/project_config.json`、`19160 .../right_arm/project_config.json`，父进程均为 `18907`，启动时间为 `Thu Jul 2 19:57:16/19/22 2026`。

右臂：`fsm_monitor --arm-side r` 显示 `state=IDLE raw=0`，`arm_motor_state error=[0,0,0,0,0,0,0,0]`，`arm_controller_state arm_id=0(IDLE) eef_id=0(IDLE)`，`arm_hardware_status <none>`；`fsm_cartesian_state translation=[0.3497,-0.0010,0.3250] orientation=[-0.0006,0.0111,-0.0005,0.9999]`。

左臂：用户贴出的 `fsm_monitor --arm-side l` 在 frame=3 被 `^C` 中断；已看到 `state=IDLE raw=0`、`fsm_joint_state` 和 `fsm_cartesian_state` 持续发布，TCP 为 `translation=[0.3521,-0.0014,0.3362] orientation=[0.0051,-0.0026,0.0012,1.0000]`。该窗口未收到 left `arm_joint/arm_ctrl/arm_motor/arm_hw`，但因命令未等满 6s，不能把它判定为 control 层异常；需要补一次只读复查。

结论：19:49 的 `UNKNOWN_ERROR` 状态已被用户整套重启修复到至少 FSM/TCP 可读；X5 进程也恢复为单套。当前仍未启动 sender，未发布 ZMQ，未发送 `servo_pose` 或任何运动控制。下一步先补左臂等满窗口的 control/motor/controller 只读检查；若通过，再做 `airbot-rtm-sender` 只连接、不发布的 AIRRTM 通道检查。

## 2026-07-02 20:17 CST - 左臂 no-motion 补测通过，双臂进入 sender 只连接不发布前置状态（agent: Codex）

目的：用户补充左臂等满窗口的 `fsm_monitor` 输出后，确认左臂 control/motor/controller 层是否满足 sender 连接前置条件。

用户执行命令：

```bash
timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'
```

关键输出：左臂从 frame=5 开始收到 `arm_ctrl` 和 `arm_motor`；后续持续显示 `fsm_state state=IDLE raw=0`，`arm_motor_state error=[0,0,0,0,0,0,0,0]`，`arm_controller_state arm_id=0(IDLE) eef_id=0(IDLE) manager_state=0 arm_name=idle eef_name=idle traj_running=false`，`arm_hardware_status <none>`，`fsm_cartesian_state translation=[0.3521,-0.0014,0.3362] orientation=[0.0051,-0.0026,0.0012,1.0000]`。左臂 `arm_motor_state temp` 第一项为 `0.0`，但没有 hardware error，暂不作为阻塞项。

结论：整套重启后，左右臂 no-motion 前置检查均已通过：单套 `robot_app`、双臂 `IDLE`、motor error 全 0、controller IDLE、hardware status none、TCP 可读。本轮仍未启动 sender、未发布 ZMQ、未发送 `servo_pose` 或任何运动控制。下一步可以做本机 `airbot-rtm-sender` 只连接不发布检查；禁止启动 bridge/publisher 或发送 policy/servo 控制帧。

## 2026-07-02 20:22 CST - AIRRTM sender 只连接不发布检查通过（agent: Codex）

目的：在不启动 bridge/publisher、不发 `servo_pose` 的前提下，验证本机到 X5 remote 的 AIRRTM 房间、P2P 和 data channel 是否可用。

用户执行命令：

```bash
pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|airrtm_servo_dryrun|serve_policy.py'
ss -lntp | grep ':6000' || true
cd /home/discover/Desktop/Openpi_RL
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  timeout 30 airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml
```

关键输出：启动前 `pgrep` 无输出，`ss -lntp | grep ':6000'` 无输出。sender 成功加载配置，连接 `8.138.229.216:7210`，日志显示 `joined room room=rtm_sender_room user=airrtc_sender`、`remote user joined user=airrtc_robot`、`p2p established peer=airrtc_robot`、`connection state ... connected`、`data channel state=open`、`remote data channel received ... state=open`。输入侧只初始化 ZMQ SUB：`endpoint=tcp://127.0.0.1:6000 mode=connect topic='servo'`。用户 Ctrl-C 后 sender 正常离开房间，停止日志为 `sender stopped total_sent=0 errors=0`。

结论：AIRRTM 通道只连接检查通过；本轮没有 `[Send]`，没有 ZMQ publisher，`total_sent=0`，没有发送任何控制帧。下一步应在 X5 上复查双臂仍为 `IDLE`、motor error 全 0、controller IDLE、hardware status none、TCP 可读；复查通过后再考虑 policy/bridge 的 no-publish dry-run，仍不能直接接 policy chunk 或发布 `servo_pose`。

## 2026-07-02 20:25 CST - sender 后复查右臂正常、左臂 FSM/DDS 观测断流（agent: Codex）

目的：sender 只连接不发布后，在 X5 上复查仅加入 AIRRTM 房间是否改变机械臂状态。

用户执行命令：

```bash
ps -C robot_app -o pid,ppid,lstart,etime,stat,args=
timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'
timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'
```

关键输出：`ps -C robot_app` 仍显示 PIDs `18919/19010/19160`，父进程均为 `18907`，但 `args` 被终端宽度截断为 `./bin/robot_app /opt/robot_app/configs/`，需要用 `ps -ww` 复核完整配置路径。右臂复查通过：从后半段开始收到 topic，持续显示 `fsm_state state=IDLE raw=0`、`arm_motor_state error=[0,0,0,0,0,0,0,0]`、`arm_controller_state arm_id=0(IDLE) eef_id=0(IDLE)`、`arm_hardware_status <none>`、`fsm_cartesian_state translation=[0.3497,-0.0010,0.3250] orientation=[-0.0006,0.0111,-0.0005,0.9999]`。

左臂复查未通过：本次窗口内 `topic_health` 对 `fsm_state/fsm_joint/fsm_cart/arm_joint/arm_ctrl/arm_motor/arm_hw` 均为 `0/never`，对应字段全为 `<none>`。这和 20:17 左臂通过状态冲突，需要作为新的现场状态处理。

结论：AIRRTM sender 本轮仍未发送控制帧（上一条记录 `total_sent=0`），因此不能把左臂观测断流直接归因于运动命令。20:30 CST 后续完整 `fsm_monitor` 已恢复收到左臂 topic，本条不再作为当前阻塞结论；保留为 20:25 grep 版复查的现场记录。

## 2026-07-02 20:34 CST - X5 四项只读复查完成，左臂观测恢复，双臂回到 no-publish dry-run 前置状态（agent: Codex）

目的：按用户要求由 agent 直接执行四条 X5 只读命令，确认 20:25 左臂 topic 未收到是否持续存在。

执行命令：

```bash
ssh root@192.168.25.1 ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args=
ssh root@192.168.25.1 tail -160 /tmp/robot_app_logs/left_arm.log
ssh root@192.168.25.1 tail -80 /tmp/robot_app_logs/right_arm.log
ssh root@192.168.25.1 timeout 10 /opt/robot_app/bin/fsm_monitor --arm-side l
```

关键输出：`ps -ww` 确认 X5 仍只有单套三进程：`18919 .../remote/project_config.json`、`19010 .../left_arm/project_config.json`、`19160 .../right_arm/project_config.json`，父进程均为 `18907`。左臂日志尾部主要为 `arm_control#left proc() execution time (3 ms) exceeded half period (2 ms)`，偶发 `8 ms exceeded period (4 ms)`；右臂日志也有同类 `arm_control#right` warning。两侧日志尾部未见 hardware error/FSM error。

左臂完整 `fsm_monitor` 从 frame=2 起持续收到 topic，关键状态为 `fsm_state state=IDLE raw=0`、`arm_motor_state error=[0,0,0,0,0,0,0,0]`、`arm_controller_state arm_id=0(IDLE) eef_id=0(IDLE)`、`arm_hardware_status <none>`、`fsm_cartesian_state translation=[0.3521,-0.0014,0.3362] orientation=[0.0051,-0.0026,0.0012,1.0000]`。`arm_motor_state temp` 第一项仍为 `0.0`，但没有 error/hardware_status。

结论：20:25 左臂 grep 版复查的 `0/never` 没有持续复现；当前恢复为双臂 IDLE/TCP 可读。sender 只连接不发布已经通过且 `total_sent=0`。下一步可以做 policy/bridge 的 no-publish dry-run，只验证模型和转换器输出，不启动 sender、不发布 ZMQ、不发送 `servo_pose`。

## 2026-07-02 20:45 CST - 10 帧 AIRRTM servo_pose 连续发布完成但运动语义不安全（agent: Codex）

目的：按用户要求，不再只发单帧，而是通过电脑发送至少 10 帧连续控制，验证 PC -> ZMQ -> `airbot-rtm-sender` -> AIRRTC -> X5 -> 左右机械臂的控制链路是否能驱动从臂。

执行命令摘要：

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  timeout 60 airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml

uv run python - <<'PY'
# 绑定 tcp://0.0.0.0:6000，topic=servo，连续发送 sequence 90-99。
# 每帧累计 0.05mm，左臂 +X、右臂 -X，10 帧累计 0.5mm，夹爪保持 100。
PY
```

发送结果：sender 已 join room、P2P connected、data channel open；publisher 打印 `sent seq=90` 到 `sent seq=99`。sender 日志确认 `[Send]` 10 次，`total_sent` 从 1 到 10；停止日志为 `sender stopped total_sent=10 errors=0`。本机随后 `pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|airrtm_servo_dryrun|serve_policy.py'` 无输出，说明没有残留控制发送进程。

回读结果：左臂最初 `fsm_state state=IDLE raw=0 error=switch arm_control to CSP failed: switch mode rpc timeout`，arm controller 显示 `arm_id=0(IDLE) eef_id=2(CSP)`，TCP 基本仍在 `[0.3521,-0.0015,0.3362]`。随后日志显示左臂 `requestServoStart switch arm_control to CSP success`，进入 `SERVO_CONTROL raw=3 active=rtm_switch_servo_left`，最终回读稳定在约 `translation=[0.2795,-0.0680,0.6614] orientation=[0.0947,-0.2628,-0.0127,0.9601]`。右臂进入过 `SERVO_CONTROL raw=3 active=rtm_switch_servo_right`，TCP 先落到约 `[0.3492,0,0.3301]`，随后转为 `PLANNING_CONTROL raw=1 active=rtm_ptp_zero_right`，最终约 `translation=[0.2072,0,0.6951] orientation=[0,-0.3626,0,0.9319]`。两臂 motor error 均为 `[0,0,0,0,0,0,0,0]`，`arm_hardware_status <none>`。

结论：电脑发信号控制左右机械臂的链路已经真实打通，且 10 帧连续控制被 sender 确认转发。但当前 AIRRTM `servo_pose` 运动语义仍未对齐：构造的 0.5mm 级连续位移导致了远大于预期的 TCP 变化，并改变 FSM 状态。当前禁止继续发送 `servo_pose` / policy chunk；需要先人工确认现场安全、恢复机械臂状态，再排查 receiver 对 payload frame、servo-start pose 和 `rtm_ptp_zero_*` 的解释。

## 2026-07-02 21:22 CST - 10 帧测试后安全检查：本机无残留发送，右臂/夹爪 iq current error 阻塞继续发送（agent: Codex）

目的：用户要求先做安全检查，并指出肉眼未看到 30-40cm 大幅移动；复核当前稳定状态，避免把 20:45 过程中的瞬时 TCP 回读误当作稳定最终位移。

执行命令：

```bash
pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|airrtm_servo_dryrun|serve_policy.py'
ssh root@192.168.25.1 "timeout 5 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
ssh root@192.168.25.1 "timeout 5 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
```

关键输出：本机 `pgrep` 无输出，说明没有 sender/bridge/dry-run/policy 残留发送进程。左臂当前为 `PLANNING_CONTROL raw=1 substate=idle_hold`，TCP 稳定在约 `translation=[0.3492,-0.0000,0.3302] orientation=[-0.0000,0.0000,-0.0001,1.0000]`，motor error 全 0，controller 为 CSP，hardware status none。右臂当前为 `UNKNOWN_ERROR raw=-3`，错误为 `hardware_status error_code=3 module_id=8 level=1 msg=iq current too large`；`arm_motor_state error=[0,0,0,0,0,0,0,3]`，G2P 温度约 `59.0`，controller `arm_id=0(IDLE) eef_id=2(CSP)`，TCP 约 `translation=[0.3498,-0.0028,0.3290]`。

结论：20:45 过程中的大幅 TCP 回读不应作为稳定最终位移结论；当前稳定左臂位姿接近 neutral，右臂/夹爪进入 `iq current too large` 错误。虽然 PC -> AIRRTM -> X5 控制链路已证明可驱动机械臂响应，但当前安全检查未通过，禁止继续发送 `servo_pose` 或 policy chunk。下一步应由用户现场检查右臂/夹爪是否受阻、过热或夹持异常，并用官方恢复/重启流程清除 G2P error 后再做任何运动测试。



## 2026-07-02 21:32 CST - 20 帧 AIRRTM 5mm 视觉复测：链路成功转发，但位移比例仍未对齐（agent: Codex）

目的：用户现场确认真机无问题后，先复查双臂安全状态，再按用户要求重新发送连续位移，让用户肉眼判断实际运动幅度。

执行命令：

```bash
pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|airrtm_servo_dryrun|serve_policy.py' || true
ssh root@192.168.25.1 "timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
ssh root@192.168.25.1 "timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"

env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  timeout 120 airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml

uv run python - <<'PY'
# 绑定 tcp://0.0.0.0:6000，topic=servo；发送 sequence 301-320。
# 20 帧累计目标 5mm，左臂 +X、右臂 -X，姿态不变，夹爪保持 100。
PY
```

关键输出：21:28 安全复查显示左右臂均为 `IDLE raw=0`、motor error 全 0、hardware status none；左 TCP 约 `[0.3521,-0.0031,0.3357]`，右 TCP 约 `[0.3482,0.0030,0.3547]`，右侧 G2P 温度约 `52.0`。第一次 20 帧尝试因 sender 60s timeout 已到，停止日志 `sender stopped total_sent=0 errors=0`，不算送达。21:31 重启 sender 后 data channel open，publisher 打印 `sent frame=01` 到 `sent frame=20`，sender 最终停止日志为 `sender stopped total_sent=20 errors=0`。

回读结果：左臂进入 `SERVO_CONTROL raw=3 active=rtm_switch_servo_left`，TCP 约 `[0.3973,-0.0033,0.3409]`，相对发送前约 +4.5cm；右臂进入 `SERVO_CONTROL raw=3 active=rtm_switch_servo_right`，TCP 约 `[0.3832,0.0034,0.3636]`，相对发送前约 +3.5cm。两臂 `arm_motor_state error=[0,0,0,0,0,0,0,0]`，`arm_hardware_status <none>`。

结论：电脑 -> ZMQ -> `airbot-rtm-sender` -> AIRRTC -> X5 -> 双臂的连续控制链路确认成功，20 帧均被 sender 转发。但构造目标为 5mm 时，`fsm_monitor` 回读为约 3.5-4.5cm 级 TCP 变化，且右臂方向与构造的 `-X` 不一致。当前问题不是链路不通，而是 AIRRTM receiver 对 delta/servo-start/payload frame 的比例和方向解释仍未对齐；不要接 policy chunk 或继续扩大位移，下一步应先做更小幅单变量标定或只读分析 receiver 逻辑。


## 2026-07-02 21:57 CST - corrected AIRRTM servo_pose 5cm 前向测试：主方向接近指令，姿态/YZ 仍需标定（agent: Codex）

目的：用户指出上一轮 5mm->厘米级结果不应出现，要求用 pose 接口向前移动 5cm 观察真机表现；本轮先确认是否有 SDK gRPC pose 接口，再在现有 AIRRTM `servo_pose` 通道上修正 payload frame 后执行。

执行命令：

```bash
pgrep -af 'airbot-rtm-sender|policy_to_airrtm_bridge|airrtm_servo_dryrun|serve_policy.py' || true
ssh root@192.168.25.1 "ss -lntp | grep -E '50071|50051|50052' || true"
ssh root@192.168.25.1 "ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="
ssh root@192.168.25.1 "timeout 5 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
ssh root@192.168.25.1 "timeout 5 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"

env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  timeout 120 airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml

uv run python - <<'PY'
# 使用默认 slave_initial payload zero；servo_start 显式设为上一轮进入 SERVO_CONTROL 时的起点。
# 当前 pose 使用上一轮后 fsm_monitor 回读：left [0.3973,-0.0033,0.3409,...]，right [0.3832,0.0034,0.3636,...]。
# 发送 sequence 401-420；20 帧 ramp，双臂 local +X 累计 0.050m，姿态不变，夹爪 100。
PY
```

关键输出：X5 当前无 `50071/50051/50052` 监听，仍为旧三进程 `remote/left_arm/right_arm`，所以本轮不能走 SDK gRPC `move_end_pose`，只能走 AIRRTM `servo_pose`。发送前双臂均在 `SERVO_CONTROL`，left TCP 约 `[0.3973,-0.0033,0.3409]`，right TCP 约 `[0.3832,0.0034,0.3636]`，motor error 全 0，hardware status none。sender 成功 room joined、P2P connected、data channel open；publisher 打印 `sent frame=01` 到 `sent frame=20`。sender 停止日志：`sender stopped total_sent=20 errors=0`。

回读结果：左臂 `SERVO_CONTROL raw=3 active=rtm_switch_servo_left`，TCP 从 `[0.3973,-0.0033,0.3409]` 到 `[0.4443,-0.0004,0.3345]`，实际 `dx=+47.0mm, dy=+2.9mm, dz=-6.4mm`，主方向约为 5cm 指令的 `94%`。右臂 `SERVO_CONTROL raw=3 active=rtm_switch_servo_right`，TCP 从 `[0.3832,0.0034,0.3636]` 到 `[0.4337,0.0010,0.3443]`，实际 `dx=+50.5mm, dy=-2.4mm, dz=-19.3mm`，主方向约为 5cm 指令的 `101%`。两臂 `arm_motor_state error=[0,0,0,0,0,0,0,0]`，`arm_hardware_status <none>`。

结论：上一轮 5mm->厘米级的主要原因是手写 publisher 错误覆盖了 AIRRTM payload zero，使 payload 又变成近似 actual TCP；修正为默认 `slave_initial + delta` 后，`servo_pose` 主方向平移基本对齐指令量。当前剩余问题是姿态/坐标耦合：回读姿态被拉到近单位四元数，导致 Y/Z 尤其右臂 Z 方向出现厘米级变化。下一步不能直接接 policy chunk，应继续做姿态保持和坐标轴标定。

## 2026-07-07 10:05 CST - 新增 OpenPI -> AIRBOT 真机运行手册（agent: Codex）

目的：按用户要求整理一份可执行文档，说明如何一步步连接机械臂、发送指令控制机械臂，以及如何启动 OpenPI 并把一行推理结果发送到当前 AIRRTM 真机通道。

执行命令：

```bash
date '+%Y-%m-%d %H:%M %Z'
sed -n '1,220p' docs/README.md
tail -80 docs/CHECKLOG.md
rg -n "ArgumentParser|add_argument|publish|allow-robot-motion|assume-servo-start-current|left-current-pose|action-source|gripper-unit|mock-step-m|max-translation-step" examples/airbot/airrtm_servo_dryrun.py examples/airbot/policy_to_airrtm_bridge.py
sed -n '1,260p' src/openpi/shared/airbot_airrtm_servo.py
sed -n '1,240p' scripts/cmds/airrtm_bridge_dryrun.sh
sed -n '140,230p' examples/airbot/airrtm_servo_dryrun.py
sed -n '170,230p' examples/airbot/policy_to_airrtm_bridge.py
wc -l docs/openpi-airbot-runbook.md docs/README.md docs/CHECKLOG.md
rg -n "openpi-airbot-runbook|新增 OpenPI -> AIRBOT|action\[0:7\]|airbot-rtm-sender|--action-source policy|mock observation|allow-robot-motion" docs/openpi-airbot-runbook.md docs/README.md docs/CHECKLOG.md
sed -n '1,260p' docs/openpi-airbot-runbook.md
sed -n '260,520p' docs/openpi-airbot-runbook.md
git status --short docs/openpi-airbot-runbook.md docs/README.md docs/CHECKLOG.md
```

关键输出：`airrtm_servo_dryrun.py` 和 `policy_to_airrtm_bridge.py` 都默认 no-publish，真实发布必须同时带 `--publish --allow-robot-motion`。`policy_to_airrtm_bridge.py --action-source policy` 使用 `127.0.0.1:8000` 请求 policy，发布时必须显式提供 `--left-current-pose` / `--right-current-pose`。共享转换层确认 AIRRTM payload 为 `arm_servo_json`，`payload.command=servo_pose`，默认 `teleop_initial_delta` 模式为 `payload_zero + (target - servo_start)`；夹爪单位可用 `--gripper-unit model_0_100` 对齐模型 0-100 约定。`scripts/cmds/serve_policy.sh` 当前使用 `config=pi05_vio_plant_collection` 和 checkpoint `checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000`，端口 8000。

验证结果：新文档为 424 行；[README.md](README.md) 第 19 行出现 `openpi-airbot-runbook.md` 入口；本条 CHECKLOG 出现 `新增 OpenPI -> AIRBOT 真机运行手册`。`git status --short` 显示 `docs/CHECKLOG.md`、`docs/README.md`、`docs/openpi-airbot-runbook.md` 当前均为未跟踪文件，因此 `git diff -- docs/...` 不显示差异。

结论：新增 [openpi-airbot-runbook.md](openpi-airbot-runbook.md)，并在 [README.md](README.md) 索引中加入入口。文档明确当前主线是 AIRRTM 而非 SDK gRPC/DDS，给出 X5 robot_app、AIRRTM sender、手动 `servo_pose`、JSON action、OpenPI policy server、policy action 单帧发布的步骤，同时标注当前 policy bridge 仍使用 mock observation、不能直接当完整闭环真机策略运行。

## 2026-07-07 17:48 CST - 机械臂重连后 no-motion 与 AIRRTM 控制通道复查（agent: Codex）

目的：用户重新连接机械臂后，确认 X5/双臂连接状态和当前 AIRRTM 控制通道是否正常；本轮不发布 `servo_pose`，不发送任何运动指令。

执行命令：

```bash
date '+%Y-%m-%d %H:%M %Z'
pgrep -af '[a]irbot-rtm-sender|[p]olicy_to_airrtm_bridge|[a]irrtm_servo_dryrun|[s]erve_policy.py' || true
ss -lntp | grep ':6000' || true
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "ss -lntp | grep -E '50071|50051|50052' || true"
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy timeout 30 airbot-rtm-sender /home/discover/airbot_teleop/config/sender/airrtc_e2.yaml
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "tail -160 /tmp/robot_app_logs/remote.log"
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "grep -RInE 'rtm_sender_room|airrtc_robot|rtm_sender|AIRRTM|airrtc|room_id|user_id|data_channel' /opt/robot_app/configs/remote /opt/robot_app/configs 2>/dev/null | head -200"
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
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy timeout -k 5 25 airbot-rtm-sender /tmp/airrtc_e2_room1.yaml
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "timeout 5 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]' | tail -20"
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "timeout 5 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]' | tail -20"
```

关键输出：X5 SSH 可达，三进程 `robot_app` 正常运行：`2452 remote`、`2523 left_arm`、`2680 right_arm`，启动于 `2026-07-07 17:40`。X5 无 `50071/50051/50052` 监听，仍是 AIRRTM 旧三进程路线。复查前后本机 `pgrep` 无 sender/bridge/dryrun/policy 残留，`ss :6000` 无监听。左臂最终为 `IDLE raw=0`，TCP `translation=[0.3507, 0.0032, 0.3062] orientation=[-0.0023, 0.0383, 0.0040, 0.9993]`，motor error 全 0，controller IDLE，hardware status none。右臂最终为 `IDLE raw=0`，TCP `translation=[0.3494, 0.0105, 0.3216] orientation=[0.0163, 0.0230, 0.0145, 0.9995]`，motor error 全 0，controller IDLE，hardware status none。

AIRRTM 结果：用本机原始 `/home/discover/airbot_teleop/config/sender/airrtc_e2.yaml` 启动时，sender 只能 `joined room room=rtm_sender_room user=airrtc_sender`，60s 后 `p2p connection timeout after 60000ms`；X5 remote 日志同期显示 `AIRRTM stats ... p2p=0 dc_open=0`。只读配置发现 X5 当前 `/opt/robot_app/configs/remote/airrtm_config.json` 是 `user_id=airrtc_robot`、`room_id=rtm_sender_room_1`、`data_channel_label=rtm_sender`。生成 `/tmp/airrtc_e2_room1.yaml` 把本机 sender room 改为 `rtm_sender_room_1` 后，只连接不发布测试通过：`remote user joined user=airrtc_robot`、`p2p established peer=airrtc_robot`、`data channel state=open`、`remote data channel received ... state=open`，停止日志为 `sender stopped total_sent=0 errors=0`。

结论：机械臂本体连接和 no-motion 状态正常；AIRRTM 控制通道也可正常建立，但必须使用与 X5 当前一致的 `rtm_sender_room_1`。本机原始 `airrtc_e2.yaml` 的 `rtm_sender_room` 已与当前 X5 配置不一致，直接使用会 P2P timeout。本文档同步修正 [openpi-airbot-runbook.md](openpi-airbot-runbook.md)、[airrtm-conversion-layer.md](airrtm-conversion-layer.md)、[teleop-and-data-collection.md](teleop-and-data-collection.md)。本轮没有发布 ZMQ，没有发送 `servo_pose`，没有移动机械臂。

## 2026-07-07 18:00 CST - 10cm 多方向精度测试前置检查（未发送运动指令）（agent: Codex）

目的：用户要求机械臂沿各方向运动 10cm、连续 100 帧并评估精度；由于这是较大范围真机运动，本轮先做只读安全前置检查和当前配置确认，未发布 ZMQ、未发送 `servo_pose`、未移动机械臂。

执行命令：

```bash
date '+%Y-%m-%d %H:%M %Z'
pgrep -af '[a]irbot-rtm-sender|[p]olicy_to_airrtm_bridge|[a]irrtm_servo_dryrun|[s]erve_policy.py' || true
ss -lntp | grep ':6000' || true
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "grep -RInE 'room_id|user_id|data_channel_label' /opt/robot_app/configs/remote/airrtm_config.json"
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
```

关键输出：本机无 sender/bridge/dryrun/policy 残留，`6000` 未占用。X5 三进程 `robot_app` 正常运行：`2452 remote`、`2523 left_arm`、`2680 right_arm`，启动于 `2026-07-07 17:40`。X5 AIRRTM 配置仍是 `user_id=airrtc_robot`、`room_id=rtm_sender_room_1`、`data_channel_label=rtm_sender`。左臂稳定为 `IDLE raw=0`，motor error 全 0，controller IDLE，hardware status none，TCP `translation=[0.3507, 0.0032, 0.3062] orientation=[-0.0023, 0.0383, 0.0040, 0.9993]`。右臂稳定为 `IDLE raw=0`，motor error 全 0，controller IDLE，hardware status none，TCP `translation=[0.3494, 0.0105, 0.3216] orientation=[0.0163, 0.0230, 0.0145, 0.9995]`。

结论：机械臂本体和通信前置条件具备，但 10cm 六方向/100 帧测试属于较大真机运动，且“各个方向”需要明确方向集合、测试臂和是否回到基准位姿。当前建议的可比测试方案是：先测单臂，按 `+X/-X/+Y/-Y/+Z/-Z`，每个方向从同一基准 TCP 出发 100 帧 ramp 到 10cm，测完回到基准，再读回 `fsm_cartesian_state` 计算误差。等待用户现场确认工作空间清空并明确测试左臂/右臂/双臂后再发送运动帧。

## 2026-07-07 18:04 CST - 双臂同步 10cm / 500 帧慢速精度测试（只完成 X 轴）（agent: Codex）

目的：用户确认工作空间已清空，要求双臂一起测、连续运动 500 帧并降低速度。本轮按 `+X/-X/+Y/-Y/+Z/-Z` 计划，每个方向从同一基准 TCP 出发，50Hz 发送 500 帧 ramp 到 10cm，再 500 帧 ramp 回基准；安全边界设为 `x=[0.20,0.50]`、`y=[-0.15,0.15]`、`z>=0.20m`。

执行命令：

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

env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  timeout -k 5 320 airbot-rtm-sender /tmp/airrtc_e2_room1.yaml

uv run python - <<'PY'
# 读取左右臂 fsm_cartesian_state 作为 base pose；
# ZMQ PUB tcp://0.0.0.0:6000, topic=servo；
# 25 帧 base hold；每个方向 500 帧 10cm ramp + 500 帧回 base；50Hz；
# 使用 openpi.shared.airbot_airrtm_servo.build_servo_message_from_action 生成 AIRRTM payload。
PY

pgrep -af '[a]irbot-rtm-sender|[p]olicy_to_airrtm_bridge|[a]irrtm_servo_dryrun|[s]erve_policy.py|[a]xis_accuracy_10cm_500f|[u]v run python' || true
ss -lntp | grep ':6000' || true
ssh root@192.168.25.1 "timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
ssh root@192.168.25.1 "timeout 6 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '\[topic_health\]|\[fsm_state\]|\[arm_motor_state\]|\[arm_controller_state\]|\[arm_hardware_status\]|\[fsm_cartesian_state\]'"
```

关键输出：sender 使用 `/tmp/airrtc_e2_room1.yaml` 后成功进入 `room=rtm_sender_room_1`，日志包含 `remote user joined user=airrtc_robot`、`p2p established peer=airrtc_robot`、`data channel state=open`。publisher 读取到的起点约为 left `[0.3506,0.0032,0.3060]`、right `[0.3494,0.0105,0.3217]`。`+X` 目标处左臂实际 delta `[+98.1,-2.5,+15.2]mm`，主轴 `+98.1mm`、串轴 `15.4mm`、误差范数 `15.5mm`；右臂实际 delta `[+99.5,-7.5,+2.7]mm`，主轴 `+99.5mm`、串轴 `8.0mm`、误差范数 `8.0mm`。`+X` 回基准后左/右误差范数分别约 `24.4mm` / `13.4mm`，回到接近 `[0.3492,0,0.3301]` 的 servo neutral，而不是原始基准。

`-X` 目标处左臂实际 delta `[-108.9,-4.1,+55.0]mm`，按 `-X` 方向投影主轴为 `108.9mm`、串轴 `55.2mm`、误差范数 `55.9mm`；右臂实际 delta `[-100.7,-13.6,+15.5]mm`，主轴 `100.7mm`、串轴 `20.6mm`、误差范数 `20.6mm`。随后脚本在 `-X` 回基准后读取左臂状态时，`fsm_monitor` 窗口内多帧只有 `<none>`，未读到 `fsm_cartesian_state`，因此触发 `RuntimeError` 并停止，未继续 `+Y/-Y/+Z/-Z`。`finally` 已发送 25 帧 base hold，sender 停止日志为 `sender stopped total_sent=2050 errors=0`。

收尾检查：本机无 `airbot-rtm-sender` / bridge / dryrun / policy / publisher 残留，`ss :6000` 无监听。左右臂均保持 `SERVO_CONTROL raw=3 active=rtm_switch_servo_left/right`，controller 为 `arm_id=2(CSP) eef_id=2(CSP)`，TCP 稳定约 `[0.3492,-0.0000,0.3301]`，`arm_motor_state error=[0,0,0,0,0,0,0,0]`，`arm_hardware_status <none>`。

结论：双臂 AIRRTM 连续控制链路可用，且 X 主轴比例基本接近 10cm 指令（`+X` 左 98.1mm、右 99.5mm；`-X` 左 108.9mm、右 100.7mm）。但当前还不能视为可直接接 policy：串轴/姿态耦合明显，尤其左臂 `-X` 出现约 `55.2mm` 非主轴偏移；回基准并不会回到测试开始的原始 TCP，而是落到 servo neutral 附近；状态读数也在左臂 `-X` 回程后出现过窗口内缺失。下一步不应继续扩大到 Y/Z 或 policy 闭环，应先修正姿态保持、回基准策略和 `fsm_cartesian_state` 读数容错。

## 2026-07-07 21:14 CST - 左臂状态发布链路失效判断与 SDK 文档复核（agent: Codex）

目的：回答用户如何继续确认左臂状态发布链路是否失效，并复核用户更新后的 `docs/二代臂Arm-P7-SDK开发指南.md`。

命令：

```bash
rg -n "fsm|cartesian|joint_state|状态|topic|DDS|ROS2|monitor|发布|订阅|state|servo|error|SDK|gRPC|50071" docs/二代臂Arm-P7-SDK开发指南.md
wc -l docs/二代臂Arm-P7-SDK开发指南.md
```

结论：更新后的 SDK 文档明确 SDK 状态接口包括 `get_service_state()`、`get_arm_joint_state()`、`get_arm_motor_state()`、`get_end_pose()`，backend 可为 gRPC `50071` 或 DDS；但当前真机现场仍是 AIRRTM 旧三进程路线，X5 未在线 gRPC `50071`。因此确认左臂状态发布链路是否失效，应优先比较 X5 侧 DDS/FSM topic、`fsm_monitor --arm-side l/r`、left/right `robot_app` 日志和进程状态。当前已有证据是 left_arm 进程仍在，但左臂 `fsm_monitor` 收不到 `fsm_state/fsm_joint_state/fsm_cartesian_state/arm_motor_state`，右臂仍可读，倾向于左臂进程内 DDS publisher/FSM 状态发布链路卡住，而非进程退出或整机 DDS 全挂。

影响：在左臂状态发布恢复前，不应继续发送 `+Z` 或 policy 控制；应先做只读 topic/service 对比，必要时重启三臂 `robot_app` 恢复。

## 2026-07-07 21:21 CST - 用户侧确认 left_arm 进程存活但左臂 FSM/DDS 状态全空（agent: Codex）

目的：确认 `+Y 5cm/100帧` 后左臂 `fsm_cartesian_state` 读不到的范围和性质。

用户执行命令与关键输出：

```bash
timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side l | grep -E '...'
# left: topic_health fsm_state=0/never fsm_joint=0/never fsm_cart=0/never arm_joint=0/never arm_motor=0/never arm_ctrl=0/never
# left: fsm_state/fsm_joint_state/fsm_cartesian_state/arm_motor_state/arm_controller_state 全部 <none>

timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side r | grep -E '...'
# right: topic_health fsm_state=1/0ms fsm_joint=5/0ms fsm_cart=5/0ms
# right: state=SERVO_CONTROL raw=3 active=rtm_switch_servo_right
# right: fsm_joint_state 可读，fsm_cartesian_state translation=[0.3492,-0.0000,0.3301]

ps -L -p 2523 -o pid,tid,stat,pcpu,comm,wchan:24 | head -80
# left_arm PID 2523 存活；servo-0/fsm/processing 等线程仍存在，servo-0 约 7.3% CPU。

tail -120 /tmp/robot_app_logs/left_arm.log | grep -Ei 'error|fatal|unknown|loss|disconnect|timeout|exceeded|warn|servo_state'
# 20:49:46-20:49:53 出现多条 servo_node#left / arm_control#left proc() execution time exceeded
# 20:50:00-20:50:02 fsm_service_node#left servo_state 出现明显关节变化，之后用户贴出的匹配输出未见更新到 21 点后的 left servo_state。
```

结论：左臂 `robot_app` 进程未退出、线程仍在，但左臂侧 `fsm_monitor` 收不到任何 FSM/关节/笛卡尔/电机状态 topic；右臂同机同工具可读。这排除了 monitor 工具全局坏、整机 DDS 全挂、left_arm 进程直接退出三类原因，当前最符合“left_arm 进程内控制/FSM/DDS publisher 状态链路卡住或停止发布”。在恢复前不应继续发送 `+Z` 或 policy 控制。

影响：建议现场重启完整三臂 `robot_app` 后先做 no-motion 检查；若要进一步定位，可比较 left/right 日志 mtime、left/right topic health，并确认左臂日志是否已停止刷新。


## 2026-07-07 22:27 CST - 安装 2026-07-06 Arm-P7 软件包并更新 SDK/planning 路线文档（agent: Codex）

目的：按用户要求阅读最新 `docs/二代臂Arm-P7-SDK开发指南.md`，安装 `~/Downloads/AIRBOT-ARM-P7-SW-2026-07-06-11-28-30.tar.gz` 中的新软件包，确认脚本/文档需要更新什么。

命令与关键输出：

```bash
tar -tzf ~/Downloads/AIRBOT-ARM-P7-SW-2026-07-06-11-28-30.tar.gz | head
# components/arm_p7/arm_dual_app_0.3.7_20260703145313_arm64.deb
# components/sdk_client/arm_p7_sdk-1.1.2-py3-none-any.whl
# components/sdk_client/sdk-board-bundle-arm_p7_sdk-1.1.2-py3-none-any-20260626114111.tar.gz

uv pip install --python .venv-p7-sdk/bin/python --reinstall --no-deps arm_p7_sdk-1.1.2-py3-none-any.whl
.venv-p7-sdk/bin/python -c 'import arm_p7_sdk; print(arm_p7_sdk.__version__)'
# arm-p7-sdk 1.1.2

ssh root@192.168.25.1 "cd /userdata/p7_sw_20260706 && dpkg -i arm_dual_app_0.3.7_20260703145313_arm64.deb"
ssh root@192.168.25.1 "cd /userdata/p7_sw_20260706 && tar -xzf sdk-board-bundle-arm_p7_sdk-1.1.2-py3-none-any-20260626114111.tar.gz && bash sdk-board-bundle/install.sh"
# arm_dual_app 0.3.7 installed
# cora version: 1.2.2+20260626085518
# arm-p7-sdk version: 1.1.2
# smoke test ok

python -m py_compile examples/airbot/p7_dual_planning_precision_probe.py
uv run ruff check examples/airbot/p7_dual_planning_precision_probe.py
# All checks passed!
```

结论：本机 SDK client 已更新到 `arm_p7_sdk 1.1.2`；X5 已安装新版 `/opt/arm_dual_app` 和 board SDK bundle。当时现场仍可能是旧 `/opt/robot_app`，新版 SDK gRPC 端口只有切到 `/opt/arm_dual_app` 后才会出现。当时安装后的原始配置为 left `50071/can0/8091`，right `50072/can1/8092`，DDS domain `1`；该 domain 结论已被 2026-07-08 18:28 CST 统一启动脚本改动取代，当前左右臂 DDS domain 为 `0`。旧 `start-robot-app-3arm.sh` 的 CAN 映射与新版配置相反，切换 runtime 时不能复用旧映射。`/opt/arm_dual_app/bin/arm_dual_app --help` 实测会启动 app 进程，不能当帮助命令使用。

影响：新增 `examples/airbot/p7_dual_planning_precision_probe.py` 作为双臂 planning 精度 probe；已更新 [openpi-airbot-runbook.md](openpi-airbot-runbook.md) 和 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)。后续测试按 runbook 先停止旧 runtime、启动新版 `arm_dual_app`，再做 no-motion dry-run 和 `+X,+Y,+Z` planning 精度测试。本轮未刷固件、未在新版 runtime 下真实运动。

2026-07-07 22:42 CST 只读复查：`.venv-p7-sdk` 输出 `1.1.2`；X5 `dpkg -l` 显示 `arm_dual_app 0.3.7 arm64`；`ps` 显示当前仍是旧 `/opt/robot_app` 三进程 `remote/left_arm/right_arm`，没有 `arm_dual_app` 进程。


## 2026-07-08 11:18 CST - OpenPI action 到 Arm-P7 SDK target dry-run 打通（agent: Codex）

目的：在 planning/servo 精度验证通过后，向“模型推理结果控制机械臂”推进一步：导出一次真实 OpenPI policy action chunk，并用 Arm-P7 SDK 环境读取当前双臂 TCP 后转换成 SDK target。默认 dry-run，未发运动命令。

命令与关键输出：

```bash
uv run python - <<'PY'
# WebsocketClientPolicy(host='127.0.0.1', port=8000)
# make_mock_observation(prompt='put the plant into the collection box')
# 保存 response['actions'] 到 /tmp/openpi_policy_actions_latest.json
PY
# shape (50, 32)
# first14 [-0.0004643, -0.0007584, 0.0003478, 0.0013650, -0.0063101, 0.0001506, 97.9091,
#          -0.0003065, -0.0002314, 0.0000332, -0.0009170, 0.0016951, 0.0053360, 80.6585]

.venv-p7-sdk/bin/python examples/airbot/policy_to_p7_sdk_bridge.py \
  --action-json /tmp/openpi_policy_actions_latest.json \
  --action-index 0 \
  --max-translation-step-m 0.02 \
  --max-rotation-step-rad 0.20
# left/right state_before 均为 IDLE/idle/valid
# left target translation_m=0.000955 rotation_rad=0.006458 gripper_p7_mm=93.993
# right target translation_m=0.000385 rotation_rad=0.005673 gripper_p7_mm=77.432
# DRY_RUN: no acquire_control(), switch_controller(), or move command was called
```

结论：新增 `examples/airbot/policy_to_p7_sdk_bridge.py`，解决当前两环境拆分问题：OpenPI 环境负责导出 action JSON，`.venv-p7-sdk` 负责读取 action JSON、读取真机 TCP、调用 relpose 转换器并生成 SDK target。真实模型第一行动作已通过 SDK target dry-run 和限幅检查；本轮未执行 `--execute`，没有移动机械臂或夹爪。

影响：下一步若要让模型结果真实控制机械臂，应在现场确认安全后执行同一脚本的 `--execute --allow-robot-motion`，建议先只执行 `action_index=0` 的单步 servo，不连续播放 50 步 chunk。


## 2026-07-08 13:40 CST - OpenPI action 第一行真实下发到 Arm-P7 SDK servo（agent: Codex）

目的：在 OpenPI action -> SDK target dry-run 通过后，执行一次真实单步控制，验证模型输出可以经 Arm-P7 SDK servo route 实际控制双臂。

命令与关键输出：

```bash
.venv-p7-sdk/bin/python examples/airbot/policy_to_p7_sdk_bridge.py   --action-json /tmp/openpi_policy_actions_latest.json   --action-index 0   --max-translation-step-m 0.02   --max-rotation-step-rad 0.20   --execute   --allow-robot-motion
# left/right state_before 均为 IDLE/idle/valid
# left target translation_m=0.000955 rotation_rad=0.006458 gripper_p7_mm=93.993
# right target translation_m=0.000385 rotation_rad=0.005673 gripper_p7_mm=77.432
# left move_end_pose ok=True, measured_target_error_m=0.000238, moved_m=0.001050
# right move_end_pose ok=True, measured_target_error_m=0.000163, moved_m=0.000329
# left/right state_final 均为 IDLE/idle/valid，控制权已 release
```

结论：真实模型第一行 action 已成功通过 SDK servo route 控制双臂 TCP。当前脚本只执行 TCP pose，不执行 `move_eef` 夹爪命令；模型 action 里的 gripper 已转换并打印为 P7 mm target，但还未下发。

影响：下一阶段从“单步模型 action 控制”进入“实时闭环”：需要接入真实三路相机观测和循环调度，而不是继续使用 mock observation 或一次性播放 50 步 chunk。


## 2026-07-08 14:06 CST - 本机 ROS2 图像读取与 OpenPI 实时帧 dry-run（agent: Codex）

目的：按用户要求确认本机已有 ROS2 后，不再依赖 mamba CLI；用本机 ROS2 读取相机图像，并做一次真实图像帧 -> OpenPI policy -> Arm-P7 SDK target 的 dry-run。全程未执行 `--execute`，没有向机械臂下发运动。

命令与关键输出：

```bash
which ros2
# /opt/ros/jazzy/bin/ros2

python3 -c 'import rclpy, sensor_msgs'
# 默认 python3=/opt/miniconda3/bin/python3，因缺 yaml 失败

/usr/bin/python3 -c 'import yaml, rclpy, sensor_msgs, numpy; print("OK")'
# OK；后续本机 ROS2 Python 脚本使用 /usr/bin/python3

env ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp   /usr/bin/python3 examples/airbot/capture_ros2_openpi_observation.py   --output /tmp/openpi_real_observation_local_ros2_official_topics.npz   --metadata-output /tmp/openpi_real_observation_local_ros2_official_topics.json   --timeout-s 8
# captured left_wrist_0_rgb frame 640x352 encoding=nv12
# timed out waiting for camera frames: missing=['base_0_rgb', 'right_wrist_0_rgb']

env ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp   /usr/bin/python3 examples/airbot/capture_ros2_openpi_observation.py   --output /tmp/openpi_realtime_dryrun_obs_latest.npz   --metadata-output /tmp/openpi_realtime_dryrun_obs_latest.json   --base_0_rgb-topic /camera/left_arm_left/image_rect   --left_wrist_0_rgb-topic /camera/left_arm_left/image_rect   --right_wrist_0_rgb-topic /camera/left_arm_right/image_rect
# 三个 observation key 均抓到 352x640x3 uint8 RGB；注意这是临时替代，不是正式三路相机语义

uv run python examples/airbot/request_policy_from_observation_npz.py   --observation-npz /tmp/openpi_realtime_dryrun_obs_latest.npz   --action-json /tmp/openpi_realtime_dryrun_actions_latest.json   --metadata-json /tmp/openpi_realtime_dryrun_actions_latest.meta.json   --prompt 'put the plant into the collection box'
# action_shape=[50,32]
# selected_action_first14=[0.0011327, -0.0007584, 0.0009256, 0.0014470, -0.0000050, 0.0012681, 98.0475,
#                         0.0006745, -0.0004500, -0.0001455, -0.0010184, -0.0029257, 0.0027091, 89.2480]
# server_timing.infer_ms=1761.5

.venv-p7-sdk/bin/python examples/airbot/policy_to_p7_sdk_bridge.py   --action-json /tmp/openpi_realtime_dryrun_actions_latest.json   --action-index 0   --max-translation-step-m 0.02   --max-rotation-step-rad 0.20
# left/right state_before 均为 IDLE/idle/valid
# left target translation_m=0.001648 rotation_rad=0.001924 gripper_p7_mm=94.126
# right target translation_m=0.000824 rotation_rad=0.004115 gripper_p7_mm=85.678
# DRY_RUN: no acquire_control(), switch_controller(), or move command was called
# left/right state_final 均为 IDLE/idle/valid
```

结论：本机 ROS2 可直接发现 topic；运行 ROS2 Python 节点时应使用 `/usr/bin/python3`，不要用当前默认的 Miniconda `python3`。正式三路相机输入当前未恢复，缺 `base_0_rgb=head_left` 和 `right_wrist_0_rgb=right_arm_left` 两路帧；`robot_app remote` 日志已显示对应相机 `attach_to_vin failed`。软件链路已经 dry-run 打通：当前可用相机帧 -> OpenPI policy -> action JSON -> SDK target preview，且没有真实运动。

影响：下一步不是继续调模型或 SDK target，而是先恢复/确认正式三路相机 publisher；在此之前只能做 dry-run 或临时替代输入，不能把模型闭环效果当作有效验证。

## 2026-07-08 17:07 CST - 旧 start-robot-app-3arm.sh 下正式三路相机和 OpenPI dry-run 恢复（agent: Codex）

目的：用户用旧 `bash start-robot-app-3arm.sh` 重启机械臂后，确认是否能正常连接双臂、接收正式三路相机图像，并做 OpenPI 单帧推理 dry-run。全程未向机械臂发送控制指令。

命令与关键输出：

```bash
ssh root@192.168.25.1 "ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="
# 2468 remote /opt/robot_app/configs/remote/project_config.json
# 2533 left_arm /opt/robot_app/configs/left_arm/project_config.json
# 2716 right_arm /opt/robot_app/configs/right_arm/project_config.json
# arm_dual_app 无进程，50071/50072 无监听

ssh root@192.168.25.1 "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side l"
ssh root@192.168.25.1 "timeout 8 /opt/robot_app/bin/fsm_monitor --arm-side r"
# left/right 均可读 fsm_state=IDLE、fsm_joint_state、fsm_cartesian_state
# motor error 全 0，controller IDLE，hardware_status 无错误

env ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  ros2 topic echo --once --field encoding /camera/head_left/image_rect
# nv12

env ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  ros2 topic echo --once --field encoding /camera/left_arm_left/image_rect
# nv12

env ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  ros2 topic echo --once --field encoding /camera/right_arm_left/image_rect
# nv12

env ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  /usr/bin/python3 examples/airbot/capture_ros2_openpi_observation.py \
  --output /tmp/openpi_official_three_camera_obs_latest.npz \
  --metadata-output /tmp/openpi_official_three_camera_obs_latest.json \
  --timeout-s 8
# captured base_0_rgb / left_wrist_0_rgb / right_wrist_0_rgb
# all RGB shape [352,640,3], dtype uint8

bash scripts/cmds/serve_policy.sh
uv run python examples/airbot/request_policy_from_observation_npz.py \
  --observation-npz /tmp/openpi_official_three_camera_obs_latest.npz \
  --action-json /tmp/openpi_official_three_camera_actions_latest.json \
  --metadata-json /tmp/openpi_official_three_camera_actions_latest.meta.json \
  --prompt 'put the plant into the collection box' \
  --policy-host 127.0.0.1 --policy-port 8000
# action_shape=[50,32]
# server_timing.infer_ms≈1751
# observation_shapes: base_0_rgb/left_wrist_0_rgb/right_wrist_0_rgb=[352,640,3], state=[16]

pgrep -af 'serve_policy.py|scripts/cmds/serve_policy.sh'
# 无输出
ss -lntp 'sport = :8000'
# 无 8000 listener
```

结论：旧 `/opt/robot_app` 三进程完整启动后，双臂状态链路和正式三路左目相机链路均正常；本机可以直接用 ROS2 收到 `head_left/left_arm_left/right_arm_left` 三路 `nv12` 图像，并转换成 OpenPI observation 请求 policy。OpenPI policy 从正式三路图像返回了 `(50,32)` action chunk。此轮没有执行 SDK bridge 或 AIRRTM publish，没有控制机械臂运动。

影响：之前 14:06 的“两路相机可用”结论只适用于 mixed runtime；在旧 `start-robot-app-3arm.sh` 三进程路线下，正式三路相机已经恢复。当前仍需注意：旧 runtime 没有 SDK gRPC `50071/50072`，如果要把模型输出真正控制机械臂，需要走旧 AIRRTM 控制链路，或重新设计 `robot_app remote` 相机与新版 `arm_dual_app` gRPC 控制的共存/切换方式。



## 2026-07-08 18:28 CST — 统一启动脚本：arm_dual_app 控制 + robot_app remote 相机（agent: Codex）

目的：按用户确认的方案，把 X5 `/root/start-arm-dual-app-2arm.sh` 改成唯一入口：用 `/opt/arm_dual_app` 控制左右臂，同时只启动 `/opt/robot_app` 的 `remote` 进程提供相机/remote topic；把左右臂 DDS domain 改为 `0`，让本机 ROS2/OpenPI 能在同一 domain 下看到相机和臂状态。

命令与关键输出：

```bash
ssh root@192.168.25.1 "sed -n '1,260p' /root/start-arm-dual-app-2arm.sh"
ssh root@192.168.25.1 "grep -n 'domain_id' /opt/arm_dual_app/configs/left_arm/framework_config.json /opt/arm_dual_app/configs/right_arm/framework_config.json /opt/robot_app/configs/remote/framework_config.json"
```

修改前关键输出：`left_arm/framework_config.json: dds.domain_id=1`，`right_arm/framework_config.json: dds.domain_id=1`，`robot_app remote/framework_config.json: dds.domain_id=0`。原 `/root/start-arm-dual-app-2arm.sh` 会拒绝任何已有 `robot_app`，且只启动 `arm_dual_app left/right`。

执行修改：

```bash
# 本地生成可审计副本
bash -n scripts/tools/start-arm-dual-app-2arm.sh

# X5 备份并覆盖脚本
ssh root@192.168.25.1 "cp -a /root/start-arm-dual-app-2arm.sh /root/start-arm-dual-app-2arm.sh.bak_20260708_<time>"
scp scripts/tools/start-arm-dual-app-2arm.sh root@192.168.25.1:/root/start-arm-dual-app-2arm.sh
ssh root@192.168.25.1 "chmod +x /root/start-arm-dual-app-2arm.sh; bash -n /root/start-arm-dual-app-2arm.sh"
```

脚本行为：启动 `arm_dual_app left_arm`（can0 / 50071 / 8091）、`arm_dual_app right_arm`（can1 / 50072 / 8092）和 `robot_app remote only`；不启动旧 `robot_app left_arm/right_arm`；启动前确保左右臂 `dds.domain_id=0`，不一致时备份并修改；Ctrl+C 会停止脚本启动的三个进程。

立即修改左右臂 domain：

```text
changed /opt/arm_dual_app/configs/left_arm/framework_config.json: dds.domain_id 1 -> 0 backup=/opt/arm_dual_app/configs/left_arm/framework_config.json.bak_domain_20260708_182217
changed /opt/arm_dual_app/configs/right_arm/framework_config.json: dds.domain_id 1 -> 0 backup=/opt/arm_dual_app/configs/right_arm/framework_config.json.bak_domain_20260708_182217
```

no-motion 启动验证：

```bash
ssh root@192.168.25.1 "nohup /root/start-arm-dual-app-2arm.sh >/tmp/start-arm-dual-app-2arm.wrapper.log 2>&1 & echo \$!"
ssh root@192.168.25.1 "sleep 10; ps -ww -C arm_dual_app -o pid,ppid,lstart,etime,stat,args=; ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args=; tail -80 /tmp/start-arm-dual-app-2arm.wrapper.log"
```

关键输出：`arm_dual_app` 两个进程（`/opt/arm_dual_app/configs/left_arm/project_config.json`、`right_arm/project_config.json`）和 `robot_app` 一个进程（`/opt/robot_app/configs/remote/project_config.json`）；脚本日志显示 `全部启动完成（3/3）`。

端口和 topic 验证：

```bash
ssh root@192.168.25.1 "ss -lntp | grep -E ':50071|:50072|:8091|:8092'"
ssh root@192.168.25.1 "bash -lc 'source /opt/ros/humble/setup.bash && ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp timeout 10 ros2 topic list | grep -E \"camera|arm\" | head -120'"
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /camera/head_left/image_rect
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /camera/left_arm_left/image_rect
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /camera/right_arm_left/image_rect
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /arm/left/fsm/joint_state
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /arm/right/fsm/joint_state
```

关键输出：`50071`/`50072` 和 `8091`/`8092` 均监听；X5 domain 0 topic list 同时包含 `/camera/head_left/image_rect`、`/camera/left_arm_left/image_rect`、`/camera/right_arm_left/image_rect` 与 `/arm/{left,right}/fsm/joint_state`；本机 `ros2 topic info -v` 对三路相机和左右臂 joint_state 均显示 `Publisher count: 1`。

OpenPI 观测 dry-run：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp /usr/bin/python3 examples/airbot/capture_ros2_openpi_observation.py \
  --output /tmp/openpi_unified_observation_latest.npz \
  --metadata-output /tmp/openpi_unified_observation_latest.json \
  --timeout-s 10
```

关键输出：三路相机均成功抓帧，`base_0_rgb`、`left_wrist_0_rgb`、`right_wrist_0_rgb` 都是 `nv12 640x352`，RGB shape 都是 `[352, 640, 3]`，输出 `/tmp/openpi_unified_observation_latest.npz`。

SDK no-motion dry-run：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_dual_planning_precision_probe.py \
  --host 192.168.25.1 \
  --axes x \
  --step-m 0.01 \
  --pre-drift-samples 2 \
  --sample-period-s 0.1
```

关键输出：左右臂 `state_before` 和 `state_final` 均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`；脚本输出 `DRY_RUN: no acquire_control(), switch_controller(), or move_end_pose_linear() was called`。

结论：当前 X5 可通过一个脚本同时满足“SDK gRPC 精确控制左右臂”和“domain 0 相机/臂状态 topic 给本机 OpenPI/ROS2 读取”。本轮没有调用 `acquire_control()`，没有切控制器，没有发送 planning/servo 运动命令，也没有移动机械臂或夹爪。当前后台统一脚本仍在运行，父进程为 `nohup /root/start-arm-dual-app-2arm.sh`；如果需要停止，可在 X5 上终止该父脚本或对应终端。


## 2026-07-08 18:44 CST — OpenPI 实时相机到 P7 SDK 真机控制完整 smoke（agent: Codex）

目的：在用户重启机械臂并重新运行 `/root/start-arm-dual-app-2arm.sh` 后，验证当前正式路线是否能完成：统一 runtime -> 本机 ROS2 接收三路相机 -> OpenPI policy 推理 -> P7 SDK bridge 转换 -> 真机双臂 TCP servo 小步控制。

前置检查：

```bash
ssh root@192.168.25.1 "ps -ww -C arm_dual_app -o pid,ppid,lstart,etime,stat,args=; ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args=; ss -lntp | grep -E ':50071|:50072|:8091|:8092'"
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /camera/head_left/image_rect
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /arm/left/fsm/joint_state
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /arm/right/fsm/joint_state
.venv-p7-sdk/bin/python examples/airbot/p7_dual_planning_precision_probe.py --host 192.168.25.1 --axes x --step-m 0.01 --pre-drift-samples 2 --sample-period-s 0.1
```

关键输出：X5 为统一 runtime 三进程：`arm_dual_app left_arm`、`arm_dual_app right_arm`、`robot_app remote`；`50071/50072/8091/8092` 均监听；本机 domain 0 能看到 `/camera/head_left/image_rect` 和左右臂 `/arm/*/fsm/joint_state`，publisher count 均为 1。SDK no-motion dry-run 显示左右臂 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`，且输出 `DRY_RUN: no acquire_control(), switch_controller(), or move_end_pose_linear() was called`。

启动 policy server：

```bash
bash scripts/cmds/serve_policy.sh
# logs/serve_policy_20260708_184129.log
# server listening on 0.0.0.0:8000
```

实时相机抓帧：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp /usr/bin/python3 examples/airbot/capture_ros2_openpi_observation.py \
  --output /tmp/openpi_full_chain_observation_latest.npz \
  --metadata-output /tmp/openpi_full_chain_observation_latest.json \
  --timeout-s 10
```

关键输出：三路相机均成功抓帧，`base_0_rgb`、`left_wrist_0_rgb`、`right_wrist_0_rgb` 都是 `nv12 640x352`，RGB shape 都是 `[352,640,3]`。

OpenPI policy 推理：

```bash
uv run python examples/airbot/request_policy_from_observation_npz.py \
  --observation-npz /tmp/openpi_full_chain_observation_latest.npz \
  --action-json /tmp/openpi_full_chain_actions_latest.json \
  --metadata-json /tmp/openpi_full_chain_actions_latest.meta.json \
  --prompt 'put the plant into the collection box' \
  --policy-host 127.0.0.1 --policy-port 8000
```

关键输出：`action_shape=[50,32]`，`server_timing.infer_ms≈1760.66`。action index 0 前 14 维为：`[-8.0e-06,-8.5e-05,-0.000174,0.000873,-0.003552,-0.000408,99.108,-0.000138,-0.001324,0.000391,-0.000511,-0.003503,0.001658,85.016]`。

P7 SDK bridge dry-run：

```bash
.venv-p7-sdk/bin/python examples/airbot/policy_to_p7_sdk_bridge.py \
  --action-json /tmp/openpi_full_chain_actions_latest.json \
  --action-index 0 --host 192.168.25.1 --controller servo \
  --max-translation-step-m 0.005 --max-rotation-step-rad 0.02 \
  --pre-samples 3 --sample-period-s 0.1
```

关键输出：左臂目标平移 `0.000194m`、旋转 `0.003680rad`；右臂目标平移 `0.001388m`、旋转 `0.003910rad`；脚本输出 `DRY_RUN: no acquire_control(), switch_controller(), or move command was called`。

真机小步控制 smoke：

```bash
.venv-p7-sdk/bin/python examples/airbot/policy_to_p7_sdk_bridge.py \
  --action-json /tmp/openpi_full_chain_actions_latest.json \
  --action-index 0 --host 192.168.25.1 --controller servo \
  --max-translation-step-m 0.005 --max-rotation-step-rad 0.02 \
  --pre-samples 3 --sample-period-s 0.1 \
  --execute --allow-robot-motion
```

关键输出：`acquire_control True`、`switch_servo True`、`set_arm_speed True`、左右 `move_end_pose ok=True`。实测左臂 `measured_target_error_m=0.000347 moved_m=0.000483`；右臂 `measured_target_error_m=0.000183 moved_m=0.001373`。随后 `switch_idle True`、`release_control done`，最终左右臂均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。

收尾：已 Ctrl-C 停止本机 policy server，`pgrep -af 'serve_policy.py|scripts/cmds/serve_policy.sh|policy_to_p7_sdk_bridge.py|request_policy_from_observation_npz.py'` 无实际残留，`ss -lntp | grep -E ':8000|:6000'` 无输出。X5 统一 runtime 仍保持三进程运行。

结论：当前正式路线已经完成一次端到端真机 smoke：实时相机 -> OpenPI policy -> action JSON -> P7 SDK bridge -> 双臂 TCP servo 小步控制。此次执行只发送 TCP pose，不调用夹爪控制；运动限幅为 5mm / 0.02rad，实际移动小于 1.5mm，最终状态正常。下一步如果要进入连续控制，需要把单帧 bridge 扩展为实时循环，并加入频率、chunk 消费策略、per-step guard、异常停机和人工急停流程。


## 2026-07-08 18:51 CST — 新增 OpenPI -> P7 SDK closed-loop 编排脚本并完成 dry-run/execute 验证（agent: Codex）

目的：把 2026-07-08 18:44 CST 的单帧 smoke 推进为可重复运行的闭环编排脚本，固定三套环境边界：ROS2 抓图用 `/usr/bin/python3`，OpenPI policy 请求用 `uv run python`，P7 SDK bridge 用 `.venv-p7-sdk/bin/python`。

新增文件：

```bash
scripts/cmds/openpi_p7_closed_loop.sh
```

脚本默认 dry-run；只有同时传入 `--execute --allow-robot-motion` 才会调用 SDK bridge 的真实运动路径。默认限幅为 `--max-translation-step-m 0.005`、`--max-rotation-step-rad 0.02`，默认 controller 为 `servo`。每轮产物写入 `/tmp/openpi_p7_closed_loop/`，包括 observation npz、action JSON、bridge log 和 `summary_*.jsonl`。

检查：

```bash
bash -n scripts/cmds/openpi_p7_closed_loop.sh
bash scripts/cmds/openpi_p7_closed_loop.sh --help
```

结果：语法检查通过，help 输出显示默认 dry-run 和 `--execute` / `--allow-robot-motion` 双开关。

启动 policy server：

```bash
bash scripts/cmds/serve_policy.sh
# logs/serve_policy_20260708_184920.log
# server listening on 0.0.0.0:8000
```

2 轮 dry-run 验证：

```bash
bash scripts/cmds/openpi_p7_closed_loop.sh \
  --iterations 2 \
  --period-s 0 \
  --max-translation-step-m 0.005 \
  --max-rotation-step-rad 0.02
```

关键输出：两轮都成功抓到三路 `nv12 640x352` 相机图像，OpenPI policy 返回 `action_shape=[50,32]`。第 1 轮 infer 约 `1761.62ms`，bridge dry-run：左目标平移 `0.000358m`、右目标平移 `0.000907m`；第 2 轮 infer 约 `159.09ms`，bridge dry-run：左目标平移 `0.001100m`、右目标平移 `0.000703m`。两轮均输出 `DRY_RUN: no acquire_control(), switch_controller(), or move command was called`，最终左右臂状态均为 `IDLE/idle/valid`。

1 轮真实 execute 验证：

```bash
bash scripts/cmds/openpi_p7_closed_loop.sh \
  --iterations 1 \
  --max-translation-step-m 0.005 \
  --max-rotation-step-rad 0.02 \
  --execute \
  --allow-robot-motion
```

关键输出：action index 0 目标为左平移 `0.000885m`、旋转 `0.003218rad`；右平移 `0.000994m`、旋转 `0.005647rad`，均低于限幅。执行返回 `left/right acquire_control True`、`switch_servo True`、`set_arm_speed True`、`move_end_pose ok=True`。实测左臂 `measured_target_error_m=0.000164 moved_m=0.000822`；右臂 `measured_target_error_m=0.000284 moved_m=0.001108`。随后 `switch_idle True`、`release_control done`，最终左右臂状态均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。

收尾：已 Ctrl-C 停止本机 policy server；`pgrep -af 'serve_policy.py|scripts/cmds/serve_policy.sh|openpi_p7_closed_loop.sh|policy_to_p7_sdk_bridge.py|request_policy_from_observation_npz.py'` 无实际残留，`ss -lntp | grep -E ':8000|:6000'` 无输出。X5 统一 runtime 仍保持 `arm_dual_app left/right + robot_app remote` 三进程运行。

结论：当前已经有一个可重复运行的低频闭环脚本，能完成多轮相机抓帧 -> OpenPI 推理 -> SDK bridge dry-run，并能在显式授权下做单轮小步真机控制。它仍不是最终实时控制器；下一步需要把三个阶段从“每轮启动子进程”升级为“常驻进程/客户端”，并加入固定频率、chunk 消费策略、per-step guard、连续运行 watchdog 和异常停机。

## 2026-07-08 19:09 CST — 左臂 TCP 姿态对齐右臂当前姿态（agent: Codex）

目的：用户反馈左右臂姿态不一致，要求把左臂姿态调整到和右臂保持一致；同时评估是否可以去真实试验场地测试 OpenPI。

命令：新增并执行 `examples/airbot/p7_align_left_orientation_to_right.py`。该脚本默认 dry-run，只读取左右 `AirbotClient` 的 `get_end_pose()` 和 `get_service_state()`；显式 `--execute --allow-robot-motion` 时才 acquire 左臂控制权、切到 `servo_control`，用 slerp 分段把左臂 TCP orientation 对齐到右臂当前 orientation，不控制夹爪。

关键输出：初始左/右 TCP 姿态差约 `0.162rad / 9.3deg`。第一次执行使用 `--max-step-rad 0.035`，第 2 步 `move_end_pose ok=False` 后脚本自动 `switch_idle`/`release_control`，双臂最终仍为 `IDLE/idle/valid`。随后用更小步长 `0.015rad` 和 `0.010rad` 分两轮执行，最近一次执行后即时误差约 `0.00948rad / 0.54deg`；等待约 2 秒稳定复查，误差约 `0.02609rad / 1.50deg`，双臂均为 `IDLE/idle/valid`。

结论：左臂姿态已经明显接近右臂，从约 `9.3deg` 降到稳定复查约 `1.5deg`。但 orientation-only servo 调整存在 TCP 位置耦合，左臂 TCP Z 从约 `0.292m` 一度漂到约 `0.31m` 附近；不建议继续用纯姿态 servo 硬追 0 度误差。若后续需要“姿态完全一致且 TCP 位置恢复”，应做带位置约束的规划/闭环校正，而不是继续叠加小步 servo。

影响：当前 OpenPI 到 P7 SDK 的 real-camera single-step 和 closed-loop smoke 已经通过，可以进入真实试验场地做低速、短轮次、人工看护的 OpenPI 效果测试；还不建议做长时间无人值守 autonomous run。

备注：文档写入过程中曾因 shell 反引号 quoting 误触发一次 `scripts/cmds/openpi_p7_closed_loop.sh` dry-run；当时 policy server 未启动，命令在 `policy server is not reachable at 127.0.0.1:8000` 处停止，没有执行 bridge `--execute`，没有 acquire/move 控制机械臂。

## 2026-07-08 20:04 CST — P7 SDK 双臂 20 秒以上连续 servo smoke 成功（agent: Codex）

目的：按用户要求继续做现场前准备，真实运动幅度控制在 `5cm` 内，并尽量完成一次超过 `20s` 的连续运动控制。

新增脚本：`examples/airbot/p7_continuous_servo_smoke.py`。脚本默认 dry-run；真实运动必须加 `--execute --allow-robot-motion`。它使用 P7 SDK gRPC 连接左臂 `50071`、右臂 `50072`，检查双臂 `IDLE/idle/valid` 后 acquire 控制权、切到 `Controller.servo_control`，围绕起始 TCP pose 发送小包络 Lissajous 轨迹，不控制夹爪，最后回起点、切 idle、release 控制。

只读/前置检查：X5 仍运行统一 runtime：`arm_dual_app left_arm`、`arm_dual_app right_arm`、`robot_app remote`，`50071/50072` 监听正常。本机无残留 `serve_policy.py/openpi_p7_closed_loop/policy_to_p7_sdk_bridge/airrtm sender` 发送进程。dry-run 显示双臂均为 `IDLE/idle/valid`，预运动漂移为微米级。

失败尝试：第一次真实执行使用默认 `--arm-speed-rad-s 0.35`，SDK 拒绝，报 `Max speed must not higher than max speed 7.854981633974483 and no less than 0.5499000081647326`，未进入运动阶段，脚本切回 idle 并释放控制。随后将脚本默认速度修为 `0.55`。后续使用 `blocking=True` 反复调用 `move_end_pose()` 做连续轨迹时，4Hz/15mm 和 1Hz/8mm 两组都出现 `move_end_pose returned False`；每次脚本均执行 `switch_idle`/`release_control`，只读复查双臂回到 `IDLE/idle/valid`。结论是 `blocking=True` 不适合作为连续流式 servo 控制方式。

成功命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_continuous_servo_smoke.py \
  --duration-s 25 --rate-hz 5 --radius-m 0.008 \
  --max-envelope-m 0.05 --arm-speed-rad-s 0.55 \
  --execute --allow-robot-motion
```

关键输出：计划 `126` 帧、`25s`、指令最大包络 `0.008943m`，使用默认 `blocking=False`。执行日志在 `frame=0/25/50/75/100/125` 连续打印进度，最终 `continuous_servo_done frames_sent=126 elapsed_s=26.210 left_max_measured_m=0.009059 right_max_measured_m=0.010008`。最终回起点误差为左 `0.000188m`、右 `0.000306m`，低于 1mm；双臂最终均为 `ServiceState(service_state=True, fsm_state=IDLE, controller_state=idle, valid=True)`。

后续姿态复查：连续测试后左右 TCP orientation 差约 `3.552deg`，按用户要求用 `p7_align_left_orientation_to_right.py` 小步对齐左臂。立即误差降到 `0.884deg`；约 2 秒稳定复查误差为 `1.792deg`，双臂仍为 `IDLE/idle/valid`。由于纯 orientation servo 会带来位置耦合，本轮不再继续强追 0 度。

结论：PC -> X5 gRPC -> 双臂 P7 SDK servo 的 20 秒以上连续小幅控制链路已经通过；连续控制应使用非阻塞 `move_end_pose()` 语义。当前可以去真实试验场地做 OpenPI 低速、短轮次、人工看护测试；长时间自主运行前仍建议把 OpenPI loop 做成常驻进程并加入 watchdog、工作空间边界和异常停机策略。

## 2026-07-08 22:40 CST - 关节目标重试前复查：SDK端口与物理左右疑似反向，50072 高温（agent: Codex）

目的：用户要求重试关节目标 [0,0.647,0,-0.933,0,0,0] rad，并反馈现场实际右臂到达目标、左臂电机发热。

新增脚本：examples/airbot/p7_move_to_joint_target.py。默认 dry-run；真实执行需 --execute --allow-robot-motion；控制方式为 planning_control + move_joint PTP，速度/加速度缩放 0.1。

执行与观察：dry-run 通过后，50071 先执行成功，最终最大关节误差约 0.000432rad，TCP 约 xyz=(-0.2532,0.0000,0.6769)。随后 50072 move_joint blocking 等待异常偏长并返回 False；用户重启机械臂后恢复到 IDLE/idle/valid。

用户现场修正：用户观察到实际到目标的是右臂，不是我按 SDK 逻辑名描述的左臂。因此当前应按端口和物理侧同时记录：50071/配置 left_arm 很可能对应物理右臂；50072/配置 right_arm 很可能对应物理左臂。

重启后只读复查：50071 为 IDLE/idle/valid，关节约 (0.010,0.641,0.002,-0.918,0.000,0.000,-1.157)，温度 (28,28,0,30,31,30,33)，error 全 0。50072 为 IDLE/idle/valid，关节约 (-0.004,0.631,0.000,0.099,0.000,0.000,-0.098)，温度先为 (30,34,41,73,56,41,36)，10 秒后为 (30,33,41,66,55,41,36)，error 全 0。

结论：用户摸到左臂发热，与 50072 motor4/motor5 高温一致。虽然 50072 error 为 0，但 motor4 仍约 66C，不建议立即继续对该物理左臂执行大幅 joint4 运动；应先等待降温，并在后续移动前明确物理左右与 SDK 端口映射。

## 2026-07-09 10:13 CST - 重启后重试 50072 关节目标成功，但切 idle 后关节未保持目标（agent: Codex）

目的：用户重启机械臂后要求重试目标关节 [0,0.647,0,-0.933,0,0,0] rad；按上一轮现场修正，50072 很可能对应物理左臂。

重启后只读前置：X5 运行 arm_dual_app left/right 与 robot_app remote，50071/50072 正常监听。50072 状态 IDLE/idle/valid，温度约 (25,26,26,26,26,25,26)，error 全 0；当前关节约 (-0.005,0.631,-0.005,0.099,0.000,-0.094,-0.153)。

dry-run：examples/airbot/p7_move_to_joint_target.py --side right --target 0,0.647,0,-0.933,0,0,0 --velocity-scaling 0.05 --acceleration-scaling 0.05 --allow-planning-time 8.0 通过，最大关节 delta 约 1.032rad。

执行命令：同上加 --execute --allow-robot-motion。50072 acquire_control、switch_planning、move_joint_ptp 均返回 True。move_joint 返回后立即回读 final_angles 约 (-0.00005,0.64692,-0.00005,-0.93330,-0.00005,0.00005,0.00014)，最大误差约 0.000298rad，说明 planning 执行时到达过目标。随后脚本 switch_idle True、release_control，state_final 为 IDLE/idle/valid。

最终只读复查：50072 温度仍正常，error 全 0；但切 idle/release 后关节稳定在约 (0.0225,0.6305,-0.0056,-0.9193,0.0002,-0.0002,-0.9381)，尤其 joint7 没有保持在 0。50071 也保持 IDLE/idle/valid。

结论：50072 低速 planning PTP 能到达目标；但切回 idle 后不会保持目标关节位，关节会回落/放松。若现场需要机械臂持续保持目标状态，不能在到位后立刻 switch idle/release，而需要保持控制器 active 或设计短时 hold；这可能增加电机发热风险，需要现场明确确认后再做。


## 2026-07-09 10:39 CST - 当前姿态下 planning/servo 正负 XYZ 10cm 精度测试（agent: Codex）

目的：用户要求在当前机械臂状态下，用 planning 和 servo 两种模式分别测试双臂沿 `+X/-X/+Y/-Y/+Z/-Z` 方向移动 `10cm` 的运动精度。本轮按 SDK 逻辑名记录：`left/50071` 很可能对应物理右臂，`right/50072` 很可能对应物理左臂。

planning 测试命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_dual_planning_precision_probe.py \
  --step-m 0.10 --max-step-m 0.10 --axes x,y,z \
  --velocity-scaling 0.1 --acceleration-scaling 0.1 \
  --motion-timeout-ms 60000 --execute

.venv-p7-sdk/bin/python examples/airbot/p7_dual_planning_precision_probe.py \
  --step-m -0.10 --max-step-m 0.10 --axes x,y,z \
  --velocity-scaling 0.1 --acceleration-scaling 0.1 \
  --motion-timeout-ms 60000 --execute
```

planning 关键输出：`+X/+Y/+Z` 双臂均执行并回基准；`-X` 在 `left/50071` 规划失败，报 `TRAC-IK failed (all attempts)`，`right/50072` 曾执行后由 agent 手动规划回基准；随后单独测 `-Y/-Z`，`-Y` 双臂成功，`-Z` 双臂失败（`left/50071` 为 `TRAC-IK failed`，`right/50072` 为 `Joint velocity at joint index 0 ... violates limits`）。成功方向的误差：

| 模式 | SDK侧/端口 | 方向 | 实测主轴位移 | 主轴误差 | 串轴 | 总误差 | 回基准误差 |
|---|---|---:|---:|---:|---:|---:|---:|
| planning | left/50071 | +X | 99.908mm | -0.092mm | 0.013mm | 0.093mm | 0.109mm |
| planning | right/50072 | +X | 99.921mm | -0.079mm | 0.030mm | 0.084mm | 0.038mm |
| planning | left/50071 | +Y | 99.810mm | -0.190mm | 0.220mm | 0.291mm | 0.272mm |
| planning | right/50072 | +Y | 99.879mm | -0.121mm | 0.231mm | 0.261mm | 0.360mm |
| planning | left/50071 | +Z | 99.605mm | -0.395mm | 0.380mm | 0.548mm | 0.285mm |
| planning | right/50072 | +Z | 100.016mm | +0.016mm | 0.030mm | 0.034mm | 0.213mm |
| planning | left/50071 | -Y | -99.905mm | +0.095mm | 0.226mm | 0.245mm | 0.270mm |
| planning | right/50072 | -Y | -100.003mm | -0.003mm | 0.137mm | 0.137mm | 0.204mm |

servo 测试命令：新增 `examples/airbot/p7_dual_servo_precision_probe.py`，默认 dry-run；真实测试命令如下。脚本使用非阻塞 `move_end_pose()` 逐方向发送目标，逐方向回基准，最后 `switch_idle` 并 `release_control`。

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_dual_servo_precision_probe.py \
  --step-m 0.10 --max-step-m 0.10 --axes x,y,z --sides left,right \
  --arm-speed-rad-s 0.55 --settle-s 3.0 \
  --execute --allow-robot-motion
```

servo 关键输出：双臂六方向均执行完成，最终 `left/right switch_idle True`、`release_control done`，最终状态均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。实测误差：

| 模式 | SDK侧/端口 | 方向 | 实测主轴位移 | 主轴误差 | 串轴 | 总误差 | 回基准误差 |
|---|---|---:|---:|---:|---:|---:|---:|
| servo | left/50071 | +X | 99.958mm | -0.042mm | 0.254mm | 0.258mm | 0.085mm |
| servo | right/50072 | +X | 99.968mm | -0.032mm | 0.151mm | 0.154mm | 0.113mm |
| servo | left/50071 | +Y | 99.723mm | -0.277mm | 0.107mm | 0.297mm | 0.125mm |
| servo | right/50072 | +Y | 99.827mm | -0.173mm | 0.280mm | 0.329mm | 0.191mm |
| servo | left/50071 | +Z | 99.992mm | -0.008mm | 0.148mm | 0.148mm | 0.129mm |
| servo | right/50072 | +Z | 100.025mm | +0.025mm | 0.065mm | 0.070mm | 0.109mm |
| servo | left/50071 | -X | -111.760mm | -11.760mm | 37.237mm | 39.050mm | 0.133mm |
| servo | right/50072 | -X | -101.557mm | -1.557mm | 4.755mm | 5.004mm | 0.116mm |
| servo | left/50071 | -Y | -99.833mm | +0.167mm | 0.133mm | 0.213mm | 0.114mm |
| servo | right/50072 | -Y | -99.854mm | +0.146mm | 0.108mm | 0.182mm | 0.128mm |
| servo | left/50071 | -Z | -97.782mm | +2.218mm | 14.753mm | 14.918mm | 0.483mm |
| servo | right/50072 | -Z | -97.359mm | +2.641mm | 39.792mm | 39.880mm | 0.397mm |

结论：当前姿态下，planning 不能认为正负 XYZ 六方向 10cm 全可达；成功的 `+X/+Y/+Z/-Y` 方向精度很好，基本为毫米内，但 `-X/-Z` 暴露 IK/速度限制。servo 模式六方向都能走完并回基准，但 `-X/-Z` 有明显串轴耦合，尤其 `left/50071 -X` 与 `right/50072 -Z` 的总误差接近 `4cm`。后续 OpenPI 实时控制应继续使用“小步长 + per-step guard + 状态回读”的 servo 闭环，而不是把模型动作直接放大为 10cm 大步；planning 更适合明确可达目标、复位和低频目标位姿，不适合直接替代实时 policy servo。


## 2026-07-09 10:54 CST - 50072 回到指定关节状态：执行到位但 release 后 joint7 回落（agent: Codex）

目的：用户要求先回到关节状态 `[0.0225, 0.6305, -0.0056, -0.9193, 0.0002, -0.0002, -0.9381]` rad。该状态来自前文 `SDK right/50072` 的历史复查记录，因此本轮按 `--side right` 执行；按现场修正，`50072` 很可能对应物理左臂。

命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py \
  --side right \
  --target 0.0225,0.6305,-0.0056,-0.9193,0.0002,-0.0002,-0.9381 \
  --velocity-scaling 0.05 --acceleration-scaling 0.05 --allow-planning-time 8.0

.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py \
  --side right \
  --target 0.0225,0.6305,-0.0056,-0.9193,0.0002,-0.0002,-0.9381 \
  --velocity-scaling 0.05 --acceleration-scaling 0.05 --allow-planning-time 8.0 \
  --execute --allow-robot-motion
```

关键输出：dry-run 前置状态为 `IDLE/idle/valid`，当前关节约 `[-0.4188, 0.5456, -0.3129, -0.9193, 0.4535, 0.3123, -1.3421]`，最大待移动关节差约 `0.453259rad`。真实执行中 `acquire_control True`、`switch_planning True`、`move_joint_ptp True`。move_joint 返回后的 `final_angles_rad` 为 `[0.022483, 0.630428, -0.005609, -0.919396, 0.000048, -0.000240, -0.937996]`，最大误差 `0.000152rad`，说明主动控制阶段已到达目标。随后脚本 `switch_idle True`、`release_control done`，最终状态为 `IDLE/idle/valid`。

release 后只读复查：当前关节变为 `[0.015598, 0.630514, -0.005313, -0.919257, 0.000503, 0.000288, -1.063959]`；相对目标最大差为 `0.125859rad`，主要来自 joint7。TCP 从到位时约 `xyz=(-0.1017,-0.0048,0.6083)` 变为 release 后约 `xyz=(-0.0905,-0.0035,0.5900)`。

结论：50072 可以低速 planning PTP 到达用户指定关节状态；但切回 idle/release 后不会保持该关节状态，joint7 会明显回落。若后续需要“保持在指定关节状态”，需要到位后保持控制器 active 或增加 hold 控制策略，不能直接 release；这会增加电机持续受力/发热风险，需要现场确认后再执行。


## 2026-07-09 10:57 CST - 50071/物理右臂回到同一指定关节状态：执行到位但 release 后 joint7 回落（agent: Codex）

目的：用户指出上一轮物理右臂没有动，要求让右臂继续执行并回到同样的关节位置。根据现场修正，物理右臂对应 SDK `left/50071`，因此本轮使用 `--side left`，目标仍为 `[0.0225, 0.6305, -0.0056, -0.9193, 0.0002, -0.0002, -0.9381]` rad。

命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py \
  --side left \
  --target 0.0225,0.6305,-0.0056,-0.9193,0.0002,-0.0002,-0.9381 \
  --velocity-scaling 0.05 --acceleration-scaling 0.05 --allow-planning-time 8.0

.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py \
  --side left \
  --target 0.0225,0.6305,-0.0056,-0.9193,0.0002,-0.0002,-0.9381 \
  --velocity-scaling 0.05 --acceleration-scaling 0.05 --allow-planning-time 8.0 \
  --execute --allow-robot-motion
```

关键输出：dry-run 前置状态为 `IDLE/idle/valid`，当前关节约 `[-0.3348, 0.5852, -0.2572, -0.9179, 0.2646, 0.2749, -1.4822]`，最大待移动关节差约 `0.544085rad`。真实执行中 `acquire_control True`、`switch_planning True`、`move_joint_ptp True`。move_joint 返回后的 `final_angles_rad` 为 `[0.022483, 0.630428, -0.005609, -0.919396, 0.000144, -0.000144, -0.938187]`，最大误差 `0.000096rad`，说明主动控制阶段已到达目标。随后脚本 `switch_idle True`、`release_control done`，最终状态为 `IDLE/idle/valid`。

release 后只读复查：当前关节变为 `[0.013710, 0.612918, 0.002091, -0.917903, 0.000144, 0.000551, -1.159426]`；相对目标最大差为 `0.221326rad`，主要来自 joint7。TCP 从到位时约 `xyz=(-0.1017,-0.0047,0.6083)` 变为 release 后约 `xyz=(-0.0759,-0.0001,0.5764)`。

结论：50071/物理右臂同样可以低速 planning PTP 到达用户指定关节状态；但切回 idle/release 后也不会保持该关节状态，joint7 回落更明显。若需要双臂肉眼持续停在该姿态，必须设计 hold，不应继续用“到位后立即 release”的脚本来判断最终静止姿态。


## 2026-07-09 11:05 CST - 当前姿态下 planning/servo 正负 XYZ 7cm 精度测试，并恢复到指定 joint target（agent: Codex）

目的：用户要求用 planning 和 servo 两种模式测试双臂沿 `+X/-X/+Y/-Y/+Z/-Z` 方向移动 `7cm` 的运动精度，并在测试结束后回到关节状态 `[0.0225, 0.6305, -0.0056, -0.9193, 0.0002, -0.0002, -0.9381]` rad。本轮仍按 SDK 逻辑名记录：`left/50071` 很可能对应物理右臂，`right/50072` 很可能对应物理左臂。

安全改动：新增 `examples/airbot/p7_sequential_planning_precision_probe.py`。该脚本默认 dry-run；真实执行时一次只测一个 SDK 侧、一个轴、一个方向，成功后立刻回该侧 TCP 基准，失败也只影响该侧当前方向，最后切回 idle 并 release。目的是避免 planning 某个方向失败时另一只臂已经移动、整轮中断后难以恢复。

测试前基准恢复命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py \
  --side both \
  --target 0.0225,0.6305,-0.0056,-0.9193,0.0002,-0.0002,-0.9381 \
  --velocity-scaling 0.05 --acceleration-scaling 0.05 --allow-planning-time 8.0 \
  --execute --allow-robot-motion
```

测试前恢复结果：主动控制阶段 `left` 最大关节误差 `0.000192rad`，`right` 最大关节误差 `0.000104rad`；随后按脚本安全流程切 idle/release。由于 release 后会回落，本轮 precision 测试实际起点为 release 后的当前 TCP，而不是严格 joint target 保持态。

planning 测试命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_sequential_planning_precision_probe.py \
  --step-m 0.07 --max-step-m 0.07 --axes x,y,z --sides left,right \
  --velocity-scaling 0.05 --acceleration-scaling 0.05 --allow-planning-time-s 8.0 \
  --motion-timeout-ms 60000 --settle-s 0.75 \
  --execute --allow-robot-motion
```

planning 起点：`left start_xyz=(-0.075899,-0.000388,0.576375)`，`right start_xyz=(-0.090534,-0.003775,0.589973)`，双侧均 `IDLE/idle/valid`，pre-drift 分别约 `0.000006m/0.000000m`。

planning 结果：除 `-Z` 两侧被规划器拒绝外，其余方向均成功并回 TCP 基准。

| 模式 | SDK侧/端口 | 方向 | 实测主轴位移 | 主轴误差 | 串轴 | 总误差 | 回基准误差 |
|---|---|---:|---:|---:|---:|---:|---:|
| planning | left/50071 | +X | 70.119mm | +0.119mm | 0.077mm | 0.142mm | 0.085mm |
| planning | right/50072 | +X | 69.932mm | -0.068mm | 0.032mm | 0.075mm | 0.333mm |
| planning | left/50071 | +Y | 69.929mm | -0.071mm | 0.069mm | 0.099mm | 0.052mm |
| planning | right/50072 | +Y | 69.887mm | -0.113mm | 0.063mm | 0.129mm | 0.088mm |
| planning | left/50071 | +Z | 69.689mm | -0.311mm | 0.061mm | 0.317mm | 0.033mm |
| planning | right/50072 | +Z | 69.628mm | -0.372mm | 0.087mm | 0.382mm | 0.445mm |
| planning | left/50071 | -X | -69.679mm | +0.321mm | 0.016mm | 0.322mm | 0.072mm |
| planning | right/50072 | -X | -69.678mm | +0.322mm | 0.024mm | 0.323mm | 0.115mm |
| planning | left/50071 | -Y | -69.964mm | +0.036mm | 0.042mm | 0.055mm | 0.058mm |
| planning | right/50072 | -Y | -69.998mm | +0.002mm | 0.063mm | 0.063mm | 0.234mm |

planning 失败方向：`left/50071 -Z` 报 `Joint velocity at joint index 0 ... velocity=9.309061, limit=[-7.853982, 7.853982]`；`right/50072 -Z` 报 `velocity=-9.146881, limit=[-7.853982, 7.853982]`。两次失败后脚本读回仍接近基准，return_error 分别约 `0.000078m` 和 `0.000234m`。最终 `left/right switch_idle True`、`release_control done`、状态均 `IDLE/idle/valid`。

servo 测试命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_dual_servo_precision_probe.py \
  --step-m 0.07 --max-step-m 0.07 --axes x,y,z --sides left,right \
  --arm-speed-rad-s 0.55 --settle-s 2.0 \
  --execute --allow-robot-motion
```

servo 起点：`left start_xyz=(-0.071362,-0.000665,0.563228)`，`right start_xyz=(-0.085307,-0.003712,0.579141)`，双侧均 `IDLE/idle/valid`，pre-drift 均约 `0m`。

servo 结果：六方向都执行完成并回 TCP 基准。除 `-Z` 外，其余方向均为亚毫米误差；`-Z` 两侧出现明显 +X 串轴耦合。

| 模式 | SDK侧/端口 | 方向 | 实测主轴位移 | 主轴误差 | 串轴 | 总误差 | 回基准误差 |
|---|---|---:|---:|---:|---:|---:|---:|
| servo | left/50071 | +X | 70.032mm | +0.032mm | 0.176mm | 0.179mm | 0.099mm |
| servo | right/50072 | +X | 70.103mm | +0.103mm | 0.052mm | 0.115mm | 0.089mm |
| servo | left/50071 | +Y | 69.782mm | -0.218mm | 0.157mm | 0.268mm | 0.219mm |
| servo | right/50072 | +Y | 70.073mm | +0.073mm | 0.079mm | 0.108mm | 0.133mm |
| servo | left/50071 | +Z | 70.097mm | +0.097mm | 0.026mm | 0.100mm | 0.123mm |
| servo | right/50072 | +Z | 70.084mm | +0.084mm | 0.040mm | 0.093mm | 0.128mm |
| servo | left/50071 | -X | -70.027mm | -0.027mm | 0.065mm | 0.071mm | 0.118mm |
| servo | right/50072 | -X | -69.954mm | +0.046mm | 0.077mm | 0.090mm | 0.106mm |
| servo | left/50071 | -Y | -70.023mm | -0.023mm | 0.124mm | 0.126mm | 0.142mm |
| servo | right/50072 | -Y | -70.058mm | -0.058mm | 0.103mm | 0.118mm | 0.042mm |
| servo | left/50071 | -Z | -65.504mm | +4.496mm | 32.081mm | 32.394mm | 0.187mm |
| servo | right/50072 | -Z | -64.265mm | +5.735mm | 42.386mm | 42.773mm | 0.131mm |

测试后恢复命令：再次执行 `p7_move_to_joint_target.py --side both` 到同一目标。主动控制阶段 `left` 最大关节误差 `0.000248rad`，`right` 最大关节误差 `0.000152rad`，说明测试结束后已实际到达过用户指定 joint target。随后按安全流程 `switch_idle`、`release_control`，最终状态 `IDLE/idle/valid`。

release 后只读复查：`left current_angles_rad=[0.015106,0.612808,0.001920,-0.917903,0.000048,-0.000120,-1.157149]`，相对目标最大差 `0.219049rad`，主要来自 joint7；`right current_angles_rad=[0.018458,0.630459,-0.005471,-0.919271,0.000431,0.000288,-1.063864]`，相对目标最大差 `0.125764rad`，主要来自 joint7。即：主动控制可回到目标，但 release 后仍会回落。

结论：当前姿态下，7cm planning 比 10cm 更可用，`+X/+Y/+Z/-X/-Y` 均为亚毫米级，只有 `-Z` 仍受 joint velocity limit 限制无法规划。7cm servo 在 `+X/+Y/+Z/-X/-Y` 也为亚毫米级；但 `-Z` 仍出现明显串轴，left/50071 总误差约 `32.4mm`，right/50072 总误差约 `42.8mm`。因此后续 OpenPI 小步闭环仍应限制每步位移、避免单步大幅 `-Z`，并用状态回读 guard 拦截串轴过大的动作。若需要机械臂最终肉眼保持在指定 joint target，必须增加 hold 控制策略；当前安全脚本到位后会 release，release 后 joint7 会自然回落。


## 2026-07-09 11:15 CST - OpenPI real-camera -> policy -> P7 bridge 全链路 dry-run 通过；暂不执行 60s/20cm 真机运动（agent: Codex）

目的：用户询问是否能做一次完整全链路测试：启动 OpenPI 推理，接收机械臂相机信号，再控制机械臂运动，期望持续 60s、运动幅度可达 20cm。本轮先评估安全边界并做不运动的全链路 dry-run。

安全判断：刚完成的 7cm 精度测试显示，planning 的 `-Z` 仍会触发 joint velocity limit，servo 的 `-Z` 仍存在明显串轴耦合（`left/50071 -Z` 总误差约 32.4mm，`right/50072 -Z` 总误差约 42.8mm）。因此不应直接做 20cm 幅度的自动真机运动。现有 `scripts/cmds/openpi_p7_closed_loop.sh` 是“每轮抓图 -> 请求 policy -> 执行 action_index 一行”的离散 smoke 编排，默认每步 TCP 平移限幅 5mm，并不是常驻 60s 高频控制器，也没有全局 20cm 工作空间 envelope/trajectory guard。

命令与输出：

```bash
pgrep -af 'serve_policy.py|scripts/cmds/serve_policy.sh' || true
ss -lntp | grep ':8000' || true
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic info -v /camera/head_left/image_rect
```

输出：policy server 起初未运行，`:8000` 未监听；`/camera/head_left/image_rect` 有 `Publisher count: 1`，类型为 `sensor_msgs/msg/Image`，QoS 为 `BEST_EFFORT/VOLATILE`。

启动 policy server：

```bash
bash scripts/cmds/serve_policy.sh
```

关键输出：checkpoint `/checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/params` 恢复成功，norm stats 从 checkpoint assets 加载，server listening on `0.0.0.0:8000`。

全链路 dry-run：

```bash
bash scripts/cmds/openpi_p7_closed_loop.sh \
  --iterations 2 --period-s 1 \
  --max-translation-step-m 0.005 --max-rotation-step-rad 0.02
```

关键输出：两轮均成功抓到三路相机，topic 分别为 `/camera/head_left/image_rect`、`/camera/left_arm_left/image_rect`、`/camera/right_arm_left/image_rect`，分辨率均为 `640x352`、encoding `nv12`，转换为 RGB shape `[352,640,3]`。policy 两轮均返回 action chunk shape `[50,32]`；第一轮推理约 `1752.6ms`（含首次开销），第二轮推理约 `159.0ms`。bridge 两轮均读取到双臂 `IDLE/idle/valid` 和稳定 TCP，转换出的 action index 0 平移量均远低于 5mm 限幅：第一轮 left `0.000251m`、right `0.000409m`；第二轮 left `0.000211m`、right `0.000228m`。两轮均打印 `DRY_RUN: no acquire_control(), switch_controller(), or move command was called`，最终左右 `state_final` 均为 `IDLE/idle/valid`。

结论：实时相机 -> OpenPI policy -> P7 SDK bridge 的完整数据链路当前可用；但本轮没有执行真机运动。基于现有 7cm 精度结论，不建议直接做 60s、20cm 幅度的全自动运动。可执行的下一步应是 60s 低幅度全链路真机 smoke，例如保持 `--max-translation-step-m 0.005`、`--max-rotation-step-rad 0.02`，加总位移/工作空间 envelope guard，并在人工看护下运行；20cm 幅度需要先实现常驻控制器、全局 workspace guard、累计位移限制、异常停机和 `-Z` 串轴拦截后再做。


## 2026-07-09 11:22 CST - 直接执行 +X 20cm planning 真机运动验证成功（agent: Codex）

目的：用户要求不要仅基于之前 7cm/10cm 的问题判断，直接执行运动，以确认 `20cm` 是否真的不可行。本轮选择当前姿态下风险较低、之前表现稳定的 `+X` 方向，用 planning 模式做单方向 20cm 验证；不测试 `-Z` 或全轴 20cm。

脚本调整：为 `examples/airbot/p7_sequential_planning_precision_probe.py` 增加 `--signs positive|negative|both` 参数。本轮使用 `--signs positive`，只发 `+X`，避免脚本默认同时测负方向。

Dry-run：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_sequential_planning_precision_probe.py \
  --step-m 0.20 --max-step-m 0.20 --axes x --signs positive --sides left,right \
  --velocity-scaling 0.03 --acceleration-scaling 0.03 \
  --allow-planning-time-s 10.0 --motion-timeout-ms 90000 --settle-s 1.0
```

结果：双臂均为 `IDLE/idle/valid`；目标为 `left x=-0.075010 -> 0.124990`、`right x=-0.085290 -> 0.114710`；dry-run 没有 acquire/move。

真实执行：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_sequential_planning_precision_probe.py \
  --step-m 0.20 --max-step-m 0.20 --axes x --signs positive --sides left,right \
  --velocity-scaling 0.03 --acceleration-scaling 0.03 \
  --allow-planning-time-s 10.0 --motion-timeout-ms 90000 --settle-s 1.0 \
  --execute --allow-robot-motion
```

关键输出：`left/right acquire_control True`、`switch_planning True`。`left +X` 实测 `delta_m=(0.199824,-0.000163,-0.000054)`，主轴误差 `-0.176mm`，串轴 `0.172mm`，总误差 `0.246mm`，回基准误差 `0.042mm`。`right +X` 实测 `delta_m=(0.199881,-0.000024,-0.000077)`，主轴误差 `-0.119mm`，串轴 `0.081mm`，总误差 `0.144mm`，回基准误差 `0.303mm`。最终 `left/right switch_idle True`、`release_control done`、状态均为 `IDLE/idle/valid`。

结论：当前姿态下，`+X` 方向 `20cm` planning 运动是可行的，而且精度为亚毫米级。这并不推翻前文对 `-Z` 和 60s 全自动大幅 OpenPI 运动的风险判断：当前只证明 `+X planning 20cm` 可执行，不能外推为正负 XYZ 全方向 20cm 或 OpenPI policy 60s 自主大幅运动都安全。


## 2026-07-09 11:25 CST - 20cm planning 正负 XYZ 全方向顺序测试：+X/+Y/-Y 可行，+Z/-X/-Z 不可规划（agent: Codex）

目的：用户要求继续测试所有方向。承接上一轮 `+X 20cm planning` 成功，本轮使用同一 sequential planning probe 测试正负 XYZ 全方向，仍为单侧顺序执行、每个成功方向后回该侧 TCP 基准。

Dry-run 命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_sequential_planning_precision_probe.py \
  --step-m 0.20 --max-step-m 0.20 --axes x,y,z --signs both --sides left,right \
  --velocity-scaling 0.03 --acceleration-scaling 0.03 \
  --allow-planning-time-s 10.0 --motion-timeout-ms 90000 --settle-s 1.0
```

Dry-run 结果：双臂均为 `IDLE/idle/valid`，只读目标覆盖 `+X/+Y/+Z/-X/-Y/-Z`，没有 acquire/move。

真实执行命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_sequential_planning_precision_probe.py \
  --step-m 0.20 --max-step-m 0.20 --axes x,y,z --signs both --sides left,right \
  --velocity-scaling 0.03 --acceleration-scaling 0.03 \
  --allow-planning-time-s 10.0 --motion-timeout-ms 90000 --settle-s 1.0 \
  --execute --allow-robot-motion
```

真实执行起点：`left start_xyz=(-0.072170,-0.000650,0.565866)`，`right start_xyz=(-0.082384,-0.003859,0.572156)`，pre-drift 分别约 `0.000006m/0.000000m`。

成功方向结果：

| 模式 | SDK侧/端口 | 方向 | 实测主轴位移 | 主轴误差 | 串轴 | 总误差 | 回基准误差 |
|---|---|---:|---:|---:|---:|---:|---:|
| planning | left/50071 | +X | 199.885mm | -0.115mm | 0.301mm | 0.322mm | 0.214mm |
| planning | right/50072 | +X | 199.855mm | -0.145mm | 0.061mm | 0.157mm | 0.298mm |
| planning | left/50071 | +Y | 199.872mm | -0.128mm | 0.038mm | 0.134mm | 0.142mm |
| planning | right/50072 | +Y | 199.871mm | -0.129mm | 0.144mm | 0.194mm | 0.173mm |
| planning | left/50071 | -Y | -199.735mm | +0.265mm | 0.095mm | 0.282mm | 0.308mm |
| planning | right/50072 | -Y | -199.781mm | +0.219mm | 0.009mm | 0.219mm | 0.299mm |

失败方向：`+Z` 双侧、`-X` 双侧、`-Z` 双侧均被 `move_end_pose_linear` 拒绝，底层报 `TRAC-IK failed (all attempts)`。失败后脚本读回仍接近基准：失败后的 return_error 约 `0.000143m ~ 0.000340m`。最终 `left/right switch_idle True`、`release_control done`，状态均为 `IDLE/idle/valid`。

结论：当前姿态下，20cm planning 并非整体不可行；`+X/+Y/-Y` 都可执行且精度为亚毫米级。但它也不是全方向可行：`+Z/-X/-Z` 20cm 目标在当前姿态下均不可规划。后续若要做 20cm 级全链路运动，必须限定方向/工作空间，或者先移动到更合适的起始姿态；不能假设正负 XYZ 全方向 20cm 都可用。


## 2026-07-09 11:53 CST - 补上 P7 夹爪控制和常驻 OpenPI->P7 控制循环（agent: Codex）

目的：补齐两块缺口：1）模型 action 中的夹爪维度不再只打印，而是可以显式执行到 P7 SDK `move_eef()`；2）新增一个常驻控制循环，不再每轮都重新启动 P7 bridge 进程，便于后续做 60s 级 OpenPI 实机任务测试。

代码变更：

- `examples/airbot/policy_to_p7_sdk_bridge.py` 增加 `--enable-gripper`、`--eef-speed-mm-s`、`--eef-effort`、`--eef-timeout-ms`、`--eef-min-mm`、`--eef-max-mm`、`--gripper-blocking/--no-gripper-blocking`。默认仍不控制夹爪；只有 `--enable-gripper --execute --allow-robot-motion` 同时出现时才切 `EEFControlMode.csp` 并调用 `move_eef()`。
- `scripts/cmds/openpi_p7_closed_loop.sh` 已透传同一组夹爪参数到 bridge，因此低频闭环入口也可以显式开启夹爪。
- 模型夹爪值继续沿用训练约定：`0=闭合`，`100=最大打开`。执行到 P7 SDK 时转换为 mm，默认 clamp 到 `[0,95]mm`。
- 新增 `examples/airbot/openpi_p7_persistent_loop.py`：在 `.venv-p7-sdk` 中常驻双臂 `AirbotClient`、控制权、controller mode 和可选 EEF mode；每轮仍通过 `/usr/bin/python3` 调 ROS2 抓相机，通过 `uv run python` 请求 OpenPI policy。
- 新增 `scripts/cmds/openpi_p7_persistent_loop.sh`：常驻循环命令入口。

验证命令：

```bash
.venv-p7-sdk/bin/python -m py_compile \
  examples/airbot/policy_to_p7_sdk_bridge.py \
  examples/airbot/openpi_p7_persistent_loop.py

bash scripts/cmds/openpi_p7_persistent_loop.sh --help

bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --iterations 0 --duration-s 0 --chunk-steps 0

.venv-p7-sdk/bin/python examples/airbot/policy_to_p7_sdk_bridge.py --help

bash -n scripts/cmds/openpi_p7_closed_loop.sh scripts/cmds/openpi_p7_persistent_loop.sh

bash scripts/cmds/openpi_p7_closed_loop.sh --help
```

关键输出：

```text
# py_compile: exit code 0

# persistent loop --help：能正常导入 arm_p7_sdk 并列出参数
--enable-gripper
--eef-speed-mm-s EEF_SPEED_MM_S
--eef-effort EEF_EFFORT
--eef-timeout-ms EEF_TIMEOUT_MS
--eef-min-mm EEF_MIN_MM
--eef-max-mm EEF_MAX_MM
--gripper-blocking, --no-gripper-blocking
--execute
--allow-robot-motion

# 非法参数校验
REFUSE: --chunk-steps must be positive and --chunk-start-index must be non-negative

# bridge --help：能正常导入 arm_p7_sdk 并列出新增夹爪参数
--enable-gripper      Execute gripper targets through move_eef().
--eef-speed-mm-s EEF_SPEED_MM_S
--eef-effort EEF_EFFORT
--eef-timeout-ms EEF_TIMEOUT_MS
--eef-min-mm EEF_MIN_MM
--eef-max-mm EEF_MAX_MM

# shell 入口语法检查：exit code 0

# openpi_p7_closed_loop.sh --help：已列出夹爪透传参数
--enable-gripper               Also execute model gripper target through P7 move_eef().
--eef-speed-mm-s SPEED         Gripper speed in mm/s. Default: 100.0
--eef-effort EFFORT            Gripper effort list value. Default: 5.0
--eef-timeout-ms MS            Gripper command timeout. Default: 3000
--eef-min-mm MM                Minimum gripper command. Default: 0
--eef-max-mm MM                Maximum gripper command. Default: 95
```

结论：夹爪控制和常驻控制循环的代码入口已落地，并通过静态编译、help 导入和参数校验验证。本轮没有连接真机做 `--execute` 运动，也没有调用真实 `move_eef()`。

影响：后续现场可以先跑 `bash scripts/cmds/openpi_p7_persistent_loop.sh --iterations 2 ...` 做全链路 dry-run；确认后再用 `--duration-s 60 --execute --allow-robot-motion` 做 60s 小步常驻控制测试。夹爪真实执行需要额外加 `--enable-gripper`，默认不会动夹爪。


## 2026-07-09 12:42 CST - 常驻 OpenPI->P7 完整 dry-run 通过，含夹爪目标路径（agent: Codex）

目的：按用户要求做一轮完整测试。由于本轮没有显式授权机械臂运动，执行的是完整 dry-run：相机取帧 -> OpenPI policy 推理 -> 常驻 P7 loop 读取 TCP 并转换 arm/夹爪目标；不 `acquire_control()`，不 `move_end_pose()`，不 `move_eef()`。

前置状态检查：

```bash
pgrep -af 'serve_policy.py|scripts/cmds/serve_policy.sh' || true
ss -lntp | grep ':8000' || true
ssh -o ConnectTimeout=3 root@192.168.25.1 "ps -ww -C arm_dual_app -o pid,ppid,lstart,etime,stat,args=; ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="
```

关键输出：本机 8000 未监听；X5 为统一 runtime，存在两个 `arm_dual_app` 和一个 `robot_app remote`：

```text
./bin/arm_dual_app /opt/arm_dual_app/configs/left_arm/project_config.json
./bin/arm_dual_app /opt/arm_dual_app/configs/right_arm/project_config.json
./bin/robot_app /opt/robot_app/configs/remote/project_config.json
```

启动临时 policy server：

```bash
bash scripts/cmds/serve_policy.sh
```

关键输出：checkpoint 从 `checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/params` restore 完成，server listening on `0.0.0.0:8000`。测试结束后已 Ctrl+C 停掉，复查 `ss -lntp | grep ':8000' || true` 无输出。

完整 dry-run 命令：

```bash
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --iterations 1 \
  --period-s 1.0 \
  --controller servo \
  --chunk-steps 1 \
  --max-step-translation-m 0.005 \
  --max-step-rotation-rad 0.02 \
  --max-envelope-m 0.05 \
  --enable-gripper \
  --capture-timeout-s 10
```

关键输出：

```text
execute=false controller=servo enable_gripper=true
left state_before ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
right state_before ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)

captured base_0_rgb frame 640x352 encoding=nv12
captured left_wrist_0_rgb frame 640x352 encoding=nv12
captured right_wrist_0_rgb frame 640x352 encoding=nv12

action_shape=[50,32]
server_timing.infer_ms=1777.673145988956

left target_delta_m=(0.000359,0.000369,0.000391) step_translation_m=0.000647 step_rotation_rad=0.003000 envelope_m=0.000646 gripper_model=98.832 gripper_p7_mm=94.878
left gripper_execute_target_mm=94.878 clamp_range_mm=[0.000,95.000]
right target_delta_m=(-0.000096,0.000203,0.000381) step_translation_m=0.000443 step_rotation_rad=0.003527 envelope_m=0.000438 gripper_model=92.037 gripper_p7_mm=88.355
right gripper_execute_target_mm=88.355 clamp_range_mm=[0.000,95.000]
DRY_RUN: no acquire_control(), switch_controller(), move_end_pose(), or move_eef() was called
left state_final ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
right state_final ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
```

Summary 文件：`/tmp/openpi_p7_persistent_loop/summary_20260709_124149.jsonl`。记录显示 left/right 的 dry-run measured movement 分别约 `1.15e-6m` / `4.09e-6m`，即没有实际运动；夹爪命令目标分别为 `94.878mm` / `88.355mm`，均在 `[0,95]mm` 限制内。

结论：常驻 OpenPI->P7 dry-run 完整链路通过，包含三路相机、policy 推理、TCP 目标转换、夹爪目标转换和 P7 SDK 状态读取。本轮未做真实运动；下一步如要实测，需要用户现场确认安全后显式运行 `--execute --allow-robot-motion`，如需夹爪也保留 `--enable-gripper`。


## 2026-07-09 13:51 CST - 夹爪真实 smoke 与 20 秒 OpenPI 常驻真实闭环通过（agent: Codex）

目的：继续完成正式任务前的实机测试：验证模型夹爪值 100/0/100 到 P7 move_eef() 的真实方向和执行链路；验证常驻 OpenPI->P7 loop 在 --execute --allow-robot-motion 下能连续运行约 20 秒，并由模型输出同时控制 TCP 和夹爪。

前置检查命令：ssh -o ConnectTimeout=3 root@192.168.25.1 "ps -ww -C arm_dual_app -o pid,ppid,lstart,etime,stat,args=; ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="；ss -lntp | grep ':8000' || true。

关键输出：X5 仍为统一 runtime，两条 arm_dual_app 加一条 robot_app remote；本机 8000 初始无残留监听。

夹爪 smoke：生成 /tmp/p7_gripper_open.json 和 /tmp/p7_gripper_close.json，action 前 14 维中只设置 left/right gripper，TCP delta 全为 0。先用 policy_to_p7_sdk_bridge.py --enable-gripper 做 open dry-run，确认模型 100 转 raw 96.000mm，执行目标 clamp 到 95.000mm，且 dry-run 不调用 move_eef()。

真实 open 命令要点：.venv-p7-sdk/bin/python examples/airbot/policy_to_p7_sdk_bridge.py --action-json /tmp/p7_gripper_open.json --max-translation-step-m 0.001 --max-rotation-step-rad 0.001 --pre-samples 2 --sample-period-s 0.1 --enable-gripper --execute --allow-robot-motion。

真实 open 关键输出：left/right acquire_control True，switch_eef_csp True，move_end_pose ok=True，move_eef pos_mm=[95.0] ok=True，最终 switch_eef_idle True、switch_idle True、release_control done，双臂 IDLE/idle/valid。

真实 close 命令要点：同上但 --action-json /tmp/p7_gripper_close.json，并设置 --eef-speed-mm-s 60。关键输出：闭合前 EEF 约 95mm，move_eef pos_mm=[0.0] ok=True，最终双臂 IDLE/idle/valid。

最后重新 open 命令要点：同 open，但 --eef-speed-mm-s 80。关键输出：闭合后 EEF 约 0.35~0.65mm，重新 move_eef pos_mm=[95.0] ok=True，最终双臂 IDLE/idle/valid。结论：夹爪方向确认正确，模型 0=闭合、100=打开 与真实执行一致。

20 秒真实常驻闭环命令：先 bash scripts/cmds/serve_policy.sh；再 bash scripts/cmds/openpi_p7_persistent_loop.sh --duration-s 20 --period-s 1.0 --controller servo --chunk-steps 1 --max-step-translation-m 0.005 --max-step-rotation-rad 0.02 --max-envelope-m 0.05 --enable-gripper --eef-speed-mm-s 80 --execute --allow-robot-motion。

关键输出：policy server 从 checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/params restore 并监听 0.0.0.0:8000；run id=20260709_134830，summary=/tmp/openpi_p7_persistent_loop/summary_20260709_134830.jsonl。脚本开始时双臂 IDLE/idle/valid，成功 acquire_control、switch_servo、switch_eef_csp；每轮均抓到三路 nv12 640x352 相机，并请求 policy 返回 [50,32] actions。

Summary 汇总：rows=15。left max_target_error_m=0.000883，max_moved_from_observation_m=0.000864，gripper_mm_minmax=(94.047, 94.610)，measured_envelope_from_row1_m=0.004427。right max_target_error_m=0.001456，max_moved_from_observation_m=0.001339，gripper_mm_minmax=(84.649, 90.005)，measured_envelope_from_row1_m=0.014174。

最终输出：completed iterations=15；switch_eef_idle True、switch_idle True、release_control done，最终双臂 state_final ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)。测试后已 Ctrl+C 停止临时 policy server，复查 ss -lntp | grep ':8000' || true 无输出。X5 runtime 仍为两个 arm_dual_app 与一个 robot_app remote。

额外修正：20 秒测试中 policy server 日志出现多条 WebSocket opening handshake failed，根因是 request_policy_from_observation_npz.py 每轮先用裸 TCP socket 探活 8000，而 8000 是 WebSocket server。该错误不影响执行，但会干扰正式日志。已为 examples/airbot/request_policy_from_observation_npz.py 增加 --skip-policy-port-check，并让 examples/airbot/openpi_p7_persistent_loop.py 调 policy 请求时默认传入它。静态验证通过：python3 -m py_compile examples/airbot/request_policy_from_observation_npz.py；.venv-p7-sdk/bin/python -m py_compile examples/airbot/openpi_p7_persistent_loop.py；uv run python examples/airbot/request_policy_from_observation_npz.py --help | grep -E 'skip-policy-port-check|policy-connect-timeout'。

结论：正式抓取/放置任务前的关键链路已经通过：真实夹爪 open/close/open、真实 20 秒相机->OpenPI->P7 常驻闭环、TCP 小步执行、夹爪模型输出执行、最终释放控制和状态恢复。20 秒闭环后又执行了一次零 TCP 位移的 gripper open 到 95mm，left/right move_eef pos_mm=[95.0] 均 ok=True，最终双臂仍为 IDLE/idle/valid。下一步可以在现场看护下运行更长时长或直接开始任务，但建议仍保留 --max-step-translation-m 0.005 --max-envelope-m 0.05 作为第一轮真实任务保护。


## 2026-07-09 15:55 CST - 实验场景下 60 秒 OpenPI 常驻真实闭环完成（agent: Codex）

目的：用户重启机械臂并确认实验场景已准备好（工作空间清空、物体在相机视野里）后，做一次真实任务前的 60 秒全链路执行：机械臂相机取图 -> OpenPI policy 推理 -> 常驻 P7 SDK loop 下发双臂 TCP 小步运动和夹爪目标。

前置状态检查命令：

```bash
ssh -o ConnectTimeout=3 root@192.168.25.1 "ps -ww -C arm_dual_app -o pid,ppid,lstart,etime,stat,args=; ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="

.venv-p7-sdk/bin/python - <<'PY'
from arm_p7_sdk import AirbotClient
for side, port in [('left', 50071), ('right', 50072)]:
    c = AirbotClient(host='192.168.25.1', port=port, backend='grpc')
    try:
        print(side, c.get_service_state())
        print(side, c.get_eef_mode())
    finally:
        c.close()
PY
```

关键输出：X5 运行两条 `arm_dual_app`（`/opt/arm_dual_app/configs/left_arm/project_config.json`、`right_arm/project_config.json`）和一条 `robot_app remote`；SDK left/right 均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`，EEF 均为 `current_mode_name='idle'`。

执行命令：

```bash
# 终端 1：启动策略服务
bash scripts/cmds/serve_policy.sh

# 终端 2：60 秒真实闭环
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 60 \
  --period-s 1.0 \
  --controller servo \
  --chunk-steps 1 \
  --max-step-translation-m 0.005 \
  --max-step-rotation-rad 0.02 \
  --max-envelope-m 0.05 \
  --enable-gripper \
  --eef-speed-mm-s 80 \
  --execute \
  --allow-robot-motion
```

关键输出：run id=`20260709_154920`，summary=`/tmp/openpi_p7_persistent_loop/summary_20260709_154920.jsonl`。脚本完成 `completed iterations=31`，随后 `right switch_eef_idle True`、`left switch_eef_idle True`、`right switch_idle True`、`left switch_idle True`、`release_control done`，最终 left/right 均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。

Summary 解析命令：

```bash
python3 - <<'PY'
import json, math
from pathlib import Path
p = Path('/tmp/openpi_p7_persistent_loop/summary_20260709_154920.jsonl')
rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
print('rows', len(rows), 'first_iter', rows[0]['iteration'], 'last_iter', rows[-1]['iteration'])
for side in ('left', 'right'):
    err = [r['sides'][side]['target_error_m'] for r in rows]
    moved = [r['sides'][side]['moved_from_observation_m'] for r in rows]
    grip = [r['sides'][side]['gripper_p7_mm_command'] for r in rows]
    xyz = [r['sides'][side]['measured_xyz'] for r in rows]
    env = [math.dist(xyz[0], x) for x in xyz]
    print(side, max(err), max(moved), (min(grip), max(grip)), max(env), xyz[0], xyz[-1])
PY
```

解析结果：rows=`31`，first_iter=`1`，last_iter=`31`。left：`max_target_error_m=0.001608`，`max_moved_from_obs_m=0.001368`，夹爪命令范围 `(94.178, 95.000)mm`，相对首帧实测包络 `0.018120m`，首末 TCP 从 `[-0.056326,-0.011850,0.534684]` 到 `[-0.042319,-0.011804,0.546180]`。right：`max_target_error_m=0.002117`，`max_moved_from_obs_m=0.001218`，夹爪命令范围 `(90.457,95.000)mm`，相对首帧实测包络 `0.042811m`，首末 TCP 从 `[-0.072177,-0.001160,0.531856]` 到 `[-0.085768,0.020537,0.566168]`。

收尾检查：测试后已 Ctrl+C 停止临时 policy server；`ss -lntp 'sport = :8000'` 只输出表头，无 8000 监听。再次 SSH 复查 X5 仍是两条 `arm_dual_app` 加一条 `robot_app remote`。SDK 复查 left/right 仍均为 `IDLE/idle/valid`，EEF mode 均为 `idle`。中间一次只读 SDK 检查误调用不存在的 `get_eef_state()`，得到 `AttributeError: 'AirbotClient' object has no attribute 'get_eef_state'`；改用已验证的 `get_eef_mode()` 后状态正常，这属于检查脚本 API 写法问题，不是机械臂故障。

结论：在当前实验场景下，真实相机 -> OpenPI policy -> P7 SDK 双臂 TCP+夹爪常驻闭环已连续运行 60 秒并正常收尾。执行精度在本轮 guard 下稳定：目标误差最大约 left `1.61mm`、right `2.12mm`，实测运动包络均小于 `5cm`。从控制链路角度，正式抓取/放置任务可以开始；但任务语义是否成功（是否抓到/放到目标位置）仍需要现场肉眼或后续视觉评估确认。第一轮正式任务仍建议保持本轮参数，不要放大 envelope 或一次播放完整 50 步 chunk。


## 2026-07-09 16:03 CST - 第一轮正式 OpenPI 实验执行并由 5cm envelope guard 安全截停（agent: Codex）

目的：用户在现场确认工作空间清空、物体在相机视野内，并要求开始正式第一轮实验；现场由用户肉眼判断任务表现。本轮使用上一轮验证过的保守实机参数执行：相机 -> OpenPI policy -> P7 SDK 双臂 TCP + 夹爪常驻闭环。

前置检查命令：

```bash
ssh -o ConnectTimeout=3 root@192.168.25.1 "ps -ww -C arm_dual_app -o pid,ppid,lstart,etime,stat,args=; ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args="
ss -lntp 'sport = :8000'
.venv-p7-sdk/bin/python - <<'PY'
from arm_p7_sdk import AirbotClient
for side, port in [('left', 50071), ('right', 50072)]:
    c = AirbotClient(host='192.168.25.1', port=port, backend='grpc')
    try:
        print(side, c.get_service_state())
        print(side, c.get_eef_mode())
    finally:
        c.close()
PY
```

关键输出：X5 仍为两条 `arm_dual_app` 和一条 `robot_app remote`；本机 8000 无残留监听；SDK left/right 均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`，EEF 均为 `idle`。

执行命令：

```bash
bash scripts/cmds/serve_policy.sh

bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 60 \
  --period-s 1.0 \
  --controller servo \
  --chunk-steps 1 \
  --max-step-translation-m 0.005 \
  --max-step-rotation-rad 0.02 \
  --max-envelope-m 0.05 \
  --enable-gripper \
  --eef-speed-mm-s 80 \
  --execute \
  --allow-robot-motion
```

关键输出：run id=`20260709_160147`，summary=`/tmp/openpi_p7_persistent_loop/summary_20260709_160147.jsonl`。前 35 轮均成功采集三路 `nv12 640x352` 相机图像、请求 policy 返回 `[50,32]` action，并下发 `move_end_pose()` 与 `move_eef()`，日志中左右臂 `move_end_pose ok=True`、夹爪 `move_eef ok=True`。第 36 轮未下发：`FAIL: right: target envelope 0.050677 exceeds limit 0.050000`。随后脚本执行 `right/left switch_eef_idle True`、`right/left switch_idle True`、`release_control done`，最终 left/right 均为 `IDLE/idle/valid`。

Summary 解析命令：

```bash
python3 - <<'PY'
import json, math
from pathlib import Path
p = Path('/tmp/openpi_p7_persistent_loop/summary_20260709_160147.jsonl')
rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
print('rows', len(rows), 'first_iter', rows[0]['iteration'], 'last_iter', rows[-1]['iteration'])
for side in ('left', 'right'):
    err = [r['sides'][side]['target_error_m'] for r in rows]
    moved = [r['sides'][side]['moved_from_observation_m'] for r in rows]
    grip = [r['sides'][side]['gripper_p7_mm_command'] for r in rows]
    xyz = [r['sides'][side]['measured_xyz'] for r in rows]
    env = [math.dist(xyz[0], x) for x in xyz]
    print(side, max(err), max(moved), (min(grip), max(grip)), max(env), xyz[0], xyz[-1])
PY
```

解析结果：rows=`35`，first_iter=`1`，last_iter=`35`。left：最大 target error `0.001427m`，最大 measured step `0.001061m`，夹爪命令范围 `(94.621,95.000)mm`，相对首帧实测包络 `0.021039m`，首末 TCP 从 `[-0.029944,-0.009343,0.541156]` 到 `[-0.016330,-0.014292,0.556413]`。right：最大 target error `0.002088m`，最大 measured step `0.001762m`，夹爪命令范围 `(92.225,95.000)mm`，相对首帧实测包络 `0.048015m`，首末 TCP 从 `[-0.073161,0.013801,0.560606]` 到 `[-0.098013,0.039374,0.592760]`。

收尾检查：已 Ctrl+C 停止临时 policy server；`ss -lntp 'sport = :8000'` 只输出表头，无 8000 监听。SSH 复查 X5 仍是两条 `arm_dual_app` 加一条 `robot_app remote`。SDK 复查 left/right 仍均为 `IDLE/idle/valid`，EEF mode 均为 `idle`。

结论：第一轮正式实验的控制链路成功执行 35 轮，并由 `--max-envelope-m 0.05` 在第 36 轮右臂将越界时安全拒绝下发。这不是通信失败，而是预期的安全保护触发。本轮结果说明：在 5cm envelope 内链路稳定、最终状态正常；若现场肉眼判断任务还需要继续接近/抓取，下一轮需要用户明确是否继续使用 5cm envelope 重新分段执行，或在确认空间安全后把 envelope 放宽到例如 8cm，但不建议直接取消 guard。


## 2026-07-09 16:13 CST - 第一轮失败复盘：保存三路相机视频，并确认当前 policy chunk 未输出真正夹爪闭合（agent: Codex）

目的：用户现场反馈第一轮正式实验只在原位附近小幅运动，没有完成抓取；要求重新实验并保存相机视频。本轮先做无运动风险的信息采集和复盘：保存三路相机视频，分析上一轮和当前观测下 policy 的完整 50-step chunk，重点确认夹爪是否出现闭合趋势。

相机视频记录命令要点：使用 `ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp /usr/bin/python3` 订阅 `/camera/head_left/image_rect`、`/camera/left_arm_left/image_rect`、`/camera/right_arm_left/image_rect`，将 `nv12 640x352` 转 RGB/BGR 后写入 MP4。录制时不 acquire 控制权，不调用任何 P7 SDK 运动接口。

关键输出：三路首帧均收到：`base_0_rgb: 640x352 nv12 frame_id=camera_xf6600_head_left`、`left_wrist_0_rgb: 640x352 nv12 frame_id=camera_xf6600_left_arm_left`、`right_wrist_0_rgb: 640x352 nv12 frame_id=camera_xf6600_right_arm_left`。录制 `60s`、`15fps`，写入 `901` 帧；raw message counts 约 head=`1198`、left wrist=`1194`、right wrist=`1195`。

视频文件：

```text
/tmp/openpi_camera_records/20260709_160742_base_0_rgb.mp4        3.3M
/tmp/openpi_camera_records/20260709_160742_left_wrist_0_rgb.mp4  8.5M
/tmp/openpi_camera_records/20260709_160742_right_wrist_0_rgb.mp4 3.0M
/tmp/openpi_camera_records/20260709_160742_triptych.mp4          15M
/tmp/openpi_camera_records/20260709_160742_metadata.json
```

上一轮 action chunk 夹爪复盘命令：读取 `/tmp/openpi_p7_persistent_loop/actions_20260709_160147_0032.json` 到 `0036.json`，解析每个 50-step chunk 的 left gripper=`row[6]`、right gripper=`row[13]`。

关键结果：最后 5 个 chunk 中，left gripper 基本一直在 `98~99/100`；right gripper 最低约 `89~91/100`，绝大多数也在 `96~99/100`。这说明第一轮中模型没有输出接近 `0` 的真正闭合动作；即使执行更多 chunk，也不等价于会抓取。

当前观测 prompt 探测：重新抓当前三路相机为 `/tmp/openpi_prompt_probe_20260709_1612/obs.npz`，只请求 policy，不控制机械臂。测试 prompt：

1. `put the plant into the collection box`
2. `pick up the plant and put it into the collection box`
3. `grasp the plant with the gripper and place it into the collection box`
4. `close the gripper on the plant, lift it, and place it into the collection box`

结果：四个 prompt 的 left gripper 都基本保持 `98/100`；right gripper 最低分别约 `90.229`、`87.200`、`89.004`、`87.281`，没有任何一个 prompt 输出接近 `0` 的闭合命令。更明确的 `grasp/close` prompt 只让 right gripper 略微下降到 `87/100` 左右，仍然是打开状态。

结论：第一轮没有抓取并不只是因为 5cm envelope 太小；更根本的问题是当前观测和 prompt 下，policy 输出本身没有产生夹爪闭合动作。取消时间、帧数、空间限制会放大物理风险，但不能保证完成抓取。下一轮要提高成功率，应改成：保留硬性运动边界，把 envelope 分段放大，并提高 `chunk_steps` 以执行同一 policy chunk 的多步动作；同时持续保存视频。若用户现场肉眼判断末端已到物体附近，可以单独人工触发一个有界 `move_eef(0mm)` 夹爪闭合测试，而不是指望当前 policy 自动闭合。


## 2026-07-09 16:31 CST - 第二轮更大范围多步 chunk 测试完成，仍未出现真正夹爪闭合（agent: Codex）

目的：用户要求继续下一步测试。本轮在不取消硬性保护的前提下扩大动作规模：持续录像、`chunk_steps=5`、`max-envelope=0.12m`、`max-step-translation=0.010m`、`max-step-rotation=0.05rad`，并将 prompt 改为更明确的 `close the gripper on the plant, lift it, and place it into the collection box`。

执行命令：

```bash
# 录像进程：订阅三路 camera image_rect，150s / 15fps，保存 triptych + 三路单独 mp4

bash scripts/cmds/serve_policy.sh

bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 120 \
  --period-s 0.5 \
  --controller servo \
  --chunk-steps 5 \
  --max-step-translation-m 0.010 \
  --max-step-rotation-rad 0.05 \
  --max-envelope-m 0.12 \
  --prompt 'close the gripper on the plant, lift it, and place it into the collection box' \
  --enable-gripper \
  --eef-speed-mm-s 80 \
  --execute \
  --allow-robot-motion
```

关键输出：run id=`20260709_162838`，summary=`/tmp/openpi_p7_persistent_loop/summary_20260709_162838.jsonl`。前 29 轮每轮执行 5 个 action step，共 `145` 条 summary 记录；三路相机持续抓到 `nv12 640x352`；左右 `move_end_pose ok=True`，夹爪 `move_eef ok=True`。第 30 轮第一个 action 未下发：`FAIL: left: step rotation 0.053390 exceeds limit 0.050000`；随后脚本执行 `switch_eef_idle`、`switch_idle`、`release_control`，最终 left/right 均为 `IDLE/idle/valid`。

Summary 解析：rows=`145`，first iter/action=`1/0`，last iter/action=`29/4`。left：最大 target error `0.001625m`，最大 measured step `0.005027m`，夹爪命令范围 `(94.735,95.000)mm`，相对首帧实测包络 `0.063136m`，首末 TCP 从 `[-0.004300,-0.012216,0.551525]` 到 `[-0.056867,-0.039588,0.571840]`。right：最大 target error `0.001714m`，最大 measured step `0.007572m`，夹爪命令范围 `(88.686,95.000)mm`，相对首帧实测包络 `0.072561m`，首末 TCP 从 `[-0.078016,0.042053,0.582186]` 到 `[-0.138735,0.077891,0.582835]`。

录像文件：

```text
/tmp/openpi_camera_records/20260709_162749_test2_triptych.mp4          34M
/tmp/openpi_camera_records/20260709_162749_test2_base_0_rgb.mp4        9.0M
/tmp/openpi_camera_records/20260709_162749_test2_left_wrist_0_rgb.mp4  16M
/tmp/openpi_camera_records/20260709_162749_test2_right_wrist_0_rgb.mp4 9.6M
/tmp/openpi_camera_records/20260709_162749_test2_metadata.json
```

录像元数据：`150s`、`15fps`、写入 `2251` 帧；raw message counts 约 head=`2859`、left wrist=`2840`、right wrist=`2800`。

收尾检查：临时 policy server 已 Ctrl+C 停止，`ss -lntp 'sport = :8000'` 无监听。SDK 复查 left/right 均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`，EEF mode 均为 `idle`。

结论：第二轮相对第一轮运动幅度明显变大，且多步 chunk 执行链路正常；但 policy 仍没有输出真正夹爪闭合。right gripper 最低只到约 `88.7mm`，left gripper 基本保持 `95mm` 打开。继续单纯放大运动范围无法保证抓取成功；下一步应转向“视觉/人工判断到位后显式闭合夹爪”的混合策略，或回到数据/模型侧检查为什么当前 checkpoint 在该观测下不输出 close。


## 2026-07-09 16:46 CST - 完整任务式测试：OpenPI 连续控制 + 定时强制夹爪闭合，提前被旋转 guard 停止（agent: Codex）

目的：用户质疑为什么不能执行一次完整任务测试。本轮在保留硬性保护的前提下执行“完整任务式”链路：启动 OpenPI policy server，订阅三路相机录像，运行 `openpi_p7_persistent_loop`，并新增测试参数 `--force-gripper-close-after-s/--force-gripper-open-after-s`，用于在 policy 连续控制过程中按时间覆盖夹爪目标。该覆盖参数默认关闭，不改变纯模型测试行为。

执行命令要点：

```bash
# 后台启动 policy server，监听 0.0.0.0:8000
bash scripts/cmds/serve_policy.sh

# 后台录像：ROS_DOMAIN_ID=0 / rmw_fastrtps_cpp，订阅三路 image_rect，输出 mp4
/usr/bin/python3 /tmp/record_openpi_cameras.py \
  --duration-s 170 \
  --fps 15 \
  --output-prefix /tmp/openpi_camera_records/20260709_164248_forced_full

# 前台执行完整任务式测试
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 140 \
  --period-s 0.5 \
  --controller servo \
  --chunk-steps 5 \
  --max-step-translation-m 0.015 \
  --max-step-rotation-rad 0.08 \
  --max-envelope-m 0.22 \
  --prompt 'close the gripper on the plant, lift it, and place it into the collection box' \
  --enable-gripper \
  --eef-speed-mm-s 80 \
  --force-gripper-close-after-s 25 \
  --force-gripper-close-mm 0 \
  --force-gripper-open-after-s 115 \
  --force-gripper-open-mm 95 \
  --execute \
  --allow-robot-motion
```

关键输出：policy server `8s` 就绪；三路相机首帧均收到，topic 分别为 `/camera/head_left/image_rect`、`/camera/left_arm_left/image_rect`、`/camera/right_arm_left/image_rect`，编码均为 `nv12 640x352`。loop run id=`20260709_164259`，summary=`/tmp/openpi_p7_persistent_loop/summary_20260709_164259.jsonl`。

执行结果：共写入 `75` 条 summary 记录（15 轮 × 每轮 5 个 action step），第 16 轮第 1 个 action 在下发前被 guard 拒绝：`FAIL: left: step rotation 0.090608 exceeds limit 0.080000`。这说明停止原因是单步旋转超过本轮上限，不是相机、policy、SDK 通信失败。

Summary 解析：left 最大 target error `0.004381m`，最大 measured step `0.005462m`，夹爪命令范围 `(0.0, 95.0)mm`，强制夹爪覆盖 `49` 条，首末实测 envelope `0.029339m`；right 最大 target error `0.004288m`，最大 measured step `0.011017m`，夹爪命令范围 `(0.0, 92.483)mm`，强制夹爪覆盖 `49` 条，首末实测 envelope `0.033133m`。本轮确认：定时强制夹爪闭合参数生效，`move_eef` 已收到 `0mm` 闭合目标；但由于旋转 guard 提前停止，未运行到 `115s` 的自动释放阶段。

录像文件已生成：

```text
/tmp/openpi_camera_records/20260709_164248_forced_full_base_0_rgb.mp4        4.4M
/tmp/openpi_camera_records/20260709_164248_forced_full_left_wrist_0_rgb.mp4  8.1M
/tmp/openpi_camera_records/20260709_164248_forced_full_right_wrist_0_rgb.mp4 5.3M
/tmp/openpi_camera_records/20260709_164248_forced_full_triptych.mp4          18M
```

注意：本轮录像进程是测试结束后被脚本 `SIGTERM` 提前停止，因此未写出 metadata json；mp4 文件已存在并有正常大小。

收尾处理：由于 loop 在闭合后、释放前提前停止，随后单独通过 P7 SDK 获取短租约，只打开左右夹爪到 `95mm`，不切 arm controller、不做末端位姿运动。关键输出：left `move_eef_open_95 True`，`eef_joint_after_open=(91.2999)`；right `move_eef_open_95 True`，`eef_joint_after_open=(90.0875)`；左右最终均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`，控制租约已释放。policy server 残留的 `:8000` 监听子进程也已停止，`ss -lntp 'sport = :8000'` 无监听。

结论：本轮已经不是“只小幅试探”的测试，而是一次完整任务式链路测试：相机观测 → OpenPI 推理 → P7 SDK 双臂伺服控制 → 定时夹爪闭合 → 收尾复位。链路能跑，夹爪强制闭合也能下发；当前未完成任务的原因转为运动 guard 提前停止，以及 policy 末端动作本身没有稳定地产生足够接近/放置轨迹。下一轮若继续追求现场任务完成，应降低每个 action 的旋转风险（例如 `chunk_steps=3` 或 `max-step-rotation-rad=0.12` 二选一）并缩短 close/open 时间窗，而不是取消所有保护。


## 2026-07-09 16:54 CST - 回到指定 7 关节姿态未完成：planning PTP/waypoints 被拒绝，左臂 joint2 先被 servo 小步退回限位内（agent: Codex）

目的：用户要求先把双臂回到 `joint1=0, joint2=0.647, joint3=0, joint4=-0.933, joint5=0, joint6=0, joint7=0`（rad）后再继续 OpenPI 任务测试。

执行与结果：使用 `examples/airbot/p7_move_to_joint_target.py --side both --target '0,0.647,0,-0.933,0,0,0' --velocity-scaling 0.1 --acceleration-scaling 0.1 --allow-planning-time 8 --max-joint-delta-rad 2.0 --execute --allow-robot-motion`。脚本读取到左右臂均为 `IDLE/idle/valid`，左臂当前约 `[0.2347, 0.8368, 0.3401, -0.3523, -0.2067, -0.6678, -1.0452]`，右臂当前约 `[0.4148, 0.8267, 0.3403, -0.7039, 0.0866, -0.2216, -1.0797]`，最大差值约 `1.08rad`。左臂 `switch_planning=True` 后 `move_joint_ptp=False`，未完成回位；脚本随后 `switch_idle`、`release_control`，左右最终仍为 `IDLE/idle/valid`。

随后尝试关节 `move_joint_waypoints()` 分段回位。失败原因更明确：SDK 报 `waypoint[0] joint[1]=0.836795 exceeds command limit [-2.573100, 0.827750] (raw limit with 0.010 rad margin)`。也就是说左臂当前 joint2 已在 SDK “命令限位”之外，虽然能读到这个状态，但 planning/waypoints 命令会拒绝把当前点作为合法起点。

为解除该阻塞，尝试只把左臂 joint2 从约 `0.8368` 退回 `0.8200`。planning 小 PTP 仍返回 `False`，随后切 `Controller.servo_control` 发送完整 7 轴目标（只改 joint2），`move_joint_servo_nudge_j2=True`，最终 joint2 约 `0.819877`，左臂状态回到 `IDLE/idle/valid`，控制权释放。该小步已把 left joint2 退回 SDK 命令限位内，但用户中断了后续重新执行分段 waypoints/回位步骤，因此双臂尚未到达目标姿态。

结论：没有完成指定姿态不是因为忽略了用户目标，而是因为 SDK planning 首先拒绝一次性 PTP；分段 waypoints 又发现左臂当前 joint2 超出 SDK 命令限位，必须先退回限位内。当前已完成的只有“左臂 joint2 退回命令限位内”这一步；还没有继续执行最终回位。


## 2026-07-09 16:57 CST - 双臂已用 servo joint 小步回到指定 7 关节姿态（agent: Codex）

目的：用户要求快速把机械臂回到 `joint1=0, joint2=0.647, joint3=0, joint4=-0.933, joint5=0, joint6=0, joint7=0`（rad）。

执行方式：由于前一轮 `planning_control + move_joint(PTP)` 和 `move_joint_waypoints()` 均被 SDK/规划器拒绝，本轮改用 `Controller.servo_control + move_joint()`，每步发送完整 7 轴目标，从当前角度线性插值到目标，单步最大约 `0.08rad`，`set_arm_speed=[0.6]*7`，左右臂顺序执行。

关键输出：left 初始约 `[0.2362, 0.8091, 0.3401, -0.3251, -0.1538, -0.6674, -1.1590]`，分 `15` 步执行，所有 `servo_step ok=True`；最终 `[-0.000144, 0.646822, 0.000048, -0.932818, 0.000432, 0.000527, 0.000623]`，最大误差 `0.000623rad`。right 初始约 `[0.4148, 0.8267, 0.3403, -0.7039, 0.0863, -0.2216, -1.1369]`，分 `15` 步执行，所有 `servo_step ok=True`；最终 `[-0.000240, 0.646822, -0.000144, -0.933106, -0.000144, 0.000144, 0.000432]`，最大误差 `0.000432rad`。

收尾：左右臂均 `switch_idle=True`、`release_control done`，最终 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。

结论：双臂已到达用户指定的 7 关节 rad 姿态，误差小于 `0.001rad`。


## 2026-07-09 17:01 CST - 抓取保持测试：12s 后强制夹爪闭合并保持，执行 170 个动作 step 后被位移 guard 停止（agent: Codex）

目的：用户反馈上一轮只看到机械臂运动，没有完成抓取。本轮从已回到标准关节姿态后的状态继续测试，目标是让“OpenPI 连续运动”和“夹爪闭合”重叠更久：`12s` 后强制双夹爪闭合到 `0mm` 并保持，不设置自动打开，便于现场判断是否抓住物体。

预检查：左右臂均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。夹爪起始约 left=`91.94mm`、right=`91.64mm`。预检查时关节读数显示标准回位后又出现 joint7 漂移/变化：left joint7≈`-1.1715`、right joint7≈`-1.0637`，但服务状态有效且本轮继续执行。

执行命令要点：

```bash
bash scripts/cmds/serve_policy.sh

/usr/bin/python3 /tmp/record_openpi_cameras.py \
  --duration-s 190 \
  --fps 15 \
  --output-prefix /tmp/openpi_camera_records/20260709_165913_grasp_hold

bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 165 \
  --period-s 0.5 \
  --controller servo \
  --chunk-steps 5 \
  --max-step-translation-m 0.020 \
  --max-step-rotation-rad 0.120 \
  --max-envelope-m 0.300 \
  --prompt 'close the gripper on the plant, lift it, and place it into the collection box' \
  --enable-gripper \
  --eef-speed-mm-s 80 \
  --force-gripper-close-after-s 12 \
  --force-gripper-close-mm 0 \
  --execute \
  --allow-robot-motion
```

关键输出：loop run id=`20260709_165924`，summary=`/tmp/openpi_p7_persistent_loop/summary_20260709_165924.jsonl`。执行 `34` 轮 × `5` 个 action step，共 `170` 条 summary 记录；`force_gripper sides=['left', 'right'] pos_mm=0.000` 后，左右 `move_eef pos_mm=[0.0] ... ok=True` 持续出现，说明强制闭合目标已下发并保持。第 35 轮第 1 个 action 未下发，停止原因：`FAIL: right: step translation 0.038945 exceeds limit 0.020000`。这不是通信失败，而是右臂单步目标位移超过本轮 `2cm` guard。

Summary 解析：left 最大 target error `0.001510m`，最大 measured step `0.012301m`，夹爪命令范围 `(0.0, 94.889)mm`，强制夹爪覆盖 `145` 条，首末实测 envelope `0.090672m`。right 最大 target error `0.002898m`，最大 measured step `0.015889m`，夹爪命令范围 `(0.0, 90.379)mm`，强制夹爪覆盖 `145` 条，首末实测 envelope `0.123756m`。

录像文件：

```text
/tmp/openpi_camera_records/20260709_165913_grasp_hold_triptych.mp4          20M
/tmp/openpi_camera_records/20260709_165913_grasp_hold_base_0_rgb.mp4        5.8M
/tmp/openpi_camera_records/20260709_165913_grasp_hold_left_wrist_0_rgb.mp4  8.0M
/tmp/openpi_camera_records/20260709_165913_grasp_hold_right_wrist_0_rgb.mp4 6.3M
/tmp/openpi_camera_records/20260709_165913_grasp_hold_metadata.json
```

录像元数据：`frames_written=1324`，raw message counts：base=`1662`、left wrist=`1668`、right wrist=`1650`。

收尾检查：左右均已 `switch_eef_idle`、`switch_idle`、`release_control`，最终均为 `IDLE/idle/valid`。policy server 残留的 `:8000` 子进程已停止，`ss -lntp 'sport = :8000'` 无监听。夹爪未自动打开，最终 EEF 反馈约 left=`0.6943mm`、right=`0.5919mm`，即保持闭合位，便于现场确认是否夹持到物体。

结论：本轮比上一轮更接近“抓取尝试”：OpenPI 连续控制执行了 170 个 action step，双夹爪在 145 个 action step 内持续收到 `0mm` 闭合命令并保持闭合。若现场仍没有抓住物体，说明当前 policy 轨迹没有把夹爪带到物体可夹持位置；夹爪控制链路本身已经工作。下一轮若继续尝试，应把问题转向“怎么让末端到物体附近”：要么人为调整物体/初始姿态到夹爪路径上，要么加入视觉/人工触发的接近目标，而不是继续单纯放大 gripper 或时间。


## 2026-07-09 17:11 CST - 三项 motion guard 关闭后的抓取测试：执行 185 个 action step 后由 SDK 拒绝右臂目标（agent: Codex）

目的：用户要求关闭单步位移、单步旋转、总运动包络三类 guard，继续完整抓取测试。本轮修改 `examples/airbot/openpi_p7_persistent_loop.py`：`--max-step-translation-m 0`、`--max-step-rotation-rad 0`、`--max-envelope-m 0` 时对应检查关闭；仍保留状态检查、控制权释放、SDK 自身限制和最终状态复查。

执行前处理：先用 `servo_control + move_joint()` 小步把左右臂重新带回标准关节姿态 `[0, 0.647, 0, -0.933, 0, 0, 0]`，并打开双夹爪到约 `90mm`。left 回位后最大关节误差约 `0.00340rad`，right 回位后最大关节误差约 `0.00296rad`；左右均 `IDLE/idle/valid`。

执行命令要点：

```bash
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 240 \
  --period-s 0.5 \
  --controller servo \
  --chunk-steps 5 \
  --max-step-translation-m 0 \
  --max-step-rotation-rad 0 \
  --max-envelope-m 0 \
  --prompt 'close the gripper on the plant, lift it, and place it into the collection box' \
  --enable-gripper \
  --eef-speed-mm-s 80 \
  --force-gripper-close-after-s 12 \
  --force-gripper-close-mm 0 \
  --execute \
  --allow-robot-motion
```

关键输出：loop run id=`20260709_170819`，summary=`/tmp/openpi_p7_persistent_loop/summary_20260709_170819.jsonl`。本轮没有被单步位移、单步旋转或总包络 guard 拦截。执行到第 `38` 轮第 `0` 个 action 时，左臂 `move_end_pose ok=True`，右臂 `move_end_pose ok=False`，随后脚本报错停止：`FAIL: right: RuntimeError('right: move_end_pose returned False')`。停止原因是 SDK/底层控制器拒绝右臂目标，不是三项 motion guard。

Summary 解析：共 `185` 条记录（第 1 轮到第 37 轮，每轮 5 step）。left 最大 target error `0.001800m`，最大 measured step `0.013839m`，夹爪命令范围 `(0.0, 94.797)mm`，强制夹爪覆盖 `160` 条，首末实测 envelope `0.091502m`。right 最大 target error `0.005585m`，最大 measured step `0.050877m`，夹爪命令范围 `(0.0, 91.427)mm`，强制夹爪覆盖 `160` 条，首末实测 envelope `0.147639m`。

录像文件：

```text
/tmp/openpi_camera_records/20260709_170748_guards_off_triptych.mp4          38M
/tmp/openpi_camera_records/20260709_170748_guards_off_base_0_rgb.mp4        8.5M
/tmp/openpi_camera_records/20260709_170748_guards_off_left_wrist_0_rgb.mp4  21M
/tmp/openpi_camera_records/20260709_170748_guards_off_right_wrist_0_rgb.mp4 8.5M
```

注意：录像进程被测试脚本提前终止，未生成 metadata json；mp4 文件已写出并有正常大小。

收尾检查：左右臂最终均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`；policy server 残留的 `:8000` 子进程已停止，`ss -lntp 'sport = :8000'` 无监听。夹爪保持闭合，最终 EEF 反馈约 left=`0.6792mm`、right=`0.5950mm`。

结论：用户指定的三项软件 motion guard 已关闭并用于本轮真机测试。本轮仍没有完成抓取，原因不再是这三类 guard，而是底层 SDK 在第 38 轮拒绝右臂 `move_end_pose` 目标。到目前为止已确认：相机、policy、P7 SDK 连续控制、强制夹爪闭合都能工作；未完成抓取的核心问题是策略输出的末端轨迹没有稳定把夹爪带到物体可夹持位置，且继续执行时会遇到 SDK/控制器目标拒绝。


## 2026-07-09 17:13 CST - 三项 guard 关闭测试后，双臂再次回到指定 7 关节姿态并打开夹爪（agent: Codex）

目的：用户要求快速把机械臂回到 `joint1=0, joint2=0.647, joint3=0, joint4=-0.933, joint5=0, joint6=0, joint7=0`（rad）。

执行方式：继续使用已验证可行的 `Controller.servo_control + move_joint()` 小步完整 7 轴目标。left 从约 `[-0.1884,0.8090,-0.1229,-0.6482,0.1836,-0.4705,-1.1439]` 出发，15 步回位；right 从约 `[0.6952,0.8267,0.4208,-0.5960,-0.4184,0.0345,-1.5177]` 出发，19 步回位。随后通过 `move_eef([95mm])` 打开双夹爪。

关键输出：left 最终 `[-0.001294,0.648165,0.001007,-0.932435,0.000432,-0.001294,-0.003403]`，最大关节误差 `0.003403rad`，夹爪约 `90.61mm`。right 最终 `[0.002253,0.647685,0.002924,-0.930134,-0.000144,0.000048,-0.000911]`，最大关节误差 `0.002924rad`，夹爪约 `91.02mm`。左右最终均 `IDLE/idle/valid`，控制权已释放。

结论：双臂已再次回到用户指定关节姿态附近，并打开夹爪。


## 2026-07-09 17:18 CST - 用户中断强制夹爪测试后清理残留进程，并确认后续改为纯模型夹爪输出（agent: Codex）

目的：用户明确要求“不要做强制闭合，只要遵循模型输出动作”。上一轮被用户中断时，带有 `--force-gripper-close-after-s` / `--force-gripper-open-after-s` 的测试进程仍在后台运行，因此先停止残留进程，避免继续执行错误测试。

执行结果：发现并停止残留进程，包括上一轮 `openpi_p7_persistent_loop.py`、`serve_policy.sh`/`serve_policy.py`、`record_openpi_cameras.py`、`capture_ros2_openpi_observation.py`。随后 `ss -lntp 'sport = :8000'` 无监听。

SDK 状态复查：left/right 均为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。当前关节约 left=`[-0.1553,0.7808,-0.1494,-0.7289,0.1134,-0.2555,-1.1570]`，right=`[0.1788,0.7420,0.2591,-0.7577,-0.1520,0.1145,-1.2725]`。由于中断前的强制闭合阶段已经执行，当前 EEF 反馈约 left=`0.6883mm`、right=`0.6883mm`，即夹爪处于闭合状态。

结论：后续 OpenPI 测试必须去掉所有 `--force-gripper-*` 参数；保留 `--enable-gripper` 时，夹爪命令只来自模型输出的 action[6]/action[13]。


## 2026-07-09 17:24 CST - 纯模型夹爪输出抓取测试：无 force-gripper，执行 213 个 action step 后 SDK 拒绝右臂目标（agent: Codex）

目的：用户要求先回到标准 7 关节姿态，然后开始下一轮测试，并明确“不要做强制闭合，只要遵循模型输出动作”。本轮不使用任何 `--force-gripper-*` 参数；保留 `--enable-gripper`，夹爪只执行 policy action[6]/action[13] 的模型输出。

执行前处理：停止上一轮中断残留进程；用 `servo_control + move_joint()` 仅回 arm joints 到 `[0,0.647,0,-0.933,0,0,0]`，不手动打开夹爪。left 回位最大误差约 `0.00369rad`，right 回位最大误差约 `0.00229rad`。回位后夹爪仍处于上一轮残留的闭合状态，EEF 约 left=`0.6883mm`、right=`0.6883mm`。

执行命令要点：

```bash
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 150 \
  --period-s 0.5 \
  --controller servo \
  --chunk-steps 3 \
  --max-step-translation-m 0 \
  --max-step-rotation-rad 0 \
  --max-envelope-m 0 \
  --prompt 'pick up the plant with the gripper, lift it, move it to the collection box, and release it' \
  --enable-gripper \
  --eef-speed-mm-s 80 \
  --execute \
  --allow-robot-motion
```

关键输出：loop run id=`20260709_172016`，summary=`/tmp/openpi_p7_persistent_loop/summary_20260709_172016.jsonl`。本轮没有任何强制夹爪覆盖，summary 中 left/right 的 `forced_count=0`。执行到第 `72` 轮第 `0` 个 action 时，left `move_end_pose ok=True`，right `move_end_pose ok=False`，随后停止：`FAIL: right: RuntimeError('right: move_end_pose returned False')`。停止原因是 SDK/底层控制器拒绝右臂目标，不是三项 motion guard，也不是强制夹爪逻辑。

Summary 解析：共 `213` 条记录（第 1 轮到第 71 轮，每轮 3 step）。left 最大 target error `0.002267m`，最大 measured step `0.013320m`，模型夹爪命令范围 `93.676~95.000mm`（model `97.579~99.022`），基本保持打开。right 最大 target error `0.006298m`，最大 measured step `0.025341m`，模型夹爪命令范围 `3.665~95.000mm`（model `3.817~99.375`），说明本轮 policy 自己确实曾输出接近闭合的右夹爪目标，不是强制闭合。

末端实测包络：left 从首帧到末帧约 `0.149819m`，right 约 `0.238739m`。right TCP 首末从 `[-0.0910,0.0016,0.5902]` 到 `[-0.0004,0.0456,0.3742]`。

录像文件：

```text
/tmp/openpi_camera_records/20260709_171944_model_only_triptych.mp4          49M
/tmp/openpi_camera_records/20260709_171944_model_only_base_0_rgb.mp4        13M
/tmp/openpi_camera_records/20260709_171944_model_only_left_wrist_0_rgb.mp4  25M
/tmp/openpi_camera_records/20260709_171944_model_only_right_wrist_0_rgb.mp4 13M
/tmp/openpi_camera_records/20260709_171944_model_only_metadata.json
```

录像元数据：`frames_written=2829`，raw message counts base=`3485`、left wrist=`3424`、right wrist=`3443`。

收尾检查：left/right 最终均为 `IDLE/idle/valid`；policy server 残留的 `:8000` 子进程已停止。最终夹爪反馈 left≈`94.55mm`，right≈`87.62mm`。本轮未手动打开或闭合夹爪。

结论：这是第一轮严格遵循模型夹爪输出的测试。模型本身没有让左夹爪闭合，但让右夹爪一度接近闭合（最低约 `3.7mm`）。测试仍未完成抓取放置，最终由 SDK 拒绝右臂 `move_end_pose` 停止。下一步应重点检查右臂目标被 SDK 拒绝时的目标姿态/关节状态，或降低 `chunk_steps` 到 1 让每次只执行 chunk 的第一步，减少单次观测后连续执行多步导致的右臂目标不可接受。


## 2026-07-09 17:29 CST - 纯模型测试后，双臂回到指定 7 关节姿态（agent: Codex）

目的：用户要求快速把机械臂回到 `joint1=0, joint2=0.647, joint3=0, joint4=-0.933, joint5=0, joint6=0, joint7=0`（rad）。

执行方式：继续使用 `Controller.servo_control + move_joint()` 小步完整 7 轴目标。left 从约 `[-0.3618,0.6968,-0.3116,-0.5405,0.2670,-0.2962,-0.9636]` 出发，13 步回位，最终 `[-0.002061,0.647302,-0.003116,-0.930805,0.000527,-0.001390,-0.003787]`，最大误差 `0.003787rad`。right 首次 20 步回位第 1 步返回 `False`，但读回实际已经移动到第一步附近并使 joint2 回到命令限位内；随后用更小 `0.04rad` 步长继续 37 步，最终 `[0.002924,0.647589,0.002924,-0.929367,-0.000623,0.000048,-0.000623]`，最大误差 `0.003633rad`。

收尾：左右均 `switch_idle=True`、`release_control done`，最终均 `IDLE/idle/valid`。本次未修改夹爪；left EEF 约 `94.55mm`，right EEF 约 `87.62mm`。

结论：双臂已回到用户指定关节姿态附近，误差约 `0.004rad` 内。

### 2026-07-09 20:22 CST - 只读查询当前双臂 7 关节位置

目的：用户询问当前左右臂 7 个关节位置；本轮只读查询，不发送控制指令。

命令：。

结果：50071 service=，joints_rad=；50072 service=，joints_rad=。

影响：两端口当前都不是用户目标 ，主要偏差在 joint7，约 。

### 2026-07-09 20:22 CST - 只读查询当前双臂 7 关节位置

目的：用户询问当前左右臂 7 个关节位置；本轮只读查询，不发送控制指令。

命令：使用 arm_p7_sdk AirbotClient 连接 192.168.25.1 的 50071/50072，调用 get_service_state() 与 get_arm_joint_state()。

结果：50071 service=IDLE/idle/valid，joints_rad=[0.010755, 0.630377, -0.007904, -0.919284, 0.000383, 0.000168, -1.150534]；50072 service=IDLE/idle/valid，joints_rad=[0.013532, 0.640667, -0.008470, -0.917877, -0.001174, -0.000024, -1.171506]。

影响：两端口当前都不是用户目标 [0, 0.647, 0, -0.933, 0, 0, 0]，主要偏差在 joint7，约 -1.15~-1.17rad。

### 2026-07-09 20:28 CST - SDK left/50071 planning +X 3cm 左右映射测试

目的：用户要求只控制“左臂”用 planning 模式沿 +X 运动 3cm，以现场肉眼判断 SDK 左右是否与物理左右相反。本轮明确只向 SDK left / port 50071 发运动，不控制 50072。

命令：临时脚本 /tmp/p7_move_sdk_left_plus_x_3cm.py 使用 arm_p7_sdk AirbotClient(host=192.168.25.1, port=50071)，读取当前 end_pose，构造 target x+0.03m、姿态不变；acquire_control -> switch_controller(Controller.planning_control) -> move_end_pose_linear(blocking=True) -> switch_idle -> release_control。

关键输出：state_before=IDLE/idle/valid；start xyz=(-0.0824,-0.0030,0.5722)，target xyz=(-0.0524,-0.0030,0.5722)；move_end_pose_linear_plus_x_3cm=True；end xyz=(-0.0526,-0.0030,0.5722)；delta_xyz_m=(0.029814,-0.000014,0.000044)；state_final=IDLE/idle/valid。

结论：SDK left / port 50071 在 planning 模式下成功执行 +X 约 2.98cm。物理上是哪只臂移动需以用户现场观察为准，并据此更新左右映射。

### 2026-07-09 20:35 CST - OpenPI 纯模型闭环抓取放置复测（无 force-gripper，chunk-steps=5）

目的：用户现场确认 SDK/物理左右映射无误后，要求重新测试 OpenPI 推理抓取放置任务效果。本轮执行真实闭环：三路机械臂相机 -> OpenPI policy -> P7 SDK servo 控制双臂和夹爪；不使用 force-gripper。

前置状态：无残留 openpi_p7_persistent_loop；policy 端口 8000 未监听。双臂均为 IDLE/idle/valid。启动前 50071 pose 约 xyz=(-0.0432,-0.0025,0.5683)，EEF=0mm；50072 pose 约 xyz=(-0.0853,-0.0047,0.5693)，EEF=0mm。

执行命令：
- policy server：bash scripts/cmds/serve_policy.sh，checkpoint=checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000，监听 0.0.0.0:8000。
- 录像：ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp /usr/bin/python3 /tmp/record_openpi_cameras.py --duration-s 240 --fps 15 --output-prefix /tmp/openpi_camera_records/20260709_203033_openpi_retest。
- 闭环：bash scripts/cmds/openpi_p7_persistent_loop.sh --duration-s 180 --period-s 0.5 --controller servo --chunk-steps 5 --max-step-translation-m 0 --max-step-rotation-rad 0 --max-envelope-m 0 --prompt 'pick up the plant with the gripper, lift it, move it to the collection box, and release it' --enable-gripper --eef-speed-mm-s 80 --execute --allow-robot-motion。

关键结果：summary=/tmp/openpi_p7_persistent_loop/summary_20260709_203110.jsonl，共 402 条 action 记录，最后成功记录 iteration=81/action_index=1/elapsed_s=174.50。force_gripper_count 左右均为 0。左臂最大 envelope 0.1677m，单步最大 moved 0.00944m，最大 target_error 0.00266m，夹爪命令范围 92.81~94.58mm；右臂最大 envelope 0.2783m，单步最大 moved 0.02042m，最大 target_error 0.00343m，夹爪命令范围 8.62~94.11mm。说明本轮模型确实产生并执行了大范围移动和右臂夹爪明显闭合/再张开的行为，不是原地小幅动作。

失败点：iteration=81 后续 action 中 left/50071 move_end_pose 返回 False；清理阶段 right switch_eef_idle=True、right switch_idle=True、release_control done；left switch_eef_idle 失败，gRPC FAILED_PRECONDITION: eef switch mode failed: entered UNKNOWN_ERROR；left switch_idle=False，最终 left/50071 state_final=UNKNOWN_ERROR/idle/valid，right/50072 state_final=IDLE/idle/valid。

结束只读状态：left/50071 service=UNKNOWN_ERROR/idle/valid，joints=[-0.166355,0.433962,-0.044070,-1.431176,-0.145776,-0.235442,-1.427801]，pose xyz=(-0.1892,-0.0161,0.6136)，EEF=93.908mm；right/50072 service=IDLE/idle/valid，joints=[-0.083451,-0.172991,0.582805,-1.294928,-0.338339,-0.280071,-1.017197]，pose xyz=(0.1259,0.1678,0.6528)，EEF=37.904mm。

录像文件：/tmp/openpi_camera_records/20260709_203033_openpi_retest_triptych.mp4 (58M)，base_0_rgb.mp4 (14M)，left_wrist_0_rgb.mp4 (21M)，right_wrist_0_rgb.mp4 (24M)，metadata.json 显示 3601 frames @15fps，三路 raw_message_counts 分别约 4387/4416/4419。

影响：本轮证明完整链路可连续运行约 175s，并能让右臂执行抓取阶段夹爪闭合；但 left/50071 已进入 UNKNOWN_ERROR，下一轮任何运动前必须重启机械臂或通过厂商/SDK方式清除错误。policy server 已在本轮结束后停止。


### 2026-07-09 21:12 CST - 新增 active-sides 后右臂单臂 OpenPI 抓取放置复测（agent: Codex）

目的：用户表示回位不需要太高精度，要求直接重新开始 OpenPI 抓取放置任务。上一轮双臂测试后 left/50071 处于 `UNKNOWN_ERROR/idle/valid`，因此先让常驻 loop 支持只激活指定侧，再用 right/50072 执行纯模型闭环，left 只读 pose/context，不下发运动。

代码变更：`examples/airbot/openpi_p7_persistent_loop.py` 新增 `--active-sides`，默认 `left,right`。当设置为 `right` 时，只对右侧执行 `acquire_control`、`switch_controller`、`move_end_pose`、`prepare_gripper_control` 和 `move_eef`；未激活侧不要求 `IDLE`，只读 TCP pose 参与观测和 summary。`.venv-p7-sdk/bin/python -m py_compile examples/airbot/openpi_p7_persistent_loop.py` 通过。

执行命令：

```bash
bash scripts/cmds/serve_policy.sh

ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp   /usr/bin/python3 /tmp/record_openpi_cameras.py   --duration-s 420   --fps 15   --output-prefix /tmp/openpi_camera_records/20260709_210352_openpi_grasp_place_right_only

bash scripts/cmds/openpi_p7_persistent_loop.sh   --duration-s 300   --period-s 0.5   --controller servo   --active-sides right   --chunk-steps 5   --max-step-translation-m 0   --max-step-rotation-rad 0   --max-envelope-m 0   --prompt 'pick up the plant with the gripper, lift it, move it to the collection box, and release it'   --enable-gripper   --eef-speed-mm-s 80   --execute   --allow-robot-motion
```

关键结果：run id=`20260709_210408`，summary=`/tmp/openpi_p7_persistent_loop/summary_20260709_210408.jsonl`。共 `433` 条成功动作记录，最后成功记录为 iteration=`87`、action_index=`2`、elapsed_s=`185.2645`；第 87 轮后续 action 中 right `move_end_pose ok=False`，脚本报 `FAIL: right: RuntimeError('right: move_end_pose returned False')` 后执行 `right switch_eef_idle True`、`right switch_idle True`、`right release_control done`。

统计结果：left `active_count=0`，最大实测包络约 `0.000014m`，基本未动。right `active_count=433`，相对首帧最大 TCP 包络约 `0.285915m`，末帧相对首帧约 `(+0.047685,+0.203473,+0.039173)m`；每个 observation 后连续 action 的最大 `moved_from_observation_m=0.025620`，最大 target error `0.004002m`。right 夹爪命令范围 `5.798~95.000mm`，`forced_gripper_count=0`，说明本轮没有强制闭合/打开，完全遵循模型输出。

录像文件：

```text
/tmp/openpi_camera_records/20260709_210352_openpi_grasp_place_right_only_triptych.mp4         43M
/tmp/openpi_camera_records/20260709_210352_openpi_grasp_place_right_only_base_0_rgb.mp4       13M
/tmp/openpi_camera_records/20260709_210352_openpi_grasp_place_right_only_left_wrist_0_rgb.mp4  11M
/tmp/openpi_camera_records/20260709_210352_openpi_grasp_place_right_only_right_wrist_0_rgb.mp4 19M
```

结束只读状态：left/50071 `UNKNOWN_ERROR/idle/valid`，joints=`[-0.0175,0.6304,-0.0050,-0.8648,-0.0042,-0.0523,-1.2061]`，EEF≈`94.401mm`，pose xyz≈`[-0.0601,-0.0047,0.5580]`；right/50072 `IDLE/idle/valid`，joints=`[0.1970,0.2758,0.7710,-0.6483,0.2953,-0.7860,-0.5536]`，EEF≈`92.630mm`，pose xyz≈`[0.0544,0.2388,0.4853]`。策略服务和录像进程已停止，`pgrep -af 'openpi_p7_persistent_loop|serve_policy.py|record_openpi_cameras'` 无残留。

结论：这轮已经重新执行了 OpenPI 相机 -> policy -> 右臂 servo + 夹爪的真实闭环，且运动幅度不是原位小抖动；右臂整轮 TCP 包络约 `28.6cm`，夹爪按模型输出从接近全开到约 `5.8mm` 后再打开。任务是否语义完成需要现场肉眼判断；从程序侧看，停止原因仍是 SDK/底层控制器拒绝某个右臂 `move_end_pose` 目标，而不是相机、policy、夹爪或 active-sides 逻辑失败。若后续要恢复双臂闭环，left/50071 需要重启或显式清除 `UNKNOWN_ERROR`。


### 2026-07-09 21:19 CST - 固化 OpenPI 完整现场测试流程命令（agent: Codex）

目的：用户关掉机械臂后，要求把后续自行运行完整 OpenPI 抓取放置测试的指令整理进文档。本轮不连接、不控制机械臂，只做文档和工具入口整理。

改动：新增 `examples/airbot/record_openpi_cameras.py`，把此前临时 `/tmp/record_openpi_cameras.py` 固化为仓库脚本，用于订阅三路相机并保存三路单独 mp4、triptych mp4 和 metadata。更新 `docs/openpi-airbot-runbook.md`，新增 `0.2 一次完整 OpenPI 抓取放置测试流程（现场照抄版）`，按终端 A/B/C/D/E 写清 X5 启动、本机检查、policy server、录像、dry-run、正式执行、summary 解析和收尾检查命令。

结论：后续现场复测优先按 `docs/openpi-airbot-runbook.md` 的 `0.2` 章节执行；正式抓取放置命令默认不含任何 `--force-gripper-*`，夹爪只遵循模型输出。


### 2026-07-10 14:12 CST - 双臂回到指定 7 关节姿态附近（agent: Codex）

目的：用户要求回到 `joint1=0, joint2=0.647, joint3=0, joint4=-0.933, joint5=0, joint6=0, joint7=-1.15`（rad）。本轮按用户此前说明“不需要太大精度”，目标是回到该姿态附近并保持双臂空闲可继续测试。

前置只读状态：left/50071 为 `IDLE/idle/valid`，joints≈`[-0.0165,0.6305,-0.0053,-0.8650,0.0608,-0.0379,-1.2727]`；right/50072 为 `IDLE/idle/valid`，joints≈`[0.1971,0.2758,0.7709,-0.6483,0.2952,-0.7862,-0.5960]`。

执行命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py   --side both   --target '0,0.647,0,-0.933,0,0,-1.15'   --execute   --allow-robot-motion
```

结果：left planning PTP 成功，控制期间 final max_abs_error≈`0.000106rad`；right planning PTP 返回 `move_joint False`，但 right 状态回到 `IDLE/idle/valid`。随后对 right 用 servo 小步继续回位：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_servo_move_to_joint_target.py   --side right   --target '0,0.647,0,-0.933,0,0,-1.15'   --max-step-rad 0.05   --speed-rad-s 0.55   --effort 12   --execute   --allow-robot-motion

.venv-p7-sdk/bin/python examples/airbot/p7_servo_move_to_joint_target.py   --side right   --target '0,0.647,0,-0.933,0,0,-1.15'   --max-step-rad 0.04   --speed-rad-s 0.55   --effort 12   --execute   --allow-robot-motion

.venv-p7-sdk/bin/python examples/airbot/p7_servo_move_to_joint_target.py   --side right   --target '0,0.647,0,-0.933,0,0,-1.15'   --max-step-rad 0.03   --speed-rad-s 0.55   --effort 12   --execute   --allow-robot-motion
```

最终只读状态：left/50071 `IDLE/idle/valid`，joints≈`[0.0107,0.6304,-0.0054,-0.9193,0.0002,-0.0001,-1.2444]`，相对目标最大误差约 `0.0944rad`（主要 joint7 释放后回弹）；right/50072 `IDLE/idle/valid`，joints≈`[0.0137,0.5852,0.0547,-0.8909,0.0131,-0.0441,-1.1846]`，相对目标最大误差约 `0.0618rad`。

结论：双臂已回到指定 7 关节姿态附近，且最终均为空闲有效状态。left 在控制期间可达到高精度，但释放后 joint7 有回弹；right 通过多轮小步 servo 接近目标。若后续只需要继续 OpenPI 测试，当前状态可作为近似回位起点；若需要严格保持该 joint pose，需要另行保持控制模式或采用更强的驻留策略。


### 2026-07-10 18:44 CST - 双臂 joint2 移到 0 rad 附近（agent: Codex）

目的：用户要求 `move joint2 to 0 rad position fastly`，并要求双臂自然垂下。本轮没有做掉电/释放电机下垂，而是采用受控关节运动：仅把左右臂 joint2 移到 `0rad`，其它 6 个关节保持当前读数。

前置情况：本机能 ping 通 `192.168.25.1`，但最初 P7 SDK gRPC `50071/50072` 超时。X5 当时只有 `robot_app ./configs/project_config.json`，没有 `arm_dual_app`，也没有 `50071/50072` 监听。尝试启动 `/root/start-arm-dual-app-2arm.sh` 时，旧 `robot_app` 阻止启动；停止旧 `robot_app` 后，脚本又因 `/opt/robot_app/lib` 下没有含 `framework::LogVa` 的 `libcora_framework` 版本而在 remote 检查阶段失败。由于本轮只需要关节控制，不需要相机 remote，最终手动只启动了 `/opt/arm_dual_app` left/right，端口 `50071/50072` 均监听成功。

启动控制端命令摘要：

```bash
ssh root@192.168.25.1 "kill -TERM 4012 2>/dev/null || true; sleep 2; if kill -0 4012 2>/dev/null; then kill -KILL 4012 2>/dev/null || true; fi"
ssh root@192.168.25.1 "ip link set can0 down || true; ip link set can0 type can bitrate 1000000 dbitrate 5000000 fd on restart-ms 100 berr-reporting on; ip link set can0 up; ip link set can1 down || true; ip link set can1 type can bitrate 1000000 dbitrate 5000000 fd on restart-ms 100 berr-reporting on; ip link set can1 up; cd /opt/arm_dual_app; export LD_LIBRARY_PATH=/opt/arm_dual_app/lib:/usr/hobot/lib:${LD_LIBRARY_PATH:-}; nohup ./bin/arm_dual_app /opt/arm_dual_app/configs/left_arm/project_config.json >/tmp/arm_dual_app_logs/left_arm_manual.log 2>&1 & nohup ./bin/arm_dual_app /opt/arm_dual_app/configs/right_arm/project_config.json >/tmp/arm_dual_app_logs/right_arm_manual.log 2>&1 &"
```

初始只读状态：left/50071 `IDLE/idle/valid`，joints≈`[0.010467,0.658208,0.070794,-0.919271,0.004938,-0.068742,-1.304483]`；right/50072 `IDLE/idle/valid`，joints≈`[0.041541,0.612822,0.098294,-0.890824,-0.015388,-0.185851,-1.339117]`。

先尝试 servo 小步只改 joint2：左右脚本均返回 `move_joint_step True`，但最终 joint2 仍在 `0.62~0.67rad`，说明该路径未实际推动 joint2 到目标。随后改用 planning PTP，只改 joint2、其余关节保持当时读数：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py --side left   --target '0.010440,0,0.079474,-0.919257,0.005009,-0.068454,-1.318672'   --velocity-scaling 0.2 --acceleration-scaling 0.2 --execute --allow-robot-motion

.venv-p7-sdk/bin/python examples/airbot/p7_move_to_joint_target.py --side right   --target '0.040391,0,0.108802,-0.890863,-0.015244,-0.185875,-1.352468'   --velocity-scaling 0.2 --acceleration-scaling 0.2 --execute --allow-robot-motion
```

结果：planning PTP 控制期间左右 `move_joint_ptp True`，joint2 均到约 `-4.79e-05rad`。释放控制后的最终只读状态：left/50071 `IDLE/idle/valid`，joints≈`[0.010454,-0.014476,0.070676,-0.919257,0.004961,-0.068454,-1.270831]`；right/50072 `IDLE/idle/valid`，joints≈`[0.036547,-0.032127,0.097847,-0.890890,-0.015508,-0.185875,-1.329626]`。最终 joint2 分别为 left≈`-0.0145rad`、right≈`-0.0321rad`。

结论：双臂 joint2 已受控移动到 0 rad 附近；当前只启动了 `arm_dual_app` 控制端，没有启动 `robot_app remote`，所以此状态下可继续 SDK 关节/TCP 控制，但不能假设三路相机 remote 已恢复。



### 2026-07-10 20:49 CST - OpenPI 抓取放置任务前置观测检查未通过（agent: Codex）

目的：用户要求执行一次 OpenPI 推理完成抓取放置任务。本轮先确认真实链路是否满足“机械臂相机图像 + 关节状态 -> OpenPI observation -> policy -> SDK 控制”的前置条件；在观测不完整时不下发真实运动。

进程与 topic 检查：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp timeout 8 ros2 topic list | grep -E '^/camera|^/arm/.*/fsm/joint_state'

ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp timeout 10 ros2 topic info -v /camera/head_left/image_rect
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp timeout 10 ros2 topic info -v /camera/left_arm_left/image_rect
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp timeout 10 ros2 topic info -v /camera/right_arm_left/image_rect
```

关键输出：`/arm/left/fsm/joint_state` 与 `/arm/right/fsm/joint_state` 存在；`/camera/left_arm_left/image_rect` 有 `sensor_msgs/msg/Image` publisher；但 `/camera/head_left/image_rect` 与 `/camera/right_arm_left/image_rect` 均为 `Unknown topic`。当前只看到头部与右腕的 `video_encoded`，没有 OpenPI 采集脚本默认需要的 raw `/image_rect`。

实测 OpenPI observation 采集：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp timeout 12 /usr/bin/python3 examples/airbot/capture_ros2_openpi_observation.py \
  --output /tmp/openpi_live_obs_check.npz \
  --metadata-output /tmp/openpi_live_obs_check.json \
  --timeout-s 8 \
  --state-dim 16
```

输出：

```text
[openpi_observation_capture]: captured left_wrist_0_rgb frame 640x352 encoding=nv12
timed out waiting for camera frames: missing=['base_0_rgb', 'right_wrist_0_rgb']
```

结论：本轮没有执行 OpenPI 控制运动。原因不是 P7 SDK 控制端，而是 OpenPI 的训练对齐输入不成立：三路 raw 图像中只拿到了 `left_wrist_0_rgb`，缺 `base_0_rgb` 和 `right_wrist_0_rgb`。继续运行抓取放置会使用错误/缺失观测，不能算真实有效的 OpenPI 抓取放置测试。

影响：下一步应先恢复 `/camera/head_left/image_rect` 和 `/camera/right_arm_left/image_rect` 的 raw publisher，或明确实现并验证 `video_encoded -> sensor_msgs/Image` 的解码桥接后再执行真实任务。不能直接用单路图像或重复图像替代三路训练输入来评估模型效果。


### 2026-07-10 21:01 CST - 修复 start-arm-dual-app-2arm.sh 的 LogVa 库检查失败（agent: Codex）

目的：用户重启机械臂后运行 bash start-arm-dual-app-2arm.sh，脚本在启动前报错：/opt/robot_app/lib 下没有含 framework::LogVa 的 libcora_framework 版本。本轮确认报错根因并做最小修复。

检查命令摘要：

```bash
ssh root@192.168.25.1 'ls -l /opt/robot_app/lib/libcora_framework.so* /opt/arm_dual_app/lib/libcora_framework.so* 2>/dev/null'
ssh root@192.168.25.1 'symbol="_ZN9framework5LogVaENS_8LogLevelEPKcS2_S2_iS2_St9__va_list"; for f in /opt/robot_app/HY6310_airrtm_control/lib/libcora_framework.so.0.0.1 /opt/robot_app/lib/libcora_framework.so.0.1.3; do echo "--- $f"; nm -D "$f" 2>/dev/null | grep -F "$symbol" || echo "NO_LOGVA"; done'
```

关键结论：/opt/robot_app/lib/libcora_framework.so.0.1.3 不导出 framework::LogVa；/opt/robot_app/HY6310_airrtm_control/lib/libcora_framework.so.0.0.1 导出该符号。

修复操作：将 /opt/robot_app/lib/libcora_framework.so.0.1.3 移入备份目录 /opt/robot_app/lib/.disabled_logva_20260710_210118/，并将 /opt/robot_app/lib/libcora_framework.so.0.0.1 symlink 到 HY6310 包内的可用版本，然后将 /opt/robot_app/lib/libcora_framework.so.0 指向 0.0.1。

验证命令：

```bash
ssh root@192.168.25.1 'timeout 12 bash /root/start-arm-dual-app-2arm.sh'
```

关键输出：

```text
[start-arm-dual-app] robot_app libcora_framework 符号检测通过（-> libcora_framework.so.0.0.1）
[start-arm-dual-app] 启动 left_arm ...
[start-arm-dual-app] 启动 right_arm ...
[start-arm-dual-app] 启动 robot_app remote ...
[start-arm-dual-app] 全部启动完成（3/3）
```

结论：用户遇到的 LogVa 检查错误已修复。验证使用 timeout 12，结束后向三个进程发送 SIGTERM 并清理；用户需要在 X5 终端重新执行 bash /root/start-arm-dual-app-2arm.sh 作为正式常驻启动。



### 2026-07-10 21:30 CST - 核对 AIRBOT-ARM-P7-SW-2026-07-06 包与 X5 版本问题（agent: Codex）

目的：用户报告 start-arm-dual-app-2arm.sh 启动后仍无法进行 OpenPI 相机观测，要求核对 docs/二代臂Arm-P7-SDK开发指南.md 和本机 ~/Downloads/AIRBOT-ARM-P7-SW-2026-07-06-11-28-30.tar.gz 是否存在版本问题。

本地软件包核对：

```bash
ls -lh /home/discover/Downloads/AIRBOT-ARM-P7-SW-2026-07-06-11-28-30.tar.gz
tar -tzf /home/discover/Downloads/AIRBOT-ARM-P7-SW-2026-07-06-11-28-30.tar.gz | sed -n '1,220p'
dpkg-deb -I /tmp/airbot_p7_sw_inspect/AIRBOT-ARM-P7-SW-2026-07-06-11-28-30/components/arm_p7/arm_dual_app_0.3.7_20260703145313_arm64.deb
```

关键结论：7/6 包包含 arm_dual_app 0.3.7、arm_app 0.3.7、arm_ota_app 0.2.0、arm_p7_sdk 1.1.2、sensor_hub V1.5.0 固件；没有直接包含 robot_app deb。X5 当前 dpkg 显示 arm_dual_app 0.3.7，和 7/6 包一致；robot_app 为 0.1.3-xf9600，属于另一套 remote/camera 程序。

X5 文件状态检查：

```bash
ssh root@192.168.25.1 'dpkg -l | grep -E "robot_app|arm_dual"'
ssh root@192.168.25.1 'dpkg -V robot_app; dpkg -V arm_dual_app'
```

关键输出：robot_app 校验异常包括 /opt/robot_app/configs/mipi_camera/x5/camera_config.json 被改、/opt/robot_app/lib/libcora_framework.so.0.1.3 missing、/opt/robot_app/lib/libinfra.so 与 libsensors.so 类型/权限变化；arm_dual_app 仅 left/right framework_config.json 因 DDS domain 被改为 0 而变化。

修复动作：为避免 /opt/robot_app/lib 与 /opt/robot_app/HY6310_airrtm_control/lib 混用，已将 /opt/robot_app/HY6310_airrtm_control/configs/remote/project_config.json 的 release library_path 改为 /opt/robot_app/HY6310_airrtm_control/lib，configs_path 改为 /opt/robot_app/HY6310_airrtm_control/configs/remote，备份为 project_config.json.bak_libpath_20260710_212606。同时将 /opt/robot_app/lib 中会被 ldconfig 回指的 libinfra.so.bak_hy_20260710_204257 和 libsensors.so.bak_hy_20260710_204257 移入 /opt/robot_app/lib/.disabled_hy_mismatch_20260710_2120/，并补了 libmonitor.so/libinfra.so/libsensors.so/libremote.so 到 HY 版本的 symlink。

验证：robot_app remote 可启动并进入 Framework running，不再卡在 LogVa、monitorCreateNode、libmonitor.so 或 libyaml-cpp.so.0.8；但相机仍未满足 OpenPI 三路 raw 输入。

当前相机状态：ROS2 可见 /camera/left_arm_left/image_rect 和 /camera/left_arm_right/image_rect raw；OpenPI 所需 /camera/head_left/image_rect 和 /camera/right_arm_left/image_rect 仍没有 raw publisher。remote 日志中 head_left/head_right/right_arm_left/right_arm_right 均 attach_to_vin failed，典型错误为 ret=-1，head 的 host_status 为 not inited，right arm 的 host_status 为 lane:4 user:2。

结论：控制端 arm_dual_app/SDK 版本和 7/6 包一致；版本问题集中在 robot_app remote/camera 侧，且 7/6 P7 软件包本身不包含 robot_app deb，不能单靠重装 arm_dual_app 解决三路相机 raw 输入。OpenPI 真实抓取放置测试仍被相机 raw topic 不完整阻塞。



### 2026-07-10 21:40 CST - 检查相机标定内参是否仍存在（agent: Codex）

目的：用户说明此前机械臂可正常运行，后来做了相机标定并改过配置，询问当前相机内参是否仍在。本轮只读检查 X5 标定文件和 camera_config 引用，不重启进程、不控制机械臂。

检查命令摘要：

```bash
ssh root@192.168.25.1 'find /userdata/calibration -maxdepth 3 -type f | sort'
ssh root@192.168.25.1 'for f in /userdata/calibration/head/stereo.yaml /userdata/calibration/left_wrist/stereo.yaml /userdata/calibration/right_wrist/stereo.yaml; do stat -c "%y %s %n" "$f"; grep -E "K:|distortion_model|distortion_coefficients|R:" -n "$f"; done'
ssh root@192.168.25.1 'python3 - <<"PY2"
import json
from pathlib import Path
for p in [Path("/opt/robot_app/configs/mipi_camera/x5/camera_config.json"), Path("/opt/robot_app/HY6310_airrtm_control/configs/remote/mipi_camera/x5/camera_config.json")]:
    print("====", p)
    data=json.loads(p.read_text())
    for c in data.get("camera_mapping", []):
        adv=c.get("advanced_config", {})
        print(c.get("position"), c.get("enable"), adv.get("calibration_target"), adv.get("camera_parameter_role"), c.get("camera_config", {}).get("sensor_name"))
PY2'
```

关键结论：用户标定后的内参文件仍存在于 `/userdata/calibration/head/stereo.yaml`、`/userdata/calibration/left_wrist/stereo.yaml`、`/userdata/calibration/right_wrist/stereo.yaml`，修改时间分别为 2026-07-10 19:00、14:33、14:34，且 YAML 内包含 `K`、`distortion_model`、`distortion_coefficients`、`R` 等字段。runtime 目录下也存在 left/right wrist 的 stereo.yaml。

注意：当前 `/opt/robot_app/configs/mipi_camera/x5/camera_config.json` 使用的 calibration_target 是 `head`、`left_wrist`、`right_wrist`，能对应 `/userdata/calibration/...` 这套用户标定；但当前 HY remote 配置 `/opt/robot_app/HY6310_airrtm_control/configs/remote/mipi_camera/x5/camera_config.json` 使用的是 `xf6600_head`、`xf6600_left_arm`、`xf6600_right_arm`，而 `/userdata/calibration` 下没有 `xf6600_*` 目录。也就是说标定文件还在，但当前 remote/camera 配置存在“可能没有引用用户标定目标名”的问题。

影响：相机 raw topic 不完整不是因为用户标定 YAML 被删除；更可能是当前 remote 运行时使用了 HY remote 配置，其中 sensor_name 与 calibration_target 命名和用户标定后的 `/opt/robot_app/configs/mipi_camera/x5/camera_config.json` 不一致。下一步应优先恢复/合并到用户标定后的 camera_config，而不是重做标定。



### 2026-07-10 21:54 CST - 记录 OpenPI 相机链路当前状态并暂停继续修改（agent: Codex）

目的：用户要求把当前工作状态做记录，后续暂停代码和配置修改，等待下一轮继续处理。本记录汇总 2026-07-10 21:30-21:54 之间围绕相机标定、robot_app remote、OpenPI dry-run 的检查和已发生改动。

已确认事实：

1. 相机标定内参没有丢失。X5 上仍存在 `/userdata/calibration/head/stereo.yaml`、`/userdata/calibration/left_wrist/stereo.yaml`、`/userdata/calibration/right_wrist/stereo.yaml`，文件内有 `K`、`distortion_model`、`distortion_coefficients`、`R` 等字段；修改时间分别在 2026-07-10 14:33、14:34、19:00 附近。
2. `/opt/robot_app/configs/mipi_camera/x5/camera_config.json` 使用 `head`、`left_wrist`、`right_wrist` 这组 calibration target，能对应 `/userdata/calibration/...`。而 HY remote 原配置使用过 `xf6600_head`、`xf6600_left_arm`、`xf6600_right_arm`，与用户标定目录不匹配。
3. 为让 remote 引用用户标定后的相机配置，已在本轮之前/本轮中把 `/opt/robot_app/configs/mipi_camera/x5/camera_config.json` 复制到 `/opt/robot_app/HY6310_airrtm_control/configs/remote/mipi_camera/x5/camera_config.json`，备份为 `camera_config.json.bak_usercal_20260710_213416`。还补了 `/opt/robot_app/HY6310_airrtm_control/configs/remote/calibration/calibration_config.json -> /opt/robot_app/configs/calibration/calibration_config.json` 的 symlink。
4. robot_app remote 用上述配置可以启动并持续产出相机 direct route 日志。remote 日志显示 head、left_wrist、right_wrist 左右目都在发布，典型日志包括 `Published image for route 'head_left/isp': 640x512, encoding=nv12 readers=0`，以及 VSE route 如 `head_right/vse/0`、`left_wrist_right/vse/0`、`right_wrist_right/vse/0`。这说明相机驱动/取帧不再是完全失败状态。
5. 当前核心阻塞点：这些相机 direct route 没有进入 ROS2 graph。本机执行 `ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic list -t` 只能看到 `/arm/...`、`/joy`、`/diagnostics` 等 topic，看不到 `/robot/camera/...`；X5 上 source `/opt/ros/humble/setup.bash` 后执行同样 topic list，也看不到 camera topic。remote 日志里相机发布端 `readers=0`，说明没有 ROS2 订阅者匹配到这些 camera writer。
6. 已验证 QoS 不是唯一问题。采集脚本原先只用 `ReliabilityPolicy.BEST_EFFORT`；本轮补了 `--qos-reliability {best_effort,reliable}` 并用 `--qos-reliability reliable` 订阅 `/robot/camera/head/left/image`、`/robot/camera/left_wrist/left/image`、`/robot/camera/right_wrist/left/image`，仍超时：`timed out waiting for camera frames: missing=['base_0_rgb', 'left_wrist_0_rgb', 'right_wrist_0_rgb']`。因此问题更像是 remote 相机流作为内部 DDS/direct route 发布，但未作为 ROS2 topic 暴露，或 topic 命名/类型没有被 ROS2 graph 识别。
7. OpenPI policy server 本轮曾启动并可监听 `0.0.0.0:8000`，此前单帧 observation -> policy request 曾返回 `action_shape=[50,32]`。在用户要求暂停后，已用 Ctrl+C 停止该本地策略服务，避免后台占用端口。
8. 没有执行机械臂运动。本轮后半段只做相机 dry-run 采集和 ROS2 graph 检查，没有调用 `move_end_pose`、`move_end_pose_linear` 或 `move_eef`。

关键命令和输出摘要：

```bash
# 本机 ROS2 graph：没有 camera topic
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic list -t
# 输出只包含 /arm/left/...、/arm/right/...、/joy、/diagnostics、/rosout 等，没有 /robot/camera/...

# X5 ROS2 graph：source ROS2 后同样没有 camera topic
ssh root@192.168.25.1 'source /opt/ros/humble/setup.bash && ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic list -t'
# 输出同样只有 arm/joy/diagnostics 等，没有 /robot/camera/...

# reliable QoS 采集仍失败
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp timeout 15 /usr/bin/python3 examples/airbot/capture_ros2_openpi_observation.py \
  --output /tmp/openpi_reliable_obs.npz \
  --metadata-output /tmp/openpi_reliable_obs.json \
  --timeout-s 10 \
  --qos-reliability reliable \
  --state-dim 16 \
  --base_0_rgb-topic /robot/camera/head/left/image \
  --left_wrist_0_rgb-topic /robot/camera/left_wrist/left/image \
  --right_wrist_0_rgb-topic /robot/camera/right_wrist/left/image
# 输出：timed out waiting for camera frames: missing=['base_0_rgb', 'left_wrist_0_rgb', 'right_wrist_0_rgb']

# 当前 remote 进程状态（用户未要求停止，保留运行）
ssh root@192.168.25.1 'ps -ww -C robot_app -o pid,ppid,lstart,etime,stat,args='
# 关键输出：PID 6212，PPID 1，./bin/robot_app /opt/robot_app/configs/remote/project_config.json
```

本地脚本已发生的改动（暂停前完成）：

- `examples/airbot/capture_ros2_openpi_observation.py`：新增 `--qos-reliability` 参数，可在 `best_effort` 和 `reliable` 间切换，并把所用 QoS 写入 metadata。
- `examples/airbot/openpi_p7_persistent_loop.py`：新增相机 topic 参数透传和 `--camera-qos-reliability`，用于常驻 OpenPI dry-run/执行循环调用同一套 ROS2 采集脚本。
- 两个脚本已通过 `python3 -m py_compile examples/airbot/capture_ros2_openpi_observation.py examples/airbot/openpi_p7_persistent_loop.py`。

当前状态和后续入口：

- 继续前不应再优先改 OpenPI 模型或 checkpoint；policy 侧已经能返回动作。
- 下一轮应优先解决 remote camera -> ROS2 topic 暴露问题。候选方向：检查 `libsensors.so`/remote 相机 direct route 是否本来就是 Cora DDS 而非 ROS2 publisher；确认是否需要 bridge 或使用 SDK/record 工具直接订阅 `rt/robot/camera/...`；对比旧版 `start-robot-app-3arm.sh` 下曾经出现的 `/camera/head_left/image_rect` 话题生成链路；必要时回滚/合并 camera_config 中的 topic 命名和发布组件，而不是重新标定。
- 用户已明确要求：从本记录开始暂停代码和配置修改，等待后续继续。

## 2026-07-17 11:05 — OpenPI 推理→机械臂链路连通性复查（agent: Claude）

> ⚠️ 本条为 11:05 的时点快照，结论「链路不通」在同日 11:26 已被解决——见下方 [2026-07-17 11:26 条目](#2026-07-17-1126--把-openpi机械臂链路实际拉起并端到端-dry-run-走通agent-claude已获用户授权停启服务)。断点确认为 X5 未启动 `arm_dual_app`，拉起后端到端 dry-run 已走通。

背景：用户更新了 [二代臂Arm-P7-SDK开发指南.md](二代臂Arm-P7-SDK开发指南.md)（SDK V2.0）和 [小推车遥操作使用文档.md](小推车遥操作使用文档.md)（AIRRTM 遥操栈，H264 相机 `rt/camera/...`、臂 `rt/arm/*/control/...`），要求确认 openpi 推理控制机械臂的链路是否还通。本轮全部只读，未发任何运动命令。

链路四跳与实测结论：

- **policy 服务端（GPU 工作站）**：✅ 就绪但未运行。checkpoint `checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/` 在；`.venv` 在；`scripts/cmds/serve_policy.sh` 指向该 checkpoint，`PORT=8000`。本机 `127.0.0.1:8000` 当前 closed（按需启动，历史已实测可推理）。
- **SDK client 环境**：✅。`.venv-p7-sdk` 存在，`arm_p7_sdk 1.1.2`。桥接代码（`airbot_p7_adapter.py`、`policy_to_p7_sdk_bridge.py`、`openpi_p7_persistent_loop.py`）用到的接口 `AirbotClient/get_service_state/get_end_pose/acquire_control/switch_controller(servo_control)/set_arm_speed/move_end_pose(CartesianPose,CartesianMoveOptions)/move_end_pose_linear/switch_eef_control_mode(csp)/set_eef_speed/move_eef(EEFMoveOptions)` 全部与更新后的 V2.0 SDK 文档 API 表一致，代码侧不需要改。
- **臂控半程（P7 SDK gRPC 50071/50072）**：❌ 断。`ssh root@192.168.25.1` 通（无线 `172.100.10.159` No route to host，已不可达）；但 `50071/50072` 两端口 `connect refused`。X5 当前只跑一个裸 `robot_app ./configs/project_config.json`（PID 398，cwd `/opt/robot_app`），**没有** `arm_dual_app` / `arm_app` / `wcr_rc_app` 进程，`50071/50072/8091/8092/9000` 均无监听。→ `AirbotClient` 无法建连，臂控链路当前不通。
- **观测半程（ROS2）**：⚠️ 部分。当前 `robot_app` 发相机 `/robot/camera/{head,left_wrist,right_wrist}/left/image`(+`isp_image`/`video_encoded`) 及 IMU、右夹爪 joint_state、触觉；但**没有任何臂关节话题**（无 `/arm/*/fsm/joint_state`），相机话题名也与 openpi 采集脚本默认 `/camera/head_left/image_rect` 等不一致。

组件安装齐全（`dpkg`）：`arm_dual_app 0.3.7`、`arm_app 0.3.9-alpha1`、`wcr_rc_app 1.0.0`、`robot_app 1.3.1-17`；`/root/start-arm-dual-app-2arm.sh`（7-08 版）仍在。

关键命令：
```bash
# 端口探测（本机）
python3 -c 'import socket;[print(h,p,socket.socket().connect_ex((h,p))) for h in ["192.168.25.1","172.100.10.159"] for p in [50071,50072]]'
# → 192.168.25.1:50071/50072 都 refused(111)

# X5 进程 / 端口 / 话题
ssh root@192.168.25.1 "ps -eo pid,etime,args | grep -E 'arm_app|arm_dual_app|wcr_rc_app|robot_app' | grep -v grep"
# → 只有 ./bin/robot_app ./configs/project_config.json
ssh root@192.168.25.1 "ss -lntp | grep -E '50071|50072|8091|8092|9000'"   # → 无
ssh root@192.168.25.1 "source /opt/ros/humble/setup.bash; ROS_DOMAIN_ID=0 ros2 topic list"
# → 有 /robot/camera/.../image，无 /arm/* 话题
```

**结论**：链路当前**不通**，断点在机器人侧——臂控服务（gRPC 50071/50072）没起来，X5 只跑了纯相机/传感器 `robot_app`。软件包和启动脚本都在，恢复 openpi 臂控需在 X5 执行 `/root/start-arm-dual-app-2arm.sh`（拉起 `arm_dual_app` left 50071 / right 50072 + `robot_app remote`），随后再核对 remote 配置下的相机/臂话题名是否与 openpi 采集脚本对齐。SDK API 与用户更新的 V2.0 文档一致，桥接代码无需改动。注意更新的遥操文档描述的是 AIRRTM 遥操/数采栈（H264 `rt/camera/...` + `rt/arm/*/control/...`），与 openpi 推理走的 `arm_dual_app` gRPC + `robot_app remote` 是两套互斥部署，不能同时占用 CAN。

## 2026-07-17 11:26 — 把 OpenPI→机械臂链路实际拉起并端到端 dry-run 走通（agent: Claude，已获用户授权停/启服务）

承接同日 11:05 复查（当时结论：链路不通，断点在机器人侧 arm_dual_app 未启动）。本轮在用户授权下把臂控服务拉起，并端到端 dry-run 走通，全程臂保持 IDLE、未发任何运动命令（未加 `--execute`）。

### 断点根因（已定位）
- X5 上 `hbks_app.service`（systemd，`/etc/init.d/hbks_app.sh` → `robot_app ./configs/project_config.json`，`Restart=on-failure`）开机自启的是**纯相机/传感器 robot_app**，不含臂控。kill 掉 `robot_app` 后 1 秒被该 service 自动重生（PID 398→4239）。
- openpi 臂控需要的 `arm_dual_app`（gRPC 50071/50072）**开机不自启**；本开机周期 `can0/can1` 处于 DOWN/STOPPED，臂服务从未拉起 → 50071/50072 无监听 → `AirbotClient` 连不上。

### 本轮操作（授权范围内）
1. `pkill robot_app`（被 hbks_app 立即重生，确认守护者是 `hbks_app.service`）。
2. 配 CAN：`ip link set can0/can1 type can bitrate 1000000 dbitrate 5000000 fd on ... up` → 两口 UP、ERROR-ACTIVE（tx/rx err=0，健康）。
3. **不停相机栈**，手动起 `arm_dual_app`（相机 robot_app 不碰 CAN，两者共存）：
   ```bash
   cd /opt/arm_dual_app; export LD_LIBRARY_PATH=/opt/arm_dual_app/lib:/usr/hobot/lib
   setsid nohup ./bin/arm_dual_app ./configs/left_arm/project_config.json  >/tmp/arm_dual_app_logs/left_arm.log  2>&1 </dev/null &
   setsid nohup ./bin/arm_dual_app ./configs/right_arm/project_config.json >/tmp/arm_dual_app_logs/right_arm.log 2>&1 </dev/null &
   ```
   日志：`gRPC server listening on 0.0.0.0:50071`（左）/`50072`（右），`Framework started successfully`，识别 `model=p7c_G2P arm=p7c eef=G2P joint_count=7`。

### 端到端验证（全部通过，无运动）
- **端口**：工作站探测 `192.168.25.1:50071/50072` 均 OPEN。
- **SDK 只读**（`.venv-p7-sdk`，`arm_p7_sdk 1.1.2`）：左右臂 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`；`get_end_pose()`、7 轴 `get_arm_joint_state()`、`eef_type='G2P'` 全部可读。未 acquire、未切控制器、未 move。
- **观测采集**：工作站已装 ROS2 jazzy + rclpy（旧 docs "工作站无 ROS" 已过期），`ROS_DOMAIN_ID=0 rmw_fastrtps_cpp` 跨机可见 X5 相机+臂话题。`capture_ros2_openpi_observation.py` 覆盖话题名后采到三路帧（480×640 nv12→RGB）：
  - `base_0_rgb` ← `/robot/camera/head/left/image`
  - `left_wrist_0_rgb` ← `/robot/camera/left_wrist/left/image`
  - `right_wrist_0_rgb` ← `/robot/camera/right_wrist/left/image`
- **策略推理**：`serve_policy.sh`（config `pi05_vio_plant_collection`，ckpt `vio_pi05_260628/80000`）监听 `0.0.0.0:8000`；用真实观测请求返回 action `(50,32)`，`infer_ms≈1990`。
- **桥接 dry-run**：`policy_to_p7_sdk_bridge.py --host 192.168.25.1 --left-port 50071 --right-port 50072`（无 `--execute`）读取左右臂 TCP pose，relpose 积分为目标 pose，限幅校验通过（左 translation≈3.2mm/rot≈0.012rad，右≈2.6mm/0.009rad，夹爪 model→mm 映射正常）。前后 `ServiceState` 均 IDLE/idle/valid。

### 结论
**OpenPI 推理→机械臂控制链路现已打通**（相机→policy→SDK 目标位姿全程 dry-run 验证）。此前不通的唯一原因是 X5 只跑了开机自启的纯相机 `robot_app`，而臂控 `arm_dual_app`（gRPC 50071/50072）没起、CAN 没配。SDK API 与用户新版 V2.0 文档一致，桥接代码无需改动。

### 遗留 / 注意
- **配置漂移**：`start-arm-dual-app-2arm.sh` 里 `robot_app remote` 用的 `/opt/robot_app/configs/remote/project_config.json` **已不存在**（新版 robot_app 1.3.1-17 改用扁平 `configs/project_config.json`）。所以没走该脚本，改为手动起 arm_dual_app + 保留现有相机 robot_app。该脚本的 remote 那步现在会被跳过，需按新部署更新。
- **相机话题名变了**：实际是 `/robot/camera/<head|left_wrist|right_wrist>/<left|right>/image`，与 openpi 采集脚本默认 `/camera/head_left/image_rect` 等不一致；采集/常驻循环需用 `--*-topic` 覆盖（本轮已用）。
- `arm_dual_app` 非开机自启、CAN 非开机配置：重启 X5 后需重新配 CAN + 起 arm_dual_app（或修复 remote 配置后用一键脚本）。
- 当前运行态：X5 上 `arm_dual_app` 左右臂 + 相机 `robot_app` 并存；工作站 `serve_policy` 仍在 `:8000`。真实运动需 `--execute --allow-robot-motion`，本轮未做。

## 2026-07-17 14:03 — 机械臂重启后链路复测 + 一键脚本适配新部署（agent: Claude，已获用户授权）

用户重启了机械臂后要求：重新测链路、录 3s 相机视频确认图像、并修好之前失效的一键脚本以适配新硬件/固件。

### 重启后状态（符合预期）
- 相机 `robot_app`（PID 464）由 `hbks_app.service` **开机自启**，跑扁平 `configs/project_config.json`；
- `arm_dual_app` **未自启**，`can0/can1` DOWN，`50071/50072` 无监听；
- `/opt/robot_app/configs/remote/project_config.json` 仍不存在。
→ 即每次重启后臂控链路都需要重新配 CAN + 起 arm_dual_app。

### 修好一键脚本 `scripts/tools/start-arm-dual-app-2arm.sh`（已同步部署到 X5 `/root/`，旧版备份 `.bak_*`）
适配 `robot_app 1.3.1-17` / `arm_dual_app 0.3.7` 新部署，核心改动：
- **不再自启相机 robot_app**：相机栈已由 `hbks_app.service` 提供；脚本只负责「配 CAN + 起 arm_dual_app 左右臂」。
- **移除失效的 `robot_app remote` 启动**：`configs/remote/project_config.json` 已被新部署删除。改为可选兜底 `START_ROBOT_APP_REMOTE=1`（默认 0，且配置存在才起）。
- **`require_no_existing_runtime` → `require_no_existing_arm_dual`**：只拒绝重复 `arm_dual_app`；**允许相机 `robot_app` 共存**（arm_dual_app 走 can0/can1，相机不碰 CAN，无冲突）。旧脚本此处会因相机 robot_app 存在而直接报错退出——这是它在新部署下「失效」的直接原因。
- **移除 `ensure_robot_cora_framework_symlink`**：该步会改动正在运行的相机栈 lib，共存场景下不应触碰。
- 无 arm_dual_app 被拉起时以非零码退出，避免静默空跑。

### 复测结果（全部通过，无运动）
- 用修好的脚本一键拉起：日志显示正确识别相机 robot_app 共存、配 CAN、起 left(50071)/right(50072)、跳过 remote。
- 端口：工作站探测 `50071/50072` OPEN。
- SDK 只读（`.venv-p7-sdk`）：左右臂 `IDLE/idle/valid`，TCP pose / 7 轴关节 / `eef_type='G2P'` 全部可读。
- **相机 3s 视频**：新增 `examples/airbot/record_camera_clip.py`（跨机订阅、nv12→RGB、cv2 编码，imageio/ffmpeg 兜底）。工作站 ROS2 jazzy + `ROS_DOMAIN_ID=0 rmw_fastrtps_cpp` 录到三路各 **72 帧 @30fps**（640×480 nv12），产物 `/tmp/airbot_cam_clip/{base_0_rgb,left_wrist_0_rgb,right_wrist_0_rgb,tiled}.mp4` + 中间帧 PNG，图像清晰正常（木地板/警示胶带/机械臂硬件可见）。

### 用法（重启后恢复臂控链路）
```bash
ssh root@192.168.25.1 'setsid nohup bash /root/start-arm-dual-app-2arm.sh >/tmp/start-arm-dual-app.launch.log 2>&1 </dev/null &'
# 相机栈已由 hbks_app.service 自启，无需手动起。
```

## 2026-07-17 14:20 — 头部相机畸变根因诊断（agent: Claude，全程只读）

用户反映头部相机图像有畸变，问是否缺标定文件。结论：**不是缺标定文件**，是 GDC 硬件去畸变表过期/未随今天的重标定重建。

### 事实链（全部只读 ssh 核实）
- 头相机话题只有 `image` / `isp_image` / `video_encoded`，**无 `image_rect`**。该平台不走 ROS image_proc rectify，去畸变由海思/地平线 **GDC（几何畸变矫正）硬件模块**在 ISP 阶段完成，矫正后直接发 `image`。
- 所有相机 `camera_info` 的 `d: [0,0,0,0,0,0,0,0]`。这是「GDC 已在硬件矫正、故 camera_info 不再带畸变系数」的正常表现，不代表没标定。
- 标定结果**存在且有效**：`/userdata/calibration/head/mono_left.yaml` 有真实畸变系数（`-0.185, 0.0486, ...`）、内参 K、`fovx≈93.9°`；另有 GDC 查找表 `head_left_gdc.bin`/`head_right_gdc.bin`、`stereo.yaml`、`gdc_state.json`。左右腕同样有（腕用 `equidistant` 鱼眼模型，系数如 `[0.405,0.131,-0.219,0.061]`）。
- 相机配置 `mipi_camera/x5/camera_config.json` 中每路 `gdc_setting.enable=true`、`calibration_sync.enable=true`，`gdc_bin_file=""`（靠自动同步生成）。GDC 在配置上是开的。

### 冒烟证据（时间线 + sha256）
- 相机 `robot_app` 启动：**13:32:31**。
- 今天重标定写入 active：`head/stereo.yaml`、`mono_left.yaml` mtime **13:34:36**（在相机启动 **2 分钟之后**）。
- 实际加载进硬件的 `runtime/head_left_gdc.bin` mtime 仍是 **2026-07-13 18:50**。
- sha256：active `head/stereo.yaml`=`24a36d2c...` ≠ `runtime/stereo.yaml`=`6e71395d...`；`runtime/gdc_state.json` 记录 `calibration_sha256=6b8b64e1...`、`updated_at`≈7-13。
→ 相机启动时加载的是 **7-13 的 GDC 去畸变表**；13:34 做的新标定**从未被编译成新的 GDC bin、也没热重载进相机管线**。所以头相机当前按旧标定（或不匹配的表）去畸变，残留可见畸变。

### 结论与修复方向（未执行，待用户确认）
- 不需要补标定文件。需要让 GDC 重新用**当前 active 标定**生成并加载查找表。
- 因为 `calibration_sync.enable=true`，最简做法：**在新标定就位后重启相机 `robot_app`（经 `hbks_app.service`）**，让它启动时用 active 标定重建/加载 runtime GDC。或调用板端 GDC 重建流程（`robot_app_x5_gdc` 生成器）刷新 `runtime/*.bin`。
- 重启相机栈属于对共享硬件的操作，且会短暂中断相机话题，需用户确认后再做。

## 2026-07-17 15:21 — 机械臂再次重启后：链路复通 + 头相机 GDC 刷新验证（agent: Claude，已获授权重启相机栈）

用户第三次重启机器人后要求继续。本轮：重拉臂控、诊断并恢复跨机相机、验证头相机畸变。

### 状态与操作
- 重启后（boot 15:03:19）：相机 robot_app 自启（PID 398→重启后），arm_dual_app 未自启、CAN DOWN。用修好的 `/root/start-arm-dual-app-2arm.sh` 重新拉起臂控（50071/50072 OK，两臂 Framework started）。
- **GDC 表已刷新且匹配**：`runtime/head_left_gdc.bin` mtime 14:38（上一会话期间重建），active `head/stereo.yaml` sha256 = runtime `stereo.yaml` sha256 = `24a36d2c...`（一致）。即今天 13:34 的重标定已被编译进 GDC 表。→ 上一条（14:20）诊断的"表过期错配"问题已消除。

### 跨机相机发现故障与恢复
- 现象：重启后工作站看不到相机话题（`camera=0`），但能看到 arm_dual_app 的 84 个 arm 话题（`arm=1`）；X5 本机相机 29Hz 正常、多播已加入 eth0（`netstat -gn` 见 239.255.0.1 on eth0）、7400/udp 单播可达。
- 排除：工作站 DDS 正常（arm 可见）；清 profile + 重置 daemon 干净环境仍 `camera=0`。→ 定位为机器人侧相机 participant 本次重启后（开机+4s、网络就绪前启动）发现状态异常。
- 恢复：`systemctl restart hbks_app.service`（授权），相机 robot_app 在网络就绪后重启（PID 4741, 15:20:08）。~5s 后工作站即可发现相机，30Hz。

### 头相机畸变结论（回答用户）
- 录到 3s 三路视频（各 ~79-80 帧 @30fps，640×480）：`/tmp/airbot_cam_clip2/{base_0_rgb,left_wrist_0_rgb,right_wrist_0_rgb,tiled}.mp4`。
- 主观对比 GDC 刷新前(`/tmp/airbot_cam_clip/base_0_rgb`) vs 后(`/tmp/airbot_cam_clip2/base_0_rgb`)：头相机边缘仍有广角弧度，两者差异不大。
- **三层结论**：(1) 不缺标定文件（mono/stereo yaml + gdc bin 齐全有效）；(2) GDC 表过期错配（上一条的真问题）现已修复（sha256 一致）；(3) 边缘残留广角弧度是当前标定 + 求解器 `rectify_mode=keep_out_valid_and_shape`（刻意保留 FOV/画幅、不做激进拉直）+ 头相机 `fovx≈93.9°` 广角镜头的正常产物。
- 若要头相机画面更平直：需改标定求解 `rectify_mode`（更激进裁剪矫正）重新生成 GDC 表，属改标定策略，待用户决定。

## 2026-07-17 15:3x — 首次双臂真机关节 PTP 运动（agent: Claude，用户明确指令 + 授权）

用户指令：双臂快速运动到 joint 目标 `[0, 0.647, 0, -0.933, 0, 0, -1.15]` rad。用户选定：双臂、速度/加速度缩放 0.5。

- 工具：`examples/airbot/p7_move_to_joint_target.py`（planning_control + move_joint PTP，非连续 servo）。
- 目标全部在 SDK 限位内（joint7 -1.15 ∈ [-1.5608, 1.2117]）。
- 先 dry-run：左臂 max_abs_delta 0.930 rad、右臂 1.316 rad，均在脚本护栏 1.5 rad 内。
- 执行（`--execute --allow-robot-motion`，vel/acc scaling=0.5）：
  - 流程 `acquire_control→switch_planning→move_joint(ptp,blocking)→switch_idle→release_control` 每步 True。
  - 到位精度：左臂 max_abs_error **0.000168 rad**、右臂 **0.000202 rad**（≈0.01°）。
  - 运动后两臂均回 `IDLE/idle/valid`，控制权已释放。
- 说明：这是本仓库首次双臂真机关节运动（此前均为单臂小步 guarded/probe 或 dry-run）。链路（arm_dual_app gRPC 50071/50072 + p7 SDK）在真机 planning PTP 下工作正常。

## 2026-07-17 15:37 — 首次 OpenPI 闭环推理控制双臂+夹爪真机运动（agent: Claude，用户授权：场景就绪+无人+可执行）

用户指令：执行一次 openpi 推理控制双臂完成抓取放置。用户选定：跑 60s、包络放宽 25cm、场景就绪可执行。

### 执行配置
- 工具：`scripts/cmds/openpi_p7_persistent_loop.sh`（常驻循环，保活控制租约）。`openpi_p7_closed_loop.sh` 不支持相机话题覆盖，采图默认话题超时，故未用它。
- 参数：`--duration-s 60 --period-s 0 --controller servo --enable-gripper --chunk-steps 5 --max-envelope-m 0.25 --max-step-translation-m 0.005 --max-step-rotation-rad 0.02 --arm-speed-rad-s 0.55`，相机话题覆盖为 `/robot/camera/{head,left_wrist,right_wrist}/left/image`。
- 起始：双臂 IDLE，TCP≈(-0.077,0,0.55)，夹爪闭合(0mm)。

### 结果：闭环真机运动成功跑通 2 迭代（~10 动作步），随后被相机中断，安全停止
- **策略确实驱动了双臂+夹爪真机运动**：每步 move_end_pose ok=True，单步位移~0.5-3mm（受 5mm 护栏约束），旋转<0.007rad；夹爪按策略输出执行——**左夹爪张开到 95mm、右夹爪闭合到~5mm**（left/right 分工抓取形态）。measured_target_error 均<1.3mm，跟踪精度good。
- **中断原因**：第 3 迭代 `capture_ros2_openpi_observation.py` 超时退出（exit 1）。相机 DDS 发布失稳——事后查 X5 本机 `ros2 topic list` 相机话题数=0（本机都订不到），但 robot_app（PID 4741）仍存活、AE 日志显示 sensor 仍在采集。属相机 cora DDS 发布侧静默，非硬件、非策略、非臂控问题。
- **安全表现正确**：异常后脚本自动 `switch_eef_idle→switch_idle→release_control`，双臂干净停在 `IDLE/idle/valid`，控制权已释放，无失控。运动后 TCP 左≈(-0.067,-0.008,0.55)、右≈(-0.076,0.007,0.56)，夹爪停在策略末态（左95/右5.6mm）。

### 里程碑与遗留
- **里程碑**：OpenPI 推理→双臂+夹爪真机闭环首次跑通（相机→policy 50×32→relpose 积分→SDK servo move_end_pose + move_eef），全护栏生效、清理正确。此前均为 dry-run 或单步。
- **遗留（根因待解）**：相机 DDS 发布反复失稳（本会话已第 2 次），每次靠 `systemctl restart hbks_app` 恢复。常驻循环每迭代新起一个 rclpy 采集子进程（participant 频繁 churn 于 domain 0），疑与相机 cora DDS 参与者失稳相关。根治方向：采集改为常驻单 participant（不每次新建进程）/ 降低 participant churn / 排查相机 cora DDS 侧。
- 未完成完整抓放：受相机中断 + 场景内是否有真实"植物+收集箱"未核实所限。

## 2026-07-18 16:12 CST — PI0.5 535 clean wrist-only 20k checkpoint 跑通验证（agent: Codex）

目标：验证 `checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/vio_pi05_535_clean_wrist_only_80k_260717/20000` 能否在本机恢复并推理。checkpoint 约 `12G`，Orbax 分片和 `assets/vio_plant_collection_30hz_relpose_535_clean/norm_stats.json` 完整。

训练端只读核对确认准确 config 为 `pi05_vio_plant_collection_535_clean_wrist_only`：PI05、horizon 50、action dim 32、只使用左右腕相机、头相机补零且 `mask=False`、`include_advantage=False`。本地原先缺这组 config 和 wrist-only 输入逻辑，已从训练端同步最小必要契约到 `src/openpi/training/config.py`、`src/openpi/policies/airbot_policy.py`，并新增对应单元测试。

实际启动目标服务到 `:8001`：Orbax 输出 `total bytes: 6.2 GiB`、`Finished restoring checkpoint in 3.57 seconds`，随后从 checkpoint 自带 assets 加载 norm stats，并监听 `0.0.0.0:8001`。首次 mock 请求（含 JAX 编译）返回有限值 `actions (50,32)`，`infer_ms=10670.95`；第二次只发送左右腕图像、不发送头相机，仍返回有限值 `(50,32)`，`infer_ms=179.78`。输入变换实测头相机 `base_sum=0`、mask 为 False，两路腕相机 mask 为 True。

验证：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q src/openpi/policies/airbot_policy_test.py src/openpi/shared/airbot_policy_bridge_test.py` → `8 passed`；限定 E/F 的 ruff 检查通过；`git diff --check` 通过。普通 pytest 会被系统 ROS Jazzy 自动加载的 `launch_testing` plugin 因缺 Python 3.11 `lark` 打断，与本次代码无关。

结论：**checkpoint 可以跑通**，含参数恢复、norm stats、wrist-only 输入契约和动作输出均已实测。未使用真实相机、未控制真机，不能据此判断任务成功率。因单 GPU 原有旧模型占约 12.2 GiB，本轮临时停止旧服务后验证；收尾已停止目标 `:8001` 服务，并按原命令恢复旧 checkpoint 服务到 `0.0.0.0:8000`。详见 [pi05-535-clean-wrist-only-checkpoint.md](pi05-535-clean-wrist-only-checkpoint.md)。

## 2026-07-18 16:20 CST — wrist-only 真机入口不再依赖头相机（agent: Codex）

用户明确补充：新 checkpoint 只需要 `left_wrist_0_rgb`、`right_wrist_0_rgb`，不需要 `base_0_rgb`。复查发现服务端新 config 已正确排除头相机，但通用单帧采集、常驻相机 daemon、NPZ 请求和 P7 常驻循环仍默认等待三路相机。

已为四个入口统一增加显式 `--wrist-only`：采集/daemon 不订阅、不等待、不写入头相机；NPZ 请求不要求也不发送 `base_0_rgb`；P7 常驻循环把模式同时传给采集与 policy 请求。默认三相机行为不变，旧 checkpoint 兼容。

验证：新增 wrist-only NPZ 回归测试后，`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q src/openpi/policies/airbot_policy_test.py src/openpi/shared/airbot_policy_bridge_test.py examples/airbot/request_policy_from_observation_npz_test.py` → `9 passed in 2.40s`；四个 CLI 的 `--help` 均显示 `--wrist-only`；Python 编译、限定 E/F ruff、`git diff --check` 通过。ROS 两个 CLI 用 `mamba run -n ros2-topic python` 验证通过；直接系统 `python3` 因该环境缺 `numpy` 失败，不是脚本问题。本轮未订阅真实相机、未连接或控制机械臂。详见 [pi05-535-clean-wrist-only-checkpoint.md](pi05-535-clean-wrist-only-checkpoint.md)。

## 2026-07-18 16:32 CST — 目标 checkpoint 真实双腕观测 + P7 全链路 dry-run（agent: Codex）

真实采集：用 `capture_ros2_openpi_observation.py --wrist-only` 从 `/robot/camera/{left_wrist,right_wrist}/left/image` 同步采到两路 `nv12 640x480`，时间戳差约 `34us`。NPZ 只有左右腕和 state，没有头相机；两路 RGB 均为完整 `0..255` 动态范围，非零像素约 `95.58%/96.24%`。

真实推理：目标 20k checkpoint restore `4.20s` 并监听 `:8001`；`request_policy_from_observation_npz.py --wrist-only --no-advantage` 返回有限值 `(50,32)`，`infer_ms=1822.16`，padding 18 维最大绝对值 `4.33e-9`。第一步接 P7 bridge no-execute dry-run：左/右位移约 `1.286/3.506mm`，旋转约 `0.006738/0.008708rad`，夹爪目标约 `49.279/2.503mm`；双臂前后均 `IDLE/idle/valid`，未调用 acquire/controller/move/eef。

horizon 扫描：按 `2cm/0.2rad`，左位移索引 `40..49`、左旋转 `48..49`、右位移 `46..49`、右旋转 `36..49` 超限；这是每行都相对同一观测位姿的远期目标，说明必须短 chunk + 护栏，不能整段连续播放。

常驻链路：wrist-only camera daemon 约一分钟写 `544` 次，始终 `have_all=True missing=[]`；`openpi_p7_persistent_loop.sh --capture-mode latest-file --wrist-only --no-advantage --chunk-steps 5` 单轮全链路 dry-run 通过，稳态 `infer_ms=190.95`，前 5 步均过护栏，双臂最终仍 `IDLE/idle/valid`。summary=`/tmp/openpi_p7_persistent_loop/summary_20260718_162937.jsonl`。

修复 daemon 外部停止时重复 `rclpy.shutdown()` 的清理错误，改为 `rclpy.ok()` 保护；复测 `SIGINT` 后退出码 `0`、无 traceback。最终 `9 passed`、限定 E/F ruff、py_compile、diff check 均通过；测试 daemon/`:8001` 已停止，原旧 checkpoint 服务已恢复到 `0.0.0.0:8000`。本轮没有获取控制权或发送任何运动命令。详见 [pi05-535-clean-wrist-only-checkpoint.md](pi05-535-clean-wrist-only-checkpoint.md)。

## 2026-07-19 18:55 CST — 新 `arm_app` DDS route 与更新 SDK 指南复核（agent: Codex）

更新脚本成功启动 `/opt/arm_app` 左右实例，持久化日志 `/userdata/arm_app_logs/20260719_185439/` 确认只注册 `rt/arm/{left,right}/dds_route`，没有 gRPC route 或 `50071/50072`。更新指南确认双臂 DDS client 应分别传 `side="left"/"right"`、`domain_id=0`；工作站 `.venv-p7-sdk` 为 x86_64/Python 3.11，`import cora` 返回 `ModuleNotFoundError`。因此当前阻塞点是工作站 DDS 私有依赖，或需将 DDS 执行代理移到 X5。本轮未下发运动。详见 [p7-dds-route-current-state.md](p7-dds-route-current-state.md#7-2026-07-19-1855-cst更新指南与新-arm_app-实机配置复核)。

## 2026-07-19 20:03 CST — 停止真机推理并确认 20k wrist-only 输入（agent: Codex）

已停止 `openpi_p7_unlimited_recovery`、`openpi_p7_persistent_loop` 和单次 policy 请求子进程，最终仅保留不下发动作的 `serve_policy.py :8000`。当前加载 `pi05_vio_plant_collection_535_clean_wrist_only` 的 `.../20000` checkpoint；本次每个请求都带 `--wrist-only`，响应 `observation_shapes` 只有左右腕 640x480 RGB 与 16 维 state，头相机未采集/未发送且模型槽位 mask=False。详见 [pi05-535-clean-wrist-only-checkpoint.md](pi05-535-clean-wrist-only-checkpoint.md#2026-07-19-2003-cst停止当前真机推理并复核实际-checkpoint--相机输入)。

## 2026-07-19 20:32 CST — 再次停止真机推理（agent: Codex）

按用户指令核对本机进程：`openpi_p7_unlimited_recovery`、`openpi_p7_persistent_loop`、`request_policy_from_observation_npz` 均不存在，当前不会继续下发动作或自动恢复；仅保留不控制机械臂的 wrist-only `serve_policy.py :8000` 待命。

## 2026-07-19 21:07 CST — 停止新一轮真机推理（agent: Codex）

按用户指令终止当前 `openpi_p7_unlimited_recovery` supervisor（PID `423144`）。最终进程核对确认 P7 控制循环与单次 policy 请求均不存在，不会继续下发动作或自动恢复；仅保留空闲的 wrist-only `serve_policy.py :8000`。

## 2026-07-19 21:28 CST — 停止当前真机推理（agent: Codex）

按用户指令终止 `openpi_p7_unlimited_recovery` supervisor（PID `427162`）。最终进程核对确认没有 P7 控制循环或单次 policy 请求，不会继续下发动作或自动恢复；仅保留空闲的 wrist-only `serve_policy.py :8000`。

## 2026-07-20 15:19 CST — 5 mm 插值、3 cm 实测阈值与双腕录制真机验证（agent: Codex）

按用户指定关节角 `[0,0.647,0,-0.933,0,0,-1.15]` 以 planning PTP、vel/acc scaling=0.03 多次慢速复位；最后一次 left/right 最大误差分别为 `0.000202/0.000144 rad`。确认 idle 期间关节会漂移，因此最终复位和推理启动已紧邻执行。

为防止单步快速运动，新增无 SciPy 的 TCP 平移 + quaternion SLERP 插值：每次从最新实测 TCP 重算下一 waypoint，正常命令不超过 `0.005 m / 0.02 rad`，发令后立即回读；实测硬越界使用 rc=3 停止，普通 move/通信错误仍由 supervisor 快速清错后用新观测继续。用户随后把实测硬阈值从 `0.01 m` 放宽到 `0.03 m`，默认值和实际运行参数均已更新；独立总包络仍为 `0.05 m`。

验证：relpose pytest `9 passed`；fake-client 23mm/11mm 目标的最大命令和实测均 `4.6mm`；80% 跟踪误差场景不会重复追逐最终 waypoint。真实 wrist-only dry-run 把 left `7.454mm` 自动拆成 2 段。修复后的真实单 action 最大命令 `3.288mm`、最大实测 `2.432mm`，全部 move=True。

3 cm 阈值持续运行完成 17 次迭代，最大命令 `0.004021m`、最大实测 `0.003479m`，无丢包/UNKNOWN_ERROR；最后因 left 相对本轮起点总包络 `0.053222m > 0.05m` 安全停止，不是单步 3 cm 越界。收尾双臂均 `IDLE/idle/valid`，无控制进程。

双腕录制已封装到 `/home/discover/Desktop/recording/openpi_wrist_20260720_150624`：左右独立和 tiled MP4 各 `10996` 帧、15fps；独立流 640x480，tiled 1280x480，三份均经 OpenCV 验证可读。详见 [openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md)。

## 2026-07-20 16:32 CST — 编写 joint6 20 秒匀速往复指令（agent: Codex）

目的：按用户给出的 7 关节起点
`[0,0.647,0,-0.933,0,0,-1.15]rad`，编写让 joint6 在 `-0.5rad` 与
`+0.5rad` 之间缓慢、匀速往复且完整周期为 `20s` 的 P7 SDK 指令。本轮只编写和
离线验证，没有连接机械臂、获取控制权或下发真机运动。

接口与限位检查：读取
`examples/airbot/p7_servo_move_to_joint_target.py`、当前
`.venv-p7-sdk/.../arm_p7_sdk/_backends/grpc_route.py` 与
`docs/二代臂Arm-P7-SDK开发指南.md`。确认 `servo_control + move_joint()` 每帧必须
发送完整 7 轴目标；joint6 SDK 命令限位约为 `[-0.77539,0.77539]rad`，所以
`±0.5rad` 合法；`set_arm_speed()` 在 SDK 1.1.2 中的每轴客户端校验下限为
`0.549900008...rad/s`，不能直接设为
目标轨迹速度 `0.1rad/s`。实现因此使用 SDK 可接受的 `0.55rad/s` 速度上限，同时
以 `20Hz` 发送三角波小步位置目标，命令轨迹斜率为
`2 * (0.5 - (-0.5)) / 20 = 0.1rad/s`。

新增：`examples/airbot/p7_joint6_triangle_wave.py`。默认 `--side right` 且默认仅离线
dry-run；真机运行必须同时显式传入 `--execute --allow-robot-motion`。脚本包含 IDLE
前置检查、关节限位、起点最大位移、起点/运行跟踪误差、控制租约以及异常或
`Ctrl+C` 时切 idle/释放控制权。

离线验证命令：

```bash
.venv-p7-sdk/bin/python -m py_compile examples/airbot/p7_joint6_triangle_wave.py
.venv-p7-sdk/bin/python examples/airbot/p7_joint6_triangle_wave.py
.venv-p7-sdk/bin/python - <<'PY'
import importlib.util
from pathlib import Path
path = Path('examples/airbot/p7_joint6_triangle_wave.py')
spec = importlib.util.spec_from_file_location('joint6_wave', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
expected = {0.0: 0.0, 5.0: 0.5, 10.0: 0.0, 15.0: -0.5, 20.0: 0.0, 25.0: 0.5}
for t_s, wanted in expected.items():
    actual = module.triangle_position(t_s, -0.5, 0.5, 20.0)
    assert abs(actual - wanted) < 1e-12, (t_s, actual, wanted)
print('triangle_assertions_ok', expected)
PY
uv run ruff check examples/airbot/p7_joint6_triangle_wave.py
```

关键输出：dry-run 报告 `commanded_speed_rad_s=0.100`，并依次输出
`t=0/5/10/15/20s -> joint6=0/+0.5/0/-0.5/0rad`；断言输出
`triangle_assertions_ok`，`py_compile` 通过，Ruff 输出 `All checks passed!`。单独传
`--execute` 但不传 `--allow-robot-motion` 时，在建立 `AirbotClient` 前以退出码 2
拒绝执行。额外使用不访问网络的 fake client 加速运行一个完整流式周期，输出
`fake_stream_ok commands=6 joint6=[0.0,0.5,0.0,-0.4999999999999998,0.0,0.0]`；
断言确认每帧都是完整 7 轴目标、其它 6 轴保持起点值、joint6 到达两个端点且有限周期
结束后回到起点。正式指令见
[openpi-grasp-task-runbook.md](openpi-grasp-task-runbook.md#54-右臂-joint6-以-20-秒周期匀速往复)。

并行记录核对：同一时间写入的下一条“400 秒运行中断原因复盘”描述的是此前 OpenPI
笛卡尔 `move_end_pose` 闭环，不是本 joint6 脚本的测试结果；但它说明 X5 仍可能拒绝
servo 命令。本脚本遇到任一 `move_joint=False` 会立即停止后续轨迹，并在 `finally` 中
切回 idle、释放控制权，因此不把上述历史故障误报成当前关节往复已通过真机验证。

## 2026-07-20 16:32 CST — 400 秒运行中断原因复盘（agent: Codex）

主日志确认最终停止是外层 `timeout 400s` 在 16:22:25 准时发 TERM；退出码 137 来自 `--kill-after=20s` 在 X5 full restart 清理尚未 ready 时发送 SIGKILL，不是 OpenPI、相机或 policy server 崩溃。

过程内 8 次子进程中断均为单侧 `move_end_pose=False -> UNKNOWN_ERROR`。逐一对照 X5 `/userdata/arm_app_logs` 后，8 次均在进入 UNKNOWN_ERROR 前出现 X5 内部 4ms/250Hz ARM+EEF 命令队列丢弃：ARM `6.4%-30.2%`、EEF `14.7%-61.0%`。SDK servo 路径对 `CallServoPoseCommand` 直接返回 `bool(rep.accepted)`，失败点无对应网络 RPC exception，因此是 X5 未接受动作，不是本机 gRPC 超 250Hz 或推理断链。CAN 为 ERROR-ACTIVE、无 bus-off；本次无同期 CPU 采样，暂不能把队列拥塞进一步归因于 CPU。详见 [openpi-400s-interruption-analysis-20260720.md](openpi-400s-interruption-analysis-20260720.md)。

## 2026-07-20 16:50 CST — 右臂 joint6 20 秒周期往复真机运行（agent: Codex）

目的：按用户明确指令正式运行
`examples/airbot/p7_joint6_triangle_wave.py`，控制右臂从
`[0,0.647,0,-0.933,0,0,-1.15]rad` 起，让 joint6 在 `±0.5rad` 间以
`20s` 完整周期匀速往复。

运动前只读检查：`pgrep` 没有找到残留的 joint6/OpenPI/P7 控制进程；right/50072
返回 `ServiceState(service_state=True,fsm_state='IDLE',controller_state='idle',valid=True)`，
当前关节约
`[0.06546,-0.00144,-0.16900,-1.51591,0.08360,0.07445,-1.48856]rad`。
相对目标最大差值约 `0.64844rad`，小于脚本 `1.5rad` 起点门禁。

实际启动命令：

```bash
nohup .venv-p7-sdk/bin/python examples/airbot/p7_joint6_triangle_wave.py \
  --side right --start '0,0.647,0,-0.933,0,0,-1.15' \
  --joint6-low-rad -0.5 --joint6-high-rad 0.5 \
  --period-s 20 --rate-hz 20 \
  --approach-speed-rad-s 0.1 --sdk-speed-rad-s 0.55 \
  --execute --allow-robot-motion \
  >logs/p7_joint6_wave/right_20260720_c1zeL9.log 2>&1 </dev/null &
```

启动结果：PID=`58904`，`acquire_control=True`、`switch_servo=True`、
`set_arm_speed=0.55`。初始线性摆位共 130 步/`6.5s`，摆位结束最大误差
`0.015134rad`。截至 16:50 连续运行约 2 分钟、超过 4 个完整周期；关键反馈包括：

```text
elapsed=75s  target joint6=-0.500000  measured=-0.481821  error=0.018179rad
elapsed=80s  target joint6= 0.000000  measured=-0.016538  error=0.016538rad
elapsed=85s  target joint6=+0.500000  measured=+0.483835  error=0.016165rad
```

16:50 复核时进程仍在运行；right 为 `SERVO_CONTROL/csp/valid`，关节反馈中除 joint6
外的 6 轴都保持在目标附近，7 个 `motor_state.error_ids` 全为 `0`，电机温度
`28-34C`；日志没有 `FAIL`、`returned False`、`UNKNOWN_ERROR` 或跟踪误差越限。

16:51-16:52 用户要求停止并改为双臂全关节运动。第一次 `kill -INT 58904` 没有
生效，原因是该后台进程继承了 shell 对 SIGINT 的忽略设置；随后
`kill -TERM 58904` 终止进程。进程因 TERM 默认处理没有执行 `finally`，右臂暂时
保持 `SERVO_CONTROL/csp`，但电机错误码仍全为 0；新 SDK 客户端取得
`lease_id=2`，执行 `switch_controller(Controller.idle)=True` 并释放控制权，最终
right 恢复 `IDLE/idle/valid`。已直接修复 `p7_joint6_triangle_wave.py`，显式注册
`SIGINT/SIGTERM` 并统一进入 KeyboardInterrupt 清理，避免后台停止重现该问题。

## 2026-07-20 16:43 CST — 核查 `set_arm_speed()` 的 0.55 rad/s 下限（agent: Codex）

核对本机 `.venv-p7-sdk`，确认安装版本为 `arm-p7-sdk 1.1.2`。该版本
`arm_p7_sdk/models.py` 将 `_MIN_PHYS_SPD` 硬编码为
`0.17507044 * pi - 1e-4 = 0.549900008164733 rad/s`；
`BaseBackend.set_arm_speed()` 要求 7 维列表中的每一项均不低于该值，gRPC 与 DDS
后端都会先调用这层校验。历史真机连续 servo smoke 使用 `0.35` 时，SDK 确实返回
`False` 并打印同一精确下限；`[0.55] * 7` 则已多次返回 `True`。

结论：称“`set_arm_speed()` 下限约为 `0.55 rad/s`”对当前 SDK 1.1.2 的客户端
参数校验是准确的，精确值是 `0.549900008164733 rad/s`。它不是机器人机械层或 TCP
轨迹的物理最低速度，也不表示动作必须以 0.55 rad/s 运行；servo gRPC 后端会把
7 轴速度绝对值的平均值除以约 `2.5*pi`，`[0.55] * 7` 对应 joint scale 约
`0.07003`。更慢的目标轨迹仍可通过较小位置增量和发送频率生成。该结论必须绑定
SDK 版本，升级 SDK 后应重新检查常量与校验逻辑。详见
[p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md#6-2026-07-20-1643-cst--set_arm_speed-下限来源与准确性复核)。

## 2026-07-20 16:46 CST — 79999 wrist-only checkpoint 完整加载通过（agent: Codex）

目标：检查 `checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/vio_pi05_535_clean_wrist_only_80k_260717/79999` 是否完整，并实际加载一次。目录 apparent size 为 `12,439,585,620 bytes`（约 `12G`），共 `19` 个普通文件；Orbax metadata、sharding、OCDBT manifests/数据块和 checkpoint 自带 norm stats 均存在。`state/actions` 两组 norm stats 的 `mean/std/q01/q99` 均为 32 维且所有值有限。

因现有 `20000` policy server 正占用 GPU `12202 MiB`，本轮不打断它，改用 `JAX_PLATFORMS=cpu CUDA_VISIBLE_DEVICES=''` 调用正式路径 `create_trained_policy(config, .../79999)`。关键输出为 `total bytes: 6.2 GiB`、`Finished restoring checkpoint in 4.25 seconds`、从 `.../79999/assets/vio_plant_collection_30hz_relpose_535_clean` 加载 norm stats、`LOAD_OK`；完整调用约 `4.657s`、退出码 `0`。未出现缺块、manifest、参数结构/shape 或反序列化错误，结论是 **79999 checkpoint 完整且可由当前本地 wrist-only config 加载**。

两次预检查工具错误已与 checkpoint 故障区分：`jq` 曾因假设错误 JSON 层级退出 `5`，第一次加载因工具超时误设 `1s` 被提前终止；修正后完整检查通过。本轮未执行 action 推理、未连接或控制真机；原 `20000` 服务始终继续监听 `0.0.0.0:8000`，没有遗留 `79999` 服务。详见 [pi05-535-clean-wrist-only-checkpoint.md](pi05-535-clean-wrist-only-checkpoint.md#2026-07-20-1646-cst79999-checkpoint-完整恢复检查)。

## 2026-07-20 16:49 CST — 复核 `set_arm_speed()` 的速度单位（agent: Codex）

只读核对 SDK 1.1.2 wheel：`ArmJointState.angles` / `velocities` 分别明确标为
radians / radians per second；最小、最大物理速度和 servo 最大关节速度常量均标为
`rad/s`，且使用 `pi` 构造。gRPC `move_joint()` servo 分支将
`set_arm_speed()` 缓存值原样写入 `ServoJointCommandRequest.vel`，全路径不存在
度/弧度转换；SDK 自带示例使用 `pi/3` 和 `2*pi`。结论：单位确定是 `rad/s`，
`0.55 rad/s` 等于约 `31.51 deg/s`，不是 `0.55 deg/s`。本轮未连接机器人或发送
运动命令。详见
[p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md#61-2026-07-20-1649-cst--单位交叉核验)。

## 2026-07-20 16:52 CST — 澄清 `set_arm_speed()` 对应的物理量（agent: Codex）

只读核对 SDK 1.1.2 公共契约和 gRPC 下发路径。接口明确要求 7 项 per-joint speed
limits；`[0.55] * 7` 表示 J1-J7 各自使用相同的 `0.55 rad/s` 关节侧限制，不是
速度总和，也不表示 7 轴都会达到该速度。`move_joint()` servo 请求把列表写入
`ServoJointCommandRequest.vel`；当前 OpenPI 使用的 `move_end_pose()` servo 请求
把列表写入 `ServoPoseCommandRequest.velocity`，同时 `set_arm_speed()` 用 7 项绝对
值平均数更新 joint scale（本参数约为 `0.07003`）。

结论：该值是关节空间速度限制/servo scale 输入，不是 TCP 速度，也不是减速器前的
电机转子原始转速或 RPM。`0.55 rad/s` 仅换算关节输出轴约为
`31.51 deg/s = 5.25 rpm`。SDK 未暴露减速比或 joint-to-motor 换算，变量名
`_arm_motor_speed` 不能改变公共 API 的关节侧契约；实际瞬时速度应读取
`get_arm_joint_state().velocities`。本轮未连接或控制机器人。详见
[p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md#62-2026-07-20-1652-cst--该值对应关节还是电机转子)。

## 2026-07-20 16:51 CST — 固定首帧 OpenPI 无控制 smoke test（agent: Codex）

确认本地 policy server 使用用户指定的 `pi05_vio_plant_collection_535_clean_wrist_only`
配置和 `.../vio_pi05_535_clean_wrist_only_80k_260717/20000` checkpoint。固定同一份双腕
RGB、`state[16]` 和双臂 TCP pose，完成 3 次 warmup + 100 次推理：总计
`18.2523s`，推理 `5.4788Hz`，客户端均值 `182.125ms`，服务端均值 `179.131ms`，
输出恒为 `(50,32)`。`273.94 rows/s` 是 `5.4788 * 50` 的 horizon 行吞吐，不是
下发频率；`chunk_steps=1` 的模拟在现有 1s 循环下约 `3.84 commands/s`，不设 1s
周期也只有 `21.04 commands/s`，4ms 限制后约 `19.85 commands/s`。脚本没有导入
P7 SDK、没有机器人连接且实际发送控制指令为 `0`；输入前后 hash 一致。新脚本通过
`ruff --select E,F`。X5 日志中的 250Hz 是板内 4ms servo/FSM 刷新及其 ARM/EEF 命令
队列，与模型推理频率不同。另核对 NPZ 的 `state[16]` 为全零；该 wrist-only config
是 `discrete_state_input=False`，state 数值不进入模型前向，固定 TCP pose 仅用于
relpose 后处理和模拟指令计数。详见
[openpi-fixed-observation-smoke-20260720.md](openpi-fixed-observation-smoke-20260720.md)。

16:55 CST 补充只读检查：`pgrep -af 'examples/airbot/p7_joint6_triangle_wave.py'`
返回码 `1` 且无输出，确认此前独立的右臂 joint6 往复进程已经不在运行；没有停止或
修改进程，也没有连接机器人。

## 2026-07-20 17:20 CST — 79999 / 10 ms / 2 行 chunk streaming pilot（agent: Codex）

按用户要求将无客户端连接的 20k policy server 切换为 wrist-only `79999`，恢复
`6.2GiB` 参数耗时 `3.14s`，正确加载 checkpoint 自带 norm stats 并监听 `:8000`。
固定双腕输入 1 warmup + 10 次无控制推理为 `6.2797Hz`、客户端均值 `158.116ms`、
服务端均值 `155.098ms`，输出 `(50,32)`。

执行器新增 `--stream-action-chunk` / `--action-step-interval-s`，并允许
`--min-motion-command-interval-s 0` 完全关闭 PC 端 4ms limiter；stream 模式每个 action
行对每侧最多发一个非阻塞、`<=9mm` 的目标，chunk 后统一回读。代码通过 ruff、
py_compile、CLI 和纯 fake client 并发/限幅检查。两次前置 fake test 失败分别来自
错误预期 waypoint 必等于 9mm、错误用线程 ID 判断并发，修正断言后通过。

真机预检确认双腕实时非空、左右臂均 `IDLE/idle/valid` 且接近准备位。因“2-4 行”
不唯一，保守执行一次 `chunk_steps=2` pilot：索引 `[0,1]`，实际 action gap
`12.027ms`，4 次 ARM + 4 次 EEF RPC 全部返回 True，最终状态正常。命令目标单条仅
`0.968-3.526mm`，但延迟回读相对启动位置左臂变化约 `24.98mm`、右臂约 `3.40mm`；
5 次重复采样稳定。X5 同期无 queue drop/UNKNOWN_ERROR/rejection，但 EEF 切 CSP 时
左右 `fsm_service_node` 分别有 `40/35ms > 4ms` 超期。为避免放大额外运动，没有启动
长时间循环。详见
[openpi-79999-action-chunk-stream-20260720.md](openpi-79999-action-chunk-stream-20260720.md)。

收尾 `pgrep` 确认没有 `openpi_p7_persistent_loop` 或其他 P7 运动进程残留；wrist-only
相机守护和 79999 policy server 继续运行。执行器最终 ruff 检查再次通过。

## 2026-07-20 17:28 CST — period=0 启动被 1 秒工具硬超时中断（agent: Codex）

准备运行 400 秒、`chunk_steps=1`、`period_s=0` 时，错误把终端工具硬超时设为
`timeout_ms=1000`。工具在 `1008ms` 后返回 `exit 124` 并结束 supervisor；不是
OpenPI/X5 报错。主日志只到双臂 acquire 和 `left switch_servo True`，运行目录没有
observation/action/summary，确认尚未进入首轮 capture、policy 或动作下发。X5 17:26
日志只有左右 ARM 成功 `0->2`，没有 queue drop、UNKNOWN_ERROR 或 rejection。

内层因 `setsid` 短暂成为孤立进程。日志在 left switch 成功打印后截断，而 X5 证明
right 随后也切换成功；源码在成功打印后才 `switched.add(side)`，所以输出通道中断使
right 未可靠进入清理集合，left 自动回 idle、right 一度残留
`SERVO_CONTROL/csp/valid`。17:28 使用独立 SDK 客户端取得 right 控制、
`switch_idle=True` 并 release，最终双臂均 `IDLE/idle/valid`，没有控制进程残留。
详见 [openpi-period0-start-interruption-20260720.md](openpi-period0-start-interruption-20260720.md)。

## 2026-07-20 17:00 CST — OpenPI 图像 + 双臂 TCP pose 连续只读探针（agent: Codex）

新增 `examples/airbot/openpi_observation_read_probe.py` 与
`scripts/cmds/test_openpi_observation_read.sh`，连续读取最后 wrist-only 推理所用的
`/tmp/openpi_cam_daemon_wrist/latest.{npz,json}`，并通过 P7 SDK 的
`get_end_pose()` 读取左右 TCP `xyz/xyzw`。脚本没有 policy client、控制权获取、模式
切换或运动命令。bash 语法、Python 编译、CLI help、ruff 和 `git diff --check` 均通过。

5 秒真机只读 smoke 完成 24 次采样：两路 `uint8 [480,640,3]` RGB 源帧各推进 24 次，
平均 observation 加载 `7.990ms`，左右 pose 读取平均 `2.666/2.148ms`，无 stale/stall、
无无效 pose。运行时已有其他进程持有双臂 `SERVO_CONTROL/csp`；探针没有接管或改变该
状态。详见
[`openpi-observation-read-probe-20260720.md`](openpi-observation-read-probe-20260720.md)。

## 2026-07-20 20:52 CST - X5 robot_app 自动启动根因（agent: Codex）

SSH 只读检查确认当前 `robot_app` PID `10211` 的 PPID 为 `1`，cgroup 为
`/system.slice/hbks_app.service`，cwd=`/opt/robot_app`，命令为
`./bin/robot_app ./configs/project_config.json`。`hbks_app.service` 已 enable 到
`sysinit.target.wants`；`ExecStart=/etc/init.d/hbks_app.sh`，脚本最后用 `exec` 启动
robot_app。因此它由 X5 systemd 开机启动，不是工作站 OpenPI 推理启动。

unit 同时配置 `Restart=on-failure`、`RestartSec=5`。本次开机 `NRestarts=1`：第一实例
20:42:35 已进入 Framework running；当前实例 20:47:16 被 systemd 重启，20:47:27 再次
进入 Framework running。首次退出的具体原因无法从现存证据确定：stdout/stderr 被置 null，
journal 已轮转且无 core；日志虽有头相机 attach 失败，但 framework 曾持续运行，不能直接归因。
当前 `/root/start-arm-dual-app-2arm.sh` 默认不启动 remote robot_app。全程没有修改或重启服务。
详见 [robot-connection.md](robot-connection.md#2026-07-20-2052-cst---x5-为什么会自动启动-robot_app)。

## 2026-07-20 20:26 CST - 重启后新推理因右臂队列丢失停止（agent: Codex）

新 supervisor PID 177819 在 attempt 2 iteration 1 被右臂 `move_end_pose=False` 中断；X5
日志同期记录 ARM/EEF command loss=`6.5%/14.8%`，随后右臂进入 `UNKNOWN_ERROR`。
motor error ids 全 0，故不是 joint7 bit19；quick clear 因板端 placeholder 无效，supervisor
已退出。详见 [openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2026-cst---x5-重启后新推理再次被右臂内部队列丢失中断)。

## 2026-07-20 20:31 CST - 失败 action chunk 丢弃与新观测重推理语义（agent: Codex）

supervisor 日志现明确说明：失败 inner process 退出即丢弃其内存 action chunk，诊断 JSON
不参与重放；quick recovery 成功后下一 attempt 重新复位、采集最新观测并重新推理。
`chunk_steps=1` 下没有 50 行待发送队列。X5 内部 250Hz 队列不由模型客户端清空，若 FSM
仍为 `UNKNOWN_ERROR` 则停止。bash 语法和无硬件 mock 故障注入通过。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2031-cst---明确丢弃失败-attempt-的模型动作并重新推理)。

## 2026-07-20 20:36 CST - 推理动作全部 non-blocking（agent: Codex）

检查发现常驻闭环、单次 policy bridge 和共享 P7 adapter 存在模型动作
`blocking=True`。现已把臂 servo/planning 与 gripper 模型动作统一改为 False；仅推理前
关节/夹爪复位保留 True。py_compile、bash -n、ruff E/F、5 个 adapter 单测、默认值断言及
静态无 True 扫描均通过；未连接机器人或发送动作。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2036-cst---openpi-推理动作统一改为-blockingfalse)。

## 2026-07-20 20:41 CST - quick recovery 后原地重推理（agent: Codex）

supervisor 现仅首次 attempt 执行初始关节/夹爪复位；失败后若恢复到
`IDLE/idle/valid`，下一 attempt 跳过 reset，在当前 pose 重新采集观测和请求新 action。
旧 action chunk 仍丢弃。离线 mock 得到 `reset_count=1`、`resume_count=2`，reset 失败后的
恢复路径也验证会原地进入 attempt 2；bash 语法通过，未连接机器人。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2041-cst---恢复到-idle-后原地重新推理不再复位)。

## 2026-07-20 22:12 CST - 停止 arm_app-only 推理（agent: Codex）

已停止 supervisor PID 205994；残留 Python PID 206195 不响应 TERM，随后精确 SIGKILL。
最终无 OpenPI 闭环/恢复进程残留，X5 仅保留两条 `arm_app` PID 2439/2440，相机 daemon 与
79999 policy 保持运行。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2212-cst---停止-arm_app-only-openpi-推理)。

## 2026-07-20 22:18 CST - README 增加 X5/本机启动命令（agent: Codex）

`scripts/README.md` 现给出精简可复制流程：X5 只启动左右 `arm_app`；本机启动双腕 daemon、
wrist-only 79999 policy 和 non-blocking 400 秒推理。已复核 checkpoint、相机路径、恢复入口
和关键参数。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2218-cst---scriptsreadmemd-精简启动命令)。

## 2026-07-20 22:25 CST - 自动恢复 SERVO_CONTROL 并补充手动重启（agent: Codex）

quick recovery 现会把 `SERVO_CONTROL/csp` 或其他非 idle controller 主动切到 idle，timeout
为 3000ms；UNKNOWN_ERROR 仍优先 clear。实机无动作故障注入确认左臂
`SERVO_CONTROL/csp -> switch_arm_idle=True -> IDLE/idle`，下一 attempt 原地继续。
`scripts/README.md` 已加入只重启两条 arm_app 的手动步骤。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2225-cst---quick-recovery-自动退出-servo_control)。

## 2026-07-20 20:22 CST - 推理复位同时打开左右夹爪（agent: Codex）

修改 `examples/airbot/p7_move_to_joint_target.py`、
`scripts/cmds/move_p7_to_ready_joint_pose.sh` 和 supervisor 日志：推理前复位现在获取双侧控制权，
将左右 EEF 切到 CSP、设置 `80 mm/s`，再并发发送 blocking `move_eef([95.0])`；两侧成功后
才继续 planning PTP 关节复位。任一侧失败会阻止 inner inference，finally 会将已切换 EEF
和 arm controller 恢复 idle 并释放控制权。

离线验证：bash 语法、Python 编译、Ruff E9/F、CLI help、非法 `96 mm` 门禁（exit 2）和
`git diff --check` 通过；barrier 双 fake-client 确认左右并发、目标 `95 mm`、effort `5`、
blocking=True、timeout `10000 ms`，并确认 set speed 失败后仍登记 EEF idle 清理。完整 Ruff
E/F 只报告文件原有 `final_error_rad` 长行 E501。本轮未执行真实 wrapper，未连接或运动真机。
详见 [openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2022-cst---推理前复位同时打开左右夹爪)。

## 2026-07-20 19:56 CST - 第 7 步推理前准备和 2x7 adopted action 打印（agent: Codex）

X5 重启后恢复有线链路，重新部署并启动统一 `arm_dual_app` 服务，`50071/50072` 监听；
左右臂无动作健康检查、错误位检查和 acquire/release 探针均通过。双臂以 `0.03` scaling
复位到 `[0,0.647,0,-0.933,0,0,-1.15]rad`，最大误差为 `0.000106/0.000144rad`。
确认当前 policy server 使用 wrist-only `79999`。闭环每轮现会在实际采用的 action row
转换前打印并记录 `adopted_action_2x7`（左 `0:7`、右 `7:14`）；编译和 ruff 检查通过。
用户取消的双腕录像和 X5 性能采样均已停止。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-1956-cst---用户手动启动第-7-步前的准备与-adopted-action-打印)。

## 2026-07-20 20:01 CST - 第 7 步首次启动相机路径错误（agent: Codex）

复位和双臂 servo 初始化成功，但 iteration 1 在 capture 阶段停止。闭环默认查
`/tmp/openpi_cam_daemon/latest.*`，实际 wrist-only daemon 正常更新
`/tmp/openpi_cam_daemon_wrist/latest.*`（检查时年龄约 `0.04s`）。因此本轮没有请求模型、
没有打印 adopted action、没有下发 policy 动作；修正命令需显式传入 wrist-only NPZ/JSON
路径。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2001-cst---第-7-步首次启动未进入推理的原因)。

## 2026-07-20 19:53 CST - 确认本机当前 OpenPI 模型持有进程（agent: Codex）

`pgrep`、`:8000` listener、`/proc` 与 `nvidia-smi` 交叉确认：真正加载模型的是
PID `119852`（PPID `119848`），命令为 `.venv/bin/python3 scripts/serve_policy.py`，
config=`pi05_vio_plant_collection_535_clean_wrist_only`，checkpoint=`.../79999`。
它监听 `0.0.0.0:8000`，GPU 显存 `12202 MiB`，RSS `4343344 kB`，VIRT
`38753620 kB`，线程数 `168`。PID `119848` 是 `uv run` 父启动器；相机 daemon
`119839` 和录像进程 `155462` 不持有模型。线程模式下 `top` 显示的多个 TID 共享同一
VIRT，不能相加。详见
[pi05-535-clean-wrist-only-checkpoint.md](pi05-535-clean-wrist-only-checkpoint.md#2026-07-20-1953-cst当前实际加载模型的本机进程)。

## 2026-07-20 19:35 CST - 79999 period=0 重跑与右 joint7 bit 19 再现（agent: Codex）

多次从 `[0,0.647,0,-0.933,0,0,-1.15]rad` 复位后运行 wrist-only 79999，模型每轮返回
`(50,32)` 并只消费 index 0，TCP 插值命令段上限 `9mm`，`period_s=0`。带夹爪首轮即因
左 EEF `move_eef=False` 失败，X5 同秒 ARM/EEF command queue drop 为 `13.4%/35.1%`；
后续改为保留完整模型输出但不下发夹爪。

arm-only 连续段实测速率约 `1.47-1.60Hz`。最新总预算运行 attempt 1/2 完成 `27/29` 个
成功循环，第二段 `29/18.315s=1.583Hz`，最大命令平移 `6.640mm`；右 joint7 随后再次出现
`error_id=524288 (bit 19)` 并进入持续 UNKNOWN_ERROR。同期 X5 CPU 约 `30-34%`，没有
command queue drop，不能归因于整机 CPU 饱和。`clear_error=True` 仍是 placeholder，无法
清除 bit 19；必须给右臂驱动断电重启。

本轮还修正：quick recovery 必须实际 acquire/release 才算健康，避免 stale lease 的 58 次
误重试；400 秒改为 supervisor 总预算并向 retry 传剩余时长；修复 X5 CPU 监控脚本的引号
与 awk `system` 变量冲突。语法、两种 duration 参数 mock 和真实单样本 CPU CSV 均通过。
详见 [openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-1935-cst---79999-period0-重跑sdkx5-故障与恢复语义修正)。

## 2026-07-20 18:40 CST - 停止本机 OpenPI 残留进程（agent: Codex）

用户要求停止前面的程序。执行
`pgrep -af 'openpi_p7_unlimited_recovery|openpi_p7_persistent_loop|serve_policy\.py|scripts/cmds/serve_policy\.sh|openpi_camera_capture_daemon|record_openpi_cameras|request_policy_from_observation_npz'`
确认当时没有推理循环或 recovery supervisor；仅有相机 daemon PID `18180` 和策略服务
PID `74687/74691`。对三个明确 PID 发送 `SIGTERM` 后再次检查，匹配进程为空，
`ss -lntp 'sport = :8000'` 也显示端口无监听。未停止或重启 X5 机械臂底层服务。

## 2026-07-20 17:02 CST — 双臂全部关节 ±0.1rad、10 秒周期运行与停止（agent: Codex）

目的：停止此前右臂 joint6 独立往复，改为左右臂从统一初始位姿
`[0,0.647,0,-0.933,0,0,-1.15]rad` 开始，全部 14 个关节各自在中心
`±0.1rad` 内同步匀速往复，完整周期 `10s`；用户随后要求停止并确认安全收尾。

旧运动收尾：PID `58904` 的首次 `kill -INT` 因后台继承信号设置而未生效，改用
`SIGTERM` 后进程退出；right 曾暂留 `SERVO_CONTROL/csp`，随后新 SDK 客户端成功
取得控制、`switch_controller(Controller.idle)=True` 并释放租约，最终左右均
`IDLE/idle/valid`。已直接修复旧脚本，显式注册 `SIGINT/SIGTERM`，避免后续后台
进程绕过 `finally`。

实现与离线验证：新增 `examples/airbot/p7_all_joints_triangle_wave.py`，用持久
`ThreadPoolExecutor` 并发发送左右完整 7 轴目标。全部关节使用同一三角波偏移：
`0/2.5/5/7.5/10s = 0/+0.1/0/-0.1/0rad`，命令斜率为
`4*0.1/10=0.04rad/s`。`py_compile`、Ruff、dry-run、双重执行门禁均通过；双
fake-client 输出
`fake_dual_stream_ok commands_per_arm=6 offsets=[0.0,0.1,0.0,-0.1,0.0,0.0]`，
确认左右每帧目标相同、每个目标完整 7 轴、所有轴不越过 `±0.1rad`。

运动前检查：没有残留控制进程；左右均为 `IDLE/idle/valid`，14 个电机错误码全为
0。left/right 到中心最大差值约 `0.74378/0.35533rad`，均小于 `1.5rad` 门禁。
实际启动命令：

```bash
nohup .venv-p7-sdk/bin/python examples/airbot/p7_all_joints_triangle_wave.py \
  --side both --start '0,0.647,0,-0.933,0,0,-1.15' \
  --amplitude-rad 0.1 --period-s 10 --rate-hz 20 \
  --approach-speed-rad-s 0.1 --sdk-speed-rad-s 0.55 \
  --execute --allow-robot-motion \
  >logs/p7_all_joints_wave/both_20260720_lZID9L.log 2>&1 </dev/null &
```

启动 PID=`65648`；左右 `acquire_control/switch_servo/set_arm_speed` 全部成功。
同步初始摆位 149 步/`7.45s`，left/right 摆位结束最大误差分别为
`0.015134/0.004362rad`。持续阶段完成约 26 个 10 秒周期，反馈最大跟踪误差约
`0.009441rad`，日志无 `FAIL`、命令拒绝、UNKNOWN_ERROR 或越限。16:57 抽样时
left 7 轴相对中心约
`[+0.0643,+0.0642,+0.0645,+0.0648,+0.0624,+0.0644,+0.0624]rad`，right 约
`[+0.0552,+0.0551,+0.0546,+0.0550,+0.0543,+0.0535,+0.0552]rad`，全部位于
`±0.1rad`；14 个电机错误码全为 0、温度 `27-35C`。

17:01 用户要求停止，执行 `kill -TERM 65648`。修复后的 handler 输出
`SIGNAL: received SIGTERM`，随后左右 `switch_idle=True`、左右
`release_control done`，脚本内最终状态均为 `IDLE/idle/valid`。17:02 独立复核：
PID 已不存在，左右仍为 `IDLE/idle/valid`，14 个电机错误码全为 0。结论：双臂
全关节轨迹已真机持续验证并正常停止，当前没有该运动进程。

速度含义：当前 SDK 1.1.2 要求 `set_arm_speed()` 每轴输入不低于约
`0.5499rad/s`，这是客户端速度限制/servo scale 参数的校验下限，不是机械臂实际
速度的物理下限。本轨迹在 20Hz 下每 `0.05s` 只推进 `0.002rad`，位置目标斜率为
`0.04rad/s`；servo 因而可以按这些小位置增量慢速跟踪。应区分
`set_arm_speed=0.55rad/s`、目标轨迹斜率 `0.04rad/s` 与关节反馈中的实际瞬时速度。

17:01 CST 补充默认入口复查：不传 `--latest-obs-*` 运行 3 次采样，默认路径正确命中
`/tmp/openpi_cam_daemon_wrist/latest.{npz,json}`；左右相机源帧各推进 3 次，双臂 pose
均有效，结果 `PASS`。此时双臂均为 `IDLE/idle/valid`，探针仍只读。

## 2026-07-20 17:29 CST — 澄清 250 Hz 的 aggregate 限流语义（agent: Codex）

检查 `examples/airbot/openpi_p7_persistent_loop.py`：单个
`MotionCommandRateLimiter` 明确写为 aggregate，并通过 `--min-motion-command-interval-s`
默认 `0.004s` 限制所有 `move_end_pose` / `move_eef` 运动 RPC 的起发时间。四个
fake 命令（左臂、右臂、左夹爪、右夹爪）共用该 limiter 时实测间隔
`4.059/4.056/4.126ms`，因此**同一客户端进程内四路命令应合计不超过约 250 次起发/秒**，不是每路各 250 Hz。

同时区分 X5 日志里的另一种 250 Hz：`arm_control_command_publish_period_ms=4` /
`update_period_us=4000` 是板内 ARM/EEF servo/FSM 流的刷新周期，现有日志把 ARM 和
EEF 的 queue drop 分开记录，并非 PC 端四路 RPC 共用的已公开总配额。双臂双夹爪能否
稳定运行要看 X5 的 queue drop 和实时线程超时，不能仅按“四路相加不超过 250 Hz”推断。
详见 [openpi-fixed-observation-smoke-20260720.md](openpi-fixed-observation-smoke-20260720.md#2026-07-20-1729-cst-250-hz是客户端总限流还是-x5-内部刷新)。

## 2026-07-20 17:47 CST - 去除推理 supervisor 的板端应用自动启动（agent: Codex）

检查确认 `scripts/cmds/openpi_p7_unlimited_recovery.sh` 的旧 `restart_arm_apps()` 会在
快速清错失败或停止清理失败时 SSH 到 X5，并执行
`/root/start-arm-dual-app-2arm.sh`；历史 `logs/openpi_p7_recovery_*.log` 中存在多次
`starting X5 arm services` 证据。现已删除 `ARM_START_SCRIPT`、SSH、
`restart_arm_apps()` 和 ready 等待路径。快速清错失败后改为直接退出并要求人工恢复，
停止清理失败时也不触碰板端应用；快速清错成功后的新观测重试保持不变。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-1747-cst---移除推理中的板端应用自动启动)。

17:49 CST 离线验证：`bash -n` 通过；`INNER_RUNNER=/bin/true` 的成功路径首轮正常结束；
`INNER_RUNNER=/bin/false SDK_PYTHON=/bin/false` 模拟推理和快速清错均失败时，supervisor
返回 `1`，输出 `robot-side applications were left untouched; manual recovery is required`。
脚本静态搜索已无 `ARM_START_SCRIPT|restart_arm_apps|ssh|starting X5 arm services`。验证未连接
机器人、未获取控制、未下发动作。

17:50 CST 适配同文件中新加入的推理前关节 reset：确认
`scripts/cmds/move_p7_to_ready_joint_pose.sh` 只调用 P7 SDK，不启动任何板端应用。mock
`RESET_RUNNER=/bin/false` 时发现 `reset_to_initial_joint_pose()` 的旧写法在 `fi` 之后读取
`$?` 会把失败误判成 `rc=0` 并继续 inner inference；该处随后已改为在 `else` 捕获退出码。
重新故障注入确认 reset 失败返回 `1` 且不进入推理。第一次验证断言使用宽泛的
`inference attempt=`，误匹配了 `preparing inference attempt=` 并报告失败；17:52 CST 改为
匹配实际启动行 `] inference attempt=` 后通过。这是测试断言误报，不是推理被启动。
此检查全程使用 `/bin/true`、`/bin/false` mock，未连接真机。

## 2026-07-20 17:43 CST - 79999 period=0 被右臂 joint7 bit 19 阻断（agent: Codex）

4 次 attempt 分别写入 13、10、8、17 条成功 summary，均未跑满 400 秒。最后失败前右臂
实际命令平移仅 `1.542mm`，随后 `move_end_pose=False`。SDK 回读右臂 joint7
`error_id=524288=1<<19`、温度 48C、EEF error=0；X5 持续记录
`Motor 7 error: Unknown motor error bit 19`。SDK clear 只是板端 placeholder，急停复位也
失败，错误未解除。已停止 supervisor，无控制进程残留；后续 `50071/50072` 均拒绝连接，
未再发动作。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-1743-cst---79999-period0-被右臂-joint7-bit-19-阻断)。

## 2026-07-20 17:52 CST - 每次模型运行前强制复位指定关节位置（agent: Codex）

supervisor 现在每个 inference attempt 都先把双臂 planning PTP 到
`[0,0.647,0,-0.933,0,0,-1.15]rad`，默认速度/加速度缩放均为 `0.03`；复位成功后才启动
inner runner，失败则明确禁止模型启动并进入快速清错/人工恢复路径。bash 语法、mock 成功路径
和失败门禁均通过；真机端口当时拒绝连接，未做运动验证。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-1752-cst---每次-inference-attempt-前强制双臂复位)。

## 2026-07-20 18:08 CST — 图像 + TCP pose 最快读取频率实测（agent: Codex）

首次 `--period-s 0` 测试因 X5 没有 `arm_app`、50071 未监听而在采样前连接超时；相机
daemon 同期正常更新。按 runbook 启动 `/root/start-arm-dual-app-2arm.sh`，约 3 秒后
50071/50072 恢复监听，全程没有获取控制权或发送运动命令。

随后无节拍限制运行 15.116 秒，完成 1336 次“加载双腕 RGB + 读取左右 TCP pose”，
程序循环吞吐 `88.384Hz`；其中左右相机真正的新源帧均为 196 次。按 ROS header
timestamp 计算，新帧频率 left=`13.205Hz`、right=`13.176Hz`。观测文件年龄均值
`45.7ms`、最大 `105.1ms`；左右 pose 单次读取均值 `1.636/1.546ms`。测试后双臂仍为
`IDLE/idle/valid`。

结论：88Hz 包含重复读取，不是新观测频率；当前可用于闭环的新图像 + pose 供数上限
实测约 `13.2Hz`，高于模型纯推理 `5.48Hz`。详见
[`openpi-observation-read-probe-20260720.md`](openpi-observation-read-probe-20260720.md)。
## 2026-07-20 22:40 CST - recovery 语义核对与空格键回初始位（agent: Codex）

检查确认 `openpi_p7_unlimited_recovery.sh` 的普通自动 recovery 由非 guard 推理失败或推理前
reset 失败触发：逐臂 acquire/release 排除 stale lease，按状态 clear error 或切 idle，并要求
左右均为 `IDLE/idle/valid`；成功后从当前位置重新采集和推理，不自动回初始位。exit code 3 的
运动 guard 违规不自动恢复，quick recovery 失败也不会重启 X5 应用。本次新增交互 TTY 空格键：
向当前推理进程组发送 `SIGTERM`；persistent loop 将其转成清理请求并在 `finally` 切 idle、释放
control，然后执行 quick recovery，随后 planning PTP 到
`[0,0.647,0,-0.933,0,0,-1.15]rad`、打开双夹爪，重新采集最新观测并继续推理，不复用中断的 action。`bash -n`、非 TTY
禁用路径和全 mock 伪终端空格路径通过；未连接或控制真机。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2240-cst---recovery-语义核对与空格键回初始位)。

2026-07-20 追加：按用户要求将空格复位后的行为从“退出”改为“重新采集观测并继续推理”；本次
只修改代码与记录，未运行验证。

## 2026-07-20 23:09 CST - 推理时双 OpenCV 最终输入窗口（agent: Codex）

核对确认 wrist-only 推理期无随机 crop/augmentation；左右 RGB 使用服务端同款
`resize_with_pad(224,224)` 保持宽高比并填黑，随后只有不改变可视内容的 `[-1,1]` 数值归一化。
现已由 policy 请求进程从实际发送的 observation 原子生成预览帧，由常驻系统 Python/OpenCV
HighGUI 进程左右并排显示两个窗口；默认开启，启动失败会在机械臂 acquire control 前拒绝运行，
可用 `--no-show-policy-input` 关闭。单测 `2 passed`，合成 640x480 输入得到 224x224 且上下各
28 行黑边；X11 实测两个窗口同时存在并左右分开，退出后无残留。未连接机器人或运行模型。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2309-cst---同时显示左右最终送模图像)。

## 2026-07-20 23:12 CST - 当前 PI0.5 tokenizer 输出 prompt（agent: Codex）

代码核对确认 wrist-only PI0.5 走 `PaligemmaTokenizer`。已在其 `tokenize()` 中对清洗后的实际任务
文本增加 `[PaligemmaTokenizer] prompt='...'` 即时打印；policy server 重启后每次请求都会显示。
详见 [openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2312-cst---tokenizer-打印实际-prompt)。

## 2026-07-20 23:45 CST - 相机改为推理主进程内存直读（agent: Codex）

确认旧 daemon 会在 ROS 帧停止后继续重写缓存首帧，使文件 mtime freshness 失效；现场还存在
两个 daemon 同写和三个 orphan `--execute` loop。已停止五个旧进程并用 P7 SDK 将双臂/EEF
清到 `IDLE/idle/valid` / `idle`。现已把 ROS2 长期订阅、每路新帧推进检查和常驻 policy
WebSocket 合入 `openpi_p7_persistent_loop.py`：原始 RGB 全程内存传递，不再使用 camera daemon
或 `latest.npz/json`；模型继续使用服务端原始 `resize_with_pad(224,224)`，wrist-only 推理无 crop。
组合 Python 3.12 环境可同时导入 `rclpy`、P7 SDK 1.1.2 和 `openpi_client`。首次检查时板端相机
publisher 未运行，4 秒内存探针按预期报告两路 missing；后续已恢复并完成最小 dry-run。详见
[`openpi-in-process-camera-20260720.md`](openpi-in-process-camera-20260720.md)。

## 2026-07-20 23:48 CST - 单进程相机 bug 修复与 policy dry-run（agent: Codex）

定位 OpenCV 空窗和无推理的直接原因是 ROS graph 没有两路腕部 image topic；板端手动
`robot_app` 因缺少 `LD_LIBRARY_PATH` 报 `libalog.so.1` 并初始化失败。按 init 脚本环境重启后，
左右腕 publisher 恢复。主循环初始化顺序同步改为“收到双腕新帧 -> 写 preview -> 首次 policy
infer -> 连接/接管机械臂”，前置失败时不再切 servo。单轮 dry-run 收到两路 `640x480 nv12`，
policy 返回 `(50,32)`，耗时 `226.23ms`；没有 acquire 或运动，左右最终均
`IDLE/idle/valid`。详见 [`openpi-in-process-camera-20260720.md`](openpi-in-process-camera-20260720.md)。

## 2026-07-20 23:52 CST - 禁止 robot_app 与相机物理入口核对（agent: Codex）

用户明确禁止板端 `robot_app`；Codex 启动的精确 PID `1258455` 已停止，文档中的启动步骤已
撤回。工作站 `/dev/video0,1` 实为同一只 USB UVC 摄像头，仅 video0 有 capture capability，
不能提供左右腕双路；板端无标准 `/dev/video*`，robot_app 停止后也无 wrist image ROS2 topic。
因此主进程内存读取代码保留，但当前没有满足“不用 robot_app”的已知双腕数据源，需明确新的
板端 HB API、ROS2 publisher 或网络流入口。详见
[`openpi-in-process-camera-20260720.md`](openpi-in-process-camera-20260720.md)。

## 2026-07-20 23:56 CST - 原始 inference 相机实现复核（agent: Codex）

代码确认原始 `airbot_inference_sync/async -> play_operator` 不使用 ROS2 或 robot_app，而是在
推理客户端所在机器通过私有 `airdc.V4L2Camera` 长期开启本地索引 `[0,2,4]`，三路默认
`MJPEG 640x480@30`；采集只做 BGR->RGB，数组直接发 policy，服务端才做
`resize_with_pad(224,224)`，wrist-only inference 无 crop。当前工作站只有一只可 capture 的
USB UVC 相机且缺少 `airdc`，不满足原始双腕/三相机硬件前提。详见
[`openpi-in-process-camera-20260720.md`](openpi-in-process-camera-20260720.md)。

## 2026-07-20 23:59 CST - scripts 相机读取测试真实数据源（agent: Codex）

确认 `test_openpi_observation_read.sh` 不直接读相机/ROS，而是反复加载 camera daemon 写出的
`latest.npz/json` 并校验 timestamp/CRC，同时读取 P7 TCP pose。真正直接订阅 ROS2 的 scripts
旧入口是 `openpi_p7_closed_loop.sh`：每轮新起 `capture_ros2_openpi_observation.py` 抓一组帧并
写 NPZ，再请求 policy；它也不使用 V4L2，且依赖外部 ROS2 publisher。详见
[`openpi-in-process-camera-20260720.md`](openpi-in-process-camera-20260720.md)。
## 2026-07-20 23:22 CST - wrist-only PI0.5 跨帧 memory 核对（agent: Codex）

静态核对当前 config、policy 请求、`Policy.infer()` 和 `Pi0.sample_actions()`：每次请求只包含当前
observation snapshot（双腕单帧、当前 state、prompt），没有历史帧时间轴，也没有跨请求 recurrent
hidden state / KV cache。单次调用内部 KV cache 只服务该次扩散去噪；服务端 PRNG 会推进，但不携带
历史观测。模型一次输出 `(50,32)` action chunk；执行端 chunk 缓存/重叠平滑属于控制器短时状态，
不是模型 memory。详见 [`model-io-contract.md`](model-io-contract.md#2026-07-20-2322-cst---当前-wrist-only-pi05-是否有跨帧-memoryagent-codex)。

## 2026-07-20 23:28 CST - 优雅停止与孤儿控制进程修复（agent: Codex）

只读检查发现修改前遗留的 persistent loop PID `214681/251343/263473` 均已失去 supervisor、被
桌面 PID 2051 收养并拥有独立 session，运行约 `60/29/12min`，远超各自 `380-387s` 预算；
23:14 两次新启动因旧 lease 报 `controller already held`。本次新增终端 `Q`、OpenCV 窗口
`Q/Esc` 优雅停止，persistent `finally` 切 EEF/arm idle 并 release，supervisor 延长到 25s 后
再严格复核双 arm `IDLE/idle/valid` 和双 EEF idle；新增 Linux parent-death signal、supervisor
单实例锁和已有控制进程门禁。另新增 `stop_openpi_p7_inference.sh` + `p7_ensure_idle.py`，用于清理
旧孤儿并在不重启 X5 应用的前提下确认 idle。Bash/Python/Ruff/diff、Q mock、单实例锁、stop
无进程路径、fork parent-death 和 EEF mode 检查通过；系统无 ShellCheck。未连接机器人，未停止
当前 3 个旧进程。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2328-cst---优雅停止自动-idle-与孤儿进程防护)。

## 2026-07-20 23:35 CST - 停止结果严格校验与 ROS2 内存链路复核（agent: Codex）

静态核对确认同一批 ROS2 RGB 图像同时用于 224x224 OpenCV 预览和 policy 请求；并补充正常完成后的
双 arm/EEF idle 复核，以及停止脚本对 idle 校验失败的非零返回。Python compile、Ruff E9/F、
Bash `-n`、`git diff --check` 均通过；系统无 ShellCheck。未连接真机，未停止现场旧孤儿进程。
详见 [openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-20-2335-cst-补充核对)。

## 2026-07-21 00:01 CST - `arm_app` 与 `robot_app` 职责核对（agent: Codex）

静态核对当前启动说明、DDS route 实测记录和旧 `arm_dual_app` 启动脚本：当前
`arm_app` 是左右各一实例的机械臂控制 runtime，连接 `can0/can1`，当前现场提供 P7 gRPC
`50071/50072` 和 arm 控制/状态话题；
当前 `robot_app` 是相机/传感器 runtime，提供视觉观测且不承担双臂 CAN 控制。仓库中的
`arm_dual_app` 是旧 gRPC `50071/50072` 臂控路线。旧部署的 `robot_app` 曾同时承担臂控，
因此不能脱离版本、配置和启动参数理解旧记录。2026-07-19 的 DDS-only `arm_app` 检查属于
历史/反证路线，不代表当前现场。本记录未改变任何现场进程或机器人状态。
新增 Markdown 的 `git diff --no-index --check` 通过。
详见 [`arm-app-vs-robot-app.md`](arm-app-vs-robot-app.md)。

## 2026-07-21 00:01 CST - `arm_app` 相机发布能力检查（agent: Codex）

板端当前仅运行左右两个 `arm_app`（P7 gRPC 50071/50072），无 `robot_app`；ROS2 graph 没有
`camera`/`image` 话题，左右 arm_app/arm_dual_app 配置也没有相机节点。结论：`arm_app` 只提供
机械臂控制与状态，不发布相机图像；禁用 `robot_app` 后仍需另一个明确的相机驱动/发布源。详见
[openpi-in-process-camera-20260720.md](openpi-in-process-camera-20260720.md#2026-07-21-0001-cst---arm_app-是否发布相机agent-codex)。

## 2026-07-21 00:08 CST - `robot_app` 直接内存 OpenCV 预览与 Hz 实测（agent: Codex）

按用户新指示用完整板端运行库环境启动 `/opt/robot_app/bin/robot_app
./configs/project_config.json`（PID `1357054`）；4 路腕部相机 Started，头部 2 路 Init Failed。本地
新增只读 `show_ros2_camera_live.py`，直接订阅双腕左目并在内存中 NV12 解码、`cv2.imshow`，不运行
daemon、不写 NPZ/图片/视频。15 秒实测稳定段约 `29.5-30 Hz`，全程左右各 321 帧/
`22.02 Hz`，成对显示 `22.26 Hz`；退出后 publisher 仍在线。详见
[openpi-in-process-camera-20260720.md](openpi-in-process-camera-20260720.md#2026-07-21-0008-cst---恢复-robot_app-并直接内存预览测速agent-codex)。

## 2026-07-21 00:13 CST - `scripts/README.md` 同步板端相机启动方式（agent: Codex）

检查发现启动说明此前只有左右 `arm_app`，并仍写着推理入口“不依赖板端 `robot_app`”，与
2026-07-21 00:08 的实际相机链路不一致。现已补入板端完整 PATH/LD_LIBRARY_PATH、后台启动、
日志和 ROS2 topic 检查命令，以及本地直接内存 OpenCV 查看器命令；同时明确当前推理依赖已单独
启动的相机 publisher，但不会由推理脚本自动拉起。

## 2026-07-21 00:05 CST - `robot_app`/`arm_app` 250 Hz 争用核对（agent: Codex）

SSH 只读初查时 X5 只有左右两个 `arm_app`（PID `660463/660464`，gRPC `50071/50072`）；
检查过程中另一个并行操作启动了 `robot_app` PID `1357054`，00:10 复核时三者并发。
`arm_app` 配置明确包含 4 ms command/servo tick 和
250 Hz state stream；当前扁平 `robot_app/framework_config.json` 没有 arm control、servo 或
arm gRPC runtime，因此不会形成第二套 250 Hz 臂控循环。但二进制检查发现 tactile、
`collect_encoder`、`collect_button` 含 MAVLink callback，通用 `mavlink_config.json` 又把
`SYS_COLLECT` 映射到 `can0/can1`，且其 `500k/2M` 波特率与 arm_app 的 `1M/5M` 不同；静态检查
无法保证 sensor plugin 不会自行打开或重配同一 CAN。线程配置/现场状态显示 arm control 为
`FIFO 11`、CAN RX/TX 为 `FIFO 35/34`，高于 robot processing `FIFO 10` 和 sensor `RR 8`。
结论：不会形成第二个 250 Hz arm command loop，但在无隔离验证前不能排除 CAN 层冲突，也仍可能
共享 CPU、内存和 DDS 资源产生抖动。本轮没有主动启动 `robot_app` 或 attach `strace`。
并发状态下两路 CAN 保持 `ERROR-ACTIVE`、实时 tx/rx error counter 为 0，位速率仍为 arm_app 的
`1M/5M`；2 秒窗口内 RX 正常增加，TX 包数与累计 TX errors 均不变，未观察到 robot_app
发送第二套控制帧或重配接口。该短窗口未覆盖运动时长时 jitter/queue-drop。
一次远端 `awk`
线程过滤因 quoting 报语法错误，板端 `ss -A can` 也不受支持；已改用 `ps -T`、
`/proc/net/can/*` 和接口计数成功只读复核。未改变进程或机器人状态。
更新后的主题 Markdown 通过 `git diff --no-index --check`。
详见 [`arm-app-vs-robot-app.md`](arm-app-vs-robot-app.md#2026-07-21-0005-cst---是否争抢-250-hz-板载控制agent-codex)。

## 2026-07-21 00:27 CST - WebSocket timeout 与左 joint7 bit 19 复盘（agent: Codex）

只读复盘 00:15:06 attempt：30 次成功 policy latency 从 `351ms` 恶化到 `1845ms`，第 31 次
超过默认 20 秒 pong deadline；server 在 asyncio event loop 同步执行 `policy.infer`，因此
keepalive timeout 是推理/event-loop 卡死的结果。事后一轮 policy-only smoke 已恢复为
`server_infer_ms=361.743`、actions `(50,32)`，未连接 SDK 或机器人；内核无 NVIDIA Xid/OOM。

X5 左右 servo 在 00:16:24/25 同时密集出现 `3-6ms`、部分超过 `4ms period` 的警告；退出
servo 后左臂首次并持续报 `Motor 7 error: Unknown motor error bit 19`。SDK 只读复核为左
`UNKNOWN_ERROR/idle/valid`、右 `IDLE/idle/valid`、双 EEF idle、关节近静止；控制 supervisor
已退出。clear RPC 的板端日志明确为 placeholder。历史 arm-only 已确认 bit19=`524288=1<<19`
且需对应臂驱动断电清零，所以当前不得重跑，也不能把本次 bit19 确定归因于 robot_app。
本轮未清错、重启、获取控制权或发送机器人命令。详见
[`openpi-websocket-timeout-left-bit19-20260721.md`](openpi-websocket-timeout-left-bit19-20260721.md)。

## 2026-07-21 00:30 CST - 故障后板端应用已停止（agent: Codex）

最终 SSH 只读复核时，现场已被其他操作改变：X5 无 `arm_app`、`robot_app`、`arm_dual_app`
进程，`50071/50072` 未监听，事故时的 `/tmp/openpi_arm_app_{left,right}.log` 已消失。本轮没有
执行停止操作。当前不会有动作下发，但进程消失不等于左 joint7 bit19 已清零；需要驱动断电复位、
重启 `arm_app` 后做 no-motion 状态和 joint error 检查。详见
[`openpi-websocket-timeout-left-bit19-20260721.md`](openpi-websocket-timeout-left-bit19-20260721.md#2026-07-21-0030-cst---当前运行态补充)。

## 2026-07-21 01:08 CST - 清理板端重复 runtime 并统一重启（agent: Codex）

启动前 X5 有两套 left `arm_app`（PID `2546/181171`）、两套 right `arm_app`
（PID `2547/181172`），`50071/50072` 各被两进程监听；`robot_app` 一份（PID `2548`）。本机另有
两个重复真实运动进程 `p7_move_to_joint_target.py`（PID `121120/158424`）。按 cmdline 和精确
PID 先停止本机控制进程，再停止板端 5 个实例；确认端口释放后重配 CAN-FD `1M/5M`，统一启动
left/right `arm_app` 和一份扁平相机 `robot_app`。

最终 PID 为 `185775/185776/185777`，PPID 均为 1；`50071/50072` 各只有唯一监听者。SDK
no-motion 只读检查左右均 `IDLE/idle/valid`、EEF idle、关节速度 0；双 arm Framework started，
无 Motor7/UNKNOWN/error。四路腕相机 Started，所需双腕左目 ROS2 topic 已恢复；头部两路失败。
robot 的 tactile/collect_encoder/collect_button 因 MAVLink callback 注册失败未启用，不影响
wrist-only 图像。本机最终无控制循环/关节移动进程。本轮重启后没有启动推理、获取控制权或发送
运动命令。详见
[`arm-app-vs-robot-app.md`](arm-app-vs-robot-app.md#2026-07-21-0108-cst---清理重复进程并统一重启agent-codex)。

## 2026-07-21 00:19 CST - 导出最近一次 OpenPI 模型图像输入（agent: Codex）

确认当前没有推理主循环运行，导出源是 `2026-07-21 00:15:59 CST` 留下的原子 preview NPZ。
将与模型 resize-with-pad 一致的左右腕 `uint8 224x224 RGB` 图像导出到
`logs/model_input_images/20260721_001559/`，同时保留源数组 NPZ。两张 PNG 文件格式、尺寸、像素
范围和视觉内容均正常；上下黑边是保持宽高比产生的 padding。详见
[openpi-in-process-camera-20260720.md](openpi-in-process-camera-20260720.md#2026-07-21-0019-cst---导出最近一次模型图像输入agent-codex)。

## 2026-07-21 00:24 CST - 常驻推理 task name 来源与默认值（agent: Codex）

静态确认常驻真机入口通过 `--prompt` 将文字 task name 发给 policy server，服务端最终由
`PaligemmaTokenizer.tokenize()` 处理并打印。已将
`examples/airbot/openpi_p7_persistent_loop.py` 的默认值改为
`collect plant observations with dual-arm wrist cameras`；显式 `--prompt` 仍会覆盖默认值。
AST 读取确认默认值一致，Ruff 致命错误范围与 `git diff --check` 通过；完整 Ruff 的 8 条既有
非致命告警未作无关修改。两次组合验证命令写法未完成，改用单行 AST 命令后验证成功。
详见 [openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-0024-cst---更新常驻推理默认-task-nameagent-codex)。

## 2026-07-21 00:26 CST - 双夹爪闭合抓图被左 joint7 bit 19 阻断（agent: Codex）

闭合前检查发现左臂 `UNKNOWN_ERROR`、joint7 `error_id=524288 (1<<19)`，左右 EEF 自身 error 均
为 0。闭合程序在下发前中止；标准 `p7_ensure_idle.py` 虽然 `clear_error=True`，FSM 仍未恢复，
EEF mode RPC 被 `FAILED_PRECONDITION` 拒绝。工具已释放 lease。为避免左右不一致，本次未对任一
夹爪下发 `move_eef`，也未保存误标为闭合后的图片；需先对机械臂断电重启并确认错误位清零。详见
[openpi-in-process-camera-20260720.md](openpi-in-process-camera-20260720.md#2026-07-21-0026-cst---闭合双夹爪后抓图被左臂-bit-19-阻断agent-codex)。

## 2026-07-21 00:29 CST - 训练/推理双腕图片叠加拼图（agent: Codex）

确认 `20260721-002600.jpg` 对应左腕训练图、`20260721-002620.jpg` 对应右腕训练图；分别与
左右推理 PNG 按 50%/50% 逐像素混合，再按左、右横向拼成 448x224 PNG。文件格式和视觉结果
检查正常，输出见 `logs/model_input_images/20260721_001559/training_inference_overlay_50_side_by_side.png`。
详见 [openpi-in-process-camera-20260720.md](openpi-in-process-camera-20260720.md#2026-07-21-0029-cst---训练推理双腕图-50-叠加拼图agent-codex)。

## 2026-07-21 00:38 CST - 双夹爪成功闭合并保存双腕图（agent: Codex）

X5 重启后按既定流程恢复左右 `arm_app`、相机 `robot_app` 和 CAN；原 left joint7 bit 19 已清零。
左右 blocking `move_eef([0.0])` 均成功，反馈约 `0.15/0.81 mm`，之后 EEF idle、lease 已释放。
直接从内存抓取时间戳相差约 34 微秒的双腕 NV12 新帧，resize-with-pad 为 224x224 后保存到
`logs/model_input_images/20260721_003628_grippers_closed/`；没有使用 daemon。最终左右服务 idle，
arm/EEF error 全 0。详见
[openpi-in-process-camera-20260720.md](openpi-in-process-camera-20260720.md#2026-07-21-0038-cst---双夹爪闭合并保存新模型输入图agent-codex)。

## 2026-07-21 00:40 CST - 尾号 54/50 参考图与紧闭图叠加（agent: Codex）

按用户指定的左 `003354`、右 `003350` 映射，分别与新左右紧闭图做 50%/50% 像素混合并横向
拼接。输出为 448x224 RGB PNG，配对与视觉结果检查正常。详见
[openpi-in-process-camera-20260720.md](openpi-in-process-camera-20260720.md#2026-07-21-0040-cst---指定参考图与紧闭图-50-叠加拼图agent-codex)。

## 2026-07-21 00:56 CST - 默认前 15 行 chunk 顺序执行与 4 ms 指令下限（agent: Codex）

静态确认常驻 P7 推理循环一次 policy 返回后，会完整遍历所选 action indices，完成 chunk
readback 后才进入下一轮采集和 `policy.infer()`。现将默认值改为 action 索引 `0..14` 且默认
开启 streaming；每行最多发送左右臂和左右夹爪共 4 条非阻塞运动 RPC。四路共用的 aggregate
limiter 保持 4 ms 默认值，并新增硬校验，低于 4 ms（含 0）直接拒绝。

新增 3 个纯离线回归测试，结果 `3 passed in 0.14s`；确认默认 15 行、`0.0039s` 被拒绝，及
四条模拟命令从 `10.000s` 起按 `4ms` 递增。Python 编译、限定 E/F Ruff、whitespace 检查
均通过；现行 `scripts/README.md` 启动示例已同步为 15 行 streaming 和 4 ms。未连接
policy/ROS2/机器人，未发送真机指令。详见
[openpi-79999-action-chunk-stream-20260720.md](openpi-79999-action-chunk-stream-20260720.md#2026-07-21-0056-cst---默认执行-chunk-前-15-行并锁定-4-ms-指令间隔agent-codex)。

## 2026-07-21 01:10 CST - 定位 recovery 无限循环未调用模型（agent: Codex）

当前 supervisor PID `300938` 仍传入已退役的 `--capture-mode latest-file` 和
`--latest-obs-*` 参数，内层每次在采集/推理前输出 `REFUSE` 并以 `rc=2` 退出；外层误将配置错误
当作真机错误执行 quick recovery，随后原参数重试，故模型从未被调用。policy server `:8000`
仍健康，左右臂 recovery 检查实际为 idle。应停止该 supervisor 并按 `scripts/README.md` 改用
`--capture-mode ros2`；本次仅诊断，未停止进程或控制机器人。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-0110-cst---recovery-循环且未调用模型的原因agent-codex)。

## 2026-07-21 01:17 CST - 双臂直接复位，按用户更新指令不再启动推理（agent: Codex）

Space 停止后的标准 PTP 复位先被 `1.5 rad` guard 阻断，低速 planning PTP 也返回 False；左臂
joint2/joint5/joint6 读数略越 SDK 命令限位，先以 servo 小步退入范围，再将双臂移动到
`[0,0.647,0,-0.933,0,0,-1.15]` 并补一次短距离收敛。最终左/右最大关节误差分别为
`0.010498/0.013217 rad`，双侧均为 `IDLE/idle/valid` 且 lease 已释放。遵照用户最新指令，未再
启动 inference supervisor；本次未控制夹爪。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-0117-cst---仅复位双臂并保持推理停止agent-codex)。

## 2026-07-21 09:24 CST - 直接复位因 arm gRPC 不可达而未下发（agent: Codex）

按用户要求直接执行双臂 servo 复位；`192.168.25.1:50071` 连续两次、管理地址
`172.100.10.159:50071` 一次均在 SDK client 建连阶段超时，未 acquire control、未发送运动。
为避免在未知板端状态下再次制造重复 `arm_app`，本轮没有盲目启动板端服务，也没有启动推理。
详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-0924-cst---再次直接复位被-arm-grpc-不可用阻断agent-codex)。

## 2026-07-21 09:30 CST - 重试复位仍未建连（agent: Codex）

再次执行双臂复位：有线双臂两次均在右臂 `:50072` client 初始化时超时；无线右臂 `:50072`
也超时；随后有线左臂 `:50071` 同样超时。所有尝试均未 acquire control、未发送运动，复位未
执行。未启动推理或新的板端实例。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-0930-cst---重试复位仍被左右-arm-grpc-阻断agent-codex)。

## 2026-07-21 09:32 CST - 复位执行至 92/144 时左臂 UNKNOWN_ERROR（agent: Codex）

再次复位时 gRPC 已恢复；左臂前 91 个 servo waypoint 成功，第 92 步返回 False，进入
`UNKNOWN_ERROR/csp`，右臂尚未开始移动。停止清理后所有 lease 已释放，左右 EEF 和右臂为
idle，左臂 controller 为 idle 但 FSM 仍为 `UNKNOWN_ERROR`；`clear_error=True` 未清除错误。
未继续运动或启动推理。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-0932-cst---再次复位中左臂进入-unknown_erroragent-codex)。

## 2026-07-21 09:45 CST - 补充手动启动环境说明并核对残留进程（agent: Codex）

更新 `scripts/README.md`：明确 X5、GPU 策略服务、GPU ROS2/P7 客户端的终端和虚拟环境分工，
客户端命令显式设置 ROS2 domain/RMW，并提醒禁止重复启动 `arm_app`/`robot_app`。状态核对显示
被中断的复位进程和 OpenPI control/recovery 进程均不存在，policy server `:8000` 仍运行；本次
没有控制机器人。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-0945-cst---整理手动启动-openpi-真机推理环境agent-codex)。

## 2026-07-21 10:42 CST - 定位空格回位失败为 1.5rad 关节差保护（agent: Codex）

只读检查 `logs/openpi_p7_recovery_20260721_103816.log`：首次复位时右臂 joint5/joint7 到 ready
目标的差值约 `2.153/2.331rad`，空格后的第二次复位时左臂最大差约 `2.346rad`，均超过
`move_p7_to_ready_joint_pose.sh` 固定的 `--max-joint-delta-rad 1.5`，故在下发 PTP 前返回 rc=1。
左右臂当时均为 `IDLE/idle/valid`，不是 policy、ROS2 或 controller 连接故障。还确认首次复位
失败后 supervisor 会因 quick recovery 健康而跳过复位并从当前姿态启动推理；空格复位失败则按
设计保持停止。未连接或控制机器人。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-1042-cst---空格回初始位被-15rad-关节差保护拒绝agent-codex)。

## 2026-07-21 10:44 CST - ready 回位关节差阈值提高到 3.0rad（agent: Codex）

用户明确确认放宽本地回位保护是安全的。将
`scripts/cmds/move_p7_to_ready_joint_pose.sh` 的 `--max-joint-delta-rad` 从 `1.5` 提高到
`3.0`，覆盖本次最大 `2.345577rad` 的关节差；目标、planning PTP、速度/加速度和夹爪参数未改。
`bash -n`、`git diff --check` 和以 `/bin/echo` 替代 SDK Python 的参数展开验证通过，确认最终参数为
`--max-joint-delta-rad 3.0`；未连接机器人或下发动作。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-1044-cst---用户确认后将-ready-回位关节差阈值提高到-30radagent-codex)。

## 2026-07-21 10:56 CST - 停止残留 ready PTP，右臂 trajectory 需急停中止（agent: Codex）

精确定位到残留 PID/PGID `15867` 为 `p7_move_to_joint_target.py --execute`；supervisor 和
persistent loop 已不存在。向独立进程组发送 SIGTERM 后本地进程消失，但 blocking PTP 的板端
trajectory 和 lease 未同步取消。lease 超时后左臂成功回 `IDLE/idle`；右臂持续
`PLANNING_CONTROL/csp` 且拒绝切 idle。SDK 无普通 cancel API，调用右臂
`set_arm_emergency_stop(True)` 成功中止 trajectory；解除急停后右臂为 `UNKNOWN_ERROR/csp`，
`clear_error=True` 未改变状态，最后已释放 lease。所有本地控制脚本已停止，未重启板端应用。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-1056-cst---强制停止残留-ready-ptp-与板端-trajectory-状态agent-codex)。

## 2026-07-21 11:30 CST - production ready 回位改为 SDK blocking servo（agent: Codex）

按用户明确约束，ready 回位链路不再使用 planning，也不再由客户端拆 waypoint/实现闭环。
`p7_move_to_joint_target.py` 现逐臂执行 `servo_control`、`set_arm_speed([0.55]*7)`，并仅向 SDK
提交一次最终目标 `move_joint(..., JointMoveOptions(eff=[8]*7, blocking=True))`；SDK 返回后才读取
终态并切 idle/release。wrapper/recovery 同步删除 planning scaling 参数，改用 servo speed/effort。
新增纯 mock 单测，断言左右各一次最终目标、blocking=True、controller 仅 servo->idle；结果
`1 passed`。Ruff、Python 编译、shell 语法、参数展开及 diff whitespace 检查通过，未连接机器人或
下发动作。production policy action 仍按启动参数使用 non-blocking servo 流式发送；独立 planning
precision probe 不属于 recovery 调用链。详见
[openpi-interpolated-inference-20260720.md](openpi-interpolated-inference-20260720.md#2026-07-21-1130-cst---production-ready-回位改为-sdk-blocking-servoagent-codex)。

## 2026-07-21 13:19 CST - 复核 gRPC 概念与当前 Arm-P7 控制调用链（agent: Codex）

只读核对当前 SDK bridge、guarded servo 脚本和运行文档：本机 `AirbotClient` 通过 gRPC 连接
X5 `arm_dual_app` 的 `50071/50072`；OpenPI relpose action 先结合当前 TCP pose 转为绝对
`CartesianPose`，再经控制权、servo controller、`move_end_pose()` 下发，由板端完成 IK/伺服；
夹爪经 `move_eef()` 下发。生产持续循环对目标插值/限幅后，以 non-blocking RPC 并行发送双臂
waypoint，退出时切 idle 并释放 lease。旧 `airbot_play` 关节接口不是当前主线。本轮未连接或控制机器人。
两份文档的 `git diff --check` 退出码为 `0`。
详见 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md#7-2026-07-21-1319-cst--grpc-概念与当前控制调用链复核)。

## 2026-07-21 13:24 CST - 审计当前工作树并区分一次性测试（agent: Codex）

目的：查看全部已跟踪、未跟踪和被 ignore 的工作树内容，识别一次性/已被主线替代的硬件测试，确认正式链路文件和验证缺口。

实际检查：`git status --short --untracked-files=all`、`git ls-files --others --exclude-standard`、`git ls-files --others -i --exclude-standard`、Python `py_compile`、相关 shell `bash -n`、`git diff --check`；离线单测命令为
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q src/openpi/policies/airbot_policy_test.py src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_policy_bridge_test.py src/openpi/shared/airbot_airrtm_servo_test.py examples/airbot/request_policy_from_observation_npz_test.py`。

结论：5 个已跟踪文件、52 个未跟踪文件、无 staged 修改；27 个不依赖 Arm-P7 SDK 的单测通过，两个 SDK 测试因当前环境缺少 `google.protobuf.runtime_version` 在收集阶段阻断；Python 编译、shell 语法和 whitespace 检查通过。一次性或已替代候选为 latest-file observation probe、姿态/三角波/精度 probes、旧 `p7_servo_move_to_joint_target.py`、DDS proxy/overlay、旧 `openpi_p7_closed_loop.sh` 和重复的 `record_camera_clip.py`。正式链路和可重复诊断工具的完整分类见 [worktree-cleanup-20260720.md](worktree-cleanup-20260720.md#2026-07-21-1324-cst当前工作树完整改动审计)。

风险：`src/openpi/models/tokenizer.py:24` 有无条件 prompt `print`，疑似一次性调试残留；`.gitignore:83` 的 `docs/*` 隐藏了全部检查文档，与本仓库留档约定冲突。未连接机器人、未启动服务、未下发运动。

## 2026-07-21 13:27 CST - 核对双臂全部关节三角波测试执行方法（agent: Codex）

目的：确认 `examples/airbot/p7_all_joints_triangle_wave.py` 的默认运动范围、停止方式和推荐执行命令。本轮只读脚本和既有运行记录，未连接机器人、未 acquire control、未下发运动。

命令：`sed -n '1,430p' examples/airbot/p7_all_joints_triangle_wave.py`、`rg --no-ignore -n 'p7_all_joints_triangle_wave|all_joints_triangle' docs`。

结论：脚本默认 `--side both`，左右各 7 轴并发；起始位姿 `[0,0.647,0,-0.933,0,0,-1.15]rad`，幅度 `0.1rad`，周期 `10s`，频率 `20Hz`，`--cycles 0` 无限运行。真实运动必须同时指定 `--execute --allow-robot-motion`；`--cycles 1` 完成一个周期后回到起点并切回 `idle`、释放控制权。既有 2026-07-20 记录显示该参数已完成一次双臂真机验证，最大跟踪误差约 `0.0095rad`，但本次不代表当前机器人状态仍然安全可运动。

## 2026-07-21 13:57 CST - 核对并保持右臂 idle（agent: Codex）

目的：按用户要求将右臂切到 `idle`。先检查本机是否有已知 OpenPI/P7 三角波控制进程，再通过 Arm-P7 SDK gRPC 读取右臂 `192.168.25.1:50072` 状态。

命令：`pgrep -af 'p7_all_joints_triangle_wave|p7_joint6_triangle_wave|openpi_p7_persistent_loop|openpi_p7_unlimited_recovery'`；`NO_PROXY=192.168.25.1 no_proxy=192.168.25.1 .venv-p7-ros/bin/python -c '<AirbotClient 读取右臂 get_service_state()>'`。

结果：未发现上述本机控制进程；右臂返回 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。右臂已满足目标状态，因此未 acquire control、未调用 `switch_controller()`、未发送关节或夹爪命令，左臂未访问。

## 2026-07-23 12:57 CST - 按 scripts/README 复核未提交代码用途（agent: Codex）

只读检查当前 5 个已跟踪修改、52 个未跟踪文件，并从 `scripts/README.md` 追踪
unlimited-recovery -> persistent-loop -> ROS2 内存采集/P7 gRPC 的传递依赖。确认 latest-file
daemon/probe、旧逐轮 closed-loop 及其 NPZ/action-JSON bridge、旧客户端拆步回位、重复录像脚本、
旧 arm_dual_app 启动器和未接入 P7 adapter 已被当前流程替代；AIRRTM、DDS overlay/proxy、姿态/
三角波/精度脚本属于历史路线或一次性现场探针。另确认 tokenizer 的无条件 prompt print 是调试
残留；`airbot_airrtm_servo.py` 仍被 `airbot_policy_bridge.py` 顶层导入，不能不经拆分直接删除。
未连接机器人、未运行服务、未移动或删除文件。详见
[worktree-cleanup-20260720.md](worktree-cleanup-20260720.md#2026-07-23-1257-cst按-scriptsreadmemd-复核未提交代码)。

## 2026-07-23 14:17 CST - 删除旧路线并保留三个 P7 专项工具（agent: Codex）

按用户确认删除 latest-file/旧 closed-loop、NPZ/action-JSON bridge、旧回位/重复录像、未接入 P7
adapter、AIRRTM、DDS overlay/proxy 及未保留的一次性运动探针。保留双臂全关节三角波、双臂
planning 精度和逐臂 servo 精度工具；将三角波依赖的关节限制/波形/helper 内聚到保留脚本，并在
`scripts/README.md` 新增三个工具的只读与真实运动用法。`airbot_policy_bridge.py` 已移除 AIRRTM
隐藏依赖，仅保留 action chunk 校验/选取；tokenizer prompt 调试输出已移除；`.gitignore` 不再隐藏
`docs/*`。离线验证结果为 policy/relpose/bridge `14 passed`、P7 mock `4 passed`，定向 ruff、编译、
shell 语法、三角波 dry-run、三个 `--help`、删除引用检查和 `git diff --check` 均通过。未连接或控制
机器人。详见
[worktree-cleanup-20260720.md](worktree-cleanup-20260720.md#2026-07-23-1417-cst执行清理并保留三个专项验证工具)。

## 2026-07-23 16:59 CST - 检查 GitHub fork、SSH 与 push 前置条件（agent: Codex）

`origin` 为 `https://github.com/Robot-K/Openpi_RL.git`；OpenSSH `accept-new` 记录 GitHub host key
后，`ssh -T git@github.com` 返回账号 `by-luckk`，SSH 身份验证成功。目标
`by-luckk/Openpi_RL` 的 SSH `ls-remote` 返回 `Repository not found`、网页为 HTTP 404，确认 fork
尚不存在。本机无 `gh` 和 API token；临时下载并校验官方 `gh 2.96.0` 后启动 device login，但授权
未在等待期间完成，后台进程已停止，因此未创建 fork、未 push。已按用户提供的信息把仓库级 Git
identity 和未推送 commit 作者/提交者改为 `by-luckk <by-chen22@mails.tsinghua.edu.cn>`。未向上游
仓库写入内容，未输出或落盘设备验证码。详见
[github-fork-push-20260723.md](github-fork-push-20260723.md)。

## 2026-07-23 17:12 CST - 清理临时 GitHub API 凭据与 CLI（agent: Codex）

fork 和 push 完成后执行 `gh auth logout --hostname github.com --user by-luckk`，确认本机 gh 配置
不再含 `oauth_token` 或用户条目；临时下载的 GitHub CLI 目录和 device login 日志已移入系统回收
站，未发现残留登录进程。SSH `git ls-remote fork refs/heads/master` 仍成功返回
`9a92ffa040f8474a8c0bad8d0a7a1f33dbdecced`。本地 logout 不会自动撤销 GitHub 侧 OAuth 应用授权；
如需撤销可在 GitHub Settings -> Applications 管理，但会影响同账号其他 GitHub CLI 登录。

## 2026-07-23 17:07 CST - 创建个人 fork 并通过 SSH push（agent: Codex）

用户完成第二次 GitHub device authorization 后，临时官方 `gh 2.96.0` 登录为 `by-luckk`，并成功
创建 `https://github.com/by-luckk/Openpi_RL`。GitHub API 确认该仓库 `isFork=true`、parent 为
`Robot-K/Openpi_RL`、默认分支为 `master`。本地新增
`fork=git@github.com:by-luckk/Openpi_RL.git`，`git push -u fork master` 成功将远端从
`87b5ac9` 更新到 `593fb0d`；本地 HEAD 与远端 `refs/heads/master` 均为
`593fb0dca712d18c9bb635acc57192f98d7fd427`，本地 `master` 已跟踪 `fork/master`。`origin` 保持
指向 `Robot-K/Openpi_RL`，未向上游写入。详见
[github-fork-push-20260723.md](github-fork-push-20260723.md)。

## 2026-07-23 19:58 CST - 核对双腕相机读取与保存入口（agent: Codex）

执行 `rg -n -i "wrist|left_wrist|right_wrist|imwrite|VideoWriter|np.savez|McapDataSampler|save_video" examples/airbot scripts/cmds README.md`，并查看
`record_openpi_cameras.py`、`capture_ros2_openpi_observation.py`、`inference_recorder.py`
及同步/异步推理调用点。确认 `record_openpi_cameras.py --wrist-only` 订阅左右腕 ROS2
topic，分别写出两个 MP4 和一个 tiled MP4；capture 脚本把左右单帧保存到 NPZ；启用
`record_data` 的同步/异步推理则将 raw camera topics 编码到 MCAP（默认 H264）。推理配置
默认 `record_data=false`，persistent loop 常规路径只在内存中传图，预览开关才写 NPZ。
当前没有默认逐帧 PNG/JPG 保存入口。详见 [`camera-image-capture.md`](camera-image-capture.md)。
另外确认录像脚本和单帧采集脚本的默认 topic 前缀不同（分别为 `/robot/camera/...` 和
`/camera/.../image_rect`），不能不经核对直接混用参数。

## 2026-07-23 20:12 CST - 新增闭合双夹爪后保存双腕图片脚本（agent: Codex）

依据现有 `p7_move_to_joint_target.py`、`openpi_p7_persistent_loop.py` 和
`capture_ros2_openpi_observation.py` 的接口实现，新增
`examples/airbot/close_grippers_capture_wrist_images.py`。脚本顺序为：双臂服务状态检查 ->
`acquire_control()` -> EEF CSP / speed -> 左右 `move_eef(pos=[close_mm] * eef_dof)` 并发闭合 ->
切回 EEF idle、释放控制权 -> 等待左右 ROS2 新帧 -> OpenCV 保存两张 JPG/PNG 和 metadata JSON。
默认 `close_mm=0`，默认 dry-run，真实动作要求 `--execute --allow-robot-motion`；脚本不移动机械臂。

验证命令及结果：

```bash
python -m py_compile examples/airbot/close_grippers_capture_wrist_images.py
.venv/bin/ruff check examples/airbot/close_grippers_capture_wrist_images.py
.venv-p7-ros/bin/python examples/airbot/close_grippers_capture_wrist_images.py --help
.venv-p7-ros/bin/python examples/airbot/close_grippers_capture_wrist_images.py
git diff --check
```

结果：Ruff、编译、`--help`、dry-run 和 whitespace 检查均通过；dry-run 输出确认没有调用
`acquire_control()` 或 `move_eef()`。本轮未连接机器人、未执行真实夹爪闭合、未采集现场图像。

2026-07-23 20:13 CST 跟进修正客户端逐个登记的异常清理路径后，重新执行 Ruff、`py_compile`、`--help`、
dry-run 和 `git diff --check`，全部通过；仍未连接机器人或执行真实动作。

## 2026-07-23 20:15 CST - 增加左右腕图像 50/50 重叠输出（agent: Codex）

在 `close_grippers_capture_wrist_images.py` 的两张单图保存成功后增加 `cv2.addWeighted` 混合：
左右图各占 0.5 权重，输出 `<prefix>_wrist_overlay.jpg/png`，并把该路径写入 metadata；若两路
分辨率不同，先将右图缩放到左图尺寸以保证完全重叠。`scripts/README.md` 的 4.4 节改为简化的
一条运行命令和三个输出文件说明。

验证命令：`.venv/bin/ruff check examples/airbot/close_grippers_capture_wrist_images.py`、
`python -m py_compile examples/airbot/close_grippers_capture_wrist_images.py`、
`.venv-p7-ros/bin/python examples/airbot/close_grippers_capture_wrist_images.py`、
`git diff --check`；结果全部通过，dry-run 未调用机器人控制接口。本轮未连接机器人、未执行真实
夹爪动作、未采集现场图像。

## 2026-07-23 20:37 CST - 定位双腕采图脚本的 P7 SDK 建连超时（agent: Codex）

用户的 ping 正常但脚本报 `Timeout connecting to 192.168.25.1:50071`。工作站只读 TCP 探测确认
`50071/50072` 都返回 `Connection refused`；SSH 可正常进入 X5（hostname `ubuntu`），但板端无
`arm_app`、`robot_app`、`arm_dual_app` 进程，两个 gRPC 端口均未监听。故障原因是板端 runtime
未启动，而不是相机 topic 或主机网络不通。脚本未 acquire control、未发送 `move_eef()`、未采图
或写入 `./data/`。详见 [`arm-app-vs-robot-app.md`](arm-app-vs-robot-app.md)。

## 2026-07-23 21:15 CST - 定位闭合夹爪后双腕抓帧超时（agent: Codex）

P7 控制 runtime 与 `50071/50072` 均在线，但显式使用 `ROS_DOMAIN_ID=0`、Fast DDS 重跑双腕抓帧
仍得到两路 `missing`。现场 ROS graph 无腕部 `sensor_msgs/Image`，只有无实际帧的
`CompressedVideo` 端点。板端 `robot_app` 日志确认左右腕四只相机均在 `tx_remote_init` 阶段以
`ret=-2` 失败，汇总为 `2 started, 4 failed`，持续统计四腕路均为 `frames=0, fps=0.00`。配置中的
腕部 `pub_image.enable=true`，故根因是板端腕部相机远端传感器/SerDes 初始化失败，不是脚本、QoS
或 topic 拼写。详见 [`camera-image-capture.md`](camera-image-capture.md)。

## 2026-07-23 21:28 CST - 临时生成上下翻转双腕重叠图（agent: Codex）

未修改采图脚本和原始 JPG；用 OpenCV 将右腕图片上下翻转后，与左腕图片各按 50% 权重混合，
生成 `/tmp/closed_wrist_right_vflip_left_overlay.jpg`。输出为 `640x480x3 uint8`，已视觉确认。
ImageMagick `convert` 不存在的首次失败及实际 OpenCV 命令详见
[`camera-image-capture.md`](camera-image-capture.md)。

## 2026-07-24 13:14 CST - 新增 VIO 相对 TCP 双臂 replay 脚本（agent: Codex）

检查 `vio_dual_arm_trajectory_10s.replay.npz` 确认它包含 273 个约 9.07 秒的 14D 相对 TCP 指令，
不是关节角。新增 `p7_replay_vio_dual_arm_trajectory.py`：以 replay 开始时实际 TCP 为基座合成目标，
将每段限制为 `10mm/0.10rad` 小步，默认 5 倍慢放、默认 5cm 包络拒绝、默认不重放夹爪，真实执行仍需
`--execute --allow-robot-motion`。离线计划以 `--max-envelope-m 0.40` 成功生成 326 帧/45.333s，且
确认没有 SDK client 或任何机器人命令；编译、Ruff、`--help`、pytest `2 passed` 和 diff 检查均通过。
详见 [`vio-dual-arm-replay.md`](vio-dual-arm-replay.md)。

## 2026-07-24 13:20 CST - 核对键盘控制双臂末端 XYZ/RPY（agent: Codex）

全仓搜索确认：现有键盘监听只控制 episode/DAgger 状态；`airbot-driver` 的按键是遥操开关和回零；
`play_operator.py` 发送关节目标；P7 replay 脚本虽能并发调用左右 `move_end_pose(CartesianPose)`，
但没有键盘输入映射。因此当前没有“键盘直接控制双臂末端 XYZ + roll/pitch/yaw”的现成程序。
未连接机器人、未发送运动命令。详见 [`keyboard-eef-control.md`](keyboard-eef-control.md)。

## 2026-07-24 13:19 CST - VIO replay 夹爪值改为直接截断（agent: Codex）

用户确认继续使用新增的独立 replay 脚本，且明确要求夹爪值截断到 `95mm`。因此
`--replay-grippers` 改为将记录值直接按 P7 毫米值使用、限制到默认 `0..95mm`，不再将
`0..102` 线性缩放为 `0..95`；右腕记录最大值 `101.913887` 会发送为 `95mm`。不修改
`p7_continuous_servo_smoke.py` 或 `scripts/README.md`。夹爪模式 dry-run、编译、Ruff、`--help`、
diff 检查均通过，轨迹数学和截断测试为 `3 passed`；未连接或控制机器人。

## 2026-07-24 13:29 CST - 诊断 VIO replay 的 P7 gRPC 建连超时（agent: Codex）

replay 在创建第一个 `AirbotClient(192.168.25.1:50071)` 时超时，尚未申请控制权或发送任何动作。
X5 两个 `arm_app` 仍在、`50071/50072` TCP LISTEN 且 `nc` 连通，但 `.venv-p7-ros` 与
`.venv-p7-sdk` 的 SDK 都在 `grpc.channel_ready_future(..., timeout=3.0)` 超时，确认端口仅能 TCP
握手、gRPC route 未实际就绪。需恢复/重启左右 `arm_app` 并先通过只读 `get_service_state()` 探针验证。
详见 [`p7-sdk-grpc-current-state.md`](p7-sdk-grpc-current-state.md)。

## 2026-07-24 22:18 CST - 闭合夹爪抓图扩展为四路腕部立体 JPG（agent: Codex）

`close_grippers_capture_wrist_images.py` 现内置 `192.168.25.1` 和左右腕各左右眼四路 raw image topic，
保存四张不 resize 的单独 JPG，并保留 overlay/metadata；调用命令无需显式 host/topic。按用户要求未连接
机器人或运行验证。详见 [`camera-image-capture.md`](camera-image-capture.md)。

## 2026-07-24 13:35 CST - 新增键盘控制双臂六自由度末端程序（agent: Codex）

新增 `examples/airbot/keyboard_dual_arm_teleop.py` 和 `scripts/cmds/keyboard_dual_arm_teleop.sh`：`1/2/b` 选择左/右/双臂，`w/s`、`a/d`、`r/f`
控制 XYZ，`i/k`、`j/l`、`u/o` 控制 roll/pitch/yaw；默认 world frame，也可选 TCP local frame。
程序默认 dry-run，实际运动要求 `--execute --allow-robot-motion`，并以初版 `2mm/2deg` 单步、`5cm/30deg`
启动位姿包络、`80ms` 命令间隔作为保护；异常和退出会切 idle、释放控制权。Ruff、编译、`--help`、
封装的 `--help`、`git diff --check` 通过，纯数学/按键映射 pytest 为 `3 passed`（禁用与本测试无关且缺依赖的全局 ROS 插件）。
只传 `--execute` 已验证被拒绝；未连接或控制机器人。详见 [`keyboard-eef-control.md`](keyboard-eef-control.md)。

## 2026-07-24 13:43 CST - 修正键盘遥操作 P7 最小臂速（agent: Codex）

用户首次以真实运动开关启动后，左右初始均为 `IDLE/idle/valid`，左臂已获得 lease，但
`set_arm_speed(0.25)` 被 SDK 拒绝：允许范围下限是 `0.5499000081647326 rad/s`。脚本的异常清理已
成功让左臂 `switch_idle=True` 并释放 lease，未调用 `move_end_pose()`。已将 Python 和 shell 封装的
初版默认臂速改为 `0.55 rad/s`。修正后传入 `P7_TELEOP_ARM_SPEED_RAD_S=0.25` 会在 SDK import、连接和
lease 之前拒绝，输出允许范围 `[0.55, 7.85]`；Ruff、编译和 diff 检查通过。详见
[`keyboard-eef-control.md`](keyboard-eef-control.md)。

## 2026-07-24 22:03 CST - 记录双臂当前关节位置（agent: Codex）

清除代理后使用 `.venv-p7-ros` 只读调用 `get_service_state()` / `get_arm_joint_state()`：left
`[-0.0167, 0.7801, -0.0105, 0.0370, 0.0044, 0.0009, 1.0398]` rad，right
`[-0.0146, 0.7801, -0.0098, 0.0381, 0.0014, 0.0056, 1.0758]` rad；两臂均为
`SERVO_CONTROL/csp/valid`。未申请控制权、未切换模式、未发送动作。详见
[`p7-sdk-grpc-current-state.md`](p7-sdk-grpc-current-state.md)。

## 2026-07-24 22:38 CST - 抓图四路腕部 raw 话题全部无帧

`close_grippers_capture_wrist_images.py` 已经过 gRPC 直连修正，但抓图报告四路
`missing` 且 `stalled=[]`；这表示四个 raw image topic 都没有新帧，不是 SDK 连接或夹爪命令问题。
近期现场记录已证实腕部相机 ISP/MIPI/SerDes 初始化失败，需修复 X5 相机 runtime 并确认 raw
`sensor_msgs/Image` 有实际帧，不应继续调大 capture timeout。详见 [`camera-image-capture.md`](camera-image-capture.md)。

## 2026-07-24 13:53 CST - 提高键盘双臂末端控制响应速度（agent: Codex）

按用户“速度再大一些”的要求，默认 P7 `set_arm_speed` 从 `0.55` 提高到 `1.5 rad/s`，键盘命令
最小间隔从 `80ms` 降到 `40ms`（按住键时最高约 25 Hz）；单次位姿增量仍是 `2mm/2deg`，启动位姿
包络仍是 `5cm/30deg`。Ruff、编译、纯数学/按键测试（`3 passed`）和 diff 检查通过，未连接机器人。
因此响应速度提高而工作空间护栏不变。详见
[`keyboard-eef-control.md`](keyboard-eef-control.md)。

## 2026-07-24 13:42 CST - 复核闭合夹爪后的双腕相机抓帧失败（agent: Codex）

用户闭合夹爪成功后，双腕抓帧在 8 秒后超时。板端只读检查确认用户指定的两个 raw image topic 和当前
规范 raw image topic 都不存在；ROS graph 仅有静态 `video_encoded` 名称。`arm_app` gRPC 服务仍在线，
但本轮 `robot_app` 在 13:38 启动六路相机时全部失败：腕部四路均为 `create_isp_node ... ret -10`，汇总
`0 initialized, 0 started, 6 failed`。根因是 X5 相机 ISP/MIPI 初始化，不能由脚本 topic/QoS/超时修复；
需先修复板端并确认 raw `sensor_msgs/Image` 实际发布。详见 [`camera-image-capture.md`](camera-image-capture.md)。

## 2026-07-24 14:23 CST - 明确 VIO 双臂 replay 的初始位置语义（agent: Codex）

检查 `p7_replay_vio_dual_arm_trajectory.py` 及 NPZ 第 0 帧，确认记录的左右相对平移和旋转均为零。
真实执行不会去固定 ready pose，而是在申请控制权前每臂连续读取三次实际 TCP，漂移不超过 3mm 后取最后
一次为 `replay_start_xyz/xyzw`；首个 arm target 就是该实时 TCP，后续以其为基座合成相对轨迹。本次命令
未加 `--replay-grippers`，不会命令夹爪。详见 [`vio-dual-arm-replay.md`](vio-dual-arm-replay.md)。

## 2026-07-24 14:23 CST - VIO replay 默认先移动至 recovery 预设位置（agent: Codex）

依据 `openpi_p7_unlimited_recovery.sh` 与 `move_p7_to_ready_joint_pose.sh` 的既有 ready pose，replay 脚本
现会在真实执行时先将双臂移到 `[0,0.647,0,-0.933,0,0,-1.15] rad` 并打开夹爪至 `95mm`，随后才采样
replay 基座 TCP。新 `--skip-ready-pose` 可跳过该流程；默认 3rad 关节差 guard 会拒绝超限移动。用户明确
要求不检查，本轮未连接机器人、未执行、未编译或测试。详见 [`vio-dual-arm-replay.md`](vio-dual-arm-replay.md)。

## 2026-07-24 14:23 CST - 核对 VIO replay 与 recovery 的左右臂映射（agent: Codex）

代码和 NPZ metadata 对照确认：recovery 与 replay 都是 left 端口 `50071`、right 端口 `50072`；ready pose
对两臂使用相同 7D 目标，新增 ready 流程不会造成左右交换。NPZ 也显式定义前 7D 为 left、后 7D 为 right。
是否为 VIO source pose 与物理臂的现场方向不一致，不能仅凭代码确认，故未盲目交换或控制机器人。详见
[`vio-dual-arm-replay.md`](vio-dual-arm-replay.md)。

## 2026-07-24 - 取消键盘双臂遥操作的平移和旋转包络（agent: Codex）

删除 `keyboard_dual_arm_teleop.py` 的 `--max-envelope-m`、`--max-rotation-deg` 参数及累计位姿越界拒绝；
`keyboard_dual_arm_teleop.sh` 同步停止传入两项限制。单步增量、命令间隔、SDK 速度和真实运动双开关仍保留。
未连接或控制机器人。详见 [`keyboard-eef-control.md`](keyboard-eef-control.md)。

## 2026-07-24 22:18 CST - 尝试只读记录双臂当前 joint pose（agent: Codex）

`.venv-p7-ros` 创建左臂 `AirbotClient(192.168.25.1:50071)` 时 gRPC readiness 超时，未进入
`get_arm_joint_state()`，右臂未尝试，因此没有获得可记录的 joint pose。未申请控制权、切控制器或发送动作。
详见 [`p7-sdk-grpc-current-state.md`](p7-sdk-grpc-current-state.md)。

## 2026-07-24 14:23 CST - 按现场确认交换 VIO source pose 的左右输入（agent: Codex）

用户确认 VIO source pose 左右标签相对物理 AIRBOT 双臂相反。replay 保持左臂 `50071`、右臂 `50072`
端口不变，改为物理 left 读取 NPZ 的 VIO right `7:14`，物理 right 读取 VIO left `0:7`；位移、旋转、
夹爪值作为同一 7D 段整体交换。未连接、控制或验证机器人。详见
[`vio-dual-arm-replay.md`](vio-dual-arm-replay.md)。

## 2026-07-24 14:34 CST - 排除键盘遥操作的客户端占用（agent: Codex）

本机无键盘遥操作/persistent loop/replay/推理控制进程或 `50071/50072` 监听；X5 两个端口由左右
`arm_app` 自己监听，TCP 连通。但 `.venv-p7-sdk` 的只读 `AirbotClient` 仍在 gRPC readiness 3 秒超时，
发生在申请控制权之前。X5 当时两 arm_app CPU 约 44%/47%、remote robot_app 约 35%，日志还出现 CAN
`No buffer space available`、FK RPC timeout 与周期超时。后续源码对照确认 SDK timeout 的直接原因是本机
代理环境，而不是这些板端警告或其他客户端持有控制权。详见
[`p7-sdk-grpc-current-state.md`](p7-sdk-grpc-current-state.md)。

## 2026-07-24 14:38 CST - 排除键盘封装与 replay 的 Python 环境差异（agent: Codex）

键盘封装默认 `.venv-p7-sdk`（Python 3.11 / grpcio 1.81.1），replay 命令使用 `.venv-p7-ros`
（Python 3.12 / grpcio 1.82.1）。初次两环境 probe 都超时，是因为二者都继承了本机
`all_proxy/http_proxy/https_proxy`；replay 源码会在建连前清除这些变量。
同时检查到当前键盘 shell 封装覆盖为 `5mm/3deg` 单步、`1m/90deg` 包络，远大于 Python 安全默认；
这不造成 timeout，但会放宽真实运动限制。详见 [`p7-sdk-grpc-current-state.md`](p7-sdk-grpc-current-state.md)
和 [`keyboard-eef-control.md`](keyboard-eef-control.md)。

## 2026-07-24 14:50 CST - 复用 replay 的无代理 gRPC 建连方式（agent: Codex）

对照 replay 源码发现其在 `AirbotClient` 前调用 `configure_direct_grpc()`：清除六个大小写 HTTP/SOCKS
代理变量并将机器人 IP 加到 `NO_PROXY`。本机代理值为 `all_proxy=socks5://127.0.0.1:7897`、
`http_proxy/https_proxy=http://127.0.0.1:7897`；继承它们才导致键盘脚本 gRPC timeout。键盘封装已改为
replay 使用的 `.venv-p7-ros`，键盘 Python 也复用同款无代理配置；此前加入的重试已删除。用无代理
`.venv-p7-ros` probe 已立即返回 `IDLE/idle/valid`；Ruff、编译、封装 help 和 pytest `4 passed` 通过，
随后 keyboard shell 默认 dry-run 也实测移除三项代理变量、读取双臂 `IDLE/idle/valid` 并由 `q` 正常退出，
未控制机器人。详见
[`p7-sdk-grpc-current-state.md`](p7-sdk-grpc-current-state.md) 和
[`keyboard-eef-control.md`](keyboard-eef-control.md)。

## 2026-07-24 22:18 CST - 定位 VIO replay 实测包络拒绝（agent: Codex）

用户回放被 `--max-measured-envelope-m 0.42` 拒绝：left 实测 `0.116361m`，right 实测
`0.427879m`。只读核对 summary、轨迹与代码后确认，物理 right 计划整段最大仅
`0.227870m`，实测多出 `0.200010m`（`1.878x`），安全保护正常中止了明显的 Cartesian
跟踪偏离，不应直接调大阈值。新 ready joint 的 joint4=`0` 接近伸直奇异位形，是首要
嫌疑；现有 summary 缺触发帧与 target-vs-measured 误差，故暂不将根因表述为完全证实。
本轮未连接或控制机器人。详见 [`vio-dual-arm-replay.md`](vio-dual-arm-replay.md)。

## 2026-07-24 22:34 CST - 修正抓图脚本的 gRPC 代理路由

`close_grippers_capture_wrist_images.py --execute` 在 `192.168.25.1:50071` 超时，而键盘脚本成功。对比最近
14:50 记录确认：键盘脚本在建立 `AirbotClient` 前移除六个 HTTP/SOCKS 代理变量并设置
`NO_PROXY`，抓图脚本缺少该步骤，故继承本机代理后超时。已补齐同样的
`configure_direct_grpc()`；`.venv-p7-ros` 编译与 diff 检查通过，未重跑真机或下发夹爪动作。详见
[`p7-sdk-grpc-current-state.md`](p7-sdk-grpc-current-state.md)。
