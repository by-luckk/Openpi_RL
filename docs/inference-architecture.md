# 推理架构与工作站就绪情况

> 维护约定见 [../AGENTS.md](../AGENTS.md) §0。最近核对：2026-07-02。

## 两进程架构

```
┌────────────────────────┐   WebSocket :8000    ┌─────────────────────────────┐
│  策略服务端 (GPU 工作站) │ <------------------> │  机器人客户端 (连机器人的机器) │
│  scripts/serve_policy.py│   obs → action       │  airbot_inference_*.py       │
│  加载 checkpoint, jax   │                      │  采集观测 / 下发动作          │
└────────────────────────┘                      └─────────────────────────────┘
```

- **服务端**：`scripts/serve_policy.py`，封装 `scripts/cmds/serve_policy.sh`。只依赖 jax/openpi，与硬件无关。
- **客户端**：`examples/airbot/airbot_inference_sync.py`（同步，验证用）/ `airbot_inference_async.py`（异步，含 TCS 时序平滑，部署用）。经 `play_operator.py` 采集观测、驱动机械臂。

## 2026-07-02 现场澄清：推理环境和机械臂通信环境

结论：这是两套运行职责和依赖环境，但部署时由一个机器人客户端/桥接进程串起来。模型推理环境只负责 checkpoint 推理；机械臂通信环境只负责把动作转换并下发到机器人。

| 层 | 作用 | 入口/进程 | 主要依赖 | 是否加载 checkpoint | 是否直接接机械臂 |
|---|---|---|---|---|---|
| 模型推理环境 | 接收 obs，输出 policy action | `scripts/serve_policy.py` / `scripts/cmds/serve_policy.sh`，WebSocket `:8000` | `jax`、`openpi`、checkpoint | 是 | 否 |
| 机器人通信环境 | 读取机器人现场状态，把 action 转成控制帧并发布 | `examples/airbot/airrtm_servo_dryrun.py` / 后续正式桥接客户端 + `airbot-rtm-sender` + X5 `robot_app` | ROS2/SSH 只读状态、ZMQ、AIRRTM/AIRRTC、X5 `robot_app` | 否 | 是 |

当前接口边界是：`obs -> policy server(:8000) -> action -> relpose/AIRRTM converter -> arm_servo_json -> ZMQ topic servo -> airbot-rtm-sender -> X5 robot_app -> 控制栈`。两套环境可以在同一台工作站上同时运行，也可以分开部署；不能把 checkpoint 加载问题和 sender/data channel 问题混为一类问题。

2026-07-02 18:16 CST 已补齐一个无真机也可跑的桥接入口：

| 层 | 新增入口 | 当前能测什么 | 默认是否发布到机械臂 |
|---|---|---|---|
| 共享逻辑 | `src/openpi/shared/airbot_policy_bridge.py` | mock observation、mock/action-json/policy action chunk 归一化、只取一行 action、转 AIRRTM message | 否 |
| CLI | `examples/airbot/policy_to_airrtm_bridge.py` | `--action-source mock/json/policy`；policy 模式会先检查 `:8000` 是否可连，避免无限等待 | 否，除非显式 `--publish --allow-robot-motion` |
| 命令封装 | `scripts/cmds/airrtm_bridge_dryrun.sh` | 默认 mock `(50,32)` action chunk → `arm_servo_json` wire preview | 否 |

这不是把推理和通信揉成一个 Python 环境；它是把两边通过一个桥接进程串起来。实际闭环时仍建议三进程：`serve_policy.sh` 加载 checkpoint，`airbot-rtm-sender` 负责 AIRRTC data channel，bridge 进程负责观测、policy 请求、action 选择、转换和 ZMQ 发布。当前没有机械臂时只跑 no-publish dry-run；真机到位后也必须先完成单帧小步和 stop/IDLE 验证，再允许连续控制。

## 当前工作站就绪情况（2026-06-30 核对）

| 检查项 | 命令 | 结果 |
|---|---|---|
| jax + GPU | `.venv/bin/python -c "import jax; print(jax.__version__, jax.devices())"` | ✅ `0.5.3` / `[CudaDevice(id=0)]` |
| checkpoint | `find checkpoints -maxdepth 4` | ✅ `checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000/`（含 `params`/`train_state`/`assets`/`_CHECKPOINT_METADATA`） |
| 客户端依赖 | `.venv/bin/python -c "import airbot_ie, airdc"` | ❌ `ModuleNotFoundError: No module named 'airbot_ie'` |

### 结论
- **策略服务端可以推理**（GPU + jax + 真实 checkpoint 齐备）。
- **机器人客户端当前不能跑**：私有 SDK `airbot_ie` / `airdc` 未安装，`airbot_inference_*.py` 连 import 都过不了。

## 起服务端：已验证可跑通（2026-06-30）

`scripts/cmds/serve_policy.sh` 的**出厂默认值与现存 checkpoint 对不上**（`POLICY_CONFIG=pi06_rl_pretrain_airbot_clothes_folding`、`CHECKPOINT_DIR=.../XXXXX` 占位）。已把它改成与权重匹配的值并实测启动成功：

```bash
# scripts/cmds/serve_policy.sh 现已改为：
POLICY_CONFIG=pi05_vio_plant_collection
CHECKPOINT_DIR=checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000
```

- **config 匹配依据**：checkpoint 内 `assets/vio_plant_collection_30hz_relpose/norm_stats.json` 的目录名，与 `src/openpi/training/config.py:729` 的 `pi05_vio_plant_collection`（`repo_id="vio_plant_collection_30hz_relpose"`）一致。
- **启动结果**（`logs/serve_policy_20260630_120935.log`）：6.2GiB params restore 用时 3.45s；norm_stats 从 checkpoint 内 assets 加载；`websockets.server: server listening on 0.0.0.0:8000`。
- **端到端验证** ✅：用 mock 观测（state 16 维 + 三路图像 + prompt）打 websocket，返回 `actions shape (50, 32)`（`action_horizon=50`, `action_dim=32`，真实有效 action=14 维）。

复现验证（服务端起来后，工作站本地）：
```bash
.venv/bin/python -c "
from openpi_client import websocket_client_policy as wcp, image_tools
import numpy as np
c = wcp.WebsocketClientPolicy('127.0.0.1', 8000)
obs = {
  'state': np.zeros(16, np.float32),   # 占位即可；当前 PI05 checkpoint 不消费 state 数值
  'base_0_rgb': np.zeros((352,640,3), np.uint8),
  'left_wrist_0_rgb': np.zeros((352,640,3), np.uint8),
  'right_wrist_0_rgb': np.zeros((352,640,3), np.uint8),
  'prompt': 'Fold clothes',
}
print(c.infer(obs)['actions'].shape)   # -> (50, 32)
"
```

> 模型 I/O 维度契约见 [model-io-contract.md](model-io-contract.md) 与权威版 [vio-relpose-deployment.md](vio-relpose-deployment.md)：训练数据 state=16/action=14，输出 action 是 relpose；但当前 PI05 checkpoint 推理不消费 `state` 数值，请求里放 dummy state 即可。

## 客户端观测/动作约定（来自 `examples/airbot/robot_config.py` + `play_operator.py`）

- 相机（3 路）：`base_0_rgb` / `left_wrist_0_rgb` / `right_wrist_0_rgb`；默认 V4L2 `camera_index=[0,2,4]`，MJPEG 640×480。图像在 `capture_observation()` 里做 **BGR→RGB**。
- 动作：每臂 7 维 = 6 关节 + 1 夹爪；`send_action` 对夹爪做缩放 `joint_target[6] *= 0.072/0.0471`。双臂共 14 维（reset_action 长度 14）。

> ⚠️ 注意：以上是 repo **通用 AIRBOT 客户端**（`play_operator.py`）的**关节空间**约定，**不等于当前 `pi05_vio_plant_collection` checkpoint 的 I/O**。该 checkpoint 是 relpose 模型（state=16 相机位姿 / action=14 位姿增量），不能直接套用这套关节空间 send_action。真实契约见 [model-io-contract.md](model-io-contract.md) / [vio-relpose-deployment.md](vio-relpose-deployment.md)。
- 臂连接：`airbot_play` gRPC，从动臂端口 `[50051, 50053]`，主臂（DAgger）`[50050, 50052]`。

> 这些是“连本地硬件”的默认路径。真机数据源是 `192.168.25.1` 的 ROS2 话题（见 [robot-connection.md](robot-connection.md)），两者不一致，需桥接。
