# OpenPI 真机推理启动

## 0. 环境和终端分工

本流程需要三类运行环境，不能把命令混在同一个终端或虚拟环境中：

| 位置 | 终端/环境 | 负责内容 |
|---|---|---|
| X5 板端 `192.168.25.1` | `root` shell，ROS2 Humble/Horizon 运行库 | `arm_app`（50071/50072）和 `robot_app`（相机话题） |
| GPU 工作站 | 仓库根目录，系统终端 1 | `bash scripts/cmds/serve_policy.sh`，脚本内部使用 `uv run` 和 `.venv` |
| GPU 工作站 | 仓库根目录，系统终端 2 | 推理客户端，脚本内部使用 `.venv-p7-ros/bin/python` |

工作站终端不需要手动 `source` 或 `activate`；两个 wrapper 会选择各自的解释器。客户端默认
连接本机策略服务 `127.0.0.1:8000`、X5 `192.168.25.1:50071/50072`，并默认使用 ROS2
域 `0`、`rmw_fastrtps_cpp`。

启动前必须保证每个 `arm_app` 和 `robot_app` 只有一份。已有监听服务时不要再次执行启动命令，
否则会造成控制端口和 250Hz 板载控制争抢。

## 1. X5：启动左右 `arm_app` 和相机 `robot_app`

### 1.1 启动左右 `arm_app`

在 X5 的 root 终端执行：

```bash
ip link set can0 down
ip link set can0 type can bitrate 1000000 dbitrate 5000000 fd on restart-ms 100 berr-reporting on
ip link set can0 up
ip link set can1 down
ip link set can1 type can bitrate 1000000 dbitrate 5000000 fd on restart-ms 100 berr-reporting on
ip link set can1 up

cd /opt/arm_app
setsid nohup env LD_LIBRARY_PATH=/opt/arm_app/lib:/usr/hobot/lib \
  ./bin/arm_app configs/left_arm/project_config.json >/tmp/openpi_arm_app_left.log 2>&1 </dev/null &
setsid nohup env LD_LIBRARY_PATH=/opt/arm_app/lib:/usr/hobot/lib \
  ./bin/arm_app configs/right_arm/project_config.json >/tmp/openpi_arm_app_right.log 2>&1 </dev/null &
```

### 1.2 启动相机 `robot_app`

当前板端 `/etc/init.d/hbks_app.sh` 的 `robot_start()` 是空函数，因此执行
`systemctl start hbks_app.service` 不会拉起 `robot_app`。在 X5 的 root 终端使用完整的
Horizon/ROS 运行库环境手动启动：

```bash
cd /opt/robot_app

export PATH=/app/bin:/middleware/bin:/usr/hobot/bin:/system/bin:/system/sbin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LD_LIBRARY_PATH=/opt/ros/humble/lib:/app/lib:/app/pub/lib:/middleware/lib:/middleware/pub/lib:/usr/hobot/lib:/usr/hobot/lib/sensor:/system/lib:/system/usr/lib:/lib

setsid nohup ./bin/robot_app ./configs/project_config.json \
  >/tmp/openpi_robot_app_camera.log 2>&1 </dev/null &
echo $! >/tmp/openpi_robot_app_camera.pid
```

确认进程和双腕图像话题：

```bash
pgrep -af robot_app
tail -n 40 /tmp/openpi_robot_app_camera.log
source /opt/ros/humble/setup.bash
ros2 topic list | grep -E '^/robot/camera/.*/image$'
```

当前 wrist-only 推理使用：

```text
/robot/camera/left_wrist/left/image
/robot/camera/right_wrist/left/image
```

本机直接从内存预览双腕画面并统计 Hz（不运行 daemon、不写图片或 NPZ）：

```bash
cd /home/discover/Desktop/Openpi_RL
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
.venv-p7-ros/bin/python examples/airbot/show_ros2_camera_live.py --duration-s 0
```

OpenCV 窗口按 `Q` 或 `Esc` 退出。`robot_app` 会继续在板端运行。

## 2. 本机：启动策略服务和推理

两个本机终端都先执行：

```bash
cd /home/discover/Desktop/Openpi_RL
```

终端 1，启动 wrist-only `79999` policy：

```bash
bash scripts/cmds/serve_policy.sh
```

终端 2，启动 400 秒推理。推理主进程会直接订阅双腕 ROS2 图像并从内存发送给 policy，
不再启动相机 daemon，也不再读写 `latest.npz/json`。当前双腕 ROS2 publisher 是上一步在板端
启动的 `robot_app`；本推理入口只订阅图像，不会自动启动 `robot_app`：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
ROBOT_HOST=192.168.25.1 LOCAL_LOG_DIR=logs \
bash scripts/cmds/openpi_p7_unlimited_recovery.sh \
  --duration-s 400 --period-s 0 \
  --controller servo --no-servo-blocking --no-gripper-blocking \
  --stream-action-chunk --chunk-start-index 0 --chunk-steps 15 \
  --action-step-interval-s 0 \
  --max-step-translation-m 0.009 \
  --max-step-rotation-rad 3.141592653589793 \
  --max-measured-translation-m 0 --max-envelope-m 0 \
  --min-motion-command-interval-s 0.004 \
  --capture-mode ros2 \
  --wrist-only --no-advantage --arm-speed-rad-s 0.55 \
  --execute --allow-robot-motion
```

## 3. 停止与复位

- 终端 2 按 `Space`：双臂通过 P7 高级 SDK 的 `servo_control + move_joint(blocking=True)`
  单次目标调用回到初始位置，然后继续推理。闭环由 SDK 内部完成，客户端不拆 waypoint、不自行追踪误差。
- 终端 2 按 `Q` 或 `Ctrl+C`：优雅停止，双臂和夹爪恢复 `idle` 并释放控制权。
- OpenCV 窗口按 `Q` 或 `Esc`：执行相同的优雅停止。
- 从另一个终端停止或清理旧残留进程：

```bash
ROBOT_HOST=192.168.25.1 bash scripts/cmds/stop_openpi_p7_inference.sh
```

正常停止不需要重启 X5 上的 `arm_app`；命令仅在双臂和夹爪均确认进入 `idle` 后返回成功。

## 4. P7 专项运动与精度验证

以下三个工具不属于日常 policy 推理入口，只用于独立验证 P7 运动能力。执行前必须先停止
OpenPI 推理，确认没有其他进程占用双臂控制权，并保证左右 `arm_app` 正在监听
`192.168.25.1:50071/50072`。三个脚本都使用 Arm-P7 SDK 环境：

```bash
cd /home/discover/Desktop/Openpi_RL
```

### 4.1 双臂全部关节三角波测试

脚本：`examples/airbot/p7_all_joints_triangle_wave.py`

不连接机器人，只检查参数并打印轨迹：

```bash
.venv-p7-ros/bin/python examples/airbot/p7_all_joints_triangle_wave.py \
  --side both --cycles 1 --amplitude-rad 0.1 --period-s 10 --rate-hz 20
```

真实执行一个完整周期：

```bash
.venv-p7-ros/bin/python examples/airbot/p7_all_joints_triangle_wave.py \
  --host 192.168.25.1 --side both \
  --cycles 1 --amplitude-rad 0.1 --period-s 10 --rate-hz 20 \
  --execute --allow-robot-motion
```

默认中心关节位为 `[0,0.647,0,-0.933,0,0,-1.15]rad`，左右臂 7 个关节同步做
`+/-0.1rad` 三角波。有限周期正常结束会下发中心位，然后切回 `idle` 并释放控制权。
`--cycles 0` 会持续运行；`Ctrl+C` 会在下一帧停止并切回 `idle`，但不会额外回中心位，因此现场
验证推荐显式使用 `--cycles 1`。

### 4.2 双臂 planning 精度测试

脚本：`examples/airbot/p7_dual_planning_precision_probe.py`

只读连接双臂、读取稳定 TCP pose 并打印目标，不 acquire control、不运动：

```bash
.venv-p7-ros/bin/python examples/airbot/p7_dual_planning_precision_probe.py \
  --host 192.168.25.1 --axes x --step-m 0.02
```

真实执行双臂并发的 X 轴 `+2cm` planning，并在测量后回到各自起点：

```bash
.venv-p7-ros/bin/python examples/airbot/p7_dual_planning_precision_probe.py \
  --host 192.168.25.1 --axes x --step-m 0.02 \
  --velocity-scaling 0.1 --acceleration-scaling 0.1 \
  --execute
```

脚本输出每只手臂的轴向误差、交叉轴位移、总目标误差和返回误差。多个轴默认每轴测完都回到
该轴起点；不要在常规验证中使用 `--no-return-between-axes`。该脚本的真实运动开关只有
`--execute`，指定后会 acquire 双臂并切到 `planning_control`。

### 4.3 逐臂 servo 精度测试

脚本：`examples/airbot/p7_dual_servo_precision_probe.py`

只读连接双臂、读取稳定 TCP pose，并打印正负方向目标：

```bash
.venv-p7-ros/bin/python examples/airbot/p7_dual_servo_precision_probe.py \
  --host 192.168.25.1 --sides left,right --axes x --step-m 0.02
```

真实执行左右臂依次进行 X 轴 `+2cm/-2cm` servo，每次测量后回到各自基准位：

```bash
.venv-p7-ros/bin/python examples/airbot/p7_dual_servo_precision_probe.py \
  --host 192.168.25.1 --sides left,right --axes x --step-m 0.02 \
  --blocking --execute --allow-robot-motion
```

脚本不会并发移动双臂；顺序为方向、轴、手臂，每个目标后输出轴向误差、交叉轴位移、总目标
误差和返回误差。`--execute` 必须与 `--allow-robot-motion` 同时提供，否则拒绝运动。

### 4.4 闭合双夹爪并保存双腕单帧图片

脚本会先闭合左右夹爪，再以原始分辨率保存左右腕部立体相机共四张 JPG，并保存一张重叠图。默认 dry-run，
真实执行需要 `--execute --allow-robot-motion`：

```bash
.venv-p7-ros/bin/python examples/airbot/close_grippers_capture_wrist_images.py \
  --output-prefix ./data/closed_wrist \
  --execute --allow-robot-motion
```

四张原始尺寸单图：

```text
./data/closed_wrist_left_wrist_left_rgb.jpg
./data/closed_wrist_left_wrist_right_rgb.jpg
./data/closed_wrist_right_wrist_left_rgb.jpg
./data/closed_wrist_right_wrist_right_rgb.jpg
./data/closed_wrist_wrist_overlay.jpg
```

默认 host 为 `192.168.25.1`，四路 topic 为 `/robot/camera/{left_wrist,right_wrist}/{left,right}/image`。

### 4.5 键盘控制双臂末端六自由度

脚本：`examples/airbot/keyboard_dual_arm_teleop.py`。默认是 dry-run，运行时仍会读取左右 TCP pose，
但不会申请控制权或调用 `move_end_pose()`：

```bash
bash scripts/cmds/keyboard_dual_arm_teleop.sh
```

清空工作空间后，实际运动必须显式传入两个开关：

```bash
bash scripts/cmds/keyboard_dual_arm_teleop.sh --execute --allow-robot-motion
```

`1`/`2`/`b` 选择左臂/右臂/双臂；`w/s`、`a/d`、`r/f` 控制 `X/Y/Z`；`i/k`、`j/l`、`u/o`
控制 roll/pitch/yaw；`q` 或 Ctrl-C 会切回 `idle` 并释放控制权。默认每次按键移动 `2mm`、旋转 `2deg`，
相对启动 TCP 受 `5cm` 平移和 `30deg` 姿态包络限制；不控制夹爪。可通过 `P7_TELEOP_*` 环境变量或
Python 脚本参数调整，`--frame local` 改为 TCP 局部坐标系。
