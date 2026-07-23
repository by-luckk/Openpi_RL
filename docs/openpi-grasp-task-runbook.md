# OpenPI 推理控制双臂抓取放置 — 启动手册（Runbook）

> 目标：从**机器人刚重启**的干净状态，一步步把 OpenPI 推理→双臂+夹爪闭环抓放跑起来，并记录三路相机数据。
> 适用 checkpoint：`pi05_vio_plant_collection_535_clean_wrist_only`（**只用左右腕两路相机**做策略输入；头部相机仅用于录像/观察）。

---

## 0. 架构速览（3 个 Python 环境 + 4 个组件）

| 组件 | 跑在哪 | 环境 | 作用 |
|---|---|---|---|
| ① policy 服务 | GPU 工作站 | `uv run`（`.venv`） | 加载 ckpt，WebSocket:8000 出 action |
| ② arm_dual_app | 机器人 X5 | 板端二进制 | gRPC 50071(左)/50072(右) 臂控 |
| ③ 相机守护进程 | GPU 工作站 | ROS2 jazzy + `/usr/bin/python3` | 单 participant 持续写最新观测到磁盘 |
| ④ 闭环执行器 | GPU 工作站 | `.venv-p7-sdk` | 读观测→请求 policy→relpose 积分→下发 servo+夹爪 |

> **为什么相机要用守护进程**：闭环若每步新起 rclpy 采集进程，DDS participant 反复 churn，会让相机 robot_app 的发布静默（本仓库多次踩坑，见 `docs/CHECKLOG.md`）。守护进程只 join 一次，从根上消除 churn。

---

## 1. 预检（每次重启后必做）

在 GPU 工作站 `cd /home/discover/Desktop/Openpi_RL`，逐项确认：

```bash
# 1.1 臂控端口（重启后通常都是 closed，需第 3 步拉起）
python3 -c 'import socket
for p in [50071,50072]:
    s=socket.socket();s.settimeout(3);print(p,"OPEN" if s.connect_ex(("192.168.25.1",p))==0 else "closed");s.close()'

# 1.2 SSH + 机器人侧状态
ssh root@192.168.25.1 "uptime -s; ps -C arm_dual_app -o pid= --no-headers|wc -l; ps -C robot_app -o pid,etime=; for c in can0 can1; do echo -n \"\$c:\"; ip -br link show \$c; done"
```

预期（干净重启后）：`arm_dual_app` 数量 0、`robot_app`（相机栈）已自启、CAN 可能 UP 也可能 DOWN（脚本会兜底配）。

---

## 2. 【终端 A · 工作站】启动 policy 服务

```bash
cd /home/discover/Desktop/Openpi_RL
bash scripts/cmds/serve_policy.sh
```

- serve 脚本已指向 wrist_only ckpt：
  - `POLICY_CONFIG=pi05_vio_plant_collection_535_clean_wrist_only`
  - `CHECKPOINT_DIR=checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/vio_pi05_535_clean_wrist_only_80k_260717/20000`
- **就绪标志**：日志出现 `server listening on 0.0.0.0:8000`（加载约 1–2 分钟）。
- 让它常驻，占一个终端。

> 换回原三相机模型：把 serve_policy.sh 的 `POLICY_CONFIG=pi05_vio_plant_collection`、`CHECKPOINT_DIR=checkpoints/pi05_vio_plant_collection/vio_pi05_260628/80000`，且第 4 步守护进程要发**三路**相机、请求可带 advantage。

---

## 3. 【机器人侧】拉起臂控 arm_dual_app（若 50071/50072 未 OPEN）

```bash
ssh root@192.168.25.1 'setsid nohup bash /root/start-arm-dual-app-2arm.sh > /tmp/start-arm-dual-app.launch.log 2>&1 < /dev/null &'
sleep 15
# 验证端口 + 6 个运动节点是否正常起来（不能出现 "Skipping N node(s)"）
ssh root@192.168.25.1 "ss -lntp | grep -E '50071|50072'; grep -h 'Framework started\|Skipping.*node' /tmp/arm_dual_app_logs/left_arm.log /tmp/arm_dual_app_logs/right_arm.log | tail -4"
```

- **健康标志**：50071/50072 监听 + 两臂 `Framework started successfully`，**没有** `Skipping 6 node(s) due to initialization failure`。
- 若出现 Skipping（电机没枚举完就起了）：停掉重来 `ssh root@192.168.25.1 'pkill -x arm_dual_app'`，等几秒再跑本步。

---

## 4. 【终端 B · 工作站 ROS2 环境】启动相机守护进程

```bash
cd /home/discover/Desktop/Openpi_RL
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE

python3 examples/airbot/openpi_camera_capture_daemon.py \
  --base_0_rgb-topic        /robot/camera/head/left/image \
  --left_wrist_0_rgb-topic  /robot/camera/left_wrist/left/image \
  --right_wrist_0_rgb-topic /robot/camera/right_wrist/left/image \
  --write-hz 15 --status-period-s 3
```

- **就绪标志**：持续打印 `have_all=True missing=[] writes=<递增>`。
- 观测文件写到 `/tmp/openpi_cam_daemon/latest.npz`（第 5 步要读）。常驻，占一个终端。
- 若守护进程报 `missing=[...]` 或工作站看不到相机话题（跨机 DDS 失稳，常见于机器人刚重启）：
  ```bash
  ssh root@192.168.25.1 'systemctl restart hbks_app'   # 重启相机栈，~10s 后恢复
  ```

> wrist-only 模型策略只吃两路腕相机，daemon 仍订三路（head 供录像/观察）也没问题；如只想订两路可加 `--wrist-only`。

---

## 5. 【终端 C · 工作站 SDK 环境】清错 → 执行闭环抓放

### 5.1 先清左右臂错误、确认双臂 IDLE（上一轮若进过 UNKNOWN_ERROR 必做）

```bash
cd /home/discover/Desktop/Openpi_RL
.venv-p7-sdk/bin/python - <<'PY'
from arm_p7_sdk import AirbotClient
for side,port in (("left",50071),("right",50072)):
    c=AirbotClient(host="192.168.25.1",port=port,backend="grpc")
    print(side,"before",c.get_service_state())
    c.clear_error(); c.set_arm_emergency_stop(False)
    print(side,"after ",c.get_service_state())
    c.close()
PY
```
两臂都要 `fsm_state='IDLE', controller_state='idle'` 才能继续。

### 5.2 （可选）先把双臂摆到初始位姿

> 如果臂当前姿态离抓放起始位太远、或某关节越限（重启后 joint4 常越限），先摆位。
> **注意**：越限起点用 PTP 会报 `Invalid start joint pose`，必须用 **servo 脚本**小步挪回。

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_servo_move_to_joint_target.py \
  --side both --target "0,0.647,0,-0.933,0,0,-1.15" \
  --max-step-rad 0.03 --speed-rad-s 0.6 \
  --execute --allow-robot-motion
```

### 5.3 执行闭环抓放（safeguard 全关）

```bash
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --duration-s 60 --period-s 0 --controller servo --enable-gripper \
  --chunk-steps 5 \
  --max-step-translation-m 0 --max-step-rotation-rad 0 --max-envelope-m 0 \
  --arm-speed-rad-s 0.6 \
  --capture-mode latest-file \
  --latest-obs-npz  /tmp/openpi_cam_daemon/latest.npz \
  --latest-obs-meta /tmp/openpi_cam_daemon/latest.json \
  --prompt "put the plant into the collection box" \
  --execute --allow-robot-motion
```

参数说明：

| 参数 | 含义 |
|---|---|
| `--max-step-translation-m 0` `--max-step-rotation-rad 0` `--max-envelope-m 0` | **safeguard 全关**（脚本里 `>0` 才检查，设 0 即禁用） |
| `--capture-mode latest-file` | 从守护进程读观测，避开相机 DDS churn |
| `--chunk-steps 5` | 每次推理执行 5 个动作步再重采图 |
| `--arm-speed-rad-s 0.6` | servo 轴速；**不能低于 ~0.55**，否则 `set_arm_speed` 被拒 |
| `--enable-gripper` | 启用夹爪 `move_eef` |
| `--duration-s 60` | 运行时长；随时 `Ctrl+C` 停，脚本会自动切 idle+释放控制权 |

> 无法关闭、也不该关闭的底线保护：SDK/固件关节限位、运动前 IDLE 前置检查、异常自动 `release_control`。这些是硬件级安全，不是可调 safeguard。

---

### 5.4 右臂 joint6 以 20 秒周期匀速往复

该指令先以不超过 `0.1rad/s` 的命令轨迹把右臂移到
`[0, 0.647, 0, -0.933, 0, 0, -1.15]rad`，随后保持其它 6 个关节不变，
让 joint6 在 `-0.5rad` 和 `+0.5rad` 之间运行三角波。完整周期是 `20s`：
`0s=0`、`5s=+0.5`、`10s=0`、`15s=-0.5`、`20s=0`，目标角速度恒为
`0.1rad/s`，仅在端点换向。

先离线预览（不连接机械臂）：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_joint6_triangle_wave.py
```

确认右臂工作空间无障碍、右臂服务为 `IDLE/idle/valid` 后正式运行：

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_joint6_triangle_wave.py \
  --side right \
  --start "0,0.647,0,-0.933,0,0,-1.15" \
  --joint6-low-rad -0.5 --joint6-high-rad 0.5 \
  --period-s 20 --rate-hz 20 \
  --approach-speed-rad-s 0.1 --sdk-speed-rad-s 0.55 \
  --execute --allow-robot-motion
```

默认持续运行，按 `Ctrl+C` 后脚本停止发令、切回 `idle` 并释放控制权。只运行有限
周期可加 `--cycles N`；控制左臂则把 `--side right` 改为 `--side left`。

> `set_arm_speed()` 在当前 SDK 中允许的最低值约为 `0.55rad/s`，所以
> `--sdk-speed-rad-s` 不能直接设为 `0.1`。脚本通过 20Hz 小步完整关节目标构造
> `0.1rad/s` 的命令轨迹；真实关节速度仍由 servo 跟踪效果决定，首次正式运行应现场
> 观察反馈，不应把离线轨迹验证当成真机速度实测。

2026-07-20 16:48-16:52 CST 右臂真机实测：初始摆位 `6.5s`，摆位结束最大误差
`0.0151rad`；连续运行约 200 秒，`-0.5/0/+0.5rad` 三个关键点的实测误差约
`0.016-0.019rad`，没有命令拒绝或电机错误。该次旧后台进程的 `SIGINT` 未生效，
最后用 `SIGTERM` 停止并由新客户端显式切 idle；脚本随后已修复为显式注册
`SIGINT/SIGTERM`，后续后台停止会进入 idle/release 清理。完整记录见
[`CHECKLOG.md`](CHECKLOG.md#2026-07-20-1650-cst--右臂-joint6-20-秒周期往复真机运行)。

### 5.5 双臂全部关节在初始位置 ±0.1rad 内以 10 秒周期同步往复

该指令先让左右臂同步到
`[0, 0.647, 0, -0.933, 0, 0, -1.15]rad`，再让双臂全部 14 个关节运行
同相三角波。所有关节的周期偏移都是：`0s=0`、`2.5s=+0.1`、`5s=0`、
`7.5s=-0.1`、`10s=0`，命令角速度为 `0.04rad/s`。

```bash
.venv-p7-sdk/bin/python examples/airbot/p7_all_joints_triangle_wave.py \
  --side both \
  --start "0,0.647,0,-0.933,0,0,-1.15" \
  --amplitude-rad 0.1 --period-s 10 --rate-hz 20 \
  --approach-speed-rad-s 0.1 --sdk-speed-rad-s 0.55 \
  --execute --allow-robot-motion
```

2026-07-20 16:56-16:57 CST 双臂真机实测通过：初始摆位 `7.45s`，左/右起点
最大误差分别为 `0.0151/0.00436rad`；连续多个周期的最大跟踪误差小于
`0.0095rad`，抽样确认两臂全部关节相对中心都在 `±0.1rad` 内，14 个电机错误码
全为 0。详见 [`CHECKLOG.md`](CHECKLOG.md#2026-07-20-1702-cst--双臂全部关节-01rad10-秒周期运行与停止)。

## 6. 记录三路相机数据（可选，另开终端）

在 ROS2 环境下（与第 4 步同环境变量）：

```bash
cd /home/discover/Desktop/Openpi_RL
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE

python3 examples/airbot/record_camera_clip.py \
  --out-dir /tmp/openpi_task_rec --duration-s 100 \
  --base_0_rgb-topic        /robot/camera/head/left/image \
  --left_wrist_0_rgb-topic  /robot/camera/left_wrist/left/image \
  --right_wrist_0_rgb-topic /robot/camera/right_wrist/left/image
```

产物：`/tmp/openpi_task_rec/{base_0_rgb,left_wrist_0_rgb,right_wrist_0_rgb,tiled}.mp4`（三路各自 + 拼接）。

---

## 7. 常见故障速查（本仓库多轮实测）

| 现象 | 原因 | 处理 |
|---|---|---|
| `move_end_pose False` + `eef switch mode failed: entered UNKNOWN_ERROR` | 夹爪切模式偶发进错误态，左臂 FSM `UNKNOWN_ERROR` | 跑 §5.1 清错后重来 |
| `set_arm_speed False` | 轴速 < ~0.55 rad/s 被 SDK 拒 | `--arm-speed-rad-s` 用 ≥0.6 |
| `plan failed: Invalid start joint pose` | 起点关节越限（重启后 joint4 常越 -2.43 下限） | 用 §5.2 servo 脚本挪回合法区，别用 PTP |
| capture 超时 / 守护 `missing=[...]` | 相机跨机 DDS 失稳（机器人刚重启易发） | `ssh root@192.168.25.1 'systemctl restart hbks_app'` |
| arm_dual_app 日志 `Skipping 6 node(s)` | 电机没枚举完就起了臂控 | `pkill -x arm_dual_app`，等几秒重起 §3 |
| 臂控 50071/50072 closed | arm_dual_app 未自启（重启后不自启） | 跑 §3 |

---

## 8. 一句话流程（各环节已 OK 时）

```
serve_policy.sh(A) → [臂控在跑] → 相机守护(B) → 清错 → persistent_loop --execute(C)
```

启动顺序建议 A/③ 并行 → 等 serve 就绪 + 守护 have_all → 清错 → 跑闭环。
