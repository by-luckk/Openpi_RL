# VIO relpose 动作部署契约（TCP 默认修正版）

> 最近核对：2026-06-30（含真机实测）。
> **本文档纠正** `model-io-contract.md` §3/§4 的"关节空间"假设：`pi05_vio_plant_collection`
> checkpoint **不是关节模型，而是 6-DOF 位姿相对增量（relpose）模型**。
> 2026-06-30 后续修正：按用户确认与上游预处理记录，当前训练/部署语义默认按 **TCP pose** 处理；早期“腕部相机 frame”表述只作为备选相机路线的历史背景。
> 权威来源 = 该 checkpoint 的真实训练 pipeline：
> `docs/VIO_Test/VIO_Test/scripts/vio_preview_converter.py` 与 `vio_convert_to_lerobot.py`
> （这是单独解压的、产出 `vio_plant_collection_30hz_relpose` 数据集的那套代码）。
> 数据语义/归一化的二次佐证见 `docs/VIO_Test/VIO_Test/docs/26-06-28/26-06-28-pi05-normalization-check.md`。

---

## 0. 一句话结论

Checkpoint `checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/` 可直接推理；
`serve_policy.py` 端零改动。**当前 policy 实际条件输入是三路图像 + prompt**。请求里仍要带 `state` 键，
但这是 `AirbotInputs`/batch shape 的接口要求；由于训练配置 `discrete_state_input=False`，PI05 前向不会消费
`state` 数值，实测不同 state 输出完全一致。部署时可传 `np.zeros(16, np.float32)` 作为占位。

模型输出仍然是按训练转换器定义的 **relpose action**：每臂 `[Δpos(3), Δrotvec(3), gripper(1)]`。
按当前确认，训练用的是 **TCP pose**，所以默认部署语义是 TCP 局部系下的相对位姿增量。要把它真正发到机械臂，执行侧要解决的是“当前 TCP pose 从哪来”，而不是固定手眼外参。
这个 pose 是动作还原/下发需要的运行时数据，**不是当前 policy 的输入条件**。

真机原生只发关节角（`joint_states`）和图像，不发训练时的 pose topic（2026-06-30 实测，见 §6）。
因此闭环前置从“补 policy state”改为“补执行侧当前 TCP pose”：可用 SDK/AIRRTM 反馈、FSM `cartesian_state`，或 `joint_states -> FK`。只有未来改走 VIO 相机 pose 参考路线时，才需要固定手眼外参 `T_eef_cam`。

## 1. 训练 topic 来源（历史命名；当前 policy 不强制订阅 pose）

来自 `vio_preview_converter.py:29-41`：

```python
CAMERA_TOPICS = {
    "base_0_rgb":        "/robot/camera/head/left/video_encoded",
    "left_wrist_0_rgb":  "/robot/camera/left_wrist/left/video_encoded",
    "right_wrist_0_rgb": "/robot/camera/right_wrist/left/video_encoded",
}
POSE_TOPICS = {                                    # ← 历史 topic 名包含 camera；当前部署按 TCP pose 语义处理
    "left":  "/robot/camera/left_wrist/left/pose",
    "right": "/robot/camera/right_wrist/left/pose",
}
GRIPPER_TOPICS = {
    "left":  "/robot/left_gripper/joint_state",
    "right": "/robot/right_gripper/joint_state",
}
```

相机消息是 H264（`video_encoded`），转换器用 `av` 解码成 `rgb24`，再 `resize_with_pad` 到 **224×224**
（`vio_convert_to_lerobot.py:37-52`，`image_size` 默认 224）。推理端必须做**完全相同**的解码 + resize。

注意：`POSE_TOPICS` 的历史命名不能再单独作为“action 是相机 frame”的结论。上游预处理文档记录过 `CAMERA_T_TCP` 转换并最终写出 TCP pose；结合用户确认，默认闭环按 TCP pose 训练语义处理。

## 2. 训练数据 State 布局（16 维，权威）

来自 `vio_preview_converter.py:482-490`，拼接顺序：

```
index   含义
[0:3]   左 TCP/pose 位置 xyz                   (米，训练 pose 世界系下绝对位置)
[3:7]   左 TCP/pose 姿态四元数 (x, y, z, w)     ← scipy 约定 xyzw；w>=0 半球归一化
[7:10]  右 TCP/pose 位置 xyz
[10:14] 右 TCP/pose 姿态四元数 (x, y, z, w)
[14]    左夹爪开合值 (0-100，开=100，闭=0)
[15]    右夹爪开合值 (0-100，开=100，闭=0)
```

四元数顺序通过 `_normalize_quat_xyzw`（:87-95）与 `Rotation.from_quat/as_quat`（scipy）确认是 **xyzw**。
`AirbotInputs` 会把这 16 维 `pad_to_dim(state, 32)` 补零到 32 —— 这解释了 norm_stats 里 16 维有效、其余为 0。但当前 `pi05_vio_plant_collection` 显式 `discrete_state_input=False`，所以这些 state 数值不会进入 PI05 的 token/prefix 或 continuous suffix；推理请求可用 dummy state。

## 3. Action 布局（每步 14 维，horizon=50，权威）

来自 `vio_preview_converter.py:492-521`。每步 14 维 = 左臂 7 + 右臂 7，每臂：

```
[Δpos(3) , Δrotvec(3) , 未来夹爪绝对值(1)]
```

相对量的精确定义（`_relative_pose_action`，:358-361）—— **在“当前帧 pose 局部系”下**；按当前确认，默认部署为 TCP 局部系：

```python
dp_local = cur_r.inv().apply(fut_p - cur_p)     # 局部系位移
dr_local = (cur_r.inv() * fut_r).as_rotvec()    # 局部系旋转，轴角 rotvec（不是欧拉角！）
```

整段拼接：`左[Δp, Δrotvec, g_fut] ++ 右[Δp, Δrotvec, g_fut]`（:519-521）。

> 注意：state 的姿态是**四元数（xyzw）**，但 action 的姿态增量是 **rotvec（轴角）**，两者表示不同，别混用。

## 4. 重构公式（推理端逆变换，直接照抄）

转换器自带正反变换且训练时已验证自洽（`vio_preview_converter.py:508-511` 的 `recon_*_errors`）：

```python
from scipy.spatial.transform import Rotation
# a = 模型输出的某一步左臂 7 维; cur_tcp_p, cur_tcp_r = 当前左臂 TCP 位姿
tgt_tcp_p = cur_tcp_p + cur_tcp_r.apply(a[0:3])               # 目标 TCP 位置
tgt_tcp_r = cur_tcp_r * Rotation.from_rotvec(a[3:6])          # 目标 TCP 姿态
gripper_target = a[6]                                         # 夹爪绝对值，0-100
```

右臂同理用 `a[7:13]`、`a[13]`。

## 5. 坐标系第一性原理（命门）

- 训练数据 state 里有 pose 字段，但当前 policy 推理不消费这个 state 数值。
- action 是**当前 pose 局部系下的相对运动**，按当前确认默认是 TCP 局部系。好消息：policy 推理时无需复现训练世界原点，也无需把当前 pose 喂给模型。
- 默认 TCP→TCP 路线里，模型输出的是 TCP 该怎么相对运动，要控制的也是机械臂 TCP/末端；因此只需要当前 TCP pose 做积分，不需要固定手眼外参。
- 固定手眼外参 `T_eef_cam` 只在备选路线中出现：例如执行端拿到的是 VIO 相机 pose，但控制接口收 TCP pose，才需要 camera pose ↔ TCP pose 的转换。

## 6. 当前机器人 topic ↔ 训练 topic 的差异（已真机实测）

**实测时间 2026-06-30**，`ssh root@192.168.25.1`（ROS2 Humble，aarch64，共 185 topic）。
机器人是 **AIRBOT FSM 命名**；训练数据是 **VIO 命名**，两套不一样：

| 训练使用 / 执行可选来源 | 机器人实测现状 | 结论 |
|---|---|---|
| `/robot/camera/*_wrist/left/pose`（历史训练 pose topic 名） | **不存在任何相机 pose topic**；`grep camera\|pose` 为空 | ✅ 不阻塞当前 policy 推理；默认 TCP 路线也不需要相机 pose topic。只有按相机 pose 重构执行时才缺参考源 |
| —（关节角，训练未直接用） | `/arm/{left,right}/control/joint_states` **正常发布**：`[joint1..joint7, G2P]` = 7 关节角(rad)+夹爪行程(m)，`frame_id=base_link`，G2P effort≈-8.45 | ✅ 关节数据可得 |
| —（FK 末端位姿） | `/arm/{left,right}/fsm/cartesian_state`（类型 `arm_msgs/CartesianState`）publisher=1 但当前未持续发布（订阅者=0，`--once` 取不到） | ⚠️ FK 位姿存在但需触发；且是法兰@base_link，非相机@VIO |
| `/robot/camera/*/left/video_encoded` | `/camera/{head_left,left_arm_left,right_arm_left}/image_rect(/video_encoded)` 6 路 H264 | ✅ 取左目 + 解码 resize 对齐即可 |
| `/robot/*_gripper/joint_state` | `joint_states` 里的 `G2P` 或夹爪反馈 | ✅ 模型侧按 `0-100`（开=100，闭=0）；若真机只给米制 G2P，需线性换算 |

实测复现命令见 §9。飞书《小推车遥操作使用文档》「数采接口」节也印证：最小采集集 =
`joint_states`(state) + `control_command`(action, rad) + 6 路 H264，**通篇无 pose topic**。

### 6.1 头号阻塞改为“执行参考 pose 从哪来”

模型推理本身不再阻塞于相机 pose：请求里给 dummy state 即可。真正要决定的是如何把 relpose action 安全地变成机械臂命令。
如果走 `FsmServoPoseCommand` 这种绝对末端目标位姿接口，执行侧必须有当前参考 pose：

- **默认路（TCP pose）**：用 SDK/AIRRTM 反馈、FSM `cartesian_state`，或 `joint_states -> FK` 得当前 TCP pose，直接套 §4 重构目标 TCP pose，再发 `servo_pose`/`servo_pose_command`。这条路不需要 `T_eef_cam`。
- **备选路（VIO 相机 pose）**：若后续确认部署端只能拿到相机 pose，或训练/控制 frame 被重新定义为相机 frame，才用当前相机 pose 重构目标相机 pose，再经固定 `T_eef_cam` 转 TCP/末端目标。

`T_eef_cam` 是备选相机路线的固定安装外参；默认 TCP 训练/控制路线不读取它。

## 7. 推理落地方案

**Server（不改）：**
```bash
uv run scripts/serve_policy.py --port 8000 policy:checkpoint \
  --policy.config pi05_vio_plant_collection \
  --policy.dir checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000
```

**Client（新写 ROS2 节点，复用 `examples/airbot/airbot_inference_async.py` 的 async/TCS 框架，替换 operator）：**
1. policy observation：订阅三路图像 `video_encoded`/`image_rect` → RGB → resize/pad；`state` 传 `np.zeros(16, np.float32)`；带上 prompt。
2. 执行参考：独立订阅/计算当前 TCP pose（SDK/AIRRTM 反馈、FSM `cartesian_state`，或 `joint_states -> FK`），这一步服务于动作下发，不喂给当前 policy。
3. send_action：取 `actions[:, :14]`，按 §4 还原目标 TCP pose → 发 `servo_pose_command`；夹爪绝对值发末端控制。
4. 频率：动作按 **30Hz** 帧间隔定义（`future_t = t + (h+1)/fps`, fps=30），必须按 30Hz 节拍消费 chunk，否则相对位移幅度失真。

## 8. 部署前对齐项（按实测状态分类）

**已实测确认（2026-06-30，见 §6）：**
- 真机无相机位姿 topic；原生只发 `joint_states`（关节角 + G2P 夹爪）+ 6 路 H264 图像。
- 真机有输出端所需 topic：`/arm/{left,right}/fsm/servo_pose_command`、`end_effector_position_control_command`。
- 当前 checkpoint 的 policy 推理不消费 `state` 数值；dummy state 与极端 state 输出完全一致。

**仍待确认 / 待提供（决定能否闭环）：**
1. **当前 TCP pose 来源** —— SDK/AIRRTM 反馈、FSM `cartesian_state`，还是 `joint_states -> FK`。它用于 action → servo 命令，不是 policy 输入。
2. **servo pose 坐标系** —— 确认 `servo_pose`/`servo_pose_command` 的 base/world frame 与训练 TCP pose 使用同一坐标系，或补一个 base-frame 常量转换。
3. **手眼外参 `T_eef_cam`** —— 默认 TCP→TCP 路线不需要；仅当未来使用相机-frame action/参考 pose 到末端-frame 的转换时，才必须标定或从机械设计获得。
4. **夹爪接口换算** —— 训练 action[6]/[13] 使用 `0-100` 原始开合值（开=100，闭=0）。若真机控制接口收同一约定则直接用；若收 G2P 米制行程，则用 `g_m = 0.096 * g_model / 100`，并实测确认方向。
5. **伺服命令实测** —— 用低速、小幅、单臂验证 `servo_pose_command` 的 frame、四元数顺序、节拍和 ack。

## 9. 复现命令

```bash
# relpose 权威定义
sed -n '29,41p;358,361p;482,521p' docs/VIO_Test/VIO_Test/scripts/vio_preview_converter.py
sed -n '163,198p' docs/VIO_Test/VIO_Test/scripts/vio_convert_to_lerobot.py

# checkpoint 维度
python -c "import json; d=json.load(open('checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/assets/vio_plant_collection_30hz_relpose/norm_stats.json')); print('state', len(d['norm_stats']['state']['mean']), 'action', len(d['norm_stats']['actions']['mean']))"

# 机器人侧（在 192.168.25.1 上）确认 VIO pose topic 是否存在
ros2 topic list | grep -E "wrist|pose|camera"
```
