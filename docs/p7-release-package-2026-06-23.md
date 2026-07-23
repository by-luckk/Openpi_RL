# AIRBOT-ARM-P7-SW-2026-06-23 软件包核对

日期：2026-07-01 11:35 CST；检查人：agent。
目的：核对用户从飞书拿到的 `docs/AIRBOT-ARM-P7-SW-2026-06-23-21-16-24/` 是否就是当前 Arm-P7 SDK gRPC 路线需要安装的软件包。

## 1. 结论

这是我们需要的软件包，但要分清装在哪里：

| 包内组件 | 路径 | 装在哪里 | 是否需要 | 作用 |
|---|---|---|---|---|
| `arm_p7_sdk-1.1.1-py3-none-any.whl` | `components/sdk_client/` | 运行机器人客户端的机器（本机/工作站/未来机器人客户端环境） | **需要** | 提供 `AirbotClient(..., backend="grpc")`、`get_end_pose()`、`move_end_pose()`、`move_eef()` |
| `robot_app_0.3.5_20260623131126_arm64.deb` | `components/arm_p7/` | X5 / 机器人板端（aarch64） | **需要** | 包含 `arm_grpc_route`、`libarm_grpc_route.so`，配置端口 `50071` |
| `robot_ota_app_0.2.0_20260623131231_arm64.deb` | `components/arm_p7/` | X5 / 机器人板端 | 可能需要 | OTA/机器人管理应用升级；是否必须取决于升级流程 |
| `sdk-board-bundle-arm_p7_sdk-1.1.1...tar.gz` | `components/sdk_client/` | X5 / aarch64 Python 3.10 | 可选 | 只在需要在 X5 上直接运行 Python SDK/例程时安装；本机 gRPC 客户端不依赖它 |

关键修正：**X5 上 `import arm_p7_sdk` 失败不等于 gRPC 路线不可用**。如果我们在本机跑 SDK client，X5 不需要 Python SDK；X5 必须有的是新 `robot_app` 中的 `arm_grpc_route` 服务并监听 `50071`。

当前现场没有覆盖安装 `/opt/robot_app`：机器人仍保留旧的 `remote + left_arm + right_arm` 多进程结构和完整备份。2026-07-01 18:18 CST 已按用户确认停止旧 `right_arm`，复位 `can0`，用隔离目录启动 `robot_app_0.3.5` 接管右臂并开放 `50071`；本机 SDK no-motion 只读验证已通过。X5 Python 仍不需要安装 `arm_p7_sdk`，因为 SDK client 在本机运行。

## 2. 包内容与完整性

命令：

```bash
find docs/AIRBOT-ARM-P7-SW-2026-06-23-21-16-24 -maxdepth 3 -type f -o -type d
sha256sum -c manifest/checksums.sha256
```

关键输出：

```text
components/sdk_client/arm_p7_sdk-1.1.1-py3-none-any.whl
components/sdk_client/arm_p7_sdk-1.1.1.tar.gz
components/sdk_client/sdk-board-bundle-arm_p7_sdk-1.1.1-py3-none-any-20260623131454.tar.gz
components/arm_p7/robot_app_0.3.5_20260623131126_arm64.deb
components/arm_p7/robot_ota_app_0.2.0_20260623131231_arm64.deb
...
all checksums: OK
```

`docs/release_notes.md` 说明这是 `airbot-p7` release：

```text
sdk_client p7-v1.1.1 commit 01d146787014
arm_p7 release-2026-6-23 commit 2e4ac4ea336c
```

## 3. SDK wheel 核对

命令：

```bash
python3 -c '用 zipfile 读取 arm_p7_sdk-1.1.1-py3-none-any.whl 的 METADATA / entry_points / 源码关键字'
```

关键事实：

```text
Name: arm-p7-sdk
Version: 1.1.1
Requires-Python: >=3.9
Requires-Dist: grpcio>=1.76.0, protobuf>=4.21, typer>=0.9, loguru>=0.7.3
console_scripts: arm-p7-sdk = arm_p7_sdk.cli:main
AirbotClient(host='localhost', port=50071, backend='grpc', ...)
```

SDK 源码确认默认就是 `port=50071`、`backend="grpc"`。关键 API 包括：

```text
get_service_state()
get_end_pose()
move_end_pose()
move_eef()
acquire_control()
release_control()
switch_controller()
switch_eef_control_mode()
```

本机当前 OpenPI `.venv` 不能直接从 wheel 导入 SDK，原因是 protobuf runtime 太旧：

```text
protobuf dist 4.25.8
grpcio dist 1.81.1
ImportError: cannot import name 'runtime_version' from 'google.protobuf'
```

SDK 内部生成的 `fsm_service_v2_pb2.py` 标注：

```text
Protobuf Python Version: 6.33.5
from google.protobuf import runtime_version as _runtime_version
```

影响：不要直接把 SDK 装进当前 OpenPI 推理 `.venv` 并随意升级 protobuf；更稳妥是给机器人客户端建独立 venv，安装 `arm_p7_sdk 1.1.1` 和 `protobuf>=6.33.5`。

## 4. 板端 deb 核对

命令：

```bash
dpkg-deb -I components/arm_p7/robot_app_0.3.5_20260623131126_arm64.deb
dpkg-deb -x components/arm_p7/robot_app_0.3.5_20260623131126_arm64.deb /tmp/openpi_p7_robot_app_extract
rg -n "50071|grpc|route" /tmp/openpi_p7_robot_app_extract/opt/robot_app/configs
```

关键输出：

```text
Package: robot_app
Version: 0.3.5
Architecture: arm64
```

`framework_config.json` 关键段：

```json
{
  "name": "arm_grpc_route",
  "path": "libarm_grpc_route.so",
  "nodes": [
    {
      "name": "grpc_route_node",
      "type": "airbot::apps::GrpcRouteNode",
      "executor": "grpc_route_executor",
      "user_param": "none;50071",
      "interval_ms": 4
    }
  ]
}
```

这说明 `robot_app_0.3.5` 正是机器人侧 gRPC route 服务包。它也包含 `arm_dds_route`，但当前路线不使用 DDS。

`postinst` 只做基础环境配置：

```text
chmod +x /opt/robot_app/bin/*
把 /opt/robot_app/bin 加到 PATH
把 /opt/robot_app/lib 写入 ld.so.conf.d 并 ldconfig
```

没有在 postinst 里看到直接启动/重启机器人服务的逻辑；实际部署后仍需要按机器人侧启动流程重启/拉起 `robot_app`。

## 5. board bundle 核对

命令：

```bash
python3 -c '用 tarfile 查看 sdk-board-bundle...tar.gz 的文件清单和 install.sh'
```

关键事实：

```text
install.sh 要求 aarch64/arm64 + Python 3.10.x
wheelhouse 含 arm_p7_sdk-1.1.1、cora-1.2.2 aarch64、grpcio aarch64、protobuf-7.35.1 等
安装方式是 --no-index --find-links wheelhouse，写入系统 Python，并运行 smoke_test.py
```

用途判断：它是**板端 Python SDK 离线安装包**。如果我们只在本机通过 gRPC 控制机器人，不需要先把这个 bundle 装到 X5；如果要在 X5 本地运行 `arm-p7-sdk` CLI 或示例，再装它。

## 6. 当前机器人只读状态

命令：

```bash
ssh root@172.100.10.159 hostname
ssh root@172.100.10.159 date
ssh root@172.100.10.159 sed -n '1,80p' /opt/robot_app/include/version.hpp
ssh root@172.100.10.159 "python3 -c 'print(__import__(\"arm_p7_sdk\").__file__)'"
ssh root@172.100.10.159 ss -lntp
python3 -c '对 172.100.10.159 / 192.168.25.1 的 50071/50051/50052 做 socket.connect_ex'
```

关键输出：

```text
hostname: ubuntu
date: Wed Jul  1 11:35:53 CST 2026
#define AIRBOT_MOTION_VERSION "0.1.1.dev90+g24fec8a"
ModuleNotFoundError: No module named 'arm_p7_sdk'
ss -lntp: 只看到 22、8020、8042 等；未看到 50071/50051/50052
172.100.10.159:50071 -> 111 connection refused
192.168.25.1:50071 -> 11 timeout
```

结论：当前机器人尚未安装/启用这个 release。现在无法直接 `AirbotClient(... port=50071)` 连接。

## 7. 建议安装顺序

1. 先不要碰 OpenPI 推理 `.venv`。给 SDK 客户端建独立环境，例如 `~/airbot_p7_sdk_client/venv`。
2. 本机/客户端环境安装 `arm_p7_sdk-1.1.1-py3-none-any.whl`，并确保 protobuf runtime >= 6.33.5。
3. 机器人侧升级/部署 `robot_app_0.3.5_...arm64.deb`；是否同时装 `robot_ota_app_0.2.0` 取决于机器人升级流程。当前实机是 `remote + left_arm + right_arm` 三进程旧栈，新包是扁平单套配置，默认 `can0`，直接 `dpkg -i` 会覆盖 `/opt/robot_app` 的二进制/库/顶层配置，不应在未确认回滚和启动方案时盲目执行。
4. 最小真机验证方案应先接管右臂 `can0`：停止当前 `/opt/robot_app/configs/right_arm/project_config.json` 对应旧进程，启动隔离解包的 0.3.5 单臂服务，再只做只读验证；`ss -lntp` 应看到 50071，本机 `connect_ex(192.168.25.1,50071)` 应成功。
5. 再用 SDK 做 no-motion：`get_service_state()`、`get_end_pose()`。
6. 最后才进入控制权 acquire/release、servo_control、极小步移动测试。

本轮没有安装任何包，没有重启 robot_app，没有发送控制命令，没有移动机械臂或夹爪。


## 8. 2026-07-01 13:55 CST — 本机独立 SDK venv 已安装

按用户确认“单独装就行”，已在当前仓库内创建独立 SDK client 环境，不污染 OpenPI 推理 `.venv`：

```bash
uv venv --python 3.11 .venv-p7-sdk
uv pip install --python .venv-p7-sdk/bin/python   docs/AIRBOT-ARM-P7-SW-2026-06-23-21-16-24/components/sdk_client/arm_p7_sdk-1.1.1-py3-none-any.whl   'protobuf>=6.33.5'
```

安装关键输出：

```text
Using CPython 3.11.15
Creating virtual environment at: .venv-p7-sdk
Installed 12 packages
arm-p7-sdk==1.1.1
protobuf==7.35.1
grpcio==1.81.1
typer==0.26.8
loguru==0.7.3
```

验证命令：

```bash
.venv-p7-sdk/bin/python -c "import arm_p7_sdk, importlib.metadata as md; from arm_p7_sdk import AirbotClient; print(md.version('arm-p7-sdk')); print(md.version('protobuf')); print(AirbotClient)"
.venv-p7-sdk/bin/python -c "import inspect; from arm_p7_sdk import AirbotClient; print(inspect.signature(AirbotClient))"
.venv-p7-sdk/bin/arm-p7-sdk version
.venv-p7-sdk/bin/arm-p7-sdk --help
```

关键输出：

```text
arm-p7-sdk 1.1.1
protobuf 7.35.1
grpcio 1.81.1
AirbotClient <class 'arm_p7_sdk.client.AirbotClient'>
(host: 'str' = 'localhost', port: 'int' = 50071, *, backend: 'str' = 'grpc', ...)
arm-p7-sdk version -> 1.1.1
```

隔离性检查：

```bash
uv run python -c "import importlib.metadata as md; print(md.version('protobuf')); print(md.version('arm-p7-sdk')); import arm_p7_sdk"
git check-ignore -v .venv-p7-sdk .venv-p7-sdk/bin/python
git status --short .venv-p7-sdk .gitignore
```

关键输出：

```text
OpenPI .venv protobuf: 4.25.8
OpenPI .venv arm-p7-sdk: 1.0.0
OpenPI .venv import arm_p7_sdk 仍失败：ImportError: cannot import name 'runtime_version' from 'google.protobuf'
.venv-p7-sdk/.gitignore:1:*  .venv-p7-sdk/bin/python
git status --short .venv-p7-sdk .gitignore: 无输出
```

结论：本机 SDK client 环境已就绪，后续本机运行 SDK 命令统一使用：

```bash
source .venv-p7-sdk/bin/activate
arm-p7-sdk version
python -c "from arm_p7_sdk import AirbotClient; print(AirbotClient)"
```

当前仍未升级机器人侧 `robot_app_0.3.5`，所以 `AirbotClient(host='172.100.10.159', port=50071, backend='grpc')` 仍无法连通。下一步是 X5/机器人侧升级并拉起 50071 gRPC route。本轮没有向机器人安装包、没有重启 robot_app、没有发送控制命令、没有移动机械臂或夹爪。

## 9. 2026-07-01 17:25 CST — 有线实机与 arm64 包隔离检查

目的：用户接好网线后，确认是否可以直接用真机 SDK gRPC；如果不行，检查 `robot_app_0.3.5` 包是否能在机器人侧部署。

有线网络与端口：

```bash
ip -br addr
ping -c 2 -W 1 192.168.25.1
python -c '对 192.168.25.1/172.100.10.159 的 22/50071/50051/50052 做 socket connect'
ssh root@192.168.25.1 'ip -br addr; ss -lntp'
timeout 8 .venv-p7-sdk/bin/python - <<'PY'
from arm_p7_sdk import AirbotClient
c = AirbotClient(host="192.168.25.1", port=50071, backend="grpc")
print(c.get_service_state())
PY
```

关键输出：

```text
本机 enp108s0 UP 192.168.25.132/24
机器人 eth0 UP 192.168.25.1/24
192.168.25.1:22 open
192.168.25.1:50071/50051/50052 refused 或 timeout
ss -lntp: 未看到 50071/50051/50052
SDK: ConnectionError Timeout connecting to 192.168.25.1:50071
```

机器人当前运行栈：

```bash
ssh root@192.168.25.1 'pgrep -af "bin/robot_app"; ps -fp 2518; sed -n "1,320p" /userdata/start-robot-app-3arm.sh'
ssh root@192.168.25.1 'grep -RInE "grpc|50071|arm_grpc" /opt/robot_app/configs || true'
ssh root@192.168.25.1 'find /opt/robot_app/lib -maxdepth 1 -type f -name "*route*" -o -name "*grpc*"'
```

关键输出：

```text
2530 ./bin/robot_app /opt/robot_app/configs/remote/project_config.json
2611 ./bin/robot_app /opt/robot_app/configs/left_arm/project_config.json
2792 ./bin/robot_app /opt/robot_app/configs/right_arm/project_config.json
2518 bash start-robot-app-3arm.sh
/opt/robot_app/configs: 未发现 arm_grpc_route / 50071
/opt/robot_app/lib: 未发现 libarm_grpc_route.so
```

结论：网线链路已经可用于 SSH、上传包和后续管理；但当前旧 `robot_app` 栈没有 gRPC route，不能直接给 SDK 用。

备份、上传与隔离解包：

```bash
ssh root@192.168.25.1 'tar -czf /userdata/openpi_robot_app_backup_20260701_1716.tgz -C /opt robot_app'
scp docs/AIRBOT-ARM-P7-SW-2026-06-23-21-16-24/components/arm_p7/robot_app_0.3.5_20260623131126_arm64.deb root@192.168.25.1:/tmp/openpi_robot_app_0.3.5_20260623131126_arm64.deb
ssh root@192.168.25.1 'sha256sum /tmp/openpi_robot_app_0.3.5_20260623131126_arm64.deb; dpkg --dry-run -i /tmp/openpi_robot_app_0.3.5_20260623131126_arm64.deb'
ssh root@192.168.25.1 'mkdir -p /tmp/openpi_robot_app_0.3.5_stage; dpkg-deb -x /tmp/openpi_robot_app_0.3.5_20260623131126_arm64.deb /tmp/openpi_robot_app_0.3.5_stage'
ssh root@192.168.25.1 'cd /tmp/openpi_robot_app_0.3.5_stage/opt/robot_app; LD_LIBRARY_PATH=lib ldd bin/robot_app | grep "not found" || true; grep -RInE "arm_grpc_route|grpc_route_node|50071" configs; sed -n "1,60p" configs/mavlink_config.json'
```

关键输出：

```text
backup: /userdata/openpi_robot_app_backup_20260701_1716.tgz, 161M
backup sha256: 0c551f65d192e643c77228566e472a0371a4e2d89042a51b4a7a1efec85ed97d
deb sha256: 037d7c1e53b59cb9466e5bf12d23d833751b02e5482240d7c710384795cb7bd4
dpkg --dry-run: Selecting previously unselected package robot_app; Preparing to unpack ...
ldd: 无 not found
configs/framework_config.json: arm_grpc_route / libarm_grpc_route.so / grpc_route_node / user_param "none;50071"
mavlink_config.json: 默认 can0
```

影响：`robot_app_0.3.5` 本身可在机器人上解包，库依赖齐全，确实能提供 50071 gRPC route；但默认配置是 `can0` 单臂服务，与当前 `remote + left_arm(can1) + right_arm(can0)` 三进程旧栈不同。下一步要启用真机 SDK，应先明确采用“停止旧 right_arm、启动隔离 0.3.5 接管 can0”的最小验证，还是做全量 `/opt/robot_app` 升级。当前未执行 `dpkg -i`，未停止任何机械臂服务，未发送控制命令，未移动机械臂或夹爪。

## 10. 2026-07-01 18:18 CST — 停旧右臂并启动隔离 0.3.5 gRPC route

目的：按用户确认“可以停止”，停止旧 `right_arm`，让隔离解包的 `robot_app 0.3.5` 接管右臂 `can0`，只做 SDK no-motion 只读验证。

执行命令摘要：

```bash
ssh root@192.168.25.1 '记录当前进程、端口、can0 状态'
ssh root@192.168.25.1 '停止 /opt/robot_app/configs/right_arm/project_config.json 对应 PID 2792；复位 can0；生成 /tmp/openpi_robot_app_035_run_20260701_181640/project_config.json；启动 /tmp/openpi_robot_app_0.3.5_stage/opt/robot_app/bin/robot_app'
ssh root@192.168.25.1 'ss -lntp | grep 50071; tail robot_app.log'
timeout 20 .venv-p7-sdk/bin/python - <<'PY'
from arm_p7_sdk import AirbotClient
c = AirbotClient(host="192.168.25.1", port=50071, backend="grpc")
print(c.get_service_state())
print(c.get_end_pose())
print(c.get_arm_joint_state())
print(c.get_eef_joint_state())
print(c.get_eef_mode())
c.close()
PY
```

关键输出：

```text
OLD_RIGHT_ARM_PIDS= 2792
RESET_CAN0
RUN_DIR=/tmp/openpi_robot_app_035_run_20260701_181640
NEW_PID=9623
NEW_STATUS=running
LISTEN *:50071 users:(("robot_app",pid=9623,fd=35))
log: gRPC server listening on 0.0.0.0:50071
log: Framework started successfully
```

SDK no-motion 只读输出：

```text
service_state ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
end_pose CartesianPose(xyz=(0.3094, -0.0097, 0.3208), xyzw=(0.0425, 0.0086, -0.0180, 0.9989))
arm_joint_state ArmJointState(angles=(-0.0137, -0.0039, -0.0085, 0.0000, 0.0783, -0.0172, -0.0133), velocities=(约 0), efforts=(约 0))
eef_joint_state EEFJointState(eef_pos=(0.0000), eef_vel=(-0.0339), eef_eff=(-8.5811))
eef_mode {'has_eef': True, 'current_mode': 0, 'current_mode_name': 'idle', 'active_eef_controller_id': 0, 'active_eef_controller_name': 'idle'}
```

当前进程状态：

```text
2530 ./bin/robot_app /opt/robot_app/configs/remote/project_config.json
2611 ./bin/robot_app /opt/robot_app/configs/left_arm/project_config.json
9623 /tmp/openpi_robot_app_0.3.5_stage/opt/robot_app/bin/robot_app /tmp/openpi_robot_app_035_run_20260701_181640/project_config.json
```

影响：真机右臂 `192.168.25.1:50071` 已可由本机 `arm_p7_sdk` 访问，no-motion 读状态通过。当前没有覆盖安装 deb，没有调用 `acquire_control()`，没有调用 `move_end_pose()` / `move_eef()`，没有移动机械臂或夹爪。下一步才是控制权 acquire/release、正式 SDK adapter 和极小步运动验证。

## 11. 2026-07-01 18:26 CST — SDK 控制权 no-motion 空操作验证

目的：在真机右臂 `192.168.25.1:50071` 已可读后，验证 SDK 控制权 acquire/release 是否正常；不切控制器、不调用任何运动接口。

命令：

```bash
timeout 20 .venv-p7-sdk/bin/python - <<'PY'
from arm_p7_sdk import AirbotClient
client = AirbotClient(host="192.168.25.1", port=50071, backend="grpc")
print(client.get_service_state())
print(client.get_end_pose())
print(client.acquire_control(lease_ms=15000, renew_period_s=5.0))
print(client.get_service_state())
print(client.get_end_pose())
client.release_control()
print(client.get_service_state())
print(client.get_end_pose())
client.close()
PY
```

关键输出：

```text
state_before ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
pose_before CartesianPose(xyz=(0.3094, -0.0097, 0.3208), xyzw=(0.0425, 0.0086, -0.0180, 0.9989))
acquire_control True
[CLIENT] control acquired: lease_id=1
state_after_acquire ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
pose_after_acquire CartesianPose(xyz=(0.3094, -0.0097, 0.3208), xyzw=(0.0425, 0.0086, -0.0180, 0.9989))
release_control done
[CLIENT] control released
state_after_release ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
pose_after_release CartesianPose(xyz=(0.3094, -0.0097, 0.3208), xyzw=(0.0425, 0.0086, -0.0180, 0.9989))
```

结论：真机右臂 SDK 控制权 acquire/release no-motion 验证通过；状态保持 `IDLE/idle`，TCP pose 没变化。随后已执行一次单臂 1mm SERVO 极小步运动，链路可真实驱动机械臂；但最终稳定位移超过预期，继续前需要先收紧 SERVO 参数和安全 guard。

## 12. 2026-07-01 18:39 CST — 右臂 1mm SERVO 极小步运动验证

目的：在控制权 acquire/release no-motion 通过后，执行一次右臂 TCP `x + 0.001m` 的极小步运动，确认 `robot_app 0.3.5` + `arm_p7_sdk 1.1.1` 的真机写链路是否真的能驱动机械臂。

执行链路：本机 `.venv-p7-sdk` -> `AirbotClient(host="192.168.25.1", port=50071, backend="grpc")` -> staged `robot_app 0.3.5` PID `9623` -> 右臂 `can0`。

关键命令形态：

```python
from arm_p7_sdk import AirbotClient
from arm_p7_sdk.constants import Controller
from arm_p7_sdk.types import CartesianMoveOptions, CartesianPose

client = AirbotClient(host="192.168.25.1", port=50071, backend="grpc")
pose_before = client.get_end_pose()
client.acquire_control(lease_ms=15000, renew_period_s=5.0)
client.switch_controller(Controller.servo_control)
target = CartesianPose(
    position=[pose_before.position[0] + 0.001, pose_before.position[1], pose_before.position[2]],
    orientation=list(pose_before.orientation),
)
ok = client.move_end_pose(
    target,
    CartesianMoveOptions(
        motion_type="ptp",
        velocity_scaling_factor=0.01,
        acceleration_scaling_factor=0.02,
        allow_planning_time=0.5,
        blocking=True,
    ),
)
client.switch_controller(Controller.idle)
client.release_control()
```

关键输出：

```text
pose_before CartesianPose(xyz=(0.3094, -0.0097, 0.3208), xyzw=(0.0425, 0.0086, -0.0180, 0.9989))
acquire_control True
switch_servo True
move_end_pose_1mm_x True
pose_after_move CartesianPose(xyz=(0.3105, -0.0097, 0.3206), xyzw=(0.0425, 0.0094, -0.0179, 0.9989))
delta_after_move ~= (0.00111, 0.00001, -0.00026), dist ~= 0.00114m
switch_idle True
final_pose CartesianPose(xyz=(0.3140, -0.0061, 0.3248), xyzw=(0.0405, 0.0100, -0.0131, 0.9990))
final_state ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
```

稳定性复查：释放后连续 8 次读数保持 `IDLE/idle`，最终 TCP pose 稳定在 `xyz=(0.3140,-0.0061,0.3248)` 附近，没有继续漂移。

SDK 后端核对：

```bash
sed -n '960,1120p' .venv-p7-sdk/lib/python3.11/site-packages/arm_p7_sdk/_backends/grpc_route.py
```

关键结论：`servo_control` 下 `move_end_pose()` 实际发 `CallServoPoseCommand`；该分支使用 `self._arm_motor_speed` 和 `options.eff`，不使用 `velocity_scaling_factor` / `acceleration_scaling_factor`。本次测试没有显式调用 `set_arm_speed()`，也没有显式传 `eff`，因此不能把这次的速度限制参数视作有效 SERVO 限速。

结论：真机右臂 SDK gRPC 写链路已经打通，`move_end_pose()` 可以真实驱动机械臂；但最终稳定位置相对起点约 `7mm`，大于本次 `1mm` 目标。继续 EEF、双臂或 policy chunk 前，必须先按官方 SERVO 示例重写极小步脚本：显式 `set_arm_speed()`、显式 `eff`、步长降到 `0.2-0.5mm`、加入命令后稳定读数循环和最大位移 guard。

## 13. 2026-07-01 19:02 CST — 受保护 0.2mm SERVO 复测脚本与真机结果

目的：把 1mm 首测后发现的 SERVO 参数问题收紧为可复用脚本，并用更小步长验证右臂写链路在 guard 下是否可控。

新增脚本：`examples/airbot/p7_guarded_servo_step.py`。

脚本安全行为：

- 默认 dry-run；不带 `--execute` 时只读 `get_service_state()` / `get_end_pose()`，不会 `acquire_control()`，不会切控制器，也不会发 `move_end_pose()`。
- 执行前要求状态为 `ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)`。
- 运动前采样多次 TCP pose，若预采样漂移超过 guard 则拒绝执行。
- 显式设置 `set_arm_speed([0.55] * 7)`；这是 SDK 当前校验下限附近的速度，SDK 默认值为 `pi/3`。
- 显式设置 `CartesianMoveOptions(eff=[8.0] * 7, blocking=True)`；不再依赖默认电流阈值 `[70,70,40,40,12,12,12]`。
- 运动后无论成功/失败都尝试 `switch_controller(Controller.idle)` 和 `release_control()`。
- 记录即时位移、target error、最终稳定位移、post drift 和最终 service state；超过 guard 时用非零退出码标记。

代码验证：

```bash
.venv-p7-sdk/bin/python -m py_compile examples/airbot/p7_guarded_servo_step.py
uv run ruff check examples/airbot/p7_guarded_servo_step.py
```

结果：`py_compile` 通过；`ruff check` 通过。

Dry-run 命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_guarded_servo_step.py --host 192.168.25.1 --port 50071
```

Dry-run 关键输出：

```text
state_before ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
pose_start xyz=(0.314030, -0.006099, 0.325622) xyzw=(0.040457, 0.009212, -0.013011, 0.999054)
pre_drift_m 0.000000
target_pose xyz=(0.314230, -0.006099, 0.325622) xyzw=(0.040457, 0.009212, -0.013011, 0.999054)
planned_step_m 0.000200 axis x
arm_speed_rad_s 0.550000
eff [8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0]
DRY_RUN: no acquire_control(), switch_controller(), or move_end_pose() was called
```

真机执行命令：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_guarded_servo_step.py \
  --host 192.168.25.1 --port 50071 --execute \
  --step-m 0.0002 --axis x \
  --arm-speed-rad-s 0.55 --eff 8,8,8,8,8,8,8 \
  --move-distance-guard-m 0.0015 --final-distance-guard-m 0.0015
```

真机关键输出：

```text
state_before ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
pose_start xyz=(0.314030, -0.006099, 0.325622) xyzw=(0.040457, 0.009212, -0.013011, 0.999054)
pre_drift_m 0.000004
target_pose xyz=(0.314230, -0.006099, 0.325622) xyzw=(0.040457, 0.009212, -0.013011, 0.999054)
acquire_control True
[CLIENT] control acquired: lease_id=3
switch_servo True
[CLIENT] Set arm speed to [0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55]
set_arm_speed True
[CLIENT] Updated servo scale to: [0.5, 0.5, 0.07002906659820268]
move_end_pose True
pose_after_move xyz=(0.313499, -0.005513, 0.324349) xyzw=(0.039837, 0.009924, -0.012438, 0.999079)
move_distance_m 0.001498
target_error_m 0.001580
switch_idle True
release_control done
[CLIENT] control released
final_pose xyz=(0.314039, -0.005809, 0.325615) xyzw=(0.040195, 0.009237, -0.012686, 0.999069)
post_drift_m 0.000013
final_distance_m 0.000290
state_final ServiceState(service_state=True, fsm_state='IDLE', controller_state='idle', valid=True)
client_closed
```

运动后机器人侧复查：

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

结论：受保护脚本和真机 0.2mm 复测通过，最终稳定后位移约 `0.29mm`，状态回到 `IDLE/idle`，`robot_app 0.3.5` PID `9623` 和 `50071` 仍正常。需要注意：`pose_after_move` 的即时位移为 `1.498mm`，虽然低于 `1.5mm` guard，但明显大于目标 `0.2mm`；正式 adapter 必须保留 guard，并且不能直接把 policy chunk 高频下发到真机。

## 14. 2026-07-01 19:26 CST — 正式 GuardedP7ArmAdapter 落地与 no-motion smoke

目的：把临时 `p7_guarded_servo_step.py` 中验证过的控制权、速度、eff 和 guard 流程沉淀为可复用 adapter，后续供 policy/relpose 单步执行层调用。

新增文件：

- `src/openpi/shared/airbot_p7_adapter.py`
- `src/openpi/shared/airbot_p7_adapter_test.py`

adapter 设计结论：

- import 阶段不依赖 `arm_p7_sdk`，避免 OpenPI 主 `.venv` 因 SDK/protobuf 环境差异无法导入。
- 真实执行时通过 `create_grpc_client()` / `load_p7_sdk_bindings()` 动态导入 SDK；单元测试通过 fake client / fake SDK bindings 覆盖控制逻辑。
- `GuardedP7Config` 固化当前真机验证过的安全默认值：`arm_speed_rad_s=0.55`、`efforts=(8.0,)*7`、`max_translation_step_m=0.0005`、`move_distance_guard_m=0.0015`、`final_distance_guard_m=0.0015`。
- `GuardedMoveResult` 结构化返回 `status`、`start_pose`、`target_pose`、`pose_after_move`、`final_pose`、pre/post drift、即时/最终位移和控制权状态。
- `execute=False` 是 dry-run，只读状态和 pose，不调用 `acquire_control()`、不切控制器、不发运动。
- `execute=True` 才执行 `acquire_control()` -> `switch_controller(servo_control)` -> `set_arm_speed()` -> `move_end_pose()` -> `switch_controller(idle)` -> `release_control()`。

代码验证：

```bash
uv run ruff check src/openpi/shared/airbot_p7_adapter.py src/openpi/shared/airbot_p7_adapter_test.py
uv run pytest src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_p7_adapter_test.py
```

关键输出：

```text
ruff: All checks passed!
pytest: 11 passed in 0.03s
```

真实 SDK no-motion smoke 命令：

```bash
.venv-p7-sdk/bin/python -c "import sys; sys.path.insert(0, 'src'); from openpi.shared.airbot_p7_adapter import GuardedP7ArmAdapter, GuardedP7Config, create_grpc_client; from openpi.shared.airbot_relpose import TcpPose; client = create_grpc_client('192.168.25.1', 50071); arm = GuardedP7ArmAdapter(client, config=GuardedP7Config(pre_samples=2, post_samples=2, sample_period_s=0.0)); cur = arm.read_current_tcp_pose(); target = TcpPose([float(cur.position[0]) + 0.0002, float(cur.position[1]), float(cur.position[2])], cur.quaternion_xyzw); result = arm.move_tcp_target(target, execute=False); print('current_xyz', tuple(round(float(v), 6) for v in cur.position)); print('result_status', result.status); print('message', result.message); print('pre_drift_m', result.pre_drift_m); print('target_xyz', tuple(round(float(v), 6) for v in result.target_pose.position)); print('acquired_control', result.acquired_control); client.close()"
```

关键输出：

```text
current_xyz (0.314036, -0.005822, 0.325609)
result_status dry_run
message dry-run: no control or motion command sent
pre_drift_m 0.0
target_xyz (0.314236, -0.005822, 0.325609)
acquired_control False
```

端口复查：

```bash
ssh root@192.168.25.1 "ss -lntp | grep 50071 || true"
```

关键输出：

```text
LISTEN *:50071 users:(("robot_app",pid=9623,fd=35))
```

结论：正式 guarded adapter 已落地，可在主 OpenPI 环境中测试，并能在 `.venv-p7-sdk` 中对真机做 no-motion smoke。当前仍未继续 EEF、双臂或 policy chunk；下一步应先把 adapter 接到单步 relpose target 的 dry-run/日志链路，再做 EEF 极小开合。
