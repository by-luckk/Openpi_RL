# 双腕相机读取与保存检查

## 2026-07-23 19:58 CST - 当前脚本检查（agent: Codex）

### 目的

确认当前仓库是否能读取并保存左右两张夹爪（wrist）相机图像，以及各入口实际保存的格式。

### 检查命令

```bash
rg -n -i "wrist|left_wrist|right_wrist|imwrite|VideoWriter|np.savez|McapDataSampler|save_video" \
  examples/airbot scripts/cmds README.md
nl -ba examples/airbot/record_openpi_cameras.py | sed -n '24,28p;89,154p'
nl -ba examples/airbot/capture_ros2_openpi_observation.py | sed -n '28,46p;119,164p;167,199p'
nl -ba examples/airbot/inference_recorder.py | sed -n '26,53p;79,107p;160,214p;309,337p'
```

### 结论

有，当前至少有三种保存路径：

1. `examples/airbot/record_openpi_cameras.py` 直接订阅左右腕部 ROS2 图像话题：
   `/robot/camera/left_wrist/left/image` 和 `/robot/camera/right_wrist/left/image`。
   使用 `--wrist-only --output-prefix <前缀>` 时，会分别写出
   `<前缀>_left_wrist_0_rgb.mp4`、`<前缀>_right_wrist_0_rgb.mp4`，并额外写入左右拼接的
   `<前缀>_tiled.mp4` 和 metadata JSON。脚本使用 `cv2.VideoWriter`，不是逐帧 PNG/JPG。

2. `examples/airbot/capture_ros2_openpi_observation.py` 使用 `--wrist-only` 读取同两路相机的
   一组新帧，转换为 RGB 后通过 `np.savez_compressed` 保存到一个 `.npz`（默认
   `/tmp/openpi_real_observation_latest.npz`），数组键为 `left_wrist_0_rgb`、
   `right_wrist_0_rgb`（另含 `state`），并写入对应 metadata JSON。这是单次快照，不是图片文件。
   注意：该脚本默认 topic 是 `/camera/left_arm_left/image_rect` 和
   `/camera/right_arm_left/image_rect`，与录像脚本默认的 `/robot/camera/...` 名称不同；现场使用时
   应按实际 ROS2 topic 显式传参。

3. `examples/airbot/inference_recorder.py` 被 `airbot_inference_sync.py` / `async.py` 使用时，
   `record_data=true` 会把每一步 `raw_obs`（包括相机图像 topic）交给 `McapDataSampler`，按
   `save_video`（默认 `h264`，也支持 `jpeg`/`raw`）写入 episode `.mcap`。推理配置中的
   `record` 默认是 `record_data=false`，因此必须显式打开 `RECORD=true` 或相应配置才会落盘。

`openpi_p7_persistent_loop.py` 的常规路径只在内存中读取双腕 RGB 并发送给 policy；只有启用
`--show-policy-input` 时才把 224x224 预览数组写成 `.npz`，不会自动生成 PNG/JPG。

4. `examples/airbot/close_grippers_capture_wrist_images.py` 是本次新增的组合入口。它先通过
   P7 SDK 将左右 EEF 移到 `--close-mm`（默认 `0 mm`），然后采集一组新鲜的左右腕图像，使用
   OpenCV 分别保存为 JPG 或 PNG，并用 `cv2.addWeighted(..., 0.5, ..., 0.5, 0)` 生成一张
   左右各 50% 透明度的 `*_wrist_overlay.jpg/png`；同时保存 metadata JSON。真实闭合受
   `--execute` 和 `--allow-robot-motion` 双重开关保护。

### 影响

若需求是“录制两路夹爪相机视频”，直接使用 `record_openpi_cameras.py --wrist-only`；若需求是
“获取一组双腕图片供推理”，使用 `capture_ros2_openpi_observation.py --wrist-only`；若希望相机
图像与动作、关节状态绑定保存用于复训，则启用同步/异步推理的 MCAP recording；若要在闭合夹爪
后得到两张普通图片，则使用新增的组合脚本。原有 capture/persistent-loop 路径本身不会自动
生成 PNG/JPG。

## 2026-07-23 21:15 CST - 闭合夹爪后双腕抓帧超时（agent: Codex）

### 目的

定位 `close_grippers_capture_wrist_images.py` 报
`missing=['left_wrist_0_rgb', 'right_wrist_0_rgb'] stalled=[]` 的原因。

### 检查命令

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  .venv-p7-ros/bin/python examples/airbot/capture_ros2_openpi_observation.py \
  --wrist-only --timeout-s 8 \
  --left_wrist_0_rgb-topic /robot/camera/left_wrist/left/image \
  --right_wrist_0_rgb-topic /robot/camera/right_wrist/right/image \
  --output /tmp/closed_wrist_topic_probe.npz \
  --metadata-output /tmp/closed_wrist_topic_probe.json

ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ros2 topic list -t

ssh -o BatchMode=yes root@192.168.25.1 \
  "pgrep -af 'robot_app|arm_app'; ss -lntp | grep -E '50071|50072'; \
   source /opt/ros/humble/setup.bash && ros2 topic list | grep -E 'camera|image'"

ssh -o BatchMode=yes root@192.168.25.1 \
  "grep -nE 'sensor_init error|Failed to initialize camera|Total: 6 cameras' \
   /tmp/openpi_robot_app_camera.log"
```

### 证据与结论

- 两个 `arm_app`、`robot_app` 均在线，P7 gRPC `50071/50072` 均在监听；本次不是控制 runtime
  未启动，也不是工作站到 X5 不通。
- 显式使用 `ROS_DOMAIN_ID=0` 和 `rmw_fastrtps_cpp` 重跑同一组 topic，仍在 8 秒后得到两路
  `missing`。`missing` 且 `stalled=[]` 表示两个订阅都从未收到首帧。
- 工作站和板端 ROS graph 都只有腕部四路 `foxglove_msgs/msg/CompressedVideo` 的
  `*/video_encoded` 名称，没有任何腕部 `sensor_msgs/msg/Image` 的 `*/image` 名称。压缩话题端点
  仍被静态创建，不代表相机有帧；运行统计中四路腕部均为 `frames=0, fps=0.00`。
- `/opt/robot_app/configs/mipi_camera/x5/camera_config.json` 对腕部四路的 VSE `pub_image.enable`
  都是 `true`，所以 raw Image 并非被配置关闭。实际失败发生在相机初始化：左腕两路均为
  `stage=tx_remote_init ret=-2 tx=0`，右腕两路均为 `stage=tx_remote_init ret=-2 tx=1`，随后日志汇总
  `Total: 6 cameras configured, 2 initialized, 2 started, 4 failed`。只有两路头相机启动成功。

因此根因在板端腕部相机远端传感器/SerDes 链路初始化，不在 Python 脚本、QoS 或 topic 拼写。
用户指定的右腕 `/right/image` 本身也存在于配置；即使改为模型常用的 `/left/image`，在当前四路
腕部相机全部初始化失败的状态下仍不会收到帧。需要先恢复腕部相机硬件链路并让 `robot_app`
重新初始化成功，再运行抓图。组合脚本的执行顺序是先闭合夹爪、再抓图，因此这次抓图失败不表示
前面的闭合动作被回滚；超时发生时图片和 metadata 尚未写入。

## 2026-07-23 21:28 CST - 临时生成上下翻转双腕重叠图（agent: Codex）

按用户要求，不修改 `close_grippers_capture_wrist_images.py` 和两张原始 JPG。系统没有安装
ImageMagick，第一次执行 `convert ...` 返回 `command not found`；随后使用 `.venv-p7-ros` 中的
OpenCV 读取 `data/closed_wrist_right_wrist_0_rgb.jpg`，以 `cv2.flip(image, 0)` 上下翻转，再与
`data/closed_wrist_left_wrist_0_rgb.jpg` 通过 `cv2.addWeighted(..., 0.5, ..., 0.5, 0)` 混合。
临时输出为 `/tmp/closed_wrist_right_vflip_left_overlay.jpg`，检查结果为 `640x480x3 uint8`，视觉
确认两路均已显示且处理方向正确。

## 2026-07-24 13:42 CST - 闭合夹爪后的双腕抓帧失败复核（agent: Codex）

### 目的

核对用户执行 `close_grippers_capture_wrist_images.py` 后的
`timed out waiting for fresh camera frames`，区分 topic 参数问题与板端相机运行状态。

### 检查命令

```bash
ssh -o ConnectTimeout=5 root@192.168.25.1 '
  source /opt/ros/humble/setup.bash
  ros2 topic list | grep -Ei "camera|image|video"
  for t in \
    /robot/camera/left_wrist/left/image \
    /robot/camera/right_wrist/right/image \
    /camera/left_arm_left/image_rect \
    /camera/right_arm_left/image_rect; do
    ros2 topic info "$t"
  done
  ps -eo pid,etime,args | grep -E "[r]obot_app|[a]rm_app"
  grep -nE "create_isp_node|Failed to initialize camera|Total: 6 cameras" \
    /tmp/openpi_robot_app_camera.log | tail -30
'
```

### 证据与结论

- 用户传入的 `/robot/camera/left_wrist/left/image` 和
  `/robot/camera/right_wrist/right/image` 均返回 `Unknown topic`；当前连规范 raw topic
  `/camera/left_arm_left/image_rect`、`/camera/right_arm_left/image_rect` 也未注册。
- graph 中仅剩六个 `*/video_encoded` 名称，且本机缺少
  `foxglove_msgs/msg/CompressedVideo` 类型，不能将其直接当作 `sensor_msgs/Image` 使用。
- `arm_app`（50071/50072）和 `robot_app` 都在运行；夹爪闭合成功，与本次图像失败是两个独立阶段。
- 本轮 `robot_app` 在 `2026-07-24 13:38:34` 至 `13:38:40` 启动六路相机时均失败。腕部四路的直接错误为
  `create_isp_node(1821) failed, ret -10`，汇总为
  `Total: 6 cameras configured, 0 initialized, 0 started, 6 failed`。

因此，抓图超时的根因仍在板端相机初始化，且本次比 2026-07-23 更严重：头部相机也未启动。修改
`--capture-timeout-s`、QoS 或 raw topic 名称都不会产生图像。应先由机器人 runtime/硬件侧修复
ISP/MIPI 相机初始化并重启 `robot_app`；在 `ros2 topic info <wrist raw topic>` 显示实际 publisher 且
`ros2 topic echo --once` 能收到 `sensor_msgs/Image` 后，再重新运行抓图脚本。当前失败发生在夹爪已经
复位 idle 并释放控制权之后；未生成新的图片或 metadata 文件。

## 2026-07-24 22:18 CST - 闭合夹爪后保存四路腕部立体原图（agent: Codex）

按用户要求修改 `close_grippers_capture_wrist_images.py`：host 默认 `192.168.25.1`，四路 topic 默认
为 `/robot/camera/{left_wrist,right_wrist}/{left,right}/image`，常用命令不再显式传 host/topic。
抓帧从两路扩展为四路，分别保存 `left_wrist_left_rgb`、`left_wrist_right_rgb`、
`right_wrist_left_rgb`、`right_wrist_right_rgb` JPG；每张单图只做 RGB 到 OpenCV BGR 的通道转换和
JPEG 编码，不做 resize。原有左右重叠图和 metadata 保留。本轮按用户要求未连接机器人或运行验证。

## 2026-07-24 22:38 CST - 四路腕部 raw 图像全部无帧

用户执行抓图后报告 `timed out waiting for fresh camera frames: missing=['left_wrist_left_rgb', 'left_wrist_right_rgb', 'right_wrist_left_rgb', 'right_wrist_right_rgb'] stalled=[]`。
`missing` 四路全部存在但一帧都没收到，`stalled=[]` 不是单路卡死，而是 raw image publisher 没有输出可用帧。
最近现场记录已确认：腕部相机 `tx_remote_init`/ISP/MIPI/SerDes 初始化失败，ROS graph 只留静态 topic 名，不是采图超时参数或脚本订阅逻辑。需修复板端相机 runtime 并确认四路 `sensor_msgs/Image` 实际有帧后再采图。
