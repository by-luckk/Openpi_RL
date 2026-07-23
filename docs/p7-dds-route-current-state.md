# DDS Route / 裸 DDS 历史核对记录（当前不采用）

日期：2026-06-30 17:54 CST；检查人：agent。
目的：保留 2026-06-30 17:54 CST 对 DDS Route / 裸 DDS / AIRRTM 的现场核对证据；2026-06-30 20:27 CST 后，当前主线已按用户指令切换为 Arm-P7 SDK gRPC，见 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)。

## 1. 结论

> 2026-06-30 20:27 CST 更新：用户明确要求“不要走 DDS”。当前执行主线已切到 [Arm-P7 SDK gRPC](p7-sdk-grpc-current-state.md)：`AirbotClient(..., backend="grpc")`、`get_end_pose()`、`move_end_pose()`、`move_eef()`。本文件以下 DDS/DDS Route 内容只作为历史核对和反证材料，不再作为当前执行方案。

当前模型已经训练好，policy 侧输入输出不需要重新定义。真正要做的是执行层适配：

1. policy 请求仍是三路 RGB 图像 + prompt + dummy `state`。
2. policy 输出每步前 14 维：左右臂各 `TCP 局部 Δpos(3) + Δrotvec(3) + gripper(1)`。
3. 执行层要读当前 TCP pose，把 relpose 积分成目标 TCP pose `[x,y,z,qx,qy,qz,qw]`。
4. 夹爪模型值是 `0-100`，开=100、闭=0；若底层走 G2P 行程，则换算成 `0.096 * g / 100` m。

17:54 CST 现场核对时，这台 X5 还不能直接按飞书 DDS Route 文档跑：

- DDS Route 文档要求 `robot_app 0.3.3+` 和 `arm_p7_sdk 1.1.0.dev50+`。
- 当前 X5 是 `AIRBOT_MOTION_VERSION "0.1.1.dev90+g24fec8a"`。
- 当前 X5 没有 `dds_route` topic、进程或 `FsmDdsRoute.idl`。
- 当前工作站有线口 `enp108s0` 是 `DOWN`，只能通过 Wi-Fi 管理地址 `172.100.10.159` SSH；直连 DDS 跨机发现暂时不成立。

20:27 CST 后，本文件中的 DDS/DDS Route 判断只作为历史材料；当前执行优先级应改成：

| 路线 | 当前状态 | 结论 |
|---|---|---|
| Arm-P7 SDK gRPC | 用户最新指定路线；目标接口是 `AirbotClient(..., backend="grpc")`、`get_end_pose()`、`move_end_pose()`、`move_eef()` | **当前主线；先安装 SDK、启动/连通 50071 gRPC 服务** |
| DDS Route RPC（飞书 wiki） | 17:54 CST 证据表明当前 X5 未部署，且 20:27 CST 用户明确不要走 DDS | 不作为当前路线，仅保留历史证据 |
| 裸 DDS/FSM topic | 当前 X5 有订阅者，但需要生成/绑定 `arm_msgs` 类型并处理 DDS QoS/网络 | 不作为当前路线 |
| AIRRTM `arm_servo_json` | X5 remote 配置曾显示可作为转换层 | 暂不作为当前主线；除非用户后续明确切换 |

## 2. 用户给的 DDS Route 文档要点（历史资料）

飞书 wiki：https://w79rvfxw83.feishu.cn/wiki/PNkUwkPtoiciYTkqsI5cNF08nCe
文档标题：《二代臂 DDS Route 开发指南》，document_id `TqNMdmC1nosChixvzvWcFtaenKg`，revision `128`。

关键结论：

- `dds_route_node` 是 FSM 控制面的 DDS/CORA facade；服务名前缀是 `rt/arm/dds_route/`，或带 side 的 `rt/arm/left/dds_route/`、`rt/arm/right/dds_route/`。
- CORA RPC topic 形如 `rpc/rt/arm/dds_route/<method>/request` 和 `/response`。
- DDS Route 和 `arm-grpc-route` 是并列 transport，不是互相调用。
- 权威 IDL 是：

```text
cora/dds/msg/arm_msgs/msg/FsmDdsRoute.idl
cora/dds/msg/rpc_msgs/msg/rpc_msgs.idl
```

控制权流程：

1. `acquire_control(client_id, lease_ms)` 获取 `lease_id`。
2. 周期 `renew_control(client_id, lease_id, lease_ms)`，推荐周期小于 lease 的一半。
3. 每个控制类命令都填业务 payload 里的 `client_id` 和 `lease_id`。
4. 结束时 `release_control`。

对当前模型最关键的接口：

| 需求 | DDS Route 接口 | 字段 |
|---|---|---|
| 读当前 TCP pose | `get_cartesian_pose` | response `value` 固定 7 维 `[x,y,z,qx,qy,qz,qw]` |
| 切到 servo | `call_switch_control_state` | `target=SWITCHABLE_FSM_SERVO_CONTROL`，`blocking=true` 等 ack |
| 发 TCP pose | `call_servo_pose_command` | `pose` 固定 7 维 `[x,y,z,qx,qy,qz,qw]`，`timestamp_ns`，`blocking=false` |
| 发夹爪 | `call_end_effector_position_control` | `position` 数组，长度按当前 EEF 模型解释 |

使用注意事项：

- DDS domain、shared memory、UDP 配置要和 `robot_app/framework_config.json` 一致。
- 先等待 `matchedServers() > 0` 再 RPC。
- `pose` 一律 `[x,y,z,qx,qy,qz,qw]`。
- `arm_dof` 和数组长度必须匹配，当前 backend 按最多 7 轴填充。
- 发送实机 position/servo/force 前必须确认工作空间、限位、速度、阈值和急停链路。

## 3. P7 SDK 指南要点（已由飞书 Arm-P7 SDK gRPC 文档校正）

最新主线文档见 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)。本节保留 17:54 CST 对本地旧文档的理解；20:27 CST 后以飞书 wiki《二代臂Arm-P7-SDK开发指南》（document_id `KqomdsMbuoep9hxbMYfc1OGdntg`，revision `215`）为准。

本地文档：`docs/二代臂Arm-P7-SDK开发指南.md`。

语义上它与 DDS Route 对齐：

- `AirbotClient(host, port)` 是 gRPC SDK 入口。
- `acquire_control()` / `release_control()` 管控制权。
- 高频跟踪走 `Controller.servo_control` + `move_end_pose(...)`。
- `get_end_pose()` 返回 `CartesianPose(position, orientation)`。
- `CartesianPose.orientation` 明确是 `(qx,qy,qz,qw)`。
- `move_eef(pos, ...)` 的 `pos` 在 SDK v1.2 语义中是毫米。

但当前 X5 现场不满足 P7 SDK 直连条件：

- `ss -ltnp` 没有 50051/50052/50071 对外监听。
- X5 `python3` 查不到 `arm_p7_sdk`。
- 本地 `.venv` 里的 `arm_p7_sdk` 因 protobuf 版本不匹配不可用；`/home/discover/Desktop/arm_sdk_test/.venv/bin/python` 可导入 `arm_p7_sdk 1.0.0`，但 DDS Route wiki 要求的是 `1.1.0.dev50+`。

## 4. 当前 X5 只读检查

### 4.1 网络

命令：

```bash
ip -br addr show wlo1
ip -br addr show enp108s0
ping -c 2 -W 1 172.100.10.159
ping -c 1 -W 1 192.168.25.1
ssh root@172.100.10.159 ip -br addr
```

关键输出：

```text
wlo1     UP    172.100.11.47/23
enp108s0 DOWN
172.100.10.159 ping 2/2 ok
192.168.25.1 ping 0/1 fail

X5:
eth0  UP 192.168.25.1/24
wlan0 UP 172.100.10.159/23
```

结论：X5 有线口是好的，但工作站有线口当前 down；本轮只能走 Wi-Fi SSH 管理，不能认为工作站直连 DDS 已就绪。

### 4.2 进程与端口

命令：

```bash
ssh root@172.100.10.159 ss -ltnp
ssh root@172.100.10.159 pgrep -af robot_app
ssh root@172.100.10.159 ps -ef | grep -E 'dds_route|control_authority|grpc-route|route_node|arm-dds-route|arm-grpc-route'
```

关键输出：

```text
LISTEN 0.0.0.0:22     sshd
LISTEN 0.0.0.0:8020   robot-agent
LISTEN 0.0.0.0:8042   robot_ota_app

./bin/robot_app /opt/robot_app/configs/remote/project_config.json
./bin/robot_app /opt/robot_app/configs/left_arm/project_config.json
./bin/robot_app /opt/robot_app/configs/right_arm/project_config.json
```

未发现 `dds_route` / `control_authority` / `arm-grpc-route` 相关进程；未发现 P7 SDK gRPC 对外端口。

版本：

```bash
ssh root@172.100.10.159 sed -n '1,160p' /opt/robot_app/include/version.hpp
```

```text
#define AIRBOT_MOTION_VERSION "0.1.1.dev90+g24fec8a"
```

### 4.3 ROS2 / DDS topic

命令：

```bash
ssh root@172.100.10.159 "source /opt/ros/humble/setup.bash; ros2 topic list"
ssh root@172.100.10.159 "source /opt/ros/humble/setup.bash; ros2 topic info -v /arm/left/fsm/servo_pose_command"
ssh root@172.100.10.159 "source /opt/ros/humble/setup.bash; ros2 topic info -v /arm/left/fsm/end_effector_position_control_command"
ssh root@172.100.10.159 "source /opt/ros/humble/setup.bash; ros2 topic hz /arm/left/control/joint_states"
```

关键事实：

- topic 列表中有 `/arm/{left,right}/fsm/cartesian_state`、`servo_pose_command`、`end_effector_position_control_command`、`switch_control_state_command`。
- topic 列表中没有 `dds_route`。
- `/arm/left/fsm/servo_pose_command` 和 `/arm/left/fsm/end_effector_position_control_command` 都有 robot_app 订阅者，QoS 为 RELIABLE + VOLATILE。
- `/arm/left/control/joint_states` 约 244.6 Hz。
- `/arm/right/control/joint_states` 可 echo 到 `[joint1..joint7,G2P]`，`G2P=0.0`。

夹爪行程配置：

```bash
ssh root@172.100.10.159 sed -n '1,220p' /opt/robot_app/configs/left_arm/arm_models.json
```

```json
"G2P": {
  "position": [0.0, 0.096],
  "velocity": [-1.5, 1.5]
}
```

servo 节拍：

```json
"servo_engine_update_period_us": 4000,
"servo_engine_incoming_command_timeout_ms": 1000,
"servo_tick_period_us": 4000
```

## 5. 对我们实际方案的影响

从第一性原理看，真正需要对齐的是“模型语义”和“机械臂控制接口语义”：

| 层 | 当前事实 | 需要做的处理 |
|---|---|---|
| policy 输入 | 三路 RGB + prompt + dummy state | 图像解码成 RGB HWC；state 用 zeros 通过 transform |
| policy 输出 | 每臂 TCP 局部 relpose + 夹爪 0-100 | 只取前 14 维；按 TCP 当前位姿积分 |
| 当前 TCP pose | 2026-07-19 当前 `/opt/arm_app` 左右实例只加载 `dds_route_node`；SDK 公共读取接口仍是 `get_end_pose()` | 客户端必须使用 DDS backend，并分别传 `side="left"` / `side="right"` |
| TCP pose 命令 | SDK DDS backend 同样提供 `move_end_pose(CartesianPose(...))`；SERVO 发送完整目标 pose，不发送 delta | `DualArmTcpTarget -> CartesianPose(position, orientation)` 后经左右 DDS route 下发 |
| 夹爪命令 | 模型 0-100；SDK 公共接口单位是 mm；wiki 已知 G2P 范围 `[0.0,95.0]` mm | `g/100 * max_mm` 后 `move_eef(pos=[...])`；不要把 DDS/FSM 米制字段混进 SDK 调用 |
| 控制权 | SDK 提供 `acquire_control()` / `release_control()` | 写控制前获取控制权，异常和结束时释放；读状态先做 no-motion 检查 |
| 网络 | 工作站可经 `192.168.25.1` SSH 到 X5；新 `arm_app` 不监听 `50071/50072`，DDS domain id 为 `0` 且启用 UDP | 工作站 DDS 客户端需具备 CORA UDP 发现与 `cora.msg.arm_msgs` |

## 6. 当前启动机械臂前还缺的事（新 `arm_app` DDS 部署）

2026-07-19 当前权威事实是：板端 `/opt/arm_app/configs/{left_arm,right_arm}` 只加载 `arm_dds_route`，不加载 `grpc_route_node`。当前缺口是：

1. 给执行客户端提供与当前架构/Python 匹配的私有 `cora` 和 `cora.msg.arm_msgs`。工作站 `.venv-p7-sdk` 是 x86_64/Python 3.11，当前 `import cora` 失败；指南里的板端 bundle 是 aarch64/Python 3.10，不能直接用于工作站。
2. OpenPI P7 客户端切换为 `backend="dds", domain_id=0`，并为左右 client 分别传 `side="left"` / `side="right"`。指南中的 `side="none"` 示例只对应 `rt/arm/dds_route`，不适用于当前双臂命名空间。
3. 先做 no-motion DDS 读检查：两侧 `get_service_state()`、`get_end_pose()`，不调用任何 move。
4. 读检查通过后，再验证控制权与 `move_end_pose()` / `move_eef()`；动作转换接口本身无需改语义。
5. 若不提供工作站 x86 CORA，替代方案是在 X5 的 aarch64/Python 3.10 环境运行 SDK DDS 执行代理，由工作站仅发送策略目标。

本文件对应轮次没有发布任何控制消息，没有切 FSM 状态，没有移动机械臂或夹爪。

## 7. 2026-07-19 18:55 CST：更新指南与新 `arm_app` 实机配置复核

检查人：Codex。板端通过更新后的 `/root/start-arm-dual-app-2arm.sh` 成功启动两个 `/opt/arm_app/bin/arm_app`，日志位于 `/userdata/arm_app_logs/20260719_185439/`。左右日志均出现 `Framework started successfully`，并分别注册：

```text
rt/arm/left/dds_route
rt/arm/right/dds_route
```

`framework_config.json` 只包含 `arm_dds_route`，没有 `grpc_route_node`；`ss -lntp` 也没有 `50071/50072`。更新指南确认 DDS client 必须传 `domain_id` 和 `side`，其中双臂应使用 `left/right` 映射。工作站验证命令：

```bash
.venv-p7-sdk/bin/python -c 'import cora; import cora.msg.arm_msgs'
```

实际输出为 `ModuleNotFoundError: No module named 'cora'`。结论：板端新 DDS route 已启动，但当前工作站 OpenPI 执行环境不能创建 DDS SDK client；在补齐 x86_64/Python 3.11 CORA，或把 DDS 执行代理移到 X5 前，不能继续真机下发动作。本轮仅检查和启动服务，没有下发机械臂运动。
