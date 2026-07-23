# 训练模型与真机 I/O 对齐表

日期：2026-06-30；检查人：agent。
目的：从 checkpoint、训练转换器、policy transform、模型前向和 AIRBOT 控制接口出发，列清楚现有
`pi05_vio_plant_collection` 推理请求需要什么、机器人回传什么、动作要怎样转成机械臂命令。

## 0. 本轮结论

当前 checkpoint 已经训练好，不需要再训练。推理时仍要给 policy 一个 observation，但这个 observation
不是“训练输入重放”：当前 PI05 checkpoint **不消费真实 state 数值**，只需要保留 `state` 键让 transforms
通过。真实闭环的关键在执行侧：拿到模型输出的 TCP relpose action 后，如何用当前 TCP pose 把它积分成机械臂 servo 命令。固定手眼外参不属于默认 TCP→TCP 路线，只在改走 VIO 相机 pose 参考时才需要。

最小 policy 请求是：三路 RGB 图像 + `prompt` + `state=np.zeros(16, np.float32)`。当前 TCP/末端 pose、关节角和夹爪反馈仍然有用，但它们是 action 执行/安全限幅/FK 的输入，不是当前 policy 的条件输入。

夹爪侧按用户确认更新：模型里的夹爪动作值是 **0-100 原始开合值**，开到最大为 `100`，闭合为 `0`。`norm_stats` 中夹爪均值约 `95/76` 正好支持这个量纲。若最终底层命令接口收 `0.0-0.096m` 的 G2P 行程，再在输出端做线性转换；不要把米制值直接当成模型夹爪值。

## 1. 证据

可复现命令：

```bash
python3 - <<'PY'
import json
from pathlib import Path
p=Path('checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/assets/vio_plant_collection_30hz_relpose/norm_stats.json')
d=json.load(p.open())['norm_stats']
for key in ['state','actions']:
    mean=d[key]['mean']; std=d[key]['std']
    nz=[i for i,x in enumerate(mean) if abs(float(x))>1e-12]
    print(key, 'len', len(mean), 'effective', max(nz)+1)
    print('mean_first20=', [round(float(x),6) for x in mean[:20]])
    print('std_first20=', [round(float(x),6) for x in std[:20]])
PY
```

关键输出：

```text
state len 32 effective 16
mean_first20= [..., 95.341217, 76.906525, 0.0, 0.0, 0.0, 0.0]
actions len 32 effective 14
mean_first20= [..., 95.307518, ..., 76.848381, 0.0, 0.0, 0.0, 0.0]
```

代码/训练证据：
- `src/openpi/training/config.py` 中 `pi05_vio_plant_collection` 显式 `discrete_state_input=False`。
- `src/openpi/policies/airbot_policy.py` 的 `AirbotInputs` 仍会读取 `data["state"]` 并 pad 到 32，所以请求必须有 `state` 键。
- `src/openpi/models/pi0.py` 只在 **非 PI05/PI06** 分支添加 continuous state token；当前模型是 PI05，所以真实 state 数值不进入该分支。
- 已有 checkpoint 实测记录：同图像、同 prompt、同 fixed noise 下，`state=zeros(16)` 与极端 state 输出 `max_abs_diff 0.0`。
- 训练/数据语义按当前确认收敛为 TCP pose：action 是每臂 TCP 局部系 `Δpos + Δrotvec + future_gripper`。本地 `vio_preview_converter.py` 的 pose topic 名包含 `camera`，但上游预处理文档记录曾将 camera pose 通过 `CAMERA_T_TCP` 写成 TCP pose；不能再把 topic 名直接当成 action frame 结论。

当前真机在线状态补充：本轮尝试本地 DDS 只读探测，`ros2 topic list` 只返回 `/parameter_events`、`/rosout`，`ping 192.168.25.1` 超时；因此本轮没有获得新的在线真机 topic 证据。真机 topic 结论沿用此前已落盘实测记录。

## 2. 输入 policy：当前 observation 怎么组

| 字段 | 当前 policy 需要 | 真机来源 | 必要处理 | 当前状态 |
|---|---|---|---|---|
| `prompt` | 任务文本 | 人给定，例如采集任务名 | 原样传字符串；不要留空 | 已明确 |
| `base_0_rgb` | RGB `uint8`，头部左目 | `/camera/head_left/image_rect` 或 `video_encoded` | nv12/H264 解码成 RGB HWC；server 内部会 `resize_with_pad(224,224)` | topic 此前已实测存在 |
| `left_wrist_0_rgb` | RGB `uint8`，左腕左目 | `/camera/left_arm_left/image_rect` 或 `video_encoded` | 同上；不要 BGR/RGB 反了 | topic 此前已实测存在 |
| `right_wrist_0_rgb` | RGB `uint8`，右腕左目 | `/camera/right_arm_left/image_rect` 或 `video_encoded` | 同上 | topic 此前已实测存在 |
| `state` | 占位即可，建议 `np.zeros(16, np.float32)` | 不需要真实真机 state | 只为 `AirbotInputs -> pad_to_dim(32)` 通过；不要为了 policy 去阻塞相机 pose | 已确认 |

服务端内部会做：`AirbotInputs` 整理图像和 pad state；`Normalize` 用 checkpoint 内 `norm_stats`；PI05 model transform 再 resize/tokenize/pad。客户端不应自己归一化。

## 3. 执行侧还需要哪些真机回传

这些量不喂给当前 policy，但把 relpose action 变成机械臂命令时需要。

| 真机/计算量 | 用途 | 必要处理 | 当前状态 |
|---|---|---|---|
| 当前 TCP pose | 将相对 `Δpos/Δrotvec` 还原成绝对 TCP 目标 pose | 可来自 SDK/AIRRTM 反馈、FSM `cartesian_state`，或 `joint_states -> FK`；这里不是手眼外参 | 待确认最可靠来源 |
| 固定手眼外参 `T_eef_cam` | 默认 TCP→TCP 路线不需要；仅在“用 VIO 相机 pose 作为执行参考、但控制接口收 TCP pose”时用于相机 pose ↔ 末端 pose | 若后续选择相机参考路线，再单独标定/确认；AIRRTM/SDK `servo_pose` 路线默认按夹爪末端/TCP pose 控制，不套用截图里的 `cam2tcp/cam2imu` | 备选路线条件项 |
| `/arm/*/control/joint_states` 的 7 关节 | FK、限幅、安全监控、servo 初始关节 | 不能直接当 policy state；可用于执行侧 pose | 此前实测可得 |
| 夹爪反馈 | 记录/安全/必要时作为下一步执行参考 | 模型动作是 `0-100`；若反馈是 G2P m，则 `g_model = 100 * g_m / 0.096` | 用户确认开=100、闭=0 |
| `/arm/*/fsm/state`、ack | 控制状态门禁 | 发 servo 前确认 SERVO_CONTROL | 此前实测有 topic |

## 4. 模型输出怎么变成机械臂命令

| 模型输出 | 含义 | 机械臂需要 | 必要处理 |
|---|---|---|---|
| `actions.shape=(50,32)` | 50 步 action chunk，32 是网络 pad 维 | 机械臂只要当前要执行的一步 | 每步取 `actions[i,:14]`，后 18 维丢掉 |
| `a[0:7]` | 左臂动作 | 左臂 pose servo + gripper | 拆成 `Δpos[0:3]`、`Δrotvec[3:6]`、`gripper[6]` |
| `a[7:14]` | 右臂动作 | 右臂 pose servo + gripper | 同上 |
| 每臂 `Δpos` | 当前按 TCP 局部系位置增量处理，m | TCP 目标位置，m | 默认：`target_tcp_p = cur_tcp_p + cur_tcp_R.apply(Δpos)` |
| 每臂 `Δrotvec` | 当前按 TCP 局部系旋转增量处理，轴角 | TCP 目标四元数 | 默认：`target_tcp_R = cur_tcp_R * Rotation.from_rotvec(Δrotvec)` |
| 每臂 `gripper` | 未来夹爪绝对值 `0-100`，开=100、闭=0 | SDK 夹爪命令 | 当前 Arm-P7 SDK 公共接口单位是 mm；按 EEF range 转成 mm 后 `move_eef(pos=[...])` |
| TCP/EEF 目标 pose | 当前 Arm-P7 SDK gRPC 路线的目标末端 pose | `CartesianPose(position, orientation)` + `move_end_pose()` | SDK 控制坐标系应是夹爪末端/TCP；默认不使用截图里的 `cam2tcp/cam2imu` |
| `target_cam_pose` | 仅当后续选择 VIO 相机 pose 参考路线时使用 | 仍需再换成 EEF/TCP pose | 若 `T_eef_cam` 定义为 EEF→camera，才使用 `T_world_eef_target = T_world_cam_target @ inv(T_eef_cam)`；不要未经验证硬编码 |

当前优先控制入口已改为 Arm-P7 SDK gRPC：`get_end_pose()` 读当前 TCP pose，`move_end_pose(CartesianPose(...))` 下发完整目标 TCP pose，`move_eef(pos=[mm])` 下发夹爪。X5/SDK 内部负责 servo/IK；本地不必先求 7 关节目标。只有未来改选 joint command 路线时，才需要 IK 或已有 joint target。

## 5. 还缺什么

1. 当前 TCP pose 来源：Arm-P7 SDK `get_end_pose()`；20:27 CST 检查时 SDK import 和 50071 端口还未就绪。
2. `CartesianPose` 的 base/world frame 定义，以及左右臂 pose 是否和训练 TCP pose 使用同一坐标系。
3. 输出端 adapter：`DualArmTcpTarget -> CartesianPose + move_end_pose()`；夹爪 `0-100 -> mm + move_eef()`。
4. 真机安全验证：确认 SDK `orientation=(qx,qy,qz,qw)`、`servo_control` 切换流程、控制权 acquire/release、夹爪 EEF range、限幅/速度/急停。
5. 只有未来改走 VIO 相机 pose 参考路线时，才需要重新确认/标定固定手眼外参 `T_eef_cam`。
