# Relpose Action 转换器实现记录

## 2026-06-30 18:11 CST — 本机/训练服务器可完成的转换器边界

检查人：agent Codex

### 目的

确认在不处理真机网络、控制通道和固件升级的前提下，哪些问题能通过本机代码和训练服务器代码直接解决；并实现一个与训练转换器对齐的纯本地 action 转换器。

### 结论

可以直接写转换器。转换器只依赖以下确定事实，不依赖机器人控制链路是否已打通：

| 层 | 当前是否可在本机/训练服务器解决 | 处理内容 | 证据/产物 |
|---|---:|---|---|
| 训练动作语义 | 是 | 确认 action 前 14 维为双臂 TCP-local relpose + gripper | 远端 `scripts/vio_preview_converter.py` |
| policy 输出切片 | 是 | `actions` 可为 `(50, 32)`，执行侧只取前 14 维 | `split_dual_arm_action()` 接受 padded policy row |
| TCP relpose 积分 | 是 | `current TCP pose + local Δpos/Δrotvec -> absolute TCP target`，quaternion 为 `xyzw` 且 `w>=0` | `integrate_tcp_local_delta()` |
| horizon 解释 | 是 | chunk 内每一行都相对同一个观测时刻 TCP pose，不做行间串联 | `convert_action_chunk()` 单测覆盖 |
| 夹爪单位 | 是 | 模型 0=闭合、100=最大打开；可转 ratio、G2P 米、P7 SDK 毫米 | `gripper_target_from_model_value()` |
| 传输适配 | 部分是 | 可先输出通道无关 target；当前主线接 Arm-P7 SDK gRPC，不接 DDS | `DualArmTcpTarget` |
| 真机当前 TCP pose 获取 | 暂不能完全本地解决 | 当前主线用 SDK `get_end_pose()`；需要先装 SDK 并连通 50071 gRPC 服务 | 受 SDK/service/network 部署影响 |
| 控制下发与 ack | 暂不能本地解决 | 需要 SDK 控制权、`servo_control`、限幅、急停、超时/释放控制权策略 | 当前 SDK/service 未就绪，见 `p7-sdk-grpc-current-state.md` |
| SDK / gRPC 服务部署 | 暂不能本地解决 | 安装 `arm_p7_sdk`，启动/开放 Arm-P7 gRPC 服务端口 50071 | 需要机器人侧部署权限和流程 |

### 训练服务器证据

只读连接训练服务器：

```bash
ssh maxliu-h200-qinghua-1 'cd /home/maxliu/projects/VIO_Test/Openpi_RL && grep -n "def _relative_pose_action\|dp_local\|dr_local" scripts/vio_preview_converter.py'
```

关键输出：

```text
358:def _relative_pose_action(cur_p: np.ndarray, cur_r: Rotation, fut_p: np.ndarray, fut_r: Rotation) -> np.ndarray:
359:    dp_local = cur_r.inv().apply(fut_p - cur_p)
360:    dr_local = (cur_r.inv() * fut_r).as_rotvec()
361:    return np.concatenate([dp_local, dr_local])
```

只读确认 state/action 维度：

```bash
ssh maxliu-h200-qinghua-1 'cd /home/maxliu/projects/VIO_Test/Openpi_RL && grep -n "states = np.zeros" scripts/vio_preview_converter.py'
ssh maxliu-h200-qinghua-1 'cd /home/maxliu/projects/VIO_Test/Openpi_RL && grep -n "STATE_KEYS\|ACTION_KEYS\|state =\|actions =\|state_arr\|action_window\|horizon\|left_gripper\|right_gripper" scripts/vio_preview_converter.py'
```

关键输出：

```text
417:    states = np.zeros((sample_times.size, 16), dtype=np.float32)
418:    actions = np.zeros((sample_times.size, horizon, 14), dtype=np.float32)
```

只读确认 quaternion 归一化规则：

```bash
ssh maxliu-h200-qinghua-1 'cd /home/maxliu/projects/VIO_Test/Openpi_RL && grep -n "def _normalize_quat_xyzw" -A10 scripts/vio_preview_converter.py'
```

关键输出：

```text
87:def _normalize_quat_xyzw(quat: np.ndarray) -> np.ndarray:
92-    quat = quat / norm
93-    if quat[3] < 0:
94-        quat = -quat
95-    return quat
```

本地转换器也采用相同的 `xyzw` 顺序、单位化和 `w >= 0` canonical quaternion 约定。

只读确认 horizon 每一步的构造方式：

```bash
ssh maxliu-h200-qinghua-1 'cd /home/maxliu/projects/VIO_Test/Openpi_RL && sed -n "418,506p" scripts/vio_preview_converter.py'
ssh maxliu-h200-qinghua-1 'cd /home/maxliu/projects/VIO_Test/Openpi_RL && sed -n "506,530p" scripts/vio_preview_converter.py'
```

关键输出等价于：每个 `hidx` 取 `future_t = timestamp + (hidx + 1) / fps`，然后用同一个 `current_pose[arm]` 计算 `rel = _relative_pose_action(cur_p, cur_r, fut_p, fut_r)`，最后写入 `actions[sidx, hidx]`。因此部署时不应把第 `i` 行 target 当成第 `i+1` 行的 current pose 去链式积分。

### 本地实现

新增纯本地模块：

- `src/openpi/shared/airbot_relpose.py`
- `src/openpi/shared/airbot_relpose_test.py`

核心 API：

| API | 输入 | 输出 | 用途 |
|---|---|---|---|
| `split_dual_arm_action(action)` | 1D action，至少 14 维，可接受 32 维 padding | 左/右臂 `ArmRelposeAction` | 从 policy row 中提取真实执行语义 |
| `integrate_tcp_local_delta(current_pose, dp_local, dr_local)` | 当前 TCP pose、局部平移、局部 rotvec | 目标 TCP pose `[x,y,z,qx,qy,qz,qw]` | 训练公式的反变换 |
| `relative_action_from_poses(current_pose, future_pose)` | 当前/未来 TCP pose | 6D relpose action | 单测和离线校验用 |
| `gripper_target_from_model_value(value)` | 模型夹爪 0-100 | ratio、G2P 米、P7 SDK 毫米 | 当前主线使用 P7 SDK 毫米输出；DDS 米制仅作历史/备选 |
| `convert_action_step(action, current_tcp_poses)` | 单行 action + 双臂当前 TCP pose | 双臂绝对 TCP target | 执行单步转换 |
| `convert_action_chunk(actions, current_tcp_poses)` | action chunk + 双臂当前 TCP pose | target list | 执行整段 chunk 转换；每行都相对同一个 current pose |

### 本地验证

```bash
uv run ruff check src/openpi/shared/airbot_relpose.py src/openpi/shared/airbot_relpose_test.py
```

关键输出：

```text
All checks passed!
```

```bash
uv run pytest src/openpi/shared/airbot_relpose_test.py
```

关键输出：

```text
collected 6 items
src/openpi/shared/airbot_relpose_test.py ......                          [100%]
6 passed in 0.03s
```

### 对启动真机的影响

这次已经把“模型输出到通道无关 TCP target”的部分落成代码并测试通过。剩下启动机械臂前仍要解决的是执行适配层，不是训练语义：

1. 从真机稳定拿到当前双臂 TCP pose：当前主线用 Arm-P7 SDK `get_end_pose()`，但 20:27 CST 检查时 SDK import 和 50071 端口都未就绪。
2. 选定唯一控制通道：当前唯一主线是 SDK gRPC，`move_end_pose()` 下发完整目标 TCP pose，`move_eef()` 下发夹爪 mm。
3. 控制安全层：限幅、频率、`acquire_control()` / `release_control()`、`servo_control` 状态、急停、ack/超时。
4. 网络链路：确认 robot IP/port，让 `AirbotClient(host, port=50071, backend="grpc")` 能完成 no-motion 读状态。

本次没有向机器人发布任何控制消息。


## 2026-06-30 19:47 CST — 飞书 VIO 文档同步

按用户要求，将本地转换器实现状态同步到飞书 VIO 文档 `Uc7GdKUSmoYYHOxZPCPcHADRnMI`，仍采用原文修改方式。

- 执行方式：`lark-cli docs +update --command block_replace`。
- 修改范围：`当前结论` 中的 action 语义、`坐标系约定` 中的转换公式、`还缺什么` 中的转换器状态、`证据来源` 中的本地实现和测试记录。
- 写入结果：revision 从 `27` 更新到 `31`。
- 读回验证：`docs +fetch --scope outline --max-depth 2` 仍只有原 5 个 H1；关键词读取可见 `转换器`、`DualArmTcpTarget`、`w >= 0`、`pytest 6 passed`。

本次没有向机器人发布任何控制消息。


## 2026-06-30 19:53 CST — 飞书 VIO 文档结构性扩充

用户指出“不是不让新增章节，凡是有必要的信息都需要写进去”。据此将飞书 VIO 文档从简单状态记录扩充为更可执行的对齐文档。

- 目标文档：`Uc7GdKUSmoYYHOxZPCPcHADRnMI`。
- 新增 H1：`模型与转换器 I/O 契约`、`转换器已完成的处理`、`本机可解决 / 真机待解决边界`。
- 改写 `还缺什么`：当时从 5 条粗待办改为 P0/P1 清单，覆盖有线 DDS、唯一控制通道、当前 TCP pose 来源、安全壳、控制适配器、真机验证顺序；20:27 CST 后已被 SDK gRPC P0/P1 覆盖。
- 扩充 `证据来源`：补入训练服务器只读证据路径 `maxliu-h200-qinghua-1:/home/maxliu/projects/VIO_Test/Openpi_RL/scripts/vio_preview_converter.py`，以及 `states=(N,16)`、`actions=(N,horizon,14)`、relpose 公式、quaternion `w>=0`。
- 读回验证：outline 显示新增 3 个 H1；`坐标系约定` section 原文仍保留；revision 更新到 `36`。

本次没有向机器人发布任何控制消息。


## 2026-06-30 20:27 CST — 当前下发通道改为 Arm-P7 SDK gRPC

按用户最新指令，转换器后续不再接 DDS Route 或裸 DDS/FSM topic。转换器本身保持不变：它只负责把模型输出的 TCP-local relpose 转成通道无关 `DualArmTcpTarget`。

执行适配层改为：

1. 用 SDK `get_end_pose()` 读取当前 TCP pose。
2. 用本地转换器把 action 积分成绝对目标 TCP pose。
3. 用 SDK `move_end_pose(CartesianPose(...))` 下发完整目标 pose。
4. 用 SDK `move_eef(pos=[mm])` 下发夹爪，模型 0=闭合、100=最大打开。

当前阻塞不在转换器，而在 SDK/service：20:27 CST 只读检查显示本机和 X5 都不能 `import arm_p7_sdk`，`172.100.10.159:50071` refused，`192.168.25.1:50071` timeout。详见 [p7-sdk-grpc-current-state.md](p7-sdk-grpc-current-state.md)。本次没有向机器人发布任何控制消息。
