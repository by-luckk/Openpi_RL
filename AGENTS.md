# 指南

本文件给在本仓库（Openpi_RL，OpenPI π0.5/π0.6 + AIRBOT 真机推理）里工作的 AI agent / 协作者使用。
**核心约定：每做一次“检查/调研”，都必须把结论与证据补写进 [`docs/`](docs/)，方便后面读取和确认。**

## 重要Guide

1. 先阅读再执行
2. 做最简修改，不要做冗余设计
3. 遵循第一性原理
4. 遇到不确定的问题时详细解释并与使用者进行确认
5. 可以多使用 subagents 以完成复杂任务

---

## 0. 最重要的工作约定：每次检查都写进 `docs/`

只要你做了下面任意一类动作，就要在 `docs/` 留下记录：

- ssh / 网络探测（例如登录 `192.168.25.1`、扫端口、`ros2 topic` 探查）
- 验证某个推理前置条件（依赖是否安装、checkpoint 是否存在、GPU/jax 是否可用）
- 跑通或跑挂某条命令（serve / infer / 转换 / 训练）
- 任何“我确认了 X 是这样”的事实结论

记录方式（二选一，能附上**实际命令和关键输出**最好）：

1. **新主题** → 在 `docs/` 新建 `docs/<主题>.md`，并在 `docs/README.md` 的索引里加一行。
2. **已有主题的增量** → 直接往对应文件追加一节，并在 `docs/CHECKLOG.md` 末尾追加一行时间线条目。

`docs/CHECKLOG.md` 的时间线条目后续统一写**绝对日期 + 具体时间**（例：`2026-06-30 21:35`），不要再用“晚三 / 晚五 / 傍晚二”这类相对时间或轮次标记。

**纠正文档矛盾时的规则**：如果发现已有文档里的结论互相矛盾、过期或被后续检查证伪，优先**直接修改原文相关段落**，把旧结论替换为当前可信结论；不要只在文档末尾追加“纠错说明”来保留矛盾文本。必要时再同步更新 `docs/CHECKLOG.md` 的时间线入口。

每条检查记录建议包含：
- **日期**（绝对日期 + 具体时间，例：2026-06-30 21:35）+ 检查人（agent/人名）
- **目的**：想确认什么
- **命令**：实际执行的命令（可复制复现）
- **结论**：是 / 否 / 数值，以及关键输出片段
- **影响**：对“能不能推理 / 怎么接数据”的影响

> 为什么这样做：真机环境（机器人固件、相机话题、网络）会变。把“某天某命令得到某输出”落盘，后面任何人都能**复现验证**而不是凭记忆。`docs/CHECKLOG.md` 是按时间排的入口，`docs/<主题>.md` 是按主题汇总的细节。

---

## 1. 这个仓库是干什么的

OpenPI（π0.5 / π0.6）策略 + AIRBOT 本体的训练 / 数据转换 / **真机推理**。推理是**两进程**架构：

| 进程 | 入口 | 跑在哪 | 作用 |
|---|---|---|---|
| 策略服务端 | `scripts/serve_policy.py`（`scripts/cmds/serve_policy.sh`） | **GPU 工作站** | 加载 checkpoint，WebSocket 端口 8000 对外提供动作 |
| 机器人客户端 | `examples/airbot/airbot_inference_{sync,async}.py` | **连着机器人的机器** | 采集观测（图像+关节）→ 请求服务端 → 下发动作 |

- 服务端只依赖 jax/openpi，与硬件无关。
- 客户端 `play_operator.py` 依赖私有 SDK `airbot_ie` / `airdc`，并默认从 **本地 V4L2 相机** + **airbot_play gRPC** 取数。

详见 [`docs/inference-architecture.md`](docs/inference-architecture.md)。

## 2. 机器人 / 实时数据源：`ssh root@192.168.25.1` / `ssh root@172.100.10.159`（本工作站已配 SSH 免密）

`192.168.25.1` 是 AIRBOT 机器人的板载 SoC（Horizon/Hobot aarch64，ROS2 Humble）。我们要的是**实时读取**，不是本机文件——板上**没有**可读的视频/episode 文件，录制数据经 cora/agora 流出。

登录入口：

- 有线 / DDS 推荐链路：`ssh root@192.168.25.1`（同一台 X5 的 root 账号；网络可达时使用已安装公钥免密）
- 无线 / 管理备用链路：`ssh root@172.100.10.159`（2026-06-30 17:44 CST 已验证本工作站 `~/.ssh/id_ed25519.pub` 免密；这是机器人 `wlan0`，不要用它走 DDS/ROS2 多播链路）
- 密码 `root` 仅作 fallback；正常从本工作站登录不需要输密码。

实时观测以 **ROS2 topic** 形式存在。我们用的三路相机是“每个立体相机取左目”：

| repo 相机名 | ROS2 topic | 编码/分辨率 |
|---|---|---|
| `base_0_rgb` | `/camera/head_left/image_rect` | nv12 640×352 ~19Hz |
| `left_wrist_0_rgb` | `/camera/left_arm_left/image_rect` | nv12 640×352 ~19Hz |
| `right_wrist_0_rgb` | `/camera/right_arm_left/image_rect` | nv12 640×352 ~19Hz |

臂关节：`/arm/{left,right}/fsm/joint_state`（`sensor_msgs/JointState`）。

完整连接方式、话题清单、关节维度、桥接方案见 [`docs/robot-connection.md`](docs/robot-connection.md)。

## 3. 仓库目录速查

- `scripts/cmds/*.sh` — 所有入口的“改参数即用”封装（serve / infer_sync / infer_async / convert / train / label / vf）。
- `examples/airbot/` — AIRBOT 本体专用：推理客户端、DAgger、MCAP↔LeRobot 转换、相机/臂操作。
- `scripts/`、`scripts/tools/` — 通用 LeRobot 数据结构工具（转换后通用）。
- `checkpoints/` — 模型权重（当前有 `pi05_vio_plant_collection/vio_pi05_260628/80000/`）。
- `docs/` — **本约定要求的检查/调研记录**（见 §0）。

> ⚠️ `docs/VIO_Test/VIO_Test/` 是**另一个独立的 openpi git 仓库**（用户解压进来的，自带 `.git/` 和 `__MACOSX/`），不是本仓库的文档。检索/改动本仓库时**忽略它**，别把它的源码当成 `src/` 的真身，也别误改。

## 4. 常用命令

```bash
# 环境
GIT_LFS_SKIP_SMUDGE=1 uv sync --python 3.11

# ssh 进机器人（本工作站已装公钥，正常免密；fallback 密码 root 见 docs/robot-connection.md）
ssh root@192.168.25.1            # 有线 / DDS 推荐链路；网络可达时同 root key 免密
ssh root@172.100.10.159          # 无线 wlan0；已验证免密，仅作 SSH/管理备用

# 机器人侧查实时话题
source /opt/ros/humble/setup.bash && ros2 topic list

# 起策略服务（已验证可跑；serve_policy.sh 已指向真实 checkpoint）
bash scripts/cmds/serve_policy.sh
#   config=pi05_vio_plant_collection  dir=checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000
#   起来后监听 0.0.0.0:8000，mock 观测可返回 actions (50,32)
```

## 5. 做改动时

- 真机相关脚本改动后，按 §0 把“验证了什么、怎么验证的”写进 `docs/`。
- 不要把私密信息（除既有的 `root` 默认密码外的凭据）写进仓库。
- 注释/命名风格跟随周边代码（仓库 README 与注释以中文为主）。

## 6. 其他说明

- 训练时候采用的远端服务器是 `ssh maxliu-h200-qinghua-1` ，位置是 `/home/maxliu/projects/VIO_Test/Openpi_RL`
- 如果有任何对模型本身不清楚的问题可以在远端服务器当中查看
