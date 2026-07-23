# 本机 amd64 robot_app 模拟器使用记录

日期：2026-07-01 14:15 CST；检查人：agent。
目的：确认用户安装的 `robot_app_0.1.0_20260629175035_amd64.deb` 是否能在本机规避真机，用于 Arm-P7 SDK gRPC 接口和转换器 smoke test。

## 1. 结论

这个包可以作为 **本机 mock robot_app / gRPC 接口模拟器** 使用，用来验证：

- `arm_p7_sdk` client 能否连通 gRPC；
- `get_service_state()`、`get_end_pose()`、`get_arm_joint_state()`、`get_eef_joint_state()` 这些 no-motion 读接口；
- 本地 `DualArmTcpTarget -> Arm-P7 SDK` 适配器的类型、字段、单位、端口和生命周期逻辑。

它不能替代最终真机验证：

- 没有真实三路相机；
- 没有真实机械臂、电机、急停、碰撞和执行延迟；
- 不能证明 X5/机器人侧 `robot_app_0.3.5` 已部署；
- 不能证明真实网络链路和控制权切换没有问题。

## 2. 安装和直接启动

用户已在 amd64 PC 上安装：

```bash
sudo dpkg -i robot_app_0.1.0_20260629175035_amd64.deb
```

本机检查结果：

```text
Package: robot_app
Architecture: amd64
Version: 0.1.0
```

包安装到 `/opt/robot_app`，关键文件：

```text
/opt/robot_app/bin/robot_app
/opt/robot_app/lib/libarm_grpc_route.so
/opt/robot_app/lib/libarm_finite_state_machine.so
/opt/robot_app/lib/libarm_motion_planning.so
/opt/robot_app/configs/framework_config.json
/opt/robot_app/share/assets/p7_arm/urdf/p7c_arm_umi_gripper.urdf
```

供应商给出的直接启动方式：

```bash
/opt/robot_app/bin/robot_app
```

本机普通用户直接执行时，进程会使用默认存储路径 `/userdata/storage`。如果该目录不可写，会失败：

```text
Using default base path: /userdata/storage
Error creating directory /userdata/storage/robot_app: Permission denied
Failed to initialize storage manager
```

因此直接启动需要满足二选一：

- 让当前用户可写 `/userdata/storage`；
- 或者用临时配置把 storage 改到 `/tmp`，推荐用于本仓库 smoke test。

## 3. 推荐 smoke test 启动方式

推荐不改 `/opt/robot_app` 原配置，而是复制一份临时配置：

```bash
mkdir -p /tmp/openpi_robot_app_sim
cp -a /opt/robot_app/configs /tmp/openpi_robot_app_sim/configs
python3 -c "import json, pathlib; base=pathlib.Path('/tmp/openpi_robot_app_sim'); p=base/'configs/storage_config.json'; data=json.loads(p.read_text()); data['base_path']='/tmp/openpi_robot_app_storage'; p.write_text(json.dumps(data, indent=2)+'\n'); (base/'project_config.json').write_text(json.dumps({'type':'release','release':[{'library_path':'/opt/robot_app/lib','configs_path':'/tmp/openpi_robot_app_sim/configs'}]}, indent=2)+'\n')"
```

启动：

```bash
/opt/robot_app/bin/robot_app /tmp/openpi_robot_app_sim/project_config.json
```

关键日志应出现：

```text
Airbot P7 control service started, version=0.1.0, build Jun 29 2026 17:51:16
Created node: mock_arm_control_node
Created node: grpc_route_node
Initializing node: grpc_route_node#none;50071
Framework started successfully
framework running... Ctrl+C to stop
```

停止：在该终端按 `Ctrl+C`。

## 4. gRPC host/port 约定

服务端固定端口：`50071`。

`framework_config.json` 里 gRPC route 节点是：

```json
"name": "grpc_route_node",
"user_param": "none;50071"
```

实测启动后监听：

```text
*:50071 users:(("robot_app",pid=183568,fd=30))
```

含义：

- 服务端 bind 到所有网卡，也就是等价于 `0.0.0.0:50071`；
- 同机 SDK smoke test 连接 `127.0.0.1:50071`；
- 其他机器连接这台 PC 时，用这台 PC 的实际 LAN IP 和 `50071`；
- `0.0.0.0` 是服务端监听地址，不建议作为 SDK client 的远端目标地址。

SDK client 示例：

```python
from arm_p7_sdk import AirbotClient

client = AirbotClient(host="127.0.0.1", port=50071, backend="grpc")
```

## 5. 只读验证结果

端口检查：

```bash
ss -lntp
```

关键输出：

```text
LISTEN 0 4096 *:50071 *:* users:(("robot_app",pid=183568,fd=30))
```

SDK 只读检查命令：

```bash
.venv-p7-sdk/bin/python -c "from arm_p7_sdk import AirbotClient; c=AirbotClient(host='127.0.0.1', port=50071, backend='grpc'); print('client_id', c.get_client_id); print('service_state', c.get_service_state()); print('end_pose', c.get_end_pose()); print('arm_joint_state', c.get_arm_joint_state()); print('eef_joint_state', c.get_eef_joint_state()); c.close()"
```

关键输出：

```text
client_id discover-183854-8875c067023c450889b842ff2b20dbf6
service_state ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
end_pose CartesianPose(xyz=(0.3089, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))
arm_joint_state ArmJointState(angles=(0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000), velocities=(0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000), efforts=(0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000))
eef_joint_state EEFJointState(eef_pos=(0.0000), eef_vel=(0.0000), eef_eff=(0.0000))
```

本次只调用了读接口，没有调用 `acquire_control()`、`move_end_pose()`、`move_eef()` 或任何运动/控制接口。

## 6. 对当前开发的影响

可以先在本机完成：

1. 启动 policy server，使用 mock 图像/或录制图像得到 `(50,32)` action。
2. 转换器取前 14 维，生成 `DualArmTcpTarget`。
3. SDK adapter 把 `DualArmTcpTarget` 转成 `CartesianPose` 和 `move_eef` 参数。
4. 在模拟器上先做 no-motion 读状态，再做受限的接口级 smoke test。

仍然不能跳过：

1. 真机 X5 部署/启动 `robot_app_0.3.5`。
2. 真实 `50071` gRPC 链路 no-motion 读状态。
3. 真实控制权、低速极小步、急停和安全壳验证。

## 7. 2026-07-01 15:28 CST 用户前台启动后的连通验证

目的：用户确认已执行 `/opt/robot_app/bin/robot_app` 后，验证 agent 是否能从另一个终端看到并连接本机模拟器。

进程检查：

```bash
pgrep -af robot_app
```

关键输出：

```text
193072 sudo /opt/robot_app/bin/robot_app
193073 sudo /opt/robot_app/bin/robot_app
193074 /opt/robot_app/bin/robot_app
```

端口检查：

```bash
ss -lntp
```

关键输出：

```text
LISTEN 0 4096 *:50071 *:*
```

结论：用户启动的本机 `robot_app` 对 agent 可见，且 `50071` 正在监听所有网卡，等价于服务端 bind `0.0.0.0:50071`。

SDK 只读验证命令：

```bash
timeout 10 .venv-p7-sdk/bin/python -c "from arm_p7_sdk import AirbotClient; c=AirbotClient(host='127.0.0.1', port=50071, backend='grpc'); print('client_id', c.get_client_id); print('service_state', c.get_service_state()); print('end_pose', c.get_end_pose()); print('arm_joint_state', c.get_arm_joint_state()); print('eef_joint_state', c.get_eef_joint_state()); c.close()"
```

关键输出：

```text
service_state ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
end_pose CartesianPose(xyz=(0.3089, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))
arm_joint_state ArmJointState(angles=(0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000), velocities=(0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000), efforts=(0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000))
eef_joint_state EEFJointState(eef_pos=(0.0000), eef_vel=(0.0000), eef_eff=(0.0000))
```

本次只调用 SDK 读接口，没有调用 `acquire_control()`、`move_end_pose()`、`move_eef()` 或任何运动/控制接口。


## 8. 2026-07-01 15:36 CST DDS domain / monitor 参数确认

目的：用户提供供应商提示“运行 `/opt/robot_app/bin/arm_fsm_monitor --domain XX`，XX 从 `robot_app` 启动日志第 4 行看”，确认当前本机 amd64 `robot_app` 应填的 `XX`。

已有文档证据：

```bash
rg -n "domain" docs AGENTS.md
```

关键输出：

```text
docs/direct-dds-control.md:278:grep domain_id /opt/robot_app/configs/remote/framework_config.json       # 0
docs/CHECKLOG.md:78:- ... FastDDS 2.6.10 ... domain_id=0 ...
```

本机实际配置检查：

```bash
rg -n "domain|domain_id|dds|50071|grpc" /opt/robot_app/configs
sed -n '1,24p' /opt/robot_app/configs/framework_config.json
sed -n '70,82p' /opt/robot_app/configs/framework_config.json
```

关键输出：

```text
/opt/robot_app/configs/framework_config.json:2:  "dds": {
/opt/robot_app/configs/framework_config.json:79:          "user_param": "none;50071",

"dds": {
  "participant_name": "cora_framework",
  "use_shared_memory": true,
  "shm_segment_size": 134217728,
  "use_udp": true,
  "callback_threads": 4
}
```

当前进程和端口检查：

```bash
pgrep -af robot_app
ss -lntp
```

关键输出：

```text
193072 sudo /opt/robot_app/bin/robot_app
193073 sudo /opt/robot_app/bin/robot_app
193074 /opt/robot_app/bin/robot_app
LISTEN 0 4096 *:50071 *:*
```

monitor 短跑验证：

```bash
timeout 6 /opt/robot_app/bin/arm_fsm_monitor --domain 0
```

关键输出：

```text
[INFO][framework] DDSParticipant initialized on domain 0 with name 'fsm_topic_monitor_v2'
FSM Monitor ...
fsm_mode=none arm_control_mode=none hw=none
```

结论：当前本机 amd64 `robot_app` 的 monitor 参数填 **`0`**：

```bash
/opt/robot_app/bin/arm_fsm_monitor --domain 0
```

影响：`framework_config.json` 没有显式 `domain_id`，本机这包使用默认 DDS domain 0；这与此前 X5/直连 DDS 记录的 `domain_id=0` 一致。monitor 这次只读启动 6 秒，没有调用任何控制权或运动接口。

## 8. 2026-07-01 15:41 CST SDK adapter / 写接口 smoke test

目的：在用户已启动的本机 amd64 `robot_app` 模拟器上，验证 relpose 转换器到 Arm-P7 SDK 参数的 dry-run，以及 SDK 控制权和写接口调用链。此测试只连接 `127.0.0.1:50071`，没有连接真机。

### 8.1 依赖补充

`.venv-p7-sdk` 最初只有 SDK 依赖，运行本仓库 `openpi.shared.airbot_relpose` 时缺少 `numpy`：

```text
ModuleNotFoundError: No module named 'numpy'
```

已单独安装到 SDK 测试环境，不污染 OpenPI 推理 `.venv`：

```bash
uv pip install --python .venv-p7-sdk/bin/python numpy
```

关键输出：

```text
Using Python 3.11.15 environment at: .venv-p7-sdk
Installed 1 package
+ numpy==2.4.6
```

### 8.2 action -> relpose -> SDK 参数 dry-run

命令逻辑：读取模拟器当前 `get_end_pose()`，构造 32 维 mock action：左臂 `+1mm local x`、夹爪 `50`；右臂 `-1mm local x`、夹爪 `100`；调用 `convert_action_step()`，再构造 SDK `CartesianPose` / options，只打印，不调用 move。

关键输出：

```text
service_state ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
current_end_pose CartesianPose(xyz=(0.3089, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))
left sdk_cart_pose CartesianPose(xyz=(0.3099, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))
left gripper_model 50.0 p7_mm 48.0
right sdk_cart_pose CartesianPose(xyz=(0.3079, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))
right gripper_model 100.0 p7_mm 96.0
```

结论：转换链路能把 `(50,32)`/32 维 action 的前 14 维映射成 SDK 可接收的 `CartesianPose(position, orientation)` 和夹爪 mm 参数。本机模拟器是 `side=none` 单服务，dry-run 中左右臂使用同一个 mock TCP pose；真机双臂仍需要分别绑定真实 left/right 服务或 route 语义。

### 8.3 模拟器写接口 smoke test

只在本机模拟器上执行以下控制链：

```text
acquire_control -> switch_controller(servo_control) -> move_end_pose(+1mm) -> switch_eef_control_mode(csp) -> move_eef(1mm) -> switch_controller(idle) -> release_control
```

关键输出：

```text
before_service_state ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
before_end_pose CartesianPose(xyz=(0.3089, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))
before_eef_state EEFJointState(eef_pos=(0.0000), eef_vel=(0.0000), eef_eff=(0.0000))
acquire_control True
switch_controller_servo True
move_end_pose_plus_1mm True CartesianPose(xyz=(0.3099, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, -0.0000, 1.0000))
switch_eef_csp True
move_eef_1mm True
after_end_pose CartesianPose(xyz=(0.3100, 0.0000, 0.3246), xyzw=(0.0000, 0.0000, 0.0001, 1.0000))
after_eef_state EEFJointState(eef_pos=(0.0000), eef_vel=(0.0000), eef_eff=(0.0000))
switch_controller_idle True
release_control done
```

随后清理 EEF/control 模式：

```text
before_cleanup_state ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
acquire_control True
switch_eef_idle True
switch_controller_idle True
release_control done
after_cleanup_state ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
```

结论：本机 mock 上 SDK 写接口调用链可用，`move_end_pose(+1mm)` 返回成功并让 mock pose 发生了约 1mm 变化；`move_eef(1mm)` 返回成功，但 mock 的 `eef_joint_state` 仍显示 0，说明该模拟器不一定模拟 EEF 反馈变化，不能据此判断真实夹爪反馈行为。

### 8.4 边界

本测试证明的是：

- SDK client 能连接本机 `0.0.0.0:50071` / `127.0.0.1:50071`；
- 控制权、模式切换、末端 pose 写接口、EEF 写接口在 mock 服务上能跑通；
- relpose 转换器输出能构造成 SDK 数据类型。

本测试不能证明：

- 真机 X5 侧 `robot_app_0.3.5` 已部署；
- 真实双臂 left/right route 语义；
- 真实机械臂坐标系、速度、碰撞、安全边界；
- 真实夹爪 EEF feedback 会按 mock 一样返回。
