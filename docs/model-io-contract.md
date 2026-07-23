# 模型 I/O 契约（训练 state=16 / action=14，PI05 推理 state 数值不生效）

> 维护约定见 [../AGENTS.md](../AGENTS.md) §0。最近核对：2026-06-30。
> ⚠️ **本文件已于 2026-06-30 修正**：早期版本误判该 checkpoint 为「关节空间、state=14、每臂 6 关节+1 夹爪」，
> 已证伪。真实情况是**位姿相对增量（relpose）模型**；按 2026-06-30 用户确认，当前默认按 **TCP pose** 语义部署。动作/状态的**逐位定义、重构公式、坐标系**以
> [vio-relpose-deployment.md](vio-relpose-deployment.md) 为**权威**，本文件只保留 config/字段/维度的速查。
>
> 2026-06-30 追加核对：当前训练配置显式设置 `discrete_state_input=False`，PI05 模型本身没有 continuous `state_proj` 路径；实测同图像、同 prompt、同 noise 下把 `state` 从全零换成极端值，`actions` 完全一致（`max_abs_diff=0.0`）。因此 `state` 是 API/transform 所需字段，不是当前 checkpoint 的有效条件输入。

---

## 0. 最新结论：推理不需要真实 state

对当前 `pi05_vio_plant_collection/80000`：

- **策略条件输入实际是三路图像 + prompt**。`state` 数值没有进入 PI05 前向计算。
- **请求里仍要有 `state` 键**，因为 `AirbotInputs` 会执行 `data["state"]` 并 pad 到 32 维；实际部署可传 `np.zeros(16, np.float32)` 作为占位。
- 训练数据中的 16 维 state 仍有文档价值：它说明 action 标签如何由 pose 构造，也说明如果用绝对 `servo_pose_command` 执行动作，需要在执行器侧维护“当前 TCP/末端参考位姿”。
- 不要再把“训练数据 state 的语义”当成当前 policy 的真实输入需求。

## 1. 选定的 config 与模型

- config 名：**`pi05_vio_plant_collection`**（`config.py:729`）
- 模型：`Pi0Config(model_type=PI05, action_horizon=50, action_dim=32, discrete_state_input=False)`
- 数据工厂：`LeRobotAirbotDataConfig(repo_id="vio_plant_collection_30hz_relpose")`，`extra_delta_transform=False`
- checkpoint：`checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/`

## 2. 维度（checkpoint norm_stats 实测，权威）

`pad_to_dim` 把真实维补零到网络的 32 维。**真实有效维 = norm_stats 里非零的部分**：

| 量 | 网络维（pad 后） | **真实有效维** | 实测依据 |
|---|---|---|---|
| `state` | 32 | **16** | norm_stats `state.mean` 第 0..15 位非零，16..31 全 0 |
| `actions` | 32 | **14** | norm_stats `actions.mean` 第 0..13 位非零，14..31 全 0 |

> 实测 mean 值（铁证，与「关节角」对不上、与「位姿+夹爪」吻合）：
> - `state.mean[14]=95.34`、`state.mean[15]=76.91` → 双臂**夹爪**，与用户确认的 `0-100`
>   开合值一致（开到最大为 `100`，闭合为 `0`）。
> - `actions.mean[6]=95.31`、`actions.mean[13]=76.85` → 双臂**夹爪**（每臂第 7 位），同样是 `0-100`。

## 3. 训练数据 state 布局（16 维，权威见 vio-relpose-deployment.md §2）

每臂 = pose `pos(3) + quat_xyzw(4)`，当前按 TCP pose 语义处理，再加双臂夹爪：

```
[0:3]   左 TCP/pose 位置 xyz (m)
[3:7]   左 TCP/pose 姿态四元数 (x,y,z,w)
[7:10]  右 TCP/pose 位置 xyz
[10:14] 右 TCP/pose 姿态四元数 (x,y,z,w)
[14]    左夹爪开合值 (0-100，开=100，闭=0)
[15]    右夹爪开合值 (0-100，开=100，闭=0)
```

**不是关节角。** state 的姿态用四元数（xyzw）。但对当前 `discrete_state_input=False` 的 PI05 checkpoint，这些数值不会作为 policy 条件输入；推理请求可用同形状 dummy state。

## 4. action 布局（每步 14 维，horizon=50，权威见 vio-relpose-deployment.md §3/§4）

每步 14 维 = 左臂 7 + 右臂 7，每臂：

```
[Δpos(3) , Δrotvec(3) , 夹爪绝对值(1)]
```

- 相对量定义在**当前帧 pose 局部系**下；按当前确认，默认作为 TCP 局部系处理（`dp_local = cur_r.inv().apply(fut_p-cur_p)`，`dr_local = (cur_r.inv()*fut_r).as_rotvec()`）。
- 那个「6」是 **6-DOF 位姿增量**，**不是 6 个关节**。姿态增量用 **rotvec（轴角）**，与 state 的四元数表示不同，别混用。
- 重构成绝对目标位姿的公式直接照抄 vio-relpose-deployment.md §4。

## 5. 推理时实际要喂的字段（repack + AirbotInputs）

| 键 | 形状/类型 | 说明 |
|---|---|---|
| `base_0_rgb` | HxWx3 uint8 | 头部左目；`_parse_image` 把 CHW→HWC、float→uint8。**不做 BGR→RGB**（代码该行已注释，按 RGB 喂） |
| `left_wrist_0_rgb` | HxWx3 uint8 | 左臂左目 |
| `right_wrist_0_rgb` | HxWx3 uint8 | 右臂左目 |
| `state` | 建议 **16 维** float 占位（如全零） | `AirbotInputs` 仍要求该键并 `pad_to_dim(state, 32)`；当前 checkpoint 不消费其数值 |
| `prompt` | str | `prompt_from_task=True`；客户端传，如 `"Fold clothes"` |

图像在训练转换器里被 `resize_with_pad` 到 **224×224**（vio-relpose-deployment.md §1），推理端需做相同处理。

输出（`AirbotOutputs`）：`{"actions": (50, 32)}`，实测已确认。**取前 14 维**为真实双臂动作。

> 训练期增强 `AirbotSymmetryAugmentation` / `AirbotChannelPermutationAugmentation` 放在 repack，**推理不触发**。

## 6. ⚠️ 与机器人关节 topic 的关系（别接错）

机器人 `/arm/*/control/joint_states` 是 **8 维关节空间**（`joint1..joint7 + G2P`，见 [teleop-and-data-collection.md](teleop-and-data-collection.md) §3）。
**这套关节数据 ≠ 本 checkpoint 的 action I/O**：本模型输出 relpose，不输出关节角。训练数据里的 state 是 pose 字段（当前按 TCP pose 语义处理），但当前 checkpoint 推理不消费真实 state 数值；关节数据主要用于执行侧 FK/限幅/夹爪反馈。

- 早期「机器人 8 关节 → 模型 7 维、丢弃 joint7」的映射讨论**作废**——前提就错了。
- 真正的落地前置是**动作执行侧对齐**（不是关节维度）：arm_msgs/AIRRTM 发布、FSM/servo 入口、当前 TCP pose 的取得方式、servo pose 坐标系、夹爪接口换算。固定手眼外参 `T_eef_cam` 只在备选相机 pose 路线需要。详见 [vio-relpose-deployment.md](vio-relpose-deployment.md) §5/§8。


## 6.1 模型输出 ↔ 机械臂输入

日期：2026-06-30；检查人：agent/Codex。
目的：把当前 checkpoint 的 action 与 X5/P7 机械臂 DDS 输入逐项对齐，并纠正“policy 推理必须真实 state”的误判。

| 项 | 模型/策略侧 | 机械臂要求输入 | 中间缺口 |
|---|---|---|---|
| policy 请求 | 三路 RGB 图像 + `prompt` + `state` 键 | 机械臂不关心 policy 请求格式 | 当前 checkpoint 不消费 `state` 数值；占位 `zeros(16)` 即可通过 transform |
| 输出整体 | `actions` shape = `(50, 32)` | 机械臂不接受 32 维 action | 只取前 14 维，其余是 padding |
| 单步有效动作 | `actions[t, :14]` | 左右臂分别发命令 | 拆成左臂 `0:7`、右臂 `7:14` |
| 每臂动作 0:3 | `Δpos[3]`，当前按 TCP 局部系下的位置增量处理，单位 m | `FsmServoPoseCommand.translation[3]`，末端目标位置 | 执行侧需要当前 TCP pose，把相对增量还原成绝对目标；这不是 policy 输入 |
| 每臂动作 3:6 | `Δrotvec[3]`，TCP 局部旋转增量，轴角/rotvec | `FsmServoPoseCommand.orientation[4]`，末端目标四元数 | 需要 `Rotation.from_rotvec()` 和当前 TCP 姿态；还要确认机械臂四元数顺序 |
| 每臂动作 6 | 夹爪未来绝对值，`0-100`（开=100，闭=0） | `FsmEndEffectorPosControlCommand.position` 或底层夹爪命令 | 若命令收 `0-100` 直接发；若收 G2P 米制行程，换算 `g_m = 0.096 * g_model / 100` |
| 推荐机械臂入口 | 模型输出的是“TCP/末端该怎么相对运动”的 relpose action | `/arm/<side>/fsm/servo_pose_command`：末端绝对目标位姿 | X5 内部做 servo/IK；本地不必自己解 IK |
| 可选机械臂入口 | 模型没有直接输出关节角 | `/arm/<side>/fsm/servo_joint_command`：`pos[7]` | 需要已有关节目标，或先调 `/rpc/arm/<side>/kdl/inverse_kinematics/*` |
| 关节回传 | policy 不需要真实关节 state | `/arm/<side>/control/joint_states`：`[joint1..joint7,G2P]` | 可用于 FK、限幅、当前姿态参考和夹爪反馈，不是模型 action 本身 |

结论：**不一定要自己做 IK**。优先路径是：模型 action → 用执行侧当前 TCP pose 还原目标 TCP pose → 发 `fsm/servo_pose_command` 或 AIRRTM `servo_pose`，由 X5 内部 servo/KDL 处理 IK。只有选择 `servo_joint_command` 时，才需要先得到 7 关节目标。

`T_eef_cam` 不是默认 TCP→TCP 路线的输入，也不是每次 policy inference 的输入。只有执行侧改用“相机 relpose/相机参考 pose → 末端绝对 pose”的路线时，才需要固定手眼外参；那时通常初始标定一次并写入配置文件，运行时每帧复用。

## 7. 复现命令

```bash
# 维度（真实有效维 = 非零部分）
python3 -c "import json; d=json.load(open('checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/assets/vio_plant_collection_30hz_relpose/norm_stats.json'))['norm_stats']; \
import numpy as np; s=np.array(d['state']['mean']); a=np.array(d['actions']['mean']); \
print('state nz=', int(np.max(np.nonzero(s))+1), 'action nz=', int(np.max(np.nonzero(a))+1))"
# → state nz= 16 action nz= 14

# 权威 relpose 定义
sed -n '29,41p;358,361p;482,521p' docs/VIO_Test/VIO_Test/scripts/vio_preview_converter.py
```
## 2026-07-20 23:22 CST - 当前 wrist-only PI0.5 是否有跨帧 memory（agent: Codex）

### 目的

确认当前 `pi05_vio_plant_collection_535_clean_wrist_only` checkpoint 每次推理是否会读取历史帧，
或在连续请求之间保留 recurrent hidden state / Transformer KV cache。

### 静态核对命令

```bash
rg -n --hidden -g '!docs/VIO_Test/VIO_Test/**' \
  'history|frame_stack|recurrent|hidden_state|action_horizon|observation' \
  examples/airbot src/openpi scripts
sed -n '730,810p' src/openpi/training/config.py
sed -n '1,120p' src/openpi/policies/policy.py
sed -n '210,280p' src/openpi/models/pi0.py
sed -n '1,150p' examples/airbot/request_policy_from_observation_npz.py
```

### 证据与结论

- 当前配置是 `PI05`、`action_horizon=50`、`action_dim=32`、`discrete_state_input=False`，实际图像输入
  只有同一份 observation snapshot 中的左、右腕 RGB；输入 schema 没有时间轴、历史图像数组或
  previous-action 字段。
- `request_policy_from_observation_npz.py` 每次独立从一个 `.npz` 读取一组 `state` 和两张腕部图像，
  组成一次 websocket 请求。persistent loop 每轮重新采集，再发一个这样的请求，没有把前轮 observation
  回传给模型。
- `Policy.infer()` 每次只把本次 `obs` 变换、加 batch 维后调用 `sample_actions()`；接口没有传入或返回
  recurrent hidden state。
- `Pi0.sample_actions()` 会在**单次扩散采样内部**为本次 observation 建立 prefix KV cache，供该次去噪
  循环复用；函数返回后 cache 不保存到下一次请求。因此它不是跨帧 memory。
- 服务端 `Policy` 的 PRNG key 会在请求间推进，所以同一输入在未固定 noise 时可能得到不同采样结果；
  RNG 状态不包含历史观测，不能视为时序记忆。
- 一次请求从当前 snapshot 预测 `(50, 32)` action chunk。执行端可以连续执行多行，并可能缓存/平滑
  新旧 action chunk；这会让控制行为带有短时历史，但属于 action buffer / temporal chunk smoothing，
  不是模型读取历史帧或保留隐状态。

最终结论：**当前部署的模型本身是无跨请求记忆的，每次推理只看本次采集的当前观测快照（双腕单帧、
当前 state、prompt），然后一次预测未来 50 步动作。** 如果任务存在部分可观测性，单靠当前实现无法从
此前画面恢复被遮挡状态；需要显式加入多帧输入、状态估计，或改成带跨步状态的策略。
