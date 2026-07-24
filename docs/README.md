# docs/ — 检查与调研记录

本目录按 [`../AGENTS.md`](../AGENTS.md) §0 的约定维护：**每做一次检查/调研，就在这里补写信息**，方便后面读取和确认（复现命令 + 关键输出 + 结论）。

## 索引

| 文件 | 内容 |
|---|---|
| [`CHECKLOG.md`](CHECKLOG.md) | **按时间排的检查时间线**（入口，先看这个） |
| [`inference-architecture.md`](inference-architecture.md) | 推理两进程架构、当前工作站就绪情况、缺什么 |
| [`arm-app-vs-robot-app.md`](arm-app-vs-robot-app.md) | 当前 `arm_app`、`robot_app` 与历史 `arm_dual_app` 的职责和接入方式对照 |
| [`repo-inference-first-principles.md`](repo-inference-first-principles.md) | 从代码/checkpoint/训练转换器出发，说明当前 repo 在做什么、policy inference 最小输入、训练 state/action 语义、真机执行缺口 |
| [`training-robot-io-alignment.md`](training-robot-io-alignment.md) | 当前 checkpoint 与真机 I/O 的完整对齐表：模型 observation、真机回传、action→servo 命令转换、夹爪 0-100 约定 |
| [`vio-relpose-deployment.md`](vio-relpose-deployment.md) | **★权威：relpose 动作部署真相**——训练 state=16/action=14，但当前 PI05 policy 推理不消费 state 数值；重点是 action 到机械臂命令的转换 |
| [`relpose-action-converter.md`](relpose-action-converter.md) | relpose action 转换器实现记录：训练服务器公式证据、本地纯函数 API、ruff/pytest 验证、与真机控制通道的边界 |
| [`model-io-contract.md`](model-io-contract.md) | 模型 I/O 契约（config=`pi05_vio_plant_collection`、相机名、训练 state=16/action=14、当前推理 state 数值不生效）。**已修正早期关节空间误判** |
| [`pi05-535-clean-wrist-only-checkpoint.md`](pi05-535-clean-wrist-only-checkpoint.md) | PI0.5 535 clean wrist-only 20k checkpoint 实测：训练 config 对齐、Orbax restore、双腕输入 mask、mock `(50,32)` 推理与耗时 |
| [`openpi-interpolated-inference-20260720.md`](openpi-interpolated-inference-20260720.md) | 2026-07-20 真机推理：指定关节复位、5 mm 自适应插值、逐步 TCP 回读、3 cm 实测硬阈值、快速清错与双腕 MP4 录制 |
| [`openpi-observation-read-probe-20260720.md`](openpi-observation-read-probe-20260720.md) | 2026-07-20 OpenPI 前置读取探针：连续读取正式 wrist-only RGB 文件与双臂 TCP pose，不运行模型、不接管或控制机械臂；含真机 5 秒 smoke 结果 |
| [`openpi-in-process-camera-20260720.md`](openpi-in-process-camera-20260720.md) | 2026-07-20 单进程相机改造：主控制进程长期订阅 ROS2 双腕新帧，内存直发 policy，取消 camera daemon 与 latest-file |
| [`openpi-400s-interruption-analysis-20260720.md`](openpi-400s-interruption-analysis-20260720.md) | 2026-07-20 400 秒运行中断复盘：外层 timeout/137 与 8 次 X5 queue_dropped -> UNKNOWN_ERROR 的分层原因 |
| [`openpi-websocket-timeout-left-bit19-20260721.md`](openpi-websocket-timeout-left-bit19-20260721.md) | 2026-07-21 policy WebSocket 瞬态卡死、双臂 4 ms deadline miss 与左 joint7 bit 19 事故复盘 |
| [`openpi-fixed-observation-smoke-20260720.md`](openpi-fixed-observation-smoke-20260720.md) | 2026-07-20 固定首帧无控制 smoke test：wrist-only 20k 本地推理 5.48 Hz、horizon 行吞吐与实际/X5 频率辨析 |
| [`openpi-79999-action-chunk-stream-20260720.md`](openpi-79999-action-chunk-stream-20260720.md) | 2026-07-20 79999 + 10 ms chunk streaming：关闭 RPC limiter、2 行真机 pilot、12.0 ms 实测间隔及左臂额外位移停跑 |
| [`openpi-period0-start-interruption-20260720.md`](openpi-period0-start-interruption-20260720.md) | 2026-07-20 period=0 启动中断：终端工具 1 秒硬超时/exit 124、孤立子进程和右臂 CSP 残留恢复 |
| [`training-robot-io-alignment.md`](training-robot-io-alignment.md) | 训练转换器、当前 PI05 policy 请求、真机回传和 relpose action 到机械臂命令的对齐表 |
| [`teleop-and-data-collection.md`](teleop-and-data-collection.md) | **遥操作链路 + 数采接口**（飞书文档落地）：topic 契约、★关节维度定论（7关节+G2P）、软件安装清单与现状 |
| [`airrtm-conversion-layer.md`](airrtm-conversion-layer.md) | **历史/已退役**：AIRRTM `arm_servo_json` / `servo_pose` 的过去实测与协议证据；当前代码已删除，生产路线为 P7 SDK gRPC |
| [`openpi-grasp-task-runbook.md`](openpi-grasp-task-runbook.md) | **★启动手册：OpenPI 推理控制双臂抓放**（wrist_only ckpt）——从重启后干净状态起：serve→arm_dual_app→相机守护→清错→闭环执行(safeguard全关)→录三路相机；含常见故障速查 |
| [`openpi-airbot-runbook.md`](openpi-airbot-runbook.md) | **OpenPI -> AIRBOT 真机运行手册**：连接 X5/robot_app、启动 AIRRTM sender、手动发 `servo_pose`、启动 OpenPI 并发布一行 policy action |
| [`p7-sdk-grpc-current-state.md`](p7-sdk-grpc-current-state.md) | **当前权威：Arm-P7 SDK gRPC 路线**：不走 DDS；基于 `AirbotClient(..., backend="grpc")`、`get_end_pose()`、`move_end_pose()`、`move_eef()` 对齐模型动作和真机输入输出 |
| [`local-amd64-robot-app-simulator.md`](local-amd64-robot-app-simulator.md) | 本机 amd64 `robot_app` 模拟器使用方法：安装后直接启动、`/userdata/storage` 权限坑、推荐临时配置、`0.0.0.0:50071` gRPC 监听和 SDK 只读验证 |
| [`p7-release-package-2026-06-23.md`](p7-release-package-2026-06-23.md) | **Arm-P7 2026-06-23 软件包核对**：确认 `arm_p7_sdk 1.1.1`、`robot_app 0.3.5`、50071 gRPC route、board bundle 用途和当前机器人未升级状态 |
| [`direct-dds-control.md`](direct-dds-control.md) | **历史/备选：直连 DDS 控制双臂**：当前不作为主线；保留裸 DDS/FSM topic、消息 IDL、QoS、落地前提作为反证和底层资料 |
| [`p7-dds-route-current-state.md`](p7-dds-route-current-state.md) | **历史/反证：DDS Route 当前不可用**：记录 DDS Route wiki、旧现场检查和 X5 当前版本/topic/网络差异；已被 Arm-P7 SDK gRPC 路线取代 |
| [`robot-connection.md`](robot-connection.md) | 连机器人 `192.168.25.1`（ssh / 网络 / ROS2）、相机与机械臂实时话题、桥接方案 |
| [`local-conda-mamba-ros2.md`](local-conda-mamba-ros2.md) | 工作站系统级 Miniconda/mamba 安装、默认 mamba/libmamba 配置、`ros2-topic` 环境与本地订阅 camera_info 实测 |
| [`network-proxy-curl.md`](network-proxy-curl.md) | 当前 VPN/Clash 代理与 curl 行为检查：`curl` 已使用 `127.0.0.1:7897`，代理访问成功，直连对照超时 |
| [`codex-cli-update.md`](codex-cli-update.md) | Codex CLI 官方安装脚本与 `codex update` 检查：确认代理下载可用，并已从 0.142.4 更新到 0.142.5 |
| [`worktree-cleanup-20260720.md`](worktree-cleanup-20260720.md) | 工作树改动审计：已删除的临时残片、保留的核心链路与实验工具分类 |
| [`github-fork-push-20260723.md`](github-fork-push-20260723.md) | GitHub fork/push：已创建 `by-luckk/Openpi_RL`，通过 SSH 推送 `master` 并验证远端 commit |
| [`camera-image-capture.md`](camera-image-capture.md) | 双腕相机读取与保存入口：MP4、单帧 NPZ、推理 MCAP 及默认开关 |
| [`vio-dual-arm-replay.md`](vio-dual-arm-replay.md) | VIO 相对 TCP 双臂轨迹的安全 replay：文件语义、插值、包络与执行命令 |
| [`keyboard-eef-control.md`](keyboard-eef-control.md) | 键盘控制双臂末端 XYZ/RPY 的现状核对：现有键盘、遥操和 P7 CartesianPose 能力边界 |

## 怎么新增记录

- **新主题**：新建 `docs/<主题>.md`，在上表加一行。
- **已有主题增量**：往对应文件追加一节，并在 `CHECKLOG.md` 末尾加一行时间线。

每条尽量带上：日期、目的、可复现命令、关键输出、结论、对推理/接数据的影响。
