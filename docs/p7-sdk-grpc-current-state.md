# Arm-P7 SDK gRPC 当前路线与现场状态

日期：2026-06-30 20:27 CST；检查人：agent。
目的：按用户最新指令，不再走 DDS / DDS Route；以飞书 wiki《二代臂Arm-P7-SDK开发指南》为目标接口，重新对齐模型动作、SDK 输入输出和当前机械臂现场状态。

## 1. 当前结论

2026-07-08 18:28 CST 更新：当前 SDK 路线已切到统一混合 runtime。本机 `.venv-p7-sdk` 为 `arm_p7_sdk 1.1.2`；X5 已安装 `arm_dual_app 0.3.7` 到 `/opt/arm_dual_app`，并安装 board bundle，smoke test 输出 `cora version: 1.2.2+20260626085518`、`arm-p7-sdk version: 1.1.2`、`smoke test ok`。X5 `/root/start-arm-dual-app-2arm.sh` 已改为唯一入口：启动 left gRPC `50071` / CAN `can0` / log `8091`、right gRPC `50072` / CAN `can1` / log `8092`，并只启动 `/opt/robot_app/configs/remote/project_config.json` 提供相机/remote topic。左右臂 `/opt/arm_dual_app/configs/{left_arm,right_arm}/framework_config.json` 已从 `dds.domain_id=1` 改为 `0`，备份文件为 `.bak_domain_20260708_182217`。no-motion 验证通过：进程形态为 `arm_dual_app` 两个 + `robot_app remote` 一个，`50071/50072/8091/8092` 均监听，本机 `ROS_DOMAIN_ID=0` 能看到三路相机和左右臂 `/arm/*/fsm/joint_state`，SDK dry-run 读取左右臂 `IDLE/idle/valid` 和 TCP pose；未调用 `acquire_control()`，未切控制器，未发送运动命令。

2026-07-01 更新：用户提供的 `AIRBOT-ARM-P7-SW-2026-06-23-21-16-24` 已核对，确认包含当前路线需要的 `arm_p7_sdk 1.1.1` 和机器人侧 `robot_app 0.3.5`。详见 [p7-release-package-2026-06-23.md](p7-release-package-2026-06-23.md)。

2026-07-01 13:55 CST 更新：本机独立 SDK client 环境 `.venv-p7-sdk` 已安装并验证 `arm-p7-sdk 1.1.1`、`protobuf 7.35.1`、默认 `AirbotClient(... port=50071, backend="grpc")`。OpenPI 推理 `.venv` 未升级 protobuf，仍不作为 SDK client 环境。

2026-07-01 14:15 CST 更新：用户安装的 `robot_app_0.1.0_20260629175035_amd64.deb` 已确认可作为本机 mock robot_app / gRPC 接口模拟器。启动后 `grpc_route_node#none;50071` 监听 `*:50071`，即服务端等价于 `0.0.0.0:50071`；同机 SDK client 用 `127.0.0.1:50071` 连接。详见 [local-amd64-robot-app-simulator.md](local-amd64-robot-app-simulator.md)。

2026-07-01 18:18 CST 更新：网线链路已确认可用，本机 `enp108s0=192.168.25.132/24`，机器人 `eth0=192.168.25.1/24`。按用户确认，已停止旧 `right_arm` 进程 `2792`，复位 `can0`，用隔离目录 `/tmp/openpi_robot_app_0.3.5_stage/opt/robot_app` 启动 `robot_app 0.3.5`（PID `9623`），运行配置目录为 `/tmp/openpi_robot_app_035_run_20260701_181640`。机器人现在监听 `*:50071`，日志显示 `gRPC server listening on 0.0.0.0:50071` 和 `Framework started successfully`。本机 SDK no-motion 只读验证 `192.168.25.1:50071` 已通过：`ServiceState(service_state=True, fsm_state="IDLE", controller_state="idle", valid=True)`，可读 TCP pose、7 维关节和 G2P EEF state。未执行 `acquire_control()` 或任何 `move_*`。

2026-07-01 18:26 CST 更新：真机 SDK 控制权 no-motion 空操作已通过。`.venv-p7-sdk` 连接 `192.168.25.1:50071`，`acquire_control(lease_ms=15000, renew_period_s=5.0)` 返回 `True`，SDK 日志显示 `control acquired: lease_id=1`；随后 `release_control()` 成功，日志显示 `control released`。前后 `ServiceState` 均为 `IDLE/idle`，TCP pose 保持 `xyz=(0.3094,-0.0097,0.3208)`、`xyzw=(0.0425,0.0086,-0.0180,0.9989)`。本轮未切控制器，未调用任何 `move_*`。

2026-07-01 18:39 CST 更新：真机右臂第一次单臂极小步运动验证已执行。流程为 `acquire_control()` -> `switch_controller(Controller.servo_control)` -> `move_end_pose(x + 0.001m)` -> `switch_controller(Controller.idle)` -> `release_control()`；`move_end_pose` 返回 `True`。即时读数约为 `xyz=(0.3105,-0.0097,0.3206)`，相对起点约 `1.14mm`；释放并稳定后读数为 `xyz=(0.3140,-0.0061,0.3248)`、`xyzw=(0.0405,0.0100,-0.0131,0.9990)`，相对起点约 `7mm`。SDK 后端确认 SERVO 分支实际调用 `CallServoPoseCommand`，`velocity_scaling_factor` / `acceleration_scaling_factor` 不参与该分支；速度来自 `set_arm_speed()` 缓存，电流阈值来自 `options.eff`。本次测试未显式设置 `set_arm_speed()` / `eff`，因此结论是链路已能真实运动，但在改测试脚本和 adapter 安全壳前，不继续做 EEF、双臂或 policy chunk。

2026-07-01 19:02 CST 更新：已新增受保护复测脚本 `examples/airbot/p7_guarded_servo_step.py`，默认 dry-run，不加 `--execute` 不会 `acquire_control()`、不切控制器、不发运动。脚本显式设置 `set_arm_speed([0.55]*7)`（SDK 允许的最低速度附近）、`CartesianMoveOptions(eff=[8]*7, blocking=True)`，并加入预采样漂移、即时位移、最终稳定位移 guard。dry-run 通过：`IDLE/idle/valid`、预采样漂移 `0`。随后执行 `x + 0.0002m` 真机复测：`lease_id=3`，`move_end_pose=True`，即时位移 `0.001498m`（低于 `0.0015m` guard，但贴边），最终稳定后位移 `0.000290m`，`post_drift=0.000013m`，最终状态 `IDLE/idle`，脚本退出码 `0`。结论：安全壳和最小速度/eff 参数有效，但 SERVO 运动中即时 pose 仍可能显著大于 0.2mm 目标；下一步不要直接扩大到 policy chunk，应先把该 guarded 流程沉淀成正式 adapter，并保留 per-step guard。

2026-07-01 19:26 CST 更新：已把 guarded 流程沉淀为正式可复用 adapter：`src/openpi/shared/airbot_p7_adapter.py`，并新增 `src/openpi/shared/airbot_p7_adapter_test.py`。adapter 在 import 时不依赖 `arm_p7_sdk`，真实执行时才动态加载 SDK；支持 fake client 测试、dry-run、`GuardedP7Config`、`GuardedMoveResult`、目标平移/旋转限幅、状态检查、预采样漂移 guard、显式 `set_arm_speed()` / `eff`、即时/最终位移 guard、异常后 `idle` / `release_control()`。验证结果：`uv run ruff check src/openpi/shared/airbot_p7_adapter.py src/openpi/shared/airbot_p7_adapter_test.py` 通过；`uv run pytest src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_p7_adapter_test.py` 为 `11 passed`。真实 SDK no-motion smoke 也通过：`.venv-p7-sdk` 连接 `192.168.25.1:50071`，adapter 读取当前 TCP `xyz=(0.314036,-0.005822,0.325609)`，构造 `x+0.0002m` 目标，`execute=False` 返回 `status=dry_run`、`acquired_control=False`、`pre_drift_m=0.0`；未发控制命令。

当前目标路线是 **Arm-P7 SDK gRPC**：

```python
from arm_p7_sdk import AirbotClient

left_client = AirbotClient(host="<robot-ip>", port=50071, backend="grpc")
right_client = AirbotClient(host="<robot-ip>", port=50072, backend="grpc")
```

不走：

- 飞书《二代臂 DDS Route 开发指南》里的 DDS Route RPC；
- 裸 DDS/FSM topic publisher；
- 为 DDS 生成 `arm_msgs` / `FsmDdsRoute.idl` 的路线。

这不改变模型侧 I/O。模型已经训练好，执行前不需要重新定义模型输入，也不需要重训。需要做的是把当前已有的 `DualArmTcpTarget` 适配到 SDK gRPC 控制接口：

| 层 | 当前事实 | 需要处理 |
|---|---|---|
| policy 输入 | 三路 RGB 图像 + prompt + dummy `state=np.zeros(16)` | 继续保持现状；当前 PI05 policy 不消费真实 state 数值 |
| policy 输出 | `(50,32)`，前 14 维有效 | 左右臂各 `TCP-local Δpos(3) + Δrotvec(3) + gripper(1)` |
| 本地转换器 | 已把 relpose action 转为通道无关 `DualArmTcpTarget` | 继续复用，不绑定 DDS |
| SDK 当前 TCP pose | `client.get_end_pose()` 返回 `CartesianPose(position, orientation)` | 作为 relpose 积分的 current TCP pose 来源 |
| SDK TCP target | `client.move_end_pose(CartesianPose(...), options)` | 发送完整目标 TCP pose，不发送 delta |
| SDK 夹爪 | `client.move_eef(pos=[...])` | SDK 公共接口单位是 mm；G2P 已知范围 `[0.0, 95.0]` mm |
| 控制权/状态 | `acquire_control()` / `release_control()`，`switch_controller(Controller.servo_control)` | 控制权空操作已通过；1mm 首测暴露最终位移过大；受保护 0.2mm 复测已通过 guard；正式 `GuardedP7ArmAdapter` 已落地并通过 fake client 单测与真机 no-motion smoke |

## 2. Arm-P7 SDK 文档要点

用户提供的 wiki：

- URL：`https://w79rvfxw83.feishu.cn/wiki/MBJCwnUKTiEZ6ukUMgKcCLnFnBZ`
- 标题：《二代臂Arm-P7-SDK开发指南》
- document_id：`KqomdsMbuoep9hxbMYfc1OGdntg`
- revision：`215`

与当前闭环直接相关的接口：

| 需求 | SDK 接口 | 契约 |
|---|---|---|
| 建连 | `AirbotClient(host, port=50071/50072, backend="grpc")` | `backend="grpc"` 是默认推荐；新版双臂 app 为 left=`50071`、right=`50072`；当前路线明确不用 DDS backend |
| 控制权 | `acquire_control(lease_ms=15000, renew_period_s=5.0)` / `release_control()` | 读状态通常不需要控制权；写控制前需要控制权 |
| 服务状态 | `get_service_state()` | no-motion 首个探测接口之一 |
| 当前 TCP pose | `get_end_pose()` | 返回 `CartesianPose`，position 单位 m，orientation 顺序 `(qx,qy,qz,qw)` |
| 切控制器 | `switch_controller(Controller.servo_control)` 或 `switch_controller(Controller.planning_control)` | SERVO 小步用 `move_end_pose`；新版 planning 精度测试用 `planning_control` |
| 发送 TCP pose | `move_end_pose(pos=CartesianPose(...), options=CartesianMoveOptions(...))` 或 `move_end_pose_linear(start, target, CartesianMoveOptions(...))` | 都发送完整目标 pose，不发送 delta；planning LIN 需要 start 和 target |
| 切夹爪模式 | `switch_eef_control_mode(EEFControlMode.csp)` | 位置控制前切到 csp |
| 发送夹爪 | `move_eef(pos=[...], options=EEFMoveOptions(...))` | 公共 SDK 位置单位是 mm；options 里的字段用 list，不用 tuple |

## 3. 2026-06-30 现场只读检查

本轮没有发布任何控制消息，没有切控制模式，没有移动机械臂或夹爪。

### 3.1 端口检查

命令等价于在本机对两个已知地址探测 SDK 常见端口：

```bash
python -c 'import socket; hosts=["172.100.10.159","192.168.25.1"]; ports=[50071,50051,50052]; print([(h,p,socket.socket().connect_ex((h,p))) for h in hosts for p in ports])'
```

关键结论：

```text
172.100.10.159:50071 refused
172.100.10.159:50051 refused
172.100.10.159:50052 refused
192.168.25.1:50071 timeout
192.168.25.1:50051 timeout
192.168.25.1:50052 timeout
```

影响：当前不能直接用本机 SDK client 连上机械臂 gRPC 服务。

### 3.2 X5 上 SDK / 进程检查

命令：

```bash
ssh root@172.100.10.159 hostname
ssh root@172.100.10.159 date
ssh root@172.100.10.159 "ss -lntp | grep -E '50071|50051|50052|grpc|route'"
ssh root@172.100.10.159 "python3 -c 'import arm_p7_sdk; print(arm_p7_sdk.__file__)'"
```

关键输出：

```text
ubuntu
Tue Jun 30 20:27:04 CST 2026
ss: 未看到 50071/50051/50052 监听
ModuleNotFoundError: No module named 'arm_p7_sdk'
```

影响：当前 X5 上没有可用的 `arm_p7_sdk` Python 包，也没有看到 `arm-grpc-route` / gRPC 端口监听。

### 3.3 本机 SDK 检查

命令：

```bash
python -c 'import arm_p7_sdk; print(arm_p7_sdk.__file__)'
```

关键输出：

```text
ModuleNotFoundError: No module named 'arm_p7_sdk'
```

影响：本机也还不能运行目标 SDK client；P0 是安装/确认 SDK wheel，而不是继续补 DDS 类型。

## 4. 执行适配器应做什么

本地已实现并测试的 `src/openpi/shared/airbot_relpose.py` 输出是通道无关的 `DualArmTcpTarget`。SDK 适配层只做最后一跳：

1. `client.get_end_pose()` 读取左右臂当前 TCP pose，得到 `[x,y,z,qx,qy,qz,qw]`。
2. `convert_action_step()` / `convert_action_chunk()` 把模型 relpose 积分成绝对目标 TCP pose。
3. 用 SDK 构造 `CartesianPose(position=[x,y,z], orientation=[qx,qy,qz,qw])`。
4. 控制前获取控制权：`acquire_control(...)`。
5. 切到末端 servo：`switch_controller(Controller.servo_control)`。
6. 低速、限幅后调用 `move_end_pose(...)`。
7. 夹爪模型值 `g in [0,100]` 转为 SDK mm 后调用 `move_eef(pos=[...])`。
8. 异常和结束时 `release_control()`。

夹爪当前应按 SDK 文档和实际 EEF 型号处理：

- 模型语义不变：闭合 = 0，最大打开 = 100。
- SDK 公共接口单位是 mm。
- wiki 已知 G2P 范围是 `[0.0, 95.0]` mm；历史配置里出现过 `0.096 m`，写适配器时不要把 DDS/FSM 的米制字段直接混入 SDK 调用。
- 推荐适配器支持从 SDK 的 EEF 信息或配置读取最大行程，默认再落到 `95.0 mm` 或显式参数。

## 5. 启动真机前还缺什么

P0：

1. 在运行 SDK client 的机器上安装/确认 `arm_p7_sdk`：**本机已完成**，独立环境为 `.venv-p7-sdk`，当前 `arm-p7-sdk=1.1.2`。
2. 在 X5/机器人板端拉起 Arm-P7 gRPC route：历史上 `robot_app 0.3.5` 做过右臂最小验证；当前正式入口改为 `/root/start-arm-dual-app-2arm.sh`，一次启动 `arm_dual_app left_arm/right_arm` 与 `robot_app remote only`。目标端口为 left `50071`、right `50072`；旧 `robot_app left_arm/right_arm` 不应再同时运行。
3. 确认 robot IP / port：有线 `192.168.25.1` 是当前主入口；新版 `arm_dual_app` 启动后应检查 left `50071`、right `50072`。无线 `172.100.10.159` 仍只作管理备用。
4. 本机模拟器 smoke test：amd64 `robot_app 0.1.0` 已完成 mock no-motion 和写接口 smoke test；它只能验证接口和 adapter，不能替代真机。
5. 真机 no-motion SDK 读检查：历史 staged `robot_app 0.3.5` 单臂检查已完成；新版统一 runtime 下左右臂 no-motion dry-run 已完成，左右臂均为 `IDLE/idle/valid`，可读 TCP pose。
6. 加安全壳：单步限幅、速度限制、控制频率、超时、异常释放控制权、人工急停确认。
7. 下一验证顺序：保持 [openpi-airbot-runbook.md](openpi-airbot-runbook.md) §1A 的统一 runtime，先用三路相机 observation 请求 OpenPI policy，再把 action JSON 接入 `examples/airbot/policy_to_p7_sdk_bridge.py` 做 SDK target dry-run；真实运动前仍要先做小步 guarded/probe 验证。历史 guarded servo adapter 仍可做单臂小步 smoke。

非 P0 / 暂不做：

- 不生成 DDS Route RPC 客户端。
- 不写裸 DDS/FSM publisher。
- 不把 `/arm/*/fsm/servo_pose_command` 作为当前主线。
- 不把固定手眼外参引入默认执行路径；训练和执行默认都是 TCP pose 闭环。

## 6. 2026-07-20 16:43 CST — `set_arm_speed()` 下限来源与准确性复核

目的：追溯“SDK 的 `set_arm_speed()` 下限约为 `0.55 rad/s`”的来源，并区分
SDK 参数校验、servo scale 和机器人实际运动速度。本轮只读取本机 SDK 与已有真机
记录，未连接机器人、未获取控制权、未发送运动命令。

版本与源码检查命令：

```bash
.venv-p7-sdk/bin/python -c \
  'import importlib.metadata as m; print(m.version("arm-p7-sdk"))'
rg -n -uu '_MIN_PHYS_SPD|def set_arm_speed' \
  .venv-p7-sdk/lib/python3.11/site-packages/arm_p7_sdk
sed -n '200,218p' \
  .venv-p7-sdk/lib/python3.11/site-packages/arm_p7_sdk/_backends/base.py
.venv-p7-sdk/bin/python -c \
  'from arm_p7_sdk.models import _MIN_PHYS_SPD; print(f"{_MIN_PHYS_SPD:.15f}")'
```

关键输出与代码事实：

```text
arm-p7-sdk version: 1.1.2
_MIN_PHYS_SPD = 0.17507044 * math.pi - 1e-4
min = 0.549900008164733 rad/s
```

`BaseBackend.set_arm_speed()` 先要求列表长度等于 7，再逐项执行：

```python
if speed > _MAX_PHYS_SPD or speed < _MIN_PHYS_SPD:
    return False
```

所以精确边界是闭区间：`0.549900008164733` 可接受，比它小的值会在客户端直接
返回 `False`；常用的 `0.55` 仅比下限高约 `0.000099992 rad/s`。gRPC 和 DDS
后端的 `set_arm_speed()` 都先调用这个基类校验，因此该结论对 SDK 1.1.2 的两种
backend 均成立。

已有真机证据来自 2026-07-08 的双臂连续 servo smoke：初次用
`--arm-speed-rad-s 0.35` 时，SDK 在进入运动阶段前拒绝并打印：

```text
Max speed must not higher than max speed 7.854981633974483 and no less than 0.5499000081647326
```

随后改为 `[0.55] * 7`，`set_arm_speed()` 返回 `True`。更早的 2026-07-01
guarded 0.2 mm 真机复测也记录了：

```text
[CLIENT] Set arm speed to [0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55]
set_arm_speed True
[CLIENT] Updated servo scale to: [0.5, 0.5, 0.07002906659820268]
```

准确表述应为：**`arm-p7-sdk 1.1.2` 的 `set_arm_speed()` 客户端逐关节参数
校验下限为 `0.549900008164733 rad/s`，工程参数可写成 `0.55 rad/s`。** 这不是
机械臂物理最低转速，也不是 TCP 实际速度下限。gRPC servo 后端会用 7 轴速度绝对
值的平均值计算 joint scale；`[0.55] * 7` 得到约 `0.07003`。目标轨迹仍可通过
更小的位置增量与发送频率做到低于 `0.55 rad/s` 的命令斜率，例如 20 秒周期的
joint6 三角波使用可接受的 `0.55 rad/s` speed limit，但位置目标斜率只有
`0.1 rad/s`。

影响：现有脚本默认 `--arm-speed-rad-s 0.55` 对当前 SDK 是正确的最低档工程值；
不应把它描述成机器人必须达到的实际速度。SDK 升级后必须重新读取
`_MIN_PHYS_SPD` 和 `set_arm_speed()` 校验逻辑，不能假定该常数永久不变。

### 6.1 2026-07-20 16:49 CST — 单位交叉核验

针对“是否其实是度/秒”的疑问，继续核对 SDK 1.1.2 wheel 内互相独立的定义和
数据路径，结果均指向 `rad/s`：

1. `models.py` 明确写明 `ArmJointState.angles` 为 radians、
   `ArmJointState.velocities` 为 radians per second。
2. 同文件把 `_MIN_PHYS_SPD` 和 `_MAX_PHYS_SPD` 分别标为 `rad/s`；数值写法是
   `0.17507044 * pi - 1e-4` 和 `2.5 * pi + 1e-3`。
3. gRPC 后端把 `_MAX_SERVO_JOINT_VEL = 2.5 * pi - 1e-4` 标为 `rad/s`，并用
   `set_arm_speed()` 输入除以这个同单位基准得到无量纲 joint scale。
4. `move_joint()` 的 servo 分支把缓存的 `_arm_motor_speed` 原样放入
   `ServoJointCommandRequest.vel`；中间没有 `degrees()`、`radians()` 或乘除
   `180/pi` 的转换。
5. SDK 自带 SERVO 示例使用 `spd = math.pi / 3`，record/replay 示例使用
   `math.pi * 2`；这与弧度制 API 一致。
6. 落地的《二代臂Arm-P7-SDK开发指南》单位表也明确列出 arm joint position 为
   `rad`、arm joint speed / velocity 为 `rad/s`，同时把 EEF 速度另列为 `mm/s`。

因此 `set_arm_speed([0.55] * 7)` 中的 `0.55` 应解释为
`0.55 rad/s = 31.5127 deg/s`，不是 `0.55 deg/s`。仍需保留前述限定：在 gRPC
Cartesian servo 路径里该值主要用于换算 joint scale，所以它是关节速度限制参数的
单位，不保证实测关节会恰好达到 `31.5 deg/s`。

### 6.2 2026-07-20 16:52 CST — 该值对应关节还是电机转子

SDK 公共接口对 `set_arm_speed(arm_speed)` 的定义是 “one speed limit for each
arm joint / per-joint speed limits”。当前 `arm_dof=7`，因此参数必须是：

```text
[J1_limit, J2_limit, J3_limit, J4_limit, J5_limit, J6_limit, J7_limit]
```

现有代码调用 `[0.55] * 7` 的含义是给 7 个关节轴分别设置相同的
`0.55 rad/s` 关节侧速度限制，不是 7 个关节速度的总和，也不表示 7 个关节都会以
这个速度运动。哪些关节实际运动、各自实际速度是多少，取决于目标关节角或笛卡尔
目标经过 IK/servo 后的轨迹；静止关节的实际速度仍可为 0。

gRPC 源码中的两条实际数据路径是：

- `servo_control + move_joint()`：把完整 7 轴目标角 `pos` 和缓存的 7 项速度列表分别
  写入 `ServoJointCommandRequest.pos` / `.vel`。
- `servo_control + move_end_pose()`：把 TCP pose 与同一 7 项列表写入
  `ServoPoseCommandRequest.pose` / `.velocity`；`set_arm_speed()` 还会用 7 项绝对值
  的平均数除以最大关节速度，更新一个全局 joint scale。`[0.55] * 7` 对应约
  `0.07003`。

所以对当前 OpenPI 使用的 `servo_control + move_end_pose()`，准确说法是：它是
**关节空间速度限制/servo scale 的输入**，不是 TCP 平移速度 `m/s`，也不是 TCP
旋转速度，更不是某一个电机转子的原始转速或 RPM。

SDK 内部缓存变量虽然命名为 `_arm_motor_speed`，但公共契约、7 维 `arm_dof`、
关节角/关节速度模型和请求字段都使用关节坐标。SDK 中没有减速比、转子 RPM 或
joint-to-motor 转换逻辑；电机转子经过减速器后的内部速度如何计算和限制属于板端
控制器/固件实现。`0.55 rad/s` 若只换算关节输出轴单位，相当于约
`31.51 deg/s = 5.25 rpm`；若减速比为 `N`，转子速度通常会与关节侧速度相差约
`N` 倍，但不能在不知道各关节减速比和固件定义时从 `0.55` 推出电机原始转速。

实际瞬时关节速度应读取 `get_arm_joint_state().velocities` 并记录，而不能把
`set_arm_speed()` 的值当成实测速度。另一个边界是 `planning_control`：其
`move_joint()` / `move_end_pose()` 请求使用 `velocity_scaling_factor`，不读取
`_arm_motor_speed`，所以 `set_arm_speed()` 的上述语义主要针对 servo/MIT 等直接
控制路径。

## 7. 2026-07-21 13:19 CST — gRPC 概念与当前控制调用链复核

检查人：agent（Codex）。目的：回答“gRPC 是什么、当前如何用 gRPC 控制机械臂”，并避免把
旧 `airbot_play` 关节接口与当前 Arm-P7 SDK 路线混在一起。本轮只读仓库代码和文档，没有连接
机器人、获取控制权或发送运动命令。

复核命令：

```bash
rg -n "grpc|AirbotClient|acquire_control|switch_controller|move_end_pose|move_joint|move_eef" \
  examples/airbot src/openpi/shared docs
nl -ba examples/airbot/policy_to_p7_sdk_bridge.py | sed -n '235,380p'
nl -ba examples/airbot/p7_guarded_servo_step.py | sed -n '130,215p'
rg -n "AirbotClient|get_end_pose|acquire_control|switch_controller|move_end_pose|move_eef|release_control" \
  examples/airbot/openpi_p7_persistent_loop.py
```

结论：gRPC 是基于 HTTP/2、以 protobuf 定义服务和消息的远程过程调用机制。对调用方来说，
`AirbotClient` 暴露的是普通 Python 方法；SDK 在内部把方法参数序列化为 gRPC 请求，发到 X5
的 `arm_dual_app`，板端再调用状态机、IK/servo 和电机控制栈。它是控制命令和状态查询的网络
传输/API 层，不是控制算法本身，也不是 OpenPI policy 的 `:8000` WebSocket。

当前双臂连接为 `192.168.25.1:50071`（SDK 配置名 left）和 `:50072`（SDK 配置名 right）。
实际写控制的顺序是：

1. `get_service_state()` 检查 `IDLE/idle/valid`，`get_end_pose()` 读取当前 TCP pose。
2. OpenPI 的 14 维有效 action 按每臂 `TCP-local delta position(3) + delta rotvec(3) + gripper(1)`
   解释，并结合当前 pose 换算成绝对 `CartesianPose`；不能把这 14 维直接当关节角。
3. `acquire_control()` 获取带续租的控制权，切 `Controller.servo_control`，设置 7 关节速度限制。
4. `move_end_pose(absolute_pose, CartesianMoveOptions(...))` 发送绝对末端目标；X5 内部负责 IK 和
   关节伺服。双臂桥接使用 `blocking=False` 并发下发；单步 guarded smoke 使用 `blocking=True`。
5. 启用夹爪时，切 `EEFControlMode.csp`，将模型 `0..100` 映射并限幅为 `0..95 mm`，调用
   `move_eef()`。
6. 无论成功或异常，最后切回 `Controller.idle`、`release_control()` 并关闭 client。

另有直接关节控制脚本使用 `get_arm_joint_state()` + `move_joint(7D target)`，但当前 relpose
checkpoint 的常规执行主线是 `get_end_pose()` + `move_end_pose()`。`play_operator.py` 中旧的
`airbot_play` gRPC 端口和 6 关节加夹爪 action 属于另一套历史客户端契约，不应与当前 P7
`50071/50072`、7 轴和 relpose 执行链路混用。现场还观察过 SDK 配置名与物理左右相反，执行前
必须按端口再次确认物理侧。

生产持续推理入口 `openpi_p7_persistent_loop.py` 也采用同一 gRPC 调用链：连接双臂、获取控制权、
切 servo、设置速度后，将每个 policy 目标插值/限幅成 waypoint，以 `blocking=False` 并行调用
`move_end_pose()`；退出清理时切 idle、释放 control lease、回读最终服务状态。这里的
“持续推理”只是重复执行有安全边界的 RPC，并未改变 gRPC 和板端控制器的职责分界。

文档写入后执行 `git diff --check -- docs/p7-sdk-grpc-current-state.md docs/CHECKLOG.md`，退出码为
`0`，未发现空白符错误。
