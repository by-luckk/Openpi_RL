# `arm_app` 与 `robot_app` 的区别

## 2026-07-21 00:01 CST - 当前仓库口径核对（agent: Codex）

### 目的

说明当前 AIRBOT X5 部署中 `arm_app`、`robot_app` 的职责，避免把历史版本中
`robot_app` 曾承担的臂控职责套到当前部署。

### 结论

| 进程 | 当前职责 | 硬件/数据 | 对 OpenPI 的作用 |
|---|---|---|---|
| `arm_app` | 单臂实时控制 runtime；左右各启动一个实例 | 分别连接 `can0` / `can1`；当前实例提供 P7 gRPC `50071/50072` 和 arm 控制/状态话题 | 接收控制命令、返回机械臂状态和 TCP pose；是动作执行侧 |
| `robot_app` | 相机和传感器 runtime | 管理头部、左右腕相机等传感器，并发布 ROS2/DDS 图像话题 | 提供 policy 的视觉观测；当前相机配置不负责双臂 CAN 控制 |

二者是并列的不同硬件服务，不是上下级：`arm_app` 管“动”，`robot_app` 管“看”。
只启动 `arm_app` 可以保留机械臂控制能力，但不会凭空产生相机图像；只启动
`robot_app` 可以有相机/传感器数据，但不能替代臂控进程下发动作。

当前仓库的 `scripts/README.md` 明确要求 X5 左右各启动一条 `/opt/arm_app/bin/arm_app`，
并说明该 OpenPI 入口不启动或依赖板端 `robot_app`。这意味着视觉数据必须已经由用户指定的
外部双腕 ROS2 publisher 提供；不用 `robot_app` 不等于不用相机数据。

### 与 `arm_dual_app` 的关系

仓库还保留 `arm_dual_app` 的历史启动脚本。它同样是臂控 runtime，旧路线中左右实例也分别
通过 gRPC `50071/50072` 对外服务。当前现场已经换成左右两个 `arm_app` 提供相同端口。因此：

- `arm_app` 和 `arm_dual_app` 是两套臂控 runtime/接入路线，不应同时占用同一组 CAN；
- `robot_app` 是当前相机/传感器 runtime，职责不同；
- 2026-07-19 曾检查过一个只加载 DDS route、不监听 `50071/50072` 的 `arm_app` 配置；那是
  历史/反证路线，不是 2026-07-21 的现场运行方式；
- 早期部署曾用 `robot_app left_arm/right_arm/remote` 同时承担臂控和图传，因此旧文档中的
  `robot_app` 含义更宽。判断现场职责必须同时看版本、配置路径和启动参数，不能只看进程名。

### 核对命令与证据

```bash
rg -n --hidden -g '!docs/VIO_Test/VIO_Test/**' -g '!.git/**' \
  '\b(arm_app|robot_app)\b' .
sed -n '1,110p' scripts/README.md
sed -n '41,95p' docs/openpi-in-process-camera-20260720.md
rg -n 'backend="grpc"|50071|50072' scripts/cmds/openpi_p7_unlimited_recovery.sh examples/airbot
sed -n '1,45p' scripts/tools/start-arm-dual-app-2arm.sh
```

关键证据：

- `scripts/README.md`：先配置 `can0/can1`，再分别启动 left/right `arm_app`；当前推理入口
  “不会启动或依赖板端 `robot_app`”。
- `docs/openpi-in-process-camera-20260720.md` 的 2026-07-21 00:01 CST 现场检查：板端只有
  left/right `arm_app`，监听 P7 gRPC `50071/50072`，有 arm 控制/状态话题，但没有任何
  camera/image 话题；四份 arm runtime 配置均无相机 publisher 节点。
- 当前执行代码用 `AirbotClient(..., backend="grpc")` 连接 `50071/50072`。
- `scripts/tools/start-arm-dual-app-2arm.sh` 的旧路线注释记录了 2026-07-17 部署：当时
  `robot_app` 由 `hbks_app.service` 启动并发布相机话题，相机 `robot_app` 不碰 CAN，
  可与臂控 runtime 共存。2026-07-21 现场没有运行 `robot_app`，不能把该启动状态当成当前事实。

### 影响与检查边界

OpenPI 完整闭环仍需要两个独立条件：视觉 publisher 可用，以及左右臂控 runtime 可用。
本记录本身仅静态检查仓库文件和既有实测记录；引用的同一时刻现场只读检查确认了当前进程、
端口和 ROS2 graph。本记录没有启动、停止或控制机器人。新增 Markdown 已用
`git diff --no-index --check /dev/null docs/arm-app-vs-robot-app.md` 检查，无 whitespace 错误。

## 2026-07-21 00:05 CST - 是否争抢 250 Hz 板载控制（agent: Codex）

### 目的与命令

只读核对当前 X5 进程、两套实际配置和线程调度，判断同时存在 `robot_app` 与 `arm_app` 时，
是否会有两个进程争用同一条 250 Hz 机械臂控制链路。

```bash
ssh -o BatchMode=yes -o ConnectTimeout=4 root@192.168.25.1 \
  'pgrep -af "arm_app|robot_app"; ss -lntp | grep -E "50071|50072"'

ssh root@192.168.25.1 \
  'sed -n "1,220p" /opt/robot_app/configs/framework_config.json; \
   grep -RniE "can[01]|arm_|servo|control|250|grpc" \
     /opt/robot_app/configs /opt/arm_app/configs/{left_arm,right_arm} \
     --include="*.json"'

ssh root@192.168.25.1 \
  'for d in left_arm right_arm; do \
     sed -n "1,70p" /opt/arm_app/configs/$d/fsm_service_config.json; \
     sed -n "1,55p" /opt/arm_app/configs/$d/servo_config.json; \
     sed -n "1,25p" /opt/arm_app/configs/$d/arm_stream_config.json; \
   done; \
   ps -T -p 660463,660464 -o pid,spid,cls,rtprio,pri,psr,comm --no-headers'

ssh root@192.168.25.1 \
  'sed -n "1,180p" /opt/robot_app/configs/mavlink_config.json; \
   sed -n "1,220p" /opt/robot_app/configs/imu_config.json; \
   strings /opt/robot_app/lib/libsensors.so | \
     grep -Ei "MAVLink callback|collect_encoder|collect_button"; \
   nm -D -C /opt/robot_app/lib/libinfra.so | grep -Ei "MavlinkNode|mavlinkCreateNode"'
```

第一次线程查看命令中的远端 `awk` 表达式因 shell quoting 丢失字段变量而报语法错误；随后改用
上述 `ps -T -p ...` 命令成功读取。板端 `ss` 不支持 `-A can`，因此无法用它把 CAN socket
直接映射到 PID；改为只读 `/proc/net/can/*`、进程 fd 和接口计数。失败命令均未改变板端状态。

### 证据

- 00:05 初查时只运行 left/right 两个 `arm_app`，PID `660463/660464`，分别监听
  `50071/50072`。检查过程中另一个并行操作启动了 `robot_app` PID `1357054`；00:10 复核时
  三者并发，未由本记录启动。
- `arm_app` 的 `fsm_service_config.json` 明确配置 command publish `4 ms`、pull `2 ms`；
  `servo_config.json` 的 engine update 和 tick 都是 `4000 us`；运动模式 state stream 为
  `250 Hz`。因此问题中的 250 Hz/4 ms 循环属于 `arm_app`。
- 当前扁平 `/opt/robot_app/configs/framework_config.json` 只加载 `sensors`（相机、IMU、触觉、
  encoder/button）、`fan_control` 和 `calibration`。它没有加载 arm control、servo、arm gRPC
  route 或显式的 `infra::MavlinkNode`，所以没有第二套 4 ms/250 Hz 臂控循环。
- 但不能进一步断言 `robot_app` 完全不触碰 CAN：`libsensors.so` 中的 tactile、
  `collect_encoder`、`collect_button` 节点包含 MAVLink callback 注册；目录中的
  `mavlink_config.json` 把 `SYS_COLLECT` 实例映射到 `can0/can1`。该文件配置为
  `500 kbit/s + 2 Mbit/s data`，而当前 `arm_app` 配置为 `1 Mbit/s + 5 Mbit/s data`。
  在不 attach 系统调用跟踪器的前提下，无法把 CAN socket 精确归属到进程；后续并发只读观测
  确认接口没有被重配，但仍不能证明 sensor plugin 完全没有被动打开 CAN socket。
- `robot_app` 相机/传感器线程配置为 `RR 8`，processing 为 `FIFO 10`；两个 `arm_app` 的
  control 线程实际为 `FIFO 11`，CAN RX/TX 实际为 `FIFO 35/34`。X5 有 8 个 CPU 核。

### 结论

按当前证据，`robot_app` 与 `arm_app` **不会形成两套 250 Hz 板载臂控命令循环**：只有
`arm_app` 配置了 4 ms control/servo tick，`robot_app` 没有 arm control/servo runtime。
但现有静态证据不足以保证 `robot_app` 不会因 collect/tactile 的 MAVLink 支持打开同一
`can0/can1`；若它打开或尝试按另一组波特率重配接口，仍可能造成 CAN 层冲突或干扰。

二者仍会共享 X5 的 CPU、内存带宽和 DDS/shared-memory 等 SoC 资源，所以相机高负载可能造成
间接调度或传输抖动；但这不同于两个控制进程同时向 CAN 发 250 Hz 命令。当前 RT 优先级也使
arm control/CAN 高于 robot processing/sensor。本轮没有主动启动 `robot_app`，但在它被其他
并行操作启动后完成了下述短时间并发只读观测；没有 attach `strace`，也没有在机械臂运动期间做
长时间 jitter/queue-drop 压测。因此安全口径仍是：**短窗口未发现直接争抢，但正式 250 Hz
运动前仍应做无运动 CAN fd 确认和受控低速并发压测**。若需进一步隔离，可先禁用 `tactile`、
`collect_encoder`、`collect_button`。

若改用旧 `robot_app left_arm/right_arm/remote` 配置，或未来在扁平配置中加载 arm/MAVLink
plugin，结论会改变：那时可能与 `arm_app` 同时占用 CAN 或形成第二个命令源，必须二选一。
本轮全程只读，未启动/停止应用、未获取控制权、未发送运动命令。

### 00:10 并发现场补充

`robot_app` 被其他并行操作启动后，本轮只读复核：

```bash
ssh root@192.168.25.1 \
  'ip -details -statistics link show can0; \
   ip -details -statistics link show can1; \
   ps -T -p 1357054 -o pid,spid,cls,rtprio,pri,psr,comm --no-headers; \
   sed -n "1,160p" /proc/net/can/rcvlist_fil; \
   sed -n "1,160p" /proc/net/can/stats'

# 分别读取两路 ip -s link，等待 2 秒后再次读取
```

- 两路 CAN 均仍为 `ERROR-ACTIVE`，实时 error counter `tx=0 rx=0`，位速率保持
  `1 Mbit/s + 5 Mbit/s data`，没有被 robot 配置中的 `500k/2M` 改写。
- 2 秒内 `can0` RX 增加 322 包、`can1` RX 增加 1730 包；两路 TX 包数分别保持
  `1455334`、`1421204` 不变，累计 TX errors 也保持 `6131`、`4801` 不变。该短窗口中没有
  任何进程向 CAN 发送新帧，也没有新增错误。
- `robot_app` 实际线程与配置一致：camera/sensor 为 `RR 8`，processing 为 `FIFO 10`；
  `arm_app` control 为 `FIFO 11`，CAN RX/TX 为 `FIFO 35/34`。

这组并发观测进一步支持“`robot_app` 没有发送第二套 250 Hz 控制命令”。即便 sensor plugin
打开 CAN raw socket 做被动接收，SocketCAN 接收是向匹配 socket 分发副本，不会从 `arm_app`
手中排他地“抢走”帧。尚未覆盖机械臂运动时的长时间 jitter/queue-drop，也无法仅凭全局 CAN
计数把每个 socket 精确归属到 PID，因此仍保留上述 CAN 辅助节点和 SoC 负载风险边界。
更新后的 Markdown 再次通过 `git diff --no-index --check`。

## 2026-07-21 01:08 CST - 清理重复进程并统一重启（agent: Codex）

### 启动前事实

用户报告板端进程重复。只读核对发现：

- X5 有两套 left `arm_app`（PID `2546/181171`）和两套 right `arm_app`
  （PID `2547/181172`）；`50071` 和 `50072` 各被两个进程同时监听。
- 相机 `robot_app` 只有一份（PID `2548`）。
- 本机同时残留两个真实运动进程 `p7_move_to_joint_target.py`（PID `121120/158424`）。

### 操作

先按精确 cmdline 校验并 TERM/KILL 两个本机运动进程；再按精确 PID/cmdline 停止 X5 上上述
5 个应用进程。确认无 arm/robot runtime、`50071/50072` 已释放后：

1. 重配 `can0/can1` 为 CAN-FD `1M/5M`；
2. 按 `scripts/README.md` 分别启动 left/right `/opt/arm_app/bin/arm_app`；
3. 用完整 Horizon/ROS `PATH`、`LD_LIBRARY_PATH` 启动一份扁平配置 `robot_app`。

新 PID 为 left `185775`、right `185776`、robot `185777`，均已脱离 SSH shell、PPID 为 1。
端口归属唯一：`50071 -> 185775`、`50072 -> 185776`。

### No-motion 验证

SDK 只读检查：左右均为 `IDLE/idle/valid`，双 EEF idle，关节速度为 0；新 arm 日志均有
`Framework started successfully`，未出现 `Motor 7`、`UNKNOWN` 或 error。本次不能据此断言
仅软件重启清除了此前 bit19，因为本轮之前现场已经发生过外部停机/重启状态变化。

`robot_app` 的四路腕部相机均 Started、头部两路 Init Failed；工作站/X5 可发现当前推理所需：

```text
/robot/camera/left_wrist/left/image
/robot/camera/right_wrist/left/image
```

相机进程的 tactile、`collect_encoder`、`collect_button` 均因无法注册 MAVLink callback 而初始化
失败，但 framework 继续运行、腕部图像正常。这也提供了当前实例没有成功接入这些 MAVLink/CAN
辅助数据源的直接证据；失败不影响 wrist-only 图像，但相应触觉/encoder/button 数据不可用。

本轮未启动 OpenPI inference，未主动获取控制权或发送运动命令。最终本机无
`openpi_p7_unlimited_recovery`、`openpi_p7_persistent_loop` 或 `p7_move_to_joint_target.py`。

## 2026-07-23 20:37 CST - 双腕采图脚本因板端 runtime 未启动而阻断（agent: Codex）

用户运行 `close_grippers_capture_wrist_images.py` 时，SDK 报
`Timeout connecting to 192.168.25.1:50071`，但 ICMP ping 正常。只读复核命令：

```bash
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/192.168.25.1/50071'
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/192.168.25.1/50072'
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.25.1 \
  'hostname; ps -eo pid,comm,args | grep -E "[a]rm_app|[r]obot_app|[a]rm_dual_app" || true; \
   ss -lnt | grep -E ":(50071|50072)\\b" || true'
```

结果：SSH 正常进入主机 `ubuntu`；板端没有上述三个 runtime 进程，也没有 `50071/50072`
监听；工作站 TCP 连接两端口均立即返回 `Connection refused`。这是板端服务未启动，不是网络
不可达或采图脚本 topic 参数问题。脚本在第一个 SDK client 建连阶段退出，未调用
`acquire_control()` / `move_eef()`，因此未闭合夹爪、未采图、未写入 `./data/`。
