# OpenPI 单进程相机输入（2026-07-20）

## 结论

- 日期：2026-07-20 23:45 CST；检查人：Codex。
- `openpi_p7_persistent_loop.py` 现在在控制主进程中创建一个长期存活的 ROS2 node，直接订阅
  `/robot/camera/left_wrist/left/image` 和 `/robot/camera/right_wrist/left/image`。
- 每轮推理要求左右相机的接收计数都比上一轮推进；任一路没有新帧会在
  `--capture-timeout-s` 后失败，不再把缓存首帧伪装为新观测。
- ROS `Image` 的 NV12/RGB/BGR/mono8 解码复用
  `capture_ros2_openpi_observation.py` 的 `image_to_rgb()`；原始 RGB 通过常驻
  `WebsocketClientPolicy` 从内存直接发给 policy server，不落盘 NPZ/JSON。
- 模型图像预处理没有在客户端重写。服务端仍走
  `model.preprocess_observation()` -> `image_tools.resize_with_pad(..., 224, 224)`；按比例缩放并
  补黑边。训练期 `RandomCrop` 仅在 `train=True` 且非 wrist 图像时启用，当前 wrist-only
  推理不裁剪。
- 新组合环境 `.venv-p7-ros` 使用 Python 3.12，可同时导入 ROS2 Jazzy `rclpy`、
  `sensor_msgs`、`arm_p7_sdk 1.1.2` 和 `openpi_client`。两个 P7 runner 默认使用该环境。

## 旧帧根因证据

旧 camera daemon 在收到首组帧后，只检查 `have_all`，即使 ROS callback 没有再收到消息，
仍按 `--write-hz` 重写缓存数组。现场文件 mtime 每秒变化，但 metadata 内两路
`stamp_sec=1784553300` 长时间不变；旧消费者只检查文件 mtime，所以持续接受同一图像。
现场还发现两个 daemon 同写一路径，以及三个 orphan `--execute` persistent loop。

## 本次操作与当前状态

执行过的关键命令：

```bash
ps -eo pid,ppid,pgid,sid,stat,cmd | rg \
  'openpi_p7_(unlimited_recovery|persistent_loop)|openpi_camera_capture_daemon'

kill -TERM -- -214681 -251343 -263473
kill -TERM 119839 267490

.venv-p7-ros/bin/python examples/airbot/p7_ensure_idle.py --host 192.168.25.1
```

## 2026-07-21 00:01 CST - `arm_app` 是否发布相机（agent: Codex）

目的：确认禁止使用 `robot_app` 后，板端现有 `arm_app` 能否直接提供相机图像。

检查命令（板端 `192.168.25.1`）：

```bash
pgrep -af 'arm_app|robot_app'
ss -lntp | grep -E '50071|50072'
source /opt/ros/humble/setup.bash && ros2 topic list
grep -RniE 'camera|image|mipi|sensor|node|plugin' \
  /opt/arm_app/configs/{left_arm,right_arm}/project_config.json \
  /opt/arm_dual_app/configs/{left_arm,right_arm}/project_config.json
```

关键结果：当前仅有左右两个 `arm_app`，分别加载
`configs/left_arm/project_config.json` 和 `configs/right_arm/project_config.json`；其 P7 gRPC
端口为 50071、50072，没有 `robot_app` 进程。ROS2 graph 中可见大量
`/arm/left/...`、`/arm/right/...` 控制与状态话题，但没有名称含 `camera` 或 `image` 的话题。
上述四份 arm 配置中也没有相机/MIPI/image publisher 节点配置。

结论：**当前运行的 `arm_app` 不发布相机图像**。它负责机械臂控制、状态话题和 P7 gRPC；相机
必须由另外的相机驱动/发布进程提供。禁止 `robot_app` 且没有其他 publisher 时，主推理进程即使
已经内置 ROS2 订阅，也没有可订阅的板载相机图像源。

五个旧进程均已退出。清理后左右臂及 EEF 均为 `IDLE/idle/valid` / `idle`。只读内存采集
探针在 4 秒内没有收到相机帧，并明确返回
`missing=['left_wrist_0_rgb','right_wrist_0_rgb']`；当时 ROS graph 无 camera image topic，板端
`hbks_app.service` inactive，且 `/etc/init.d/hbks_app.sh` 的 `robot_start()` 为空函数。因此该次
失败是上游相机 publisher 未运行，不是读取旧文件。

## 23:48 bug 修复与最小验证

第一次手动启动板端 `/opt/robot_app/bin/robot_app` 没有继承 init 脚本的运行库环境，日志为：

```text
Cannot load plugin: libalog.so.1: cannot open shared object file
Failed to initialize framework
```

用 `/etc/init.d/hbks_app.sh` 中的 `PATH` 和 `LD_LIBRARY_PATH` 重启后，PID `1258455` 的
camera node 初始化成功；左右腕四路相机 started，头部两路 init failed，但不影响当前
wrist-only checkpoint。工作站 ROS graph 随后出现：

```text
/robot/camera/left_wrist/left/image
/robot/camera/right_wrist/left/image
```

同时修正主循环初始化顺序：在连接/接管机械臂之前，必须先收到左右新帧、写入 OpenCV
预览，并完成第一次 policy inference。相机或 policy 不可用时不会 acquire control 或切 servo。

最小验证命令：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
.venv-p7-ros/bin/python examples/airbot/openpi_p7_persistent_loop.py \
  --iterations 1 --period-s 0 --capture-mode ros2 --wrist-only --no-advantage
```

关键输出：两路均收到 `640x480 encoding=nv12`；OpenCV preview 进程正常启动；首次 policy
返回 `action_shape=[50,32] infer_ms=226.23`；完成一轮 dry-run。明确打印未调用
`acquire_control/switch_controller/move_end_pose/move_eef`，左右最终均为
`IDLE/idle/valid`。

## 23:52 用户约束修正：禁止板端 robot_app

用户明确要求不使用板端 `robot_app`。Codex 启动的 PID `1258455` 已停止；该进程对
SIGTERM/SIGINT 未退出，最后仅对精确 PID 使用 SIGKILL。启动文档已撤回 robot_app 步骤，
推理代码本身从未包含自动启动 robot_app 的逻辑。

工作站设备检查显示 `/dev/video0` 和 `/dev/video1` 都属于同一只
`USB2.0 HD UVC WebCam`：只有 video0 带 `ID_V4L_CAPABILITIES=:capture:`，video1 不具备
capture capability，因此不能映射为左右腕两路。板端当前没有标准 `/dev/video*` 输出；在
robot_app 停止后也没有任何 wrist image ROS2 topic。

结论：单进程内存读取机制已实现，但在“禁止 robot_app”约束下，当前仓库/机器没有已确定的
双腕像素入口。继续完成真机输入需要用户指定另一数据源，或选择把客户端部署到板端并新增
Horizon/Hobot MIPI API 适配；不能把一只本地 USB 相机复制成左右腕输入。

## 23:56 原始 AIRBOT inference 相机链路复核

原始链路为 `airbot_inference_{sync,async}.py -> play_operator.Robot -> airdc.V4L2Camera`，与
ROS2、camera daemon、板端 `robot_app` 均无关。它要求运行 inference client 的机器本地直接
连接相机设备：

- `RobotConfig.camera_names=[base_0_rgb,left_wrist_0_rgb,right_wrist_0_rgb]`；
- `camera_index=[0,2,4]`，即本地 V4L2 索引；
- 三路均为 `MJPEG 640x480 @ 30fps`；
- `Robot.__init__()` 为每路构造并 `configure()` 一个长期存活的 `V4L2Camera`；
- `capture_observation()` 调每个设备的 `capture_observation()`，仅将 OpenCV/V4L2 的 BGR
  三通道反转为 RGB；
- sync/async 客户端从 `<camera_name>/color/image_raw` 取数组，直接放进 WebSocket policy
  observation；
- 服务端 `preprocess_observation()` 才执行 `resize_with_pad(...,224,224)`。`RandomCrop(95%)`
  只在 `train=True` 且非 wrist 图像时执行，wrist-only inference 不 crop。

当前工作站不满足原始默认硬件前提：`/dev/video0,1` 属于同一只 USB UVC 摄像头，只有 video0
可 capture，没有原代码期望的三只（或 wrist-only 所需的两只）独立相机设备；私有 `airdc`
包在当前组合环境也未安装。

## 23:59 scripts 相机测试入口复核

`scripts/cmds/test_openpi_observation_read.sh` 本身不打开相机、不订阅 ROS2。它用
`.venv-p7-sdk/bin/python` 启动 `openpi_observation_read_probe.py`，后者循环读取
`/tmp/openpi_cam_daemon_wrist/latest.npz/json`，校验文件 mtime、RGB shape/dtype、ROS header
timestamp/CRC 是否推进，并通过 P7 gRPC 读取左右 TCP pose。真正的图像采集者仍是已经取消的
`openpi_camera_capture_daemon.py`；因此该测试通过只代表 daemon 文件链路可读，不代表 probe
直接访问了相机。

另一个旧入口 `scripts/cmds/openpi_p7_closed_loop.sh` 才会直接发起 ROS2 抓图：它每次 iteration
用 `/usr/bin/python3` 新起 `capture_ros2_openpi_observation.py`，订阅配置的 image topic，收到一组
帧后写 `obs_*.npz/json`，随后再由 `uv run python` 请求 policy。它不使用 V4L2，仍要求外部
ROS2 image publisher 存在，而且每轮新建 DDS participant。

## 当前启动命令

不再运行 `openpi_camera_capture_daemon.py`。policy server 启动后直接执行：

```bash
ROBOT_HOST=192.168.25.1 LOCAL_LOG_DIR=logs \
bash scripts/cmds/openpi_p7_unlimited_recovery.sh \
  --duration-s 400 --period-s 0 \
  --controller servo --no-servo-blocking --no-gripper-blocking \
  --chunk-steps 1 --action-step-interval-s 0 \
  --max-step-translation-m 0.009 \
  --max-step-rotation-rad 3.141592653589793 \
  --max-measured-translation-m 0 --max-envelope-m 0 \
  --min-motion-command-interval-s 0 \
  --capture-mode ros2 --wrist-only --no-advantage --arm-speed-rad-s 0.55 \
  --execute --allow-robot-motion
```

## 2026-07-21 00:08 CST - 恢复 `robot_app` 并直接内存预览测速（agent: Codex）

用户重新确认需要板端 `robot_app`。本次仅启动相机 publisher 和运行本地只读查看器，没有连接
policy、申请机械臂控制权或发送运动命令，也没有运行 camera daemon、写 NPZ/图片/视频。

板端启动命令的关键部分如下。由于当前 `/etc/init.d/hbks_app.sh` 中 `robot_start()` 为空，不能
通过 `systemctl start hbks_app` 启动应用，故直接使用 unit 中相同的 Horizon/ROS 运行库环境：

```bash
ssh root@192.168.25.1
cd /opt/robot_app
export PATH=/app/bin:/middleware/bin:/usr/hobot/bin:/system/bin:/system/sbin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LD_LIBRARY_PATH=/opt/ros/humble/lib:/app/lib:/app/pub/lib:/middleware/lib:/middleware/pub/lib:/usr/hobot/lib:/usr/hobot/lib/sensor:/system/lib:/system/usr/lib:/lib
nohup ./bin/robot_app ./configs/project_config.json >/tmp/openpi_robot_app_camera.log 2>&1 </dev/null &
```

启动结果：PID `1357054` 持续运行。左右腕的左右目共 4 路初始化并 Started；头部 2 路 Init
Failed。工作站可见：

```text
/robot/camera/left_wrist/left/image
/robot/camera/left_wrist/right/image
/robot/camera/right_wrist/left/image
/robot/camera/right_wrist/right/image
```

新增只读查看器 `examples/airbot/show_ros2_camera_live.py`。它在单进程内以 QoS depth 1 订阅左右
腕左目，在 ROS callback 中只保留最新 `sensor_msgs/Image`，直接从内存完成 NV12 -> RGB -> BGR，
随后调用 `cv2.imshow` 并按 callback 到达时间统计每路 Hz；没有中间文件或 daemon。

验证命令：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
.venv-p7-ros/bin/python examples/airbot/show_ros2_camera_live.py --duration-s 15
```

15 秒测试中，启动后的稳定段左右两路均达到约 `29.5 Hz`，OpenCV 成对显示约 `30 Hz`；后半段
接收速率下降，整段汇总为左右各 `321 frames / 22.02 Hz`，成对显示
`321 frames / 22.26 Hz`。因此本次可确认峰值/稳定段约 30 Hz，但 15 秒全程平均约 22 Hz；不能
把峰值当作持续全程速率。退出查看器后 `robot_app` 与四路 wrist image topic 仍在线。

## 2026-07-21 00:19 CST - 导出最近一次模型图像输入（agent: Codex）

用户要求导出推理时送入模型的图片。检查时没有推理主循环在运行；源文件是最近一次推理于
`2026-07-21 00:15:59 CST` 原子写入的
`/tmp/openpi_p7_persistent_loop/policy_input_preview.npz`，不是实时更新中的文件。该文件由主循环
对当次发送给 policy 的 ROS2 RGB 帧执行与模型预处理一致的
`image_tools.resize_with_pad(image, 224, 224)` 后生成。

导出目录：`logs/model_input_images/20260721_001559/`。其中包含：

- `left_wrist_0_rgb.png`：RGB 224x224，SHA256
  `5cb6e39bce1d66eed9d0ec3183cb71c94a4b2a0908f86e52cefa842348e48a42`；
- `right_wrist_0_rgb.png`：RGB 224x224，SHA256
  `1b9e7be5f1b2521f1a6360a1a477b366edec4b22766e427a9551b93f90a0c8f9`；
- `model_input_rgb.npz`：保留同一个原子快照的 RGB 数组，SHA256
  `c566616e437c3899713359efb4e3f3bde13deeef9753a6b51ac45764e13abdd3`。

数组检查为左右两路均 `uint8 (224,224,3)`，像素范围分别 `0..253`、`0..254`。视觉检查确认
两路均为有效工作台画面；上下黑边来自保持宽高比的 resize-with-pad，不是坏帧。

## 2026-07-21 00:26 CST - 闭合双夹爪后抓图被左臂 bit 19 阻断（agent: Codex）

目的：按用户要求将左右 G2P 夹爪以 `0.0 mm`、`100 mm/s`、blocking、effort `5.0` 完全闭合，
确认反馈后再抓取双腕模型输入图像。预检查发现没有 OpenPI 推理控制进程，左右
`arm_app`、相机 `robot_app` 和双腕 image topic 均在线，但左臂服务状态为
`UNKNOWN_ERROR/idle/valid`，第 7 关节 `error_id=524288 (1<<19)`；左 EEF 自身 error 为 0、位置
约 `92.707 mm`，右臂为 `IDLE/idle/valid`、右 EEF 约 `95.090 mm`。

首次闭合程序在任何 `acquire_control()` / `move_eef()` 前因左臂不是 IDLE 而中止。随后只执行
现有标准恢复工具：

```bash
.venv-p7-ros/bin/python examples/airbot/p7_ensure_idle.py \
  --host 192.168.25.1 --acquire-timeout-s 3 --controller-timeout-ms 3000
```

左侧 `clear_error()` 返回 True，但 FSM 仍是 UNKNOWN_ERROR；切 EEF idle/CSP 被 route 以
`FAILED_PRECONDITION: eef switch mode failed: entered UNKNOWN_ERROR` 拒绝，arm idle 切换也被
当前 FSM 拒绝。工具最终释放左右 lease，右侧保持正常 IDLE。该 bit 19 与已有记录一致，软件
clear 不能清除，历史上需要机械臂断电重启。

影响：本次**没有向任一夹爪发送闭合命令，也没有保存所谓“闭合后”图片**，避免左右状态不一致
或绕过硬件错误强行动作。必须先清除左臂 joint7 bit 19，再重新执行闭合和双腕抓图。

## 2026-07-21 00:29 CST - 训练/推理双腕图 50% 叠加拼图（agent: Codex）

检查 `logs/model_input_images/20260721_001559/` 中四张 224x224 图片并按视角配对：

- 左腕：训练 `20260721-002600.jpg`，推理 `left_wrist_0_rgb.png`；
- 右腕：训练 `20260721-002620.jpg`，推理 `right_wrist_0_rgb.png`。

每侧使用 OpenCV `addWeighted(training, 0.5, inference, 0.5, 0)` 做同像素位置 50%/50% 混合，
再按左腕、右腕顺序横向拼接。输出为
`logs/model_input_images/20260721_001559/training_inference_overlay_50_side_by_side.png`，格式 RGB
PNG、尺寸 448x224，SHA256 为
`ee6f8f3cebc83de42a87e29279a534b214a69539433c9b0bd808b320a8f2bbf2`。视觉检查确认左右顺序、
叠加和拼接均正确；双影体现两次采集之间的相机位姿/场景差异。

## 2026-07-21 00:38 CST - 双夹爪闭合并保存新模型输入图（agent: Codex）

用户对 00:26 被 bit 19 阻断的操作重新发起执行。检查发现 X5 已重启，`arm_app/robot_app` 均未
运行、CAN0/1 为 STOPPED；按 `scripts/README.md` 配置 CAN `1M/5M`，启动左右 `arm_app`
（PID `2546/2547`）和相机 `robot_app`（PID `2548`）。随后 `50071/50072` 正常监听，四路腕部
相机 Started，头部两路仍 Init Failed。

重启后左右服务均为 `IDLE/idle/valid`，14 个 arm motor error 和两个 EEF error 全为 0。
获取左右 lease 后，将 EEF 切至 CSP、速度设为 `100 mm/s`，分别 blocking 下发
`move_eef(pos=[0.0], eff=[5.0])`；左右 RPC 均返回 True。0.5 秒反馈为左 `0.1507 mm`、右
`0.8088 mm`。随后双 EEF 均恢复 idle，并释放 lease。

闭合后直接在内存订阅双腕左目新帧；两帧 ROS header 时间戳仅相差约 34 微秒，均为 NV12
640x480。按模型路径执行 `resize_with_pad(...,224,224)` 后保存到：

- `logs/model_input_images/20260721_003628_grippers_closed/left_wrist_0_rgb.png`，SHA256
  `87ae08ee68d61f19081652b660468fa312ea892522555ca50711c9fab330001c`；
- `logs/model_input_images/20260721_003628_grippers_closed/right_wrist_0_rgb.png`，SHA256
  `bda098900cd5db63099ca374d986dbefa40a072f8d3611ab7251ca4faf317590`。

没有运行 camera daemon。两张 224x224 RGB PNG 已视觉确认有效并能看到闭合夹爪。最终复核：
左右仍为 `IDLE/idle/valid`，EEF idle，arm/EEF error 全 0；闭合反馈左 `0.1507 mm`、右
`0.8057 mm`。

## 2026-07-21 00:40 CST - 指定参考图与紧闭图 50% 叠加拼图（agent: Codex）

按用户明确映射，将 `20260721-003354.jpg` 作为左腕参考图、`20260721-003350.jpg` 作为右腕
参考图，分别与 `20260721_003628_grippers_closed/` 中新保存的左右紧闭图配对。四图均为
224x224，无 resize；每侧执行 `addWeighted(reference,0.5,closed,0.5,0)`，再按左、右顺序横向
拼接。

输出：
`logs/model_input_images/20260721_003628_grippers_closed/reference_3354_3350_vs_closed_overlay_50_side_by_side.png`，
RGB PNG 448x224，SHA256
`a003d8452e01c5cda0e84b6a7ab9477553a5cd8cca55f0e45ebfcac7d1f8b564`。视觉检查确认配对、左右
顺序和透明度叠加正确；参考 JPG 自带的顶部绿色帧/夹爪文字也以 50% 权重保留。
