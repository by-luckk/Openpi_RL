# Repo 与推理输入的第一性原理检查

> 日期：2026-06-30；检查人：Codex。
> 目的：回答“当前 repo 在做什么、需要输入什么数据才能 inference”，并用当前代码、checkpoint、转换器证据核对。

## 1. Repo 在做什么

本仓库是 OpenPI 策略/VF 训练与 AIRBOT 示例部署仓库，主要分三层：

1. `src/openpi/`：模型、训练配置、policy transforms、WebSocket policy serving 的核心代码。
2. `scripts/` 与 `scripts/cmds/`：训练、统计、policy serving、推理脚本封装。
3. `examples/airbot/`：AIRBOT 示例 I/O，包括 MCAP 转 LeRobot、DAgger 录制、同步/异步推理客户端。

当前可用部署不是泛化的“任意 AIRBOT 关节模型”，而是：

```bash
POLICY_CONFIG=pi05_vio_plant_collection
CHECKPOINT_DIR=checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000
```

`scripts/serve_policy.py` 加载该 config/checkpoint 后，在 WebSocket `:8000` 接收 observation，返回 action chunk。

## 2. 第一性原理：inference 到底需要什么

Policy inference 的基本形式是：

```text
observation_t  --transforms/normalize/tokenize-->  model.sample_actions()
              <--unnormalize/output transforms--  actions_{t:t+H}
```

所以推理输入先要满足**代码接口**，再看哪些字段真的被模型消费。对当前
`pi05_vio_plant_collection` checkpoint，外部 client 发给 server 的最小 observation 是：

```python
{
    "state": np.zeros(16, dtype=np.float32),  # 占位即可；当前 checkpoint 不消费 state 数值
    "base_0_rgb": np.ndarray(shape=(H, W, 3), dtype=np.uint8),        # RGB
    "left_wrist_0_rgb": np.ndarray(shape=(H, W, 3), dtype=np.uint8),  # RGB
    "right_wrist_0_rgb": np.ndarray(shape=(H, W, 3), dtype=np.uint8), # RGB
    "prompt": "Fold clothes",
}
```

说明：

- `state` 键仍必需，因为 `AirbotInputs` 会读取并 pad 到 32 维；但当前训练配置 `discrete_state_input=False`，PI05 模型没有 continuous state token，实测 state 数值不影响输出。
- 图像可传 HWC RGB uint8；`ResizeImages(224, 224)` 会在 server transform 中 resize/pad 到 224。
- `prompt` 必填；当前示例客户端传 `advantage=True`，但 PI05 配置不是 advantage-conditioned，`Observation.from_dict()` 不读取该字段，故它不是必要输入。
- server 返回 `actions` 形状为 `(50, 32)`；真实有效动作取前 14 维。

## 3. 当前 checkpoint 的真实 I/O 语义

当前 checkpoint 是 **VIO relpose 模型**，不是关节空间模型。

### 训练数据 State: 16 维

```text
[0:3]    left wrist camera position xyz
[3:7]    left wrist camera quat xyzw
[7:10]   right wrist camera position xyz
[10:14]  right wrist camera quat xyzw
[14]     left gripper position
[15]     right gripper position
```

### Action: 每步 14 维，horizon=50

每臂 7 维：

```text
[local Δpos(3), local Δrotvec(3), gripper absolute position(1)]
```

左右臂拼接后为 14 维。相对位姿定义来自训练转换器：

```python
dp_local = cur_r.inv().apply(fut_p - cur_p)
dr_local = (cur_r.inv() * fut_r).as_rotvec()
```

执行端把某一步动作还原为绝对目标 TCP 位姿：

```python
tgt_tcp_p = cur_tcp_p + cur_tcp_r.apply(a[0:3])
tgt_tcp_r = cur_tcp_r * Rotation.from_rotvec(a[3:6])
```

这段 state/action 语义来自训练转换器；当前 policy 不消费真实 state 数值。按当前确认，训练/部署默认是 TCP pose，因此执行端若走绝对笛卡尔伺服，需要当前 TCP pose 把 relpose action 换成末端目标；固定手眼外参 `T_eef_cam` 只在备选相机 pose 路线需要。

## 4. 真机 inference 与执行分别需要什么

| 数据 | 当前 checkpoint/pipeline 的语义 | 当前机器人实测/文档状态 | 影响 |
|---|---|---|---|
| 三路图像 | policy 真实条件输入：`base_0_rgb`、`left_wrist_0_rgb`、`right_wrist_0_rgb`，RGB 左目 | 真机有 `/camera/head_left/image_rect`、`/camera/left_arm_left/image_rect`、`/camera/right_arm_left/image_rect`，nv12/H264 | 需 ROS2 订阅并转 RGB |
| `state` 键 | transform/API 必需；当前 policy 不消费数值 | 可直接传 `zeros(16)` | 不再是推理 P0 阻塞 |
| prompt | 任务文本 | 脚本默认 `"Fold clothes"` | 必填 |
| 当前 TCP pose | 执行 relpose action 时用，不是 policy 输入 | 真机无训练 pose topic；有关节状态和可能的 FK/cartesian_state/AIRRTM 反馈 | 默认需 TCP pose 来源；相机 pose 路线才需要手眼外参 |
| 夹爪反馈/命令 | action[6]/[13] 是夹爪绝对值，`0-100`，开=100、闭=0 | `joint_states` 里有 `G2P` 或夹爪反馈 | 若来源/命令是米制 G2P，换算 `g_model = 100 * g_m / 0.096` 或 `g_m = 0.096 * g_model / 100` |
| 输出执行 | TCP/末端局部相对位姿动作 | 真机控制端是末端/关节伺服 topic | 需 `arm_msgs`/AIRRTM + FSM + pose/夹爪转换 |

结论：服务端可用，模型也可推理；真机闭环缺的是 **ROS2 client/operator 适配层和执行侧动作转换**，不是 server 端模型代码，也不是 policy state 数据源。

## 5. 为什么现有 `examples/airbot` 客户端不能直接作为真机 relpose 客户端

`examples/airbot/airbot_inference_{sync,async}.py` 当前通过 `play_operator.py`：

- 采本地 V4L2 相机。
- 通过私有 `airbot_ie` / `airdc` 的 `AIRBOTPlay` gRPC 读写机器人。
- `get_qpos()` 组的是关节空间 qpos。
- `send_action()` 把每臂 7 维当成 `6 arm joints + 1 gripper` 下发。

这套代码适合关节空间 AIRBOT Play 示例，但不等于当前 `pi05_vio_plant_collection` 的 relpose I/O。真机部署应复用它的 async/TCS/recording 框架，替换 operator：

1. ROS2 订阅三路相机；policy observation 里的 `state` 传 dummy zeros。
2. 独立获取当前 TCP pose（SDK/AIRRTM 反馈、`cartesian_state` 或 FK），用于动作下发。
3. 取 `actions[:, :14]`，按 §3 或等价末端-frame 公式重构目标 pose。
4. 默认直接得到 TCP/末端目标，发 `/arm/*/fsm/servo_pose_command` 和夹爪命令；只有改走相机 pose 路线时才加 `T_eef_cam`/frame 转换。

## 6. 本轮检查命令与关键输出

```bash
rg --files -g '!docs/VIO_Test/**'
sed -n '1,260p' scripts/serve_policy.py
sed -n '259,370p' src/openpi/training/config.py
sed -n '1,280p' src/openpi/policies/airbot_policy.py
sed -n '1,360p' examples/airbot/play_operator.py
sed -n '29,41p;358,361p;482,521p' docs/VIO_Test/VIO_Test/scripts/vio_preview_converter.py
sed -n '163,198p' docs/VIO_Test/VIO_Test/scripts/vio_convert_to_lerobot.py
find checkpoints -maxdepth 5
```

关键输出：

```text
checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/
  params/
  train_state/
  assets/vio_plant_collection_30hz_relpose/
  _CHECKPOINT_METADATA
```

系统 Python 没有 numpy：

```text
python3 -c "... import numpy ..."
ModuleNotFoundError: No module named 'numpy'
```

改用 repo `.venv` 后，norm_stats 与 relpose 契约一致：

```bash
.venv/bin/python -c "...读取 norm_stats..."
```

```text
keys ['actions', 'state']
state_len 32 state_effective 16
action_len 32 action_effective 14
state_tail16_31_all_zero True
action_tail14_31_all_zero True
state_mean_14_15 [95.34121704101562, 76.90652465820312]
actions_mean_6_13 [95.3075180053711, 76.84838104248047]
```

影响：当前 checkpoint 的训练数据维度与 `vio_convert_to_lerobot.py` 声明的 `state: (16,)`、`actions: (50,14)` 对齐；server transform 仍要求 `state` 键并 pad 到 32，但本次代码/实测确认 state 数值不参与当前 PI05 policy 推理。
