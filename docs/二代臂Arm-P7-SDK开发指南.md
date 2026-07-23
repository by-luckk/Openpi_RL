# 二代臂Arm\-P7\-SDK开发指南

# Arm\-P7 SDK 开发指南

|版本|日期|修改记录|编写人|备注|
|---|---|---|---|---|
|V1\.0|2026\.4\.2|初版|@VitaminT|- First version|
|V1\.1|2026\.4\.15|重构SDK接口|@VitaminT|- 解耦七轴和六轴臂的SDK，现在七轴和六轴臂的SDK彻底独立<br>- 重构SDK结构和部分接口，以及所有数据模型|
|V1\.2<br>|2026\.6\.2<br>|速度前馈<br>|@VitaminT|- 改写servo速度接口，适配电机速度前馈固件，删除direct control控制模式<br>- 夹爪单位修改为毫米|
|V2\.0|2026\-06\-18|按当前仓库重构为面向 SDK 使用者的开发指南|@VitaminT|- 对齐 `AirbotClient`、数据模型、gRPC backend、DDS backend、examples、安装脚本和测试|

软件大包最新下载地址：

https://jihulab\.com/api/v4/projects/346009/packages/generic/airbot\-p7\-sw/AIRBOT\-ARM\-P7\-SW\-2026\-07\-06\-11\-28\-30/AIRBOT\-ARM\-P7\-SW\-2026\-07\-06\-11\-28\-30\.tar\.gz

## SDK 概述

Arm\-P7 SDK 的公共入口是 `AirbotClient`。应用侧通过它完成以下工作：

- 选择连接 backend：默认 `backend="grpc"`，也可使用 `backend="dds"`。

- 管理控制权：`acquire_control()` / `release_control()`。

- 读取状态：关节、电机、末端、IMU、末端位姿、固件信息、服务状态。

- 切换控制模式：机械臂 `Controller`，末端 `EEFControlMode`。

- 下发运动命令：关节 PTP、SERVO 小步跟踪、笛卡尔 PTP/LIN/CIRCLE、路点、MIT 风格控制、末端 CSP/MIT。

当前 SDK 默认面向 7 轴 Arm\-P7，公共 `AirbotClient` 构造函数不暴露 `arm_dof` 参数。应用代码应按 7 轴准备机械臂关节位置、速度、effort、seed 等列表。

旧版 direct control/PVT 臂控入口不再作为公共机械臂控制模式暴露。请使用 `Controller.servo_control`、`Controller.planning_control` 或 `Controller.mit_control`。


![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NjExOWZmMmQzNjU0ZjdkYTRiODNiZGU0OWJiMzk0M2RfNDBmMTc3MWIyNTYwMWQyMGRlYjI1ZGNkZDYwNmRkZWFfSUQ6NzY1NTMyMTc0MzA3NDQxMzU0OF8xNzg0NDU4NjE3OjE3ODQ1NDUwMTdfVjM)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=M2MyYjZiZDM2YzRmOTA0MmQwZTg1NGM1ZTkyZjJlMzhfYjI0MmUwZTc4NzAzMGUwNDdmMmU2Zjc3MDg3MTQzMzJfSUQ6NzY1NTMyMTc5NDMzMDEzNTc4OV8xNzg0NDU4NjE2OjE3ODQ1NDUwMTZfVjM)

## 安装与运行环境

### Python 环境

当前 `pyproject.toml` 要求：

- Python：`>=3.9`

- 主要依赖：`grpcio`、`protobuf`、`typer`、`loguru`

- CLI 入口：`arm-p7-sdk`

如果你拿到的是 wheel 包，直接安装：

```Bash
python -m pip install /path/to/arm_p7_sdk-*.whl
```

验证安装：

```Bash
python -c "import arm_p7_sdk; print(arm_p7_sdk.__version__)"
arm-p7-sdk version
```

从源码开发安装：

```Bash
python -m pip install -e .
```

### 服务端前置条件

运行示例或业务程序前，需要确保机械臂侧服务已经启动：

- gRPC backend 连接 `grpc_route_node` / Arm\-P7 控制服务。

- DDS backend 连接 `dds_route_node`，并依赖私有 `cora` Python SDK。

默认导入 SDK、使用默认 gRPC backend 时，不会导入或依赖 `cora`。只有创建 `AirbotClient(backend="dds", ...)` 时，SDK 才会懒加载 `cora`。

## 快速开始

### 创建 client

gRPC 是默认 backend，默认端口是 `50071`：

```Python
from arm_p7_sdk import AirbotClient

client = AirbotClient(host="127.0.0.1", port=50071)
print(client)
client.close()
```

推荐使用上下文管理器，离开 `with` 时会关闭连接并尝试释放控制权：

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(host="127.0.0.1", port=50071) as client:
    print("client_id:", client.get_client_id)
```

### 获取和释放控制权

控制类接口需要独占控制权。SDK 侧对部分接口会自动尝试获取控制权，但业务代码推荐显式获取、显式释放：

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control(lease_ms=15000, renew_period_s=5.0):
        raise RuntimeError("Failed to acquire control")

    try:
        print("control acquired")
    finally:
        client.release_control()
```

### 查询状态

状态读取通常不需要控制权：

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(host="127.0.0.1", port=50071) as client:
    print("service:", client.get_service_state())
    print("firmware:", client.get_firmware_info())
    print("arm joint:", client.get_arm_joint_state())
    print("arm motor:", client.get_arm_motor_state())
    print("end pose:", client.get_end_pose())
    print("eef joint:", client.get_eef_joint_state())
    print("eef motor:", client.get_eef_motor_state())
    print("imu:", client.get_imu_state())
    print("eef mode:", client.get_eef_mode())
```

### planning\_control 下执行一次安全的关节 PTP

这个示例以当前关节状态为起点，只让第 1 轴小幅移动 `0.10 rad`，并使用 SDK 导出的关节限位做裁剪。

```Python
from arm_p7_sdk import (
    ARM_JOINT_LIMITS,
    AirbotClient,
    Controller,
    JointMoveOptions,
)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        state = client.get_arm_joint_state()
        if state is None:
            raise RuntimeError("Failed to read arm joint state")

        target = list(state.angles)
        low, high = ARM_JOINT_LIMITS[0]
        target[0] = clamp(target[0] + 0.10, low, high)

        if not client.switch_controller(Controller.planning_control):
            raise RuntimeError("Failed to switch to planning_control")

        ok = client.move_joint(
            pos=target,
            options=JointMoveOptions(
                motion_type="ptp",
                velocity_scaling_factor=0.1,
                acceleration_scaling_factor=0.1,
                allow_planning_time=5.0,
                blocking=True,
            ),
            timeout_ms=10000,
        )
        print("move_joint PTP:", ok)

    finally:
        try:
            client.switch_controller(Controller.idle)
        except Exception:
            pass
        client.release_control()
```

### 末端 EEF CSP 控制示例

`move_eef()` 的 `pos` 是 `list[float]`，单位是 `mm`，长度必须匹配运行时 EEF DOF。`EEFMoveOptions.eff` 也是列表。

```Python
from arm_p7_sdk import AirbotClient, EEFControlMode, EEFMoveOptions

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        mode = client.get_eef_mode()
        if not mode or not mode.get("has_eef"):
            raise RuntimeError("No EEF is reported by the service")

        state = client.get_eef_joint_state()
        if state is None:
            raise RuntimeError("Failed to read EEF joint state")

        eef_dof = len(state.eef_pos)
        target = [max(0.0, pos_mm - 2.0) for pos_mm in state.eef_pos]

        if not client.switch_eef_control_mode(EEFControlMode.csp):
            raise RuntimeError("Failed to switch EEF to csp")

        if not client.set_eef_speed(100.0):
            raise RuntimeError("Failed to set EEF speed")

        ok = client.move_eef(
            pos=target,
            options=EEFMoveOptions(
                eff=[5.0] * eef_dof,
                blocking=True,
            ),
            timeout_ms=3000,
        )
        print("move_eef CSP:", ok)

    finally:
        try:
            client.switch_eef_control_mode(EEFControlMode.idle)
        except Exception:
            pass
        client.release_control()
```

### DDS backend 连接示例

DDS backend 需要私有 `cora` SDK。`host` / `port` 只用于 gRPC；DDS 使用 `domain_id`、`side` 和 CORA participant 参数。

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(
    backend="dds",
    domain_id=0,
    side="none",
    participant_name="arm_app",
    use_shared_memory=True,
    use_udp=True,
    default_timeout_ms=3000,
    shutdown_on_close=False,
) as client:
    print(client)
    print(client.get_service_state())
```

## 连接 backend 选择

### AirbotClient 构造函数

完整构造参数如下，默认值以当前 `AirbotClient.__init__` 为准。

```Python
AirbotClient(
    host: str = "localhost",
    port: int = 50071,
    *,
    backend: str = "grpc",
    domain_id: int = 0,
    side: str = "none",
    participant_name: str | None = None,
    use_shared_memory: bool = True,
    use_udp: bool = True,
    default_timeout_ms: int = 3000,
    shutdown_on_close: bool = False,
) -> None
```

|参数|默认值|适用 backend|说明|
|---|---|---|---|
|`host`|`"localhost"`|gRPC|目标服务主机名或 IP|
|`port`|`50071`|gRPC|目标服务端口|
|`backend`|`"grpc"`|全部|`"grpc"` / `"grpc_route"` 使用 gRPC；`"dds"` / `"cora"` / `"cora_dds"` / `"dds_route"` 使用 DDS|
|`domain_id`|`0`|DDS|CORA DDS domain id|
|`side`|`"none"`|DDS|机械臂命名空间，见下表|
|`participant_name`|`None`|DDS|`None` 时 SDK 使用 `arm_p7_sdk_dds_<pid>`|
|`use_shared_memory`|`True`|DDS|传给 `cora.init()` 的共享内存传输开关|
|`use_udp`|`True`|DDS|传给 `cora.init()` 的 UDP 传输开关|
|`default_timeout_ms`|`3000`|DDS|DDS RPCClient 默认等待超时|
|`shutdown_on_close`|`False`|DDS|`True` 时最后一个 SDK DDS backend 关闭后请求关闭进程级 CORA participant|

### backend 使用建议

|backend|适用场景|依赖|
|---|---|---|
|`backend="grpc"`|默认推荐；PC 或应用进程通过 TCP 连接 route service|不依赖 `cora`|
|`backend="dds"`|与 `dds_route_node` 同域通信，常用于板端或 DDS 系统集成|需要私有 `cora` SDK 和 `cora.msg.arm_msgs`|

### DDS side 参数

当前 SDK 会将 `side` 归一化为 `none`、`left` 或 `right`，并映射到对应 DDS route service prefix：

|输入|归一化|route prefix|
|---|---|---|
|`""`、`"none"`、`"default"`、`"single"`、`"single_arm"`、`"single-arm"`|`none`|`rt/arm/dds_route`|
|`"left"`、`"l"`、`"arm_left"`、`"left_arm"`、`"left-arm"`、`"0"`|`left`|`rt/arm/left/dds_route`|
|`"right"`、`"r"`、`"arm_right"`、`"right_arm"`、`"right-arm"`、`"1"`|`right`|`rt/arm/right/dds_route`|

未知 `side` 当前 SDK 侧会回退到默认 `none` 命名空间。

## 控制权生命周期

|接口|说明|
|---|---|
|`client.acquire_control(lease_ms=15000, renew_period_s=5.0) -> bool`|获取控制权|
|`client.release_control() -> None`|释放当前控制权|
|`client.close() -> None`|关闭客户端资源|
|`client.get_client_id -> str`|当前客户端 ID property|

控制权是独占租约：

- `lease_ms` 是租约有效期，单位 `ms`。当前 SDK 侧拒绝大于 `3600000` 的租约。

- `renew_period_s` 是自动续租周期，单位 `s`。`lease_ms / 1000.0` 必须大于等于 `renew_period_s`。

- `close()` 会停止后台线程，停止续租，并尝试释放控制权。

- 多客户端并发时，只有持有租约的客户端能成功执行控制类接口。

带控制权要求的接口在 SDK 侧使用控制权装饰器；如果当前没有租约，SDK 侧可能尝试自动 acquire。实际业务仍建议按“显式 acquire \-\> 控制 \-\> 切 idle \-\> release”的生命周期组织代码，这样排障更清晰。

## 控制模式与末端模式

### Controller

|枚举值|值|说明|常用接口|
|---|---|---|---|
|`Controller.idle`|`0`|空闲模式|结束控制后切回|
|`Controller.servo_control`|`2`|实时伺服跟踪|`move_joint()`、`move_end_pose()`|
|`Controller.planning_control`|`3`|规划控制|PTP、LIN、CIRCLE、WAYPOINTS|
|`Controller.mit_control`|`4`|MIT / force\-style 控制|`move_joint()`、`move_end_pose()`|

切换接口：`client.switch_controller(controller: Controller, timeout_ms=1000) -> bool`，以及 `client.enter_gravity_compensation_mode(timeout_ms=1000) -> bool`。

`enter_gravity_compensation_mode()` 是独立模式切换接口，不对应一个 `Controller` 枚举值。当前 SDK 侧成功进入后会把客户端缓存的机械臂 controller 置为 `Controller.idle`。

### EEFControlMode

|枚举值|值|说明|常用接口|
|---|---|---|---|
|`EEFControlMode.idle`|`0`|末端空闲|结束末端控制后切回|
|`EEFControlMode.mit`|`1`|末端 MIT / force\-style|`move_eef()` \+ `torque/kp/kd`|
|`EEFControlMode.csp`|`2`|末端位置控制|`move_eef()` \+ `pos/eff`|

末端模式接口：`client.get_eef_mode() -> dict[str, object] | None`，以及 `client.switch_eef_control_mode(target_mode: EEFControlMode, timeout_ms=1000) -> bool`。

`get_eef_mode()` 当前返回字典包含：

|key|类型|说明|
|---|---|---|
|`has_eef`|`bool`|服务端是否报告存在 EEF|
|`current_mode`|`int`|当前末端模式数值|
|`current_mode_name`|`str`|`"idle"` / `"mit"` / `"csp"` / `"unknown(...)"`|
|`active_eef_controller_id`|`int`|服务端报告的当前 EEF controller id|
|`active_eef_controller_name`|`str`|服务端报告的当前 EEF controller 名称|

## 数据模型与单位约定

### 单位约定

|数据/命令|单位或格式|
|---|---|
|arm joint position|`rad`|
|arm joint speed / velocity|`rad/s`|
|Cartesian position|`m`|
|Cartesian orientation|quaternion: `(qx, qy, qz, qw)`|
|public EEF command position|`mm`|
|public EEF command speed|`mm/s`|
|`get_eef_joint_state().eef_pos`|当前 SDK backend 已从服务端 `m` 转换为 `mm`|
|`get_eef_joint_state().eef_vel`|当前 SDK backend 已从服务端 `m/s` 转换为 `mm/s`|

`move_eef()` 的公开输入是毫米，SDK 下发到 route 前会转换为米。`get_eef_joint_state()` 当前 gRPC 和 DDS backend 都会把服务端 joint state 中 EEF 部分从米转换为毫米后返回给用户。

### 数据模型字段

|模型|字段|类型|说明|
|---|---|---|---|
|`ArmJointState`<br>|`angles`|`tuple[float, ...]`|关节位置，`rad`|
||`velocities`|`tuple[float, ...]`|关节速度，通常为 `rad/s`|
||`efforts`|`tuple[float, ...]`|effort\-like 反馈|
|`ArmMotorState`|`motor_temperatures`|`tuple[float, ...]`|电机温度|
||`error_ids`|`tuple[int, ...]`|电机错误码|
|`EEFJointState`|`eef_pos`|`tuple[float, ...]`|EEF 位置，当前 SDK 返回 `mm`|
||`eef_vel`|`tuple[float, ...]`|EEF 速度，当前 SDK 返回 `mm/s`|
||`eef_eff`|`tuple[float, ...]`|EEF effort\-like 反馈|
|`EEFMotorState`|`eef_motor_temp`|`tuple[float, ...]`|EEF 电机温度|
||`eef_error_id`|`tuple[int, ...]`|EEF 电机错误码|
|`ServiceState`|`service_state`|`bool`|服务是否可达/运行|
||`fsm_state`|`str`|服务端 FSM 状态字符串|
||`controller_state`|`str`|服务端 active controller 名称|
||`valid`|`bool`|当前缓存快照是否被 SDK 认为新鲜|
|`ImuState`|`angular_velocity`|`tuple[float, float, float]`|`(x, y, z)` 角速度|
||`linear_acceleration`|`tuple[float, float, float]`|`(x, y, z)` 线加速度|
|`CartesianPose`|`position`|`tuple[float, float, float]`|`(x, y, z)`，单位 `m`|
||`orientation`|`tuple[float, float, float, float]`|`(qx, qy, qz, qw)`|
|`ArmFirmwareInfo`<br>|`arm_sn`|`str`|机械臂序列号|
||`base_board_sn`|`str`|base board 序列号|
||`end_board_sn`|`str`|end board 序列号|
||`arm_firmware_version`|`list[str]`|机械臂侧固件版本列表|
||`arm_motor_type`|`list[str]`|机械臂关节电机类型|
||`eef_type`|`str`|末端类型；无末端时通常为空字符串|
||`eef_firmware_version`|`str`|EEF 固件版本|
||`end_board_firmware_version`|`str`|end board 固件版本|

### 机械臂关节命令限位

SDK 侧在原始关节限位内收缩 `0.010 rad` 作为命令限位。`move_joint()`、路点、seed 都会按该限位校验。

|关节|原始限位 `rad`|SDK 命令限位 `rad`|
|---|---|---|
|1|`[-2.9669, 2.9669]`|`[-2.9569, 2.9569]`|
|2|`[-2.5831, 0.83775]`|`[-2.5731, 0.82775]`|
|3|`[-2.9669, 2.9669]`|`[-2.9569, 2.9569]`|
|4|`[-2.4435, 0.17452]`|`[-2.4335, 0.16452]`|
|5|`[-2.9669, 2.9669]`|`[-2.9569, 2.9569]`|
|6|`[-0.78539, 0.78539]`|`[-0.77539, 0.77539]`|
|7|`[-1.5708, 1.2217]`|`[-1.5608, 1.2117]`|

### 速度与 effort 限制

|项|当前 SDK 侧限制|
|---|---|
|`set_arm_speed(arm_speed)`|必须是 7 维列表；SDK 1.1.2 客户端校验要求每轴速度在 `[0.549900008..., 7.854981634...] rad/s`|
|默认 arm speed|`[pi / 3] * 7`|
|`set_eef_speed(eef_speed)`|`[10.0, 1000.0] mm/s`|
|默认 EEF speed|`1000.0 mm/s`|
|arm effort 默认值|`[70.0, 70.0, 40.0, 40.0, 12.0, 12.0, 12.0]`|
|arm effort 限制|`[(0,70), (0,70), (0,40), (0,40), (0,12), (0,12), (0,12)]`|

## AirbotClient API 总览

### 连接、控制权、系统控制

|接口|返回值|说明|支持情况|
|---|---|---|---|
|`close() -> None`|`None`|关闭客户端资源，尝试释放控制权|gRPC / DDS|
|`get_client_id -> str`|`str`|当前客户端唯一 ID property|gRPC / DDS|
|`acquire_control(lease_ms=15000, renew_period_s=5.0) -> bool`|`bool`|获取独占控制权并启动续租|gRPC / DDS|
|`release_control() -> None`|`None`|释放当前租约|gRPC / DDS|
|`set_arm_speed(arm_speed: list[float]) -> bool`|`bool`|设置客户端侧机械臂关节速度上限|gRPC / DDS|
|`set_eef_speed(eef_speed: float) -> bool`|`bool`|设置客户端侧 EEF 速度上限，单位 `mm/s`|gRPC / DDS|
|`switch_controller(controller: Controller, timeout_ms=1000) -> bool`|`bool`|切换机械臂控制模式|gRPC / DDS|
|`enter_gravity_compensation_mode(timeout_ms=1000) -> bool`|`bool`|进入重力补偿|gRPC / DDS|
|`set_arm_emergency_stop(mode: bool) -> bool`|`bool`|`True` 触发急停，`False` 复位急停|gRPC / DDS|
|`clear_error() -> bool`|`bool`|清除 FSM unknown\-error 状态|gRPC / DDS|
|`return_zero() -> bool`|`bool`|切到 SERVO 并发送 7 轴零位命令|gRPC / DDS|

### 状态读取

|接口|返回值|说明|支持情况|
|---|---|---|---|
|`get_service_state() -> ServiceState or None`|`ServiceState or None`|服务状态缓存快照|gRPC / DDS|
|`get_arm_joint_state() -> ArmJointState or None`|`ArmJointState or None`|机械臂关节状态|gRPC / DDS|
|`get_arm_motor_state() -> ArmMotorState or None`|`ArmMotorState or None`|机械臂电机温度/错误码|gRPC / DDS|
|`get_eef_joint_state() -> EEFJointState or None`|`EEFJointState or None`|EEF joint state；无 EEF 或服务端未上报时返回 `None`|gRPC / DDS|
|`get_eef_motor_state() -> EEFMotorState or None`|`EEFMotorState or None`|EEF 电机状态；无数据时返回 `None`|gRPC / DDS|
|`get_imu_state() -> ImuState or None`|`ImuState or None`|IMU 三维角速度和线加速度|gRPC / DDS|
|`get_end_pose() -> CartesianPose or None`|`CartesianPose or None`|当前末端笛卡尔位姿|gRPC / DDS|
|`get_firmware_info() -> ArmFirmwareInfo or None`|`ArmFirmwareInfo or None`|构造 client 时读取并缓存的固件/硬件信息|gRPC / DDS|
|`get_eef_mode() -> dict[str, object] or None`|`dict or None`|当前 EEF 模式信息|gRPC / DDS|

### 运动控制

|接口|返回值|说明|支持情况|
|---|---|---|---|
|`move_joint(pos: list[float], options: JointMoveOptions, timeout_ms=1000) -> bool`|`bool`|关节空间运动；按当前 `Controller` 分发到 SERVO / planning / MIT|gRPC / DDS|
|`move_end_pose(pos: CartesianPose, options: CartesianMoveOptions, timeout_ms=1000) -> bool`|`bool`|笛卡尔位姿运动；按当前 `Controller` 分发|gRPC / DDS|
|`move_end_pose_linear(start: CartesianPose, target: CartesianPose, options: CartesianMoveOptions, timeout_ms=1000) -> bool`|`bool`|笛卡尔直线规划|gRPC / DDS|
|`move_end_pose_circle(start: CartesianPose, path: CartesianPose, target: CartesianPose, options: CartesianMoveOptions, timeout_ms=3000) -> bool`|`bool`|笛卡尔圆弧规划|gRPC / DDS|
|`move_joint_waypoints(waypoints: list[list[float]], options: JointWaypointsMoveOptions, timeout_ms=1000) -> bool`|`bool`|关节多路点规划，至少 2 个 waypoint|gRPC / DDS|
|`move_end_pose_waypoints(waypoints: list[CartesianPose], options: CartesianWaypointsMoveOptions, timeout_ms=1000) -> bool`|`bool`|笛卡尔多路点规划，至少 2 个 waypoint|gRPC / DDS|
|`move_eef(pos: list[float], options: EEFMoveOptions, timeout_ms=1000) -> bool`|`bool`|末端执行器控制；按当前 `EEFControlMode` 分发|gRPC / DDS|
|`switch_eef_control_mode(target_mode: EEFControlMode, timeout_ms=1000) -> bool`|`bool`|切换 EEF 控制模式|gRPC / DDS|

### 当前不支持的接口

|接口|当前行为|
|---|---|
|`clear_eef_motor_err() -> bool`|gRPC 和 DDS backend 当前都会抛出 `UnsupportedOperationError`|
|`clear_arm_motor_err() -> bool`|gRPC 和 DDS backend 当前都会抛出 `UnsupportedOperationError`|

如果需要兼容调用，必须捕获异常：

```Python
from arm_p7_sdk import AirbotClient
from arm_p7_sdk.exceptions import UnsupportedOperationError

with AirbotClient(host="127.0.0.1", port=50071) as client:
    try:
        client.clear_arm_motor_err()
    except UnsupportedOperationError as exc:
        print("clear_arm_motor_err is not supported by current backends:", exc)
```

## 状态读取

### 服务状态

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(host="127.0.0.1", port=50071) as client:
    state = client.get_service_state()
    if state is not None and state.valid:
        print(state.service_state, state.fsm_state, state.controller_state)
```

`valid` 表示 SDK 侧缓存是否仍被认为新鲜，不等价于服务端业务状态一定可执行。控制命令失败时仍应检查返回值和服务端日志。

### 机械臂关节和电机状态

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(host="127.0.0.1", port=50071) as client:
    joint = client.get_arm_joint_state()
    if joint is not None:
        print("angles(rad):", joint.angles)
        print("velocities(rad/s):", joint.velocities)
        print("efforts:", joint.efforts)

    motor = client.get_arm_motor_state()
    if motor is not None:
        print("motor temperatures:", motor.motor_temperatures)
        print("error ids:", motor.error_ids)
```

### 末端位姿、IMU、末端状态

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(host="127.0.0.1", port=50071) as client:
    pose = client.get_end_pose()
    if pose is not None:
        print("position(m):", pose.position)
        print("orientation qx qy qz qw:", pose.orientation)

    imu = client.get_imu_state()
    if imu is not None:
        print("angular velocity xyz:", imu.angular_velocity)
        print("linear acceleration xyz:", imu.linear_acceleration)

    eef = client.get_eef_joint_state()
    if eef is not None:
        print("eef_pos(mm):", eef.eef_pos)
        print("eef_vel(mm/s):", eef.eef_vel)
        print("eef_eff:", eef.eef_eff)
```

## 控制参数

所有 options 类都是 dataclass。向量字段必须传 `list[float]`，不要传 tuple。

### JointMoveOptions

```Python
JointMoveOptions(
    eff: list[float] = [70.0, 70.0, 40.0, 40.0, 12.0, 12.0, 12.0],
    torque: list[float] = [3.50] * 7,
    kp: list[float] = [0.1] * 7,
    kd: list[float] = [0.1] * 7,
    motion_type: Literal["ptp", "lin", "ompl"] = "ptp",
    use_collision: bool = False,
    velocity_scaling_factor: float = 0.4,
    acceleration_scaling_factor: float = 0.3,
    sampling_time: float = 0.01,
    allow_planning_time: float = 0.5,
    circ_is_center: bool = False,
    max_retry_attempts: int = 1,
    ompl_planner_type: Literal["rrt_connect", "rrt_star", "prm", "est"] = "rrt_connect",
    ompl_longest_valid_segment_fraction: float = 0.01,
    ompl_optimization_objective: str = "path_length",
    ompl_simplify_solutions: bool = True,
    ompl_interpolate: bool = True,
    ompl_minimum_waypoint_count: int = 64,
    has_seed_start: bool = False,
    has_seed_goal: bool = False,
    seed_start: list[float] = [],
    seed_goal: list[float] = [],
    blocking: bool = False,
)
```

主要范围：

- `eff`：按关节限制 `[(0,70), (0,70), (0,40), (0,40), (0,12), (0,12), (0,12)]`。

- `torque`：每项 `[-2.0, 7.0]`。

- `kp` / `kd`：每项 `[0.0, 5000.0]`。

- `velocity_scaling_factor` / `acceleration_scaling_factor`：`[0.01, 1.0]`。

- `sampling_time`：`[0.01, 0.5]`。

- `allow_planning_time`：`[0.01, 60.0]`。

- `max_retry_attempts`：`[1, 1000]`。

- `ompl_longest_valid_segment_fraction`：`[1e-6, 1.0]`。

- `ompl_minimum_waypoint_count`：`[2, 100000]`。

### CartesianMoveOptions

字段与 `JointMoveOptions` 基本一致，目标由关节位置变为 `CartesianPose`。差异是 `torque` 每项范围为 `[-7.0, 7.0]`。

```Python
CartesianMoveOptions(
    motion_type="ptp",
    use_collision=False,
    velocity_scaling_factor=0.4,
    acceleration_scaling_factor=0.3,
    sampling_time=0.01,
    allow_planning_time=0.5,
    blocking=False,
)
```

`move_end_pose_circle()` 会直接使用圆弧规划接口，不需要也不应通过 `motion_type` 手动传圆弧类型；圆弧参考点语义由 `circ_is_center` 控制。

### EEFMoveOptions

```Python
EEFMoveOptions(
    eff: list[float] = [8.0],
    torque: list[float] = [10.0],
    kp: list[float] = [0.1],
    kd: list[float] = [0.1],
    blocking: bool = False,
)
```

范围：

- `eff`：每项 `[0.0, 100.0]`。

- `torque`：每项 `[-30.0, 30.0]`。

- `kp` / `kd`：每项 `[0.0, 5000.0]`。

虽然默认值是一维列表，但真实 EEF DOF 来自运行时。调用 `move_eef()` 时：

- `pos` 长度必须等于运行时 `eef_dof`。

- `EEFControlMode.csp` 下，`options.eff` 长度必须等于运行时 `eef_dof`。

- `EEFControlMode.mit` 下，`options.torque` / `options.kp` / `options.kd` 长度必须等于运行时 `eef_dof`。

### Waypoints Options

```Python
JointWaypointsMoveOptions(
    motion_type: Literal["ptp", "ompl"] = "ptp",
    sampling_time: float = 0.01,
    min_blend_radius: float = 0.005,
    velocity_scaling_factor: float = 0.4,
    acceleration_scaling_factor: float = 0.3,
    allow_planning_time: float = 0.5,
    enable_blend: bool = True,
    use_collision: bool = False,
    circ_is_center: bool = False,
    max_retry_attempts: int = 1,
    ompl_planner_type: Literal["rrt_connect", "rrt_star", "prm", "est"] = "rrt_connect",
    ompl_longest_valid_segment_fraction: float = 0.01,
    ompl_optimization_objective: str = "path_length",
    ompl_simplify_solutions: bool = True,
    ompl_interpolate: bool = True,
    ompl_minimum_waypoint_count: int = 64,
    has_seed_start: bool = False,
    has_seed_goal: bool = False,
    seed_start: list[float] = [],
    seed_goal: list[float] = [],
    segments: list[JointWaypointsMoveOptions] = [],
    blocking: bool = False,
)
```

```Python
CartesianWaypointsMoveOptions(
    motion_type: Literal["ptp", "lin", "ompl"] = "ptp",
    sampling_time: float = 0.01,
    min_blend_radius: float = 0.005,
    velocity_scaling_factor: float = 0.4,
    acceleration_scaling_factor: float = 0.3,
    allow_planning_time: float = 0.5,
    enable_blend: bool = True,
    use_collision: bool = False,
    circ_is_center: bool = False,
    max_retry_attempts: int = 1,
    ompl_planner_type: Literal["rrt_connect", "rrt_star", "prm", "est"] = "rrt_connect",
    ompl_longest_valid_segment_fraction: float = 0.01,
    ompl_optimization_objective: str = "path_length",
    ompl_simplify_solutions: bool = True,
    ompl_interpolate: bool = True,
    ompl_minimum_waypoint_count: int = 64,
    has_seed_start: bool = False,
    has_seed_goal: bool = False,
    seed_start: list[float] = [],
    seed_goal: list[float] = [],
    segments: list[CartesianWaypointsMoveOptions] = [],
    blocking: bool = False,
)
```

`segments` 用于逐段覆盖参数。若使用逐段配置，建议长度严格等于 `len(waypoints) - 1`；当前 SDK 侧在长度不匹配时会退回为每段复制全局 options。

## 运动控制

### PTP

关节 PTP 使用 `Controller.planning_control` \+ `move_joint()` \+ `JointMoveOptions(motion_type="ptp")`。快速开始中的 PTP 示例就是推荐模板。

笛卡尔 PTP 使用 `Controller.planning_control` \+ `move_end_pose()`：

```Python
from arm_p7_sdk import AirbotClient, CartesianMoveOptions, CartesianPose, Controller

target = CartesianPose(
    position=(0.46, 0.0, 0.32),
    orientation=(0.0, 0.0, 0.0, 1.0),
)

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        if not client.switch_controller(Controller.planning_control):
            raise RuntimeError("Failed to switch controller")

        ok = client.move_end_pose(
            pos=target,
            options=CartesianMoveOptions(
                motion_type="ptp",
                velocity_scaling_factor=0.1,
                acceleration_scaling_factor=0.1,
                blocking=True,
            ),
            timeout_ms=10000,
        )
        print("cartesian PTP:", ok)
    finally:
        try:
            client.switch_controller(Controller.idle)
        except Exception:
            pass
        client.release_control()
```

### SERVO

SERVO 使用 `Controller.servo_control`。它适合高频小步跟踪、遥操作、视觉伺服等场景。每次命令仍需要完整 7 轴目标或完整 `CartesianPose`，不要只传变化量。

关节 SERVO 示例见快速开始。笛卡尔 SERVO 形态如下：

```Python
from arm_p7_sdk import AirbotClient, CartesianMoveOptions, CartesianPose, Controller

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        pose = client.get_end_pose()
        if pose is None:
            raise RuntimeError("Failed to read end pose")

        target = CartesianPose(
            position=(pose.position[0] + 0.055, pose.position[1], pose.position[2]),
            orientation=pose.orientation,
        )

        if not client.switch_controller(Controller.servo_control):
            raise RuntimeError("Failed to switch controller")

        ok = client.move_end_pose(
            pos=target,
            options=CartesianMoveOptions(blocking=True),
            timeout_ms=3000,
        )
        print("cartesian SERVO:", ok)
    finally:
        try:
            client.switch_controller(Controller.idle)
        except Exception:
            pass
        client.release_control()
```

### LIN

直线运动使用专用接口 `move_end_pose_linear()`，通常在 `Controller.planning_control` 下使用：

```Python
from arm_p7_sdk import AirbotClient, CartesianMoveOptions, CartesianPose, Controller

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        start = client.get_end_pose()
        if start is None:
            raise RuntimeError("Failed to read start pose")

        target = CartesianPose(
            position=(start.position[0] + 0.02, start.position[1], start.position[2]),
            orientation=start.orientation,
        )

        if not client.switch_controller(Controller.planning_control):
            raise RuntimeError("Failed to switch controller")

        ok = client.move_end_pose_linear(
            start=start,
            target=target,
            options=CartesianMoveOptions(
                velocity_scaling_factor=0.1,
                acceleration_scaling_factor=0.1,
                allow_planning_time=5.0,
                blocking=True,
            ),
            timeout_ms=10000,
        )
        print("LIN:", ok)
    finally:
        try:
            client.switch_controller(Controller.idle)
        except Exception:
            pass
        client.release_control()
```

### CIRCLE

圆弧运动使用 `move_end_pose_circle(start, path, target, options)`：

- `start`：圆弧起点位姿。

- `path`：圆弧中间参考位姿，或在 `options.circ_is_center=True` 时作为圆心参考。

- `target`：圆弧终点位姿。

- `timeout_ms` 默认 `3000`。

```Python
from arm_p7_sdk import AirbotClient, CartesianMoveOptions, CartesianPose, Controller

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        start = client.get_end_pose()
        if start is None:
            raise RuntimeError("Failed to read start pose")

        path = CartesianPose(
            position=(start.position[0] + 0.01, start.position[1] + 0.01, start.position[2]),
            orientation=start.orientation,
        )
        target = CartesianPose(
            position=(start.position[0] + 0.02, start.position[1], start.position[2]),
            orientation=start.orientation,
        )

        if not client.switch_controller(Controller.planning_control):
            raise RuntimeError("Failed to switch controller")

        ok = client.move_end_pose_circle(
            start=start,
            path=path,
            target=target,
            options=CartesianMoveOptions(
                circ_is_center=False,
                velocity_scaling_factor=0.1,
                acceleration_scaling_factor=0.1,
                allow_planning_time=5.0,
                blocking=True,
            ),
            timeout_ms=10000,
        )
        print("CIRCLE:", ok)
    finally:
        try:
            client.switch_controller(Controller.idle)
        except Exception:
            pass
        client.release_control()
```

### WAYPOINTS

路点接口至少需要 2 个 waypoint。关节路点每个 waypoint 必须是 7 维 `list[float]`，笛卡尔路点每个 waypoint 必须是 `CartesianPose`。

```Python
from arm_p7_sdk import (
    ARM_JOINT_LIMITS,
    AirbotClient,
    Controller,
    JointWaypointsMoveOptions,
)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        state = client.get_arm_joint_state()
        if state is None:
            raise RuntimeError("Failed to read joint state")

        wp1 = list(state.angles)
        wp2 = list(state.angles)
        wp3 = list(state.angles)
        low, high = ARM_JOINT_LIMITS[0]
        wp2[0] = clamp(wp2[0] + 0.03, low, high)
        wp3[0] = clamp(wp3[0] - 0.03, low, high)

        if not client.switch_controller(Controller.planning_control):
            raise RuntimeError("Failed to switch controller")

        ok = client.move_joint_waypoints(
            waypoints=[wp1, wp2, wp3],
            options=JointWaypointsMoveOptions(
                motion_type="ptp",
                enable_blend=True,
                min_blend_radius=0.005,
                velocity_scaling_factor=0.1,
                acceleration_scaling_factor=0.1,
                allow_planning_time=5.0,
                blocking=True,
            ),
            timeout_ms=15000,
        )
        print("joint WAYPOINTS:", ok)
    finally:
        try:
            client.switch_controller(Controller.idle)
        except Exception:
            pass
        client.release_control()
```

### MIT

MIT / force\-style 控制风险高，参数不合理可能导致抖动、冲击或设备损伤。只建议在明确理解机械臂动力学边界、现场具备急停条件时使用。

当前 `move_joint()` 在 `Controller.mit_control` 下会发送：

- `position=pos`

- `velocity=list(self._arm_motor_speed)`

- `torque=options.torque`，长度不是 7 时当前 SDK 侧会回退为 7 个 `0.0`

- `kp=options.kp`，长度不是 7 时当前 SDK 侧会回退为 7 个 `0.0`

- `kd=options.kd`，长度不是 7 时当前 SDK 侧会回退为 7 个 `0.0`

MIT 调用形态：

```Python
from arm_p7_sdk import AirbotClient, Controller, JointMoveOptions

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        state = client.get_arm_joint_state()
        if state is None:
            raise RuntimeError("Failed to read joint state")

        if not client.switch_controller(Controller.mit_control):
            raise RuntimeError("Failed to switch controller")

        ok = client.move_joint(
            pos=list(state.angles),
            options=JointMoveOptions(
                torque=[0.0] * 7,
                kp=[0.0] * 7,
                kd=[0.0] * 7,
            ),
            timeout_ms=1000,
        )
        print("MIT command accepted:", ok)
    finally:
        try:
            client.switch_controller(Controller.idle)
        except Exception:
            pass
        client.release_control()
```

## 末端控制

### 查询是否存在 EEF

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(host="127.0.0.1", port=50071) as client:
    mode = client.get_eef_mode()
    if not mode or not mode.get("has_eef"):
        print("No EEF")
```

也可以通过固件信息判断：

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(host="127.0.0.1", port=50071) as client:
    firmware = client.get_firmware_info()
    if firmware is not None:
        print("eef_type:", firmware.eef_type)
```

### EEF CSP

CSP 是末端位置控制模式：

```Python
from arm_p7_sdk import AirbotClient, EEFControlMode, EEFMoveOptions

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        if not client.switch_eef_control_mode(EEFControlMode.csp):
            raise RuntimeError("Failed to switch EEF mode")

        client.set_eef_speed(100.0)
        ok = client.move_eef(
            pos=[10.0],
            options=EEFMoveOptions(eff=[5.0], blocking=True),
            timeout_ms=3000,
        )
        print("EEF CSP:", ok)
    finally:
        try:
            client.switch_eef_control_mode(EEFControlMode.idle)
        except Exception:
            pass
        client.release_control()
```

对多自由度 EEF，`pos` 和 `eff` 都必须按运行时 DOF 扩展，例如 `[10.0, 10.0]`。

SDK 侧会按固件报告的 EEF 类型对位置做已知范围裁剪：

|EEF 类型|位置范围 `mm`|
|---|---|
|`G2`|`[0.0, 72.0]`|
|`G2L`|`[0.0, 100.0]`|
|`G2P`|`[0.0, 95.0]`|

未知 EEF 类型当前 SDK 侧只记录 warning，不做范围裁剪。

### EEF MIT

末端 MIT 使用 `EEFControlMode.mit`，`pos` 仍是 `mm`，`torque/kp/kd` 必须是列表并匹配运行时 EEF DOF：

```Python
from arm_p7_sdk import AirbotClient, EEFControlMode, EEFMoveOptions

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("Failed to acquire control")

    try:
        if not client.switch_eef_control_mode(EEFControlMode.mit):
            raise RuntimeError("Failed to switch EEF mode")

        ok = client.move_eef(
            pos=[10.0],
            options=EEFMoveOptions(
                torque=[0.0],
                kp=[0.0],
                kd=[0.0],
                blocking=False,
            ),
            timeout_ms=1000,
        )
        print("EEF MIT:", ok)
    finally:
        try:
            client.switch_eef_control_mode(EEFControlMode.idle)
        except Exception:
            pass
        client.release_control()
```

末端 MIT 同样属于高风险低层控制路径，业务应用优先使用 CSP。

## CLI examples 使用

安装后可使用 CLI：

```Bash
arm-p7-sdk version
arm-p7-sdk examples list
```

运行示例：

```Bash
arm-p7-sdk examples run airbot_example_get_service_states -- --host 127.0.0.1 --port 50071 --duration-s 2
arm-p7-sdk examples run airbot_example_get_arm_joint_states -- --host 127.0.0.1 --port 50071 --duration-s 2
arm-p7-sdk examples run airbot_example_move_joint_PTP -- --host 127.0.0.1 --port 50071 --pos "0,0,0,0,0,0,0"
arm-p7-sdk examples run airbot_example_move_joint_SERVO -- --host 127.0.0.1 --port 50071
```

查看单个示例参数：

```Bash
arm-p7-sdk examples run airbot_example_move_joint_PTP -- --help
```

所有 example 都通过统一的 transport 参数创建 client：

- gRPC：`--backend grpc --host <host> --port 50071`

- DDS：`--backend dds --domain-id 0 --side none --participant-name <name> --default-timeout-ms 3000`

## 开发板离线安装包

仓库提供嵌入式开发板端离线安装包，目标环境固定为：

- 架构：`aarch64` / `arm64`

- Python：`3.10.x`

- `cora` 私有 wheel：默认使用 `cora-1.2.2+20260617084411-cp310-cp310-linux_aarch64.whl`

- `sdk-board-bundle-arm_p7_sdk-<version>-py3-none-any-<timestamp>.tar.gz`

拷贝到开发板并安装：

```Bash
scp dist/sdk-board-bundle-arm_p7_sdk-*.tar.gz user@BOARD_IP:/tmp/
ssh user@BOARD_IP
cd /tmp
tar -xzf sdk-board-bundle-arm_p7_sdk-*.tar.gz
sudo ./sdk-board-bundle/install.sh
```

`bundle/install.sh` 当前会执行以下检查和安装步骤：

- 检查 `uname -m` 必须是 `aarch64` 或 `arm64`。

- 检查 `python3` 必须是 `3.10.x`，可用 `PYTHON_BIN=/path/to/python3` 覆盖。

- 检查 `wheelhouse/` 和 `requirements-board.lock` 存在。

- 从离线 `wheelhouse` 引导/安装 `pip setuptools wheel`。

- 使用 `--no-index --find-links wheelhouse -r requirements-board.lock` 离线安装。

- 运行 `smoke_test.py`，该 smoke test 会导入 `cora`、`cora.msg.arm_msgs`、`arm_p7_sdk` 和 `AirbotClient`，但不会连接真实机械臂。

## 当前限制与常见问题

### `timeout_ms` 不是运动总时长

`timeout_ms` 是请求/RPC 等待超时或后端请求参数，不等于轨迹规划和执行的总时长。尤其在 `blocking=False` 时，接口返回 `True` 通常只表示命令被接受或请求触发成功。

在 DDS backend 中，`timeout_ms` 会作为本次 DDS RPC 调用超时；未传时使用 `default_timeout_ms`。gRPC backend 中该参数是否影响服务端等待行为依赖 route service 实现。无论哪种 backend，都不要把它当作“机械臂必须在该时间内运动完成”的保证。

### `blocking=True` 会改变返回时机

许多运动 options 都有 `blocking` 字段：

- `blocking=False`：通常表示请求被接受后尽快返回。

- `blocking=True`：请求会带上阻塞语义，服务端可能等待规划/执行结束后再返回。

具体等待到哪个阶段，依赖服务端实现和当前控制路径。应用侧仍应检查返回值，并根据需要继续读取状态确认。

### 控制类接口需要控制权

`switch_controller()`、`move_joint()`、`move_end_pose()`、`move_eef()`、`set_arm_emergency_stop()` 等控制类接口都需要控制权。SDK 可能自动尝试 acquire，但推荐业务代码显式调用：

```Python
from arm_p7_sdk import AirbotClient

with AirbotClient(host="127.0.0.1", port=50071) as client:
    if not client.acquire_control():
        raise RuntimeError("another client may be controlling")
```

### 先切 controller / EEF mode，再发命令

常见正确顺序：

- 机械臂规划：`acquire_control()` \-\> `switch_controller(Controller.planning_control)` \-\> `move_joint()` / `move_end_pose*()`。

- 机械臂伺服：`acquire_control()` \-\> `switch_controller(Controller.servo_control)` \-\> 连续小步 `move_joint()` / `move_end_pose()`。

- 末端执行器位置：`acquire_control()` \-\> `switch_eef_control_mode(EEFControlMode.csp)` \-\> `move_eef()`。

如果 controller 或 EEF mode 仍在 idle，SDK 会拒绝对应运动命令并返回 `False`。

### 路点至少需要 2 个 waypoint

`move_joint_waypoints()` 和 `move_end_pose_waypoints()` 都要求 `len(waypoints) >= 2`。每个关节 waypoint 必须是 7 维列表，每个笛卡尔 waypoint 必须是 `CartesianPose`。

### seed 开启后必须满足 7 轴长度和关节限位

当 `has_seed_start=True` 或 `has_seed_goal=True` 时，`seed_start` / `seed_goal` 必须是 7 维关节列表，并且每一项都在 SDK 命令限位内。未开启 seed 时，对应 seed 列表会被忽略。

### EEF DOF 来自运行时

不要假设 EEF 永远是一维。`move_eef()` 会根据运行时 `eef_dof` 校验：

- `pos` 长度必须匹配。

- CSP 模式下 `eff` 长度必须匹配。

- MIT 模式下 `torque/kp/kd` 长度必须匹配。

如果服务端报告 `eef_dof=0`，或 joint state 中没有 EEF 关节，`move_eef()` 会返回 `False`，`get_eef_joint_state()` 可能返回 `None`。

### 当前清电机错误接口不支持

`clear_eef_motor_err()` 和 `clear_arm_motor_err()` 当前后端都没有暴露对应 route 能力，会抛出 `UnsupportedOperationError`。普通恢复流程请使用：

- `clear_error()`：清 FSM unknown\-error 状态。

- `set_arm_emergency_stop(False)`：急停复位。

电机级错误清除是否可用依赖后续后端和服务端实现。

### gRPC 连接失败

检查：

- `host` 是否可解析或可访问。

- `port` 是否为当前服务端口，SDK 默认是 `50071`。

- 机械臂服务 / `arm-grpc-route` 是否启动。

- 防火墙或容器网络是否阻断连接。

gRPC backend 构造时会等待 channel ready，当前 SDK 侧连接等待约 3 秒；失败会抛出 `ConnectionError`。

### DDS 连接失败

检查：

- 当前 Python 环境是否安装私有 `cora` SDK。

- `domain_id` 是否和 `dds_route_node` 一致。

- `side` 是否映射到正确命名空间。

- DDS discovery 是否需要更多时间。

- `use_shared_memory` / `use_udp` 是否符合部署环境。

如果没有安装 `cora`，创建 DDS backend 会抛出 `ConnectionError`，提示使用默认 gRPC backend 或安装 `cora`。

## 附录：灯效说明

|状态|灯效|
|---|---|
|抱闸，机械臂内部服务程序 `robot_app` 未启动|白色常亮|
|抱闸，机械臂内部服务程序已启动，控制服务处于 `IDLE` 状态|黄色常亮|
|抱闸，机械臂内部服务程序 `robot_app` 启动中|黄色呼吸|
|解抱闸，机械臂处于伺服控制模式，控制服务处于 `SERVO_CONTROL` 状态|绿色常亮|
|解抱闸，示教重放功能，机械臂处于伺服模式，进入重放准备状态|绿色呼吸|
|解抱闸，示教重放功能，机械臂处于伺服模式，回到初始点|绿色常亮|
|解抱闸，示教重放功能，机械臂处于伺服模式，重放中|绿色流水|
|解抱闸，机械臂处于重力补偿模式，控制服务处于 `GRAVITY_COMPENSATION` 状态|青色常亮|
|解抱闸，示教重放功能，机械臂处于重力补偿模式，正在录制|青色流水|
|解抱闸，机械臂处于位置控制模式，控制服务处于 `POSITION_CONTROL` 状态|灰绿常亮|
|解抱闸，机械臂处于力控模式，控制服务处于 `FORCE_CONTROL` 状态|紫色常亮|
|解抱闸，机械臂处于未知错误，控制服务处于 `UNKNOWN_ERROR` 状态|粉红常亮|
