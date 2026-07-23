# OpenPI 图像 + TCP pose 只读探针（2026-07-20）

## 结论

- 日期：2026-07-20 16:58-17:00 CST；检查人：Codex。
- 新增 `examples/airbot/openpi_observation_read_probe.py`：连续读取当前 wrist-only
  OpenPI 真机推理使用的双腕 RGB 观测文件，并通过 P7 SDK 连续读取左右臂 TCP pose。
- 新增命令入口 `scripts/cmds/test_openpi_observation_read.sh`，固定使用
  `.venv-p7-sdk/bin/python`，不需要启动 policy server。
- 探针没有 policy client、`acquire_control()`、控制器切换或任何运动/夹爪命令；只调用
  `get_service_state()`、`get_end_pose()` 和 `close()`。
- 5 秒真机只读 smoke 通过：24 次完整采样，两路相机源帧各推进 24 次，左右 TCP pose
  每轮均成功读取。探针运行期间已有其他进程持有双臂 `SERVO_CONTROL/csp`，本探针没有
  接管或改变该状态。

## 与正式推理一致的数据边界

```text
ROS2 wrist image topics
  -> openpi_camera_capture_daemon.py（NV12 -> RGB）
  -> /tmp/openpi_cam_daemon_wrist/latest.{npz,json}
  -> openpi_observation_read_probe.py（实际加载并检查 RGB 数组）

P7 gRPC 50071/50072
  -> AirbotClient.get_end_pose()
  -> left/right TCP xyz[m] + quaternion xyzw
```

当前最后一版 wrist-only OpenPI 闭环也从同一对 `latest.npz/latest.json` 读取图像，并用
同样的 `AirbotClient.get_end_pose()` 给 relpose action 提供当前 TCP 参考。这里的 pose
不是 7 关节角；当前模型的 `state[16]` 仍为零且不进入模型前向，详见
[`openpi-fixed-observation-smoke-20260720.md`](openpi-fixed-observation-smoke-20260720.md)。

除检查文件 mtime 外，探针还检查每路 ROS 图像 header timestamp 是否持续推进。这可以
发现“daemon 还在反复写文件，但上游 publisher 已停止、文件里一直是缓存旧帧”的情况。

## 使用方式

先保持当前相机守护进程运行。wrist-only 的对应启动方式是：

```bash
cd /home/discover/Desktop/Openpi_RL
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE

/usr/bin/python3 examples/airbot/openpi_camera_capture_daemon.py \
  --wrist-only \
  --output /tmp/openpi_cam_daemon_wrist/latest.npz \
  --metadata-output /tmp/openpi_cam_daemon_wrist/latest.json \
  --write-hz 15 --status-period-s 3
```

另开终端运行只读探针；默认持续 30 秒、以 5 Hz 读取：

```bash
bash scripts/cmds/test_openpi_observation_read.sh
```

持续运行直到 `Ctrl+C`：

```bash
bash scripts/cmds/test_openpi_observation_read.sh --duration-s 0
```

若要测试三相机模型，使用 `--no-wrist-only`，并显式传入三相机 daemon 的路径：

```bash
bash scripts/cmds/test_openpi_observation_read.sh \
  --no-wrist-only \
  --latest-obs-npz /tmp/openpi_cam_daemon/latest.npz \
  --latest-obs-meta /tmp/openpi_cam_daemon/latest.json
```

逐样本 JSONL 默认写入
`/tmp/openpi_observation_read_probe/<timestamp>.jsonl`。每条记录包含图像 shape/dtype、
亮度范围、CRC32、ROS header stamp、文件年龄、观测加载耗时，以及左右 TCP
`xyz/xyzw`、四元数范数和读取耗时。任一图像文件过期、shape/dtype 错误、源帧停止推进
超过 2 秒、pose 为 `None` 或包含非有限值时，脚本立即以非零状态退出并打印 `FAIL`。

## 2026-07-20 实际检查

### 前置状态

命令：

```bash
pgrep -af '[o]penpi_camera_capture_daemon.py'
ssh -o BatchMode=yes -o ConnectTimeout=3 root@192.168.25.1 \
  "ss -lntp | grep -E '50071|50072'"
```

关键输出：

```text
18180 /usr/bin/python3 examples/airbot/openpi_camera_capture_daemon.py --wrist-only \
  --output /tmp/openpi_cam_daemon_wrist/latest.npz \
  --metadata-output /tmp/openpi_cam_daemon_wrist/latest.json --write-hz 15 --status-period-s 3
LISTEN ... *:50072 ... arm_app
LISTEN ... *:50071 ... arm_app
```

结论：当前 wrist-only daemon 与左右 P7 gRPC 只读入口在线。本轮没有启动、停止或修改
X5 上的服务。

### 静态验证

命令：

```bash
bash -n scripts/cmds/test_openpi_observation_read.sh
.venv-p7-sdk/bin/python -m py_compile examples/airbot/openpi_observation_read_probe.py
.venv-p7-sdk/bin/python examples/airbot/openpi_observation_read_probe.py --help
uv run ruff check examples/airbot/openpi_observation_read_probe.py --output-format concise
git diff --check -- examples/airbot/openpi_observation_read_probe.py \
  scripts/cmds/test_openpi_observation_read.sh
```

输出：bash 语法、Python 编译、CLI help、ruff 与 `git diff --check` 均通过。ruff 只打印
仓库已有的 `tool.uv.dev-dependencies` 弃用告警。

### 真机只读 smoke

命令：

```bash
scripts/cmds/test_openpi_observation_read.sh \
  --duration-s 5 --period-s 0.2 --report-every 5 \
  --latest-obs-npz /tmp/openpi_cam_daemon_wrist/latest.npz \
  --latest-obs-meta /tmp/openpi_cam_daemon_wrist/latest.json \
  --output-jsonl /tmp/openpi_observation_read_probe/live_smoke_20260720.jsonl
```

关键输出：

```text
left state  ServiceState(... fsm_state='SERVO_CONTROL', controller_state='csp', valid=True)
right state ServiceState(... fsm_state='SERVO_CONTROL', controller_state='csp', valid=True)
left_wrist_0_rgb=[480, 640, 3] ... new=True
right_wrist_0_rgb=[480, 640, 3] ... new=True
PASS ... samples=24 ... sample_rate_hz=4.6678
```

汇总数值：

- 两路 RGB：`uint8 [480,640,3]`，原始编码均为 `nv12`；24 次采样中两路源帧各更新
  24 次，没有 stale/stall。
- 平均 observation `.npz` 加载耗时：`7.990 ms`。
- 平均 `get_end_pose()` 耗时：left `2.666 ms`，right `2.148 ms`。
- 最后一帧左右四元数范数均为 `1.0`；图像像素范围均为 `[0,255]`。
- 结果文件：`/tmp/openpi_observation_read_probe/live_smoke_20260720.jsonl`。

影响：相机 daemon -> RGB 文件读取，以及 P7 gRPC -> 双臂 TCP pose 读取这两个正式推理
前置阶段在本次检查时均工作正常。该结论不覆盖 policy server、模型推理或运动下发。

### 17:01 默认入口复查

不传 `--latest-obs-*`，直接验证脚本默认值：

```bash
scripts/cmds/test_openpi_observation_read.sh \
  --iterations 3 --duration-s 10 --period-s 0.2 --report-every 1 \
  --output-jsonl /tmp/openpi_observation_read_probe/default_path_smoke_20260720.jsonl
```

结果为 `PASS`：默认路径正确命中 `/tmp/openpi_cam_daemon_wrist/latest.{npz,json}`，
3 次采样中左右源帧各推进 3 次、pose 均有效。此时左右臂状态均为
`IDLE/idle/valid`。这进一步确认当前直接运行 shell 入口不需要补观测路径参数。

## 2026-07-20 18:06-18:08 最快读取频率实测

### 前置恢复

第一次尝试使用 `--period-s 0` 时在采样前失败：

```text
FAIL: Timeout connecting to 192.168.25.1:50071
```

只读检查确认相机 daemon 正常写文件，但 X5 上没有 `arm_app` 进程，50071/50072
均未监听。为恢复 pose 只读入口，按现有 runbook 启动双臂服务：

```bash
ssh root@192.168.25.1 \
  'setsid nohup bash /root/start-arm-dual-app-2arm.sh \
  > /tmp/start-arm-dual-app.read-probe.log 2>&1 < /dev/null &'
```

约 3 秒后 50071/50072 均由 `arm_app` 监听。本轮只启动服务，没有获取控制权或发送
运动命令。

### 无节拍限制测试

命令：

```bash
scripts/cmds/test_openpi_observation_read.sh \
  --duration-s 15 --period-s 0 --report-every 0 \
  --output-jsonl /tmp/openpi_observation_read_probe/max_rate_20260720_1807.jsonl
```

关键汇总：

```text
PASS samples=1336 elapsed_s=15.1158 sample_rate_hz=88.3844
camera_source_updates: left=196 right=196
mean_observation_load_ms=6.7726
mean_pose_read_ms: left=1.6356 right=1.5460
```

`88.38Hz` 是“反复加载当前 latest RGB + 读取左右 TCP pose”的程序循环吞吐，包含
同一相机帧被读取多次，不能当作新观测频率。再按每次 source frame changed 的 ROS
header timestamp 计算：

```text
left  count=196 stamp_span_s=14.766766 source_hz=13.205329
right count=196 stamp_span_s=14.800103 source_hz=13.175584
```

1336 次读取中 observation 文件年龄为 `5.9-105.1ms`，平均 `45.7ms`。测试结束后
再次只读检查，左右臂均为 `IDLE/idle/valid`。

结论：当前链路真正可提供的**新图像 + 当前 TCP pose** 频率约为 **13.2Hz**。daemon
虽然配置 `--write-hz 15`，但以本轮实际 RGB 转换、NPZ 压缩写盘和 ROS 源帧推进结果，
不应把 15Hz 配置值当作实测值。当前模型纯推理 `5.48Hz` 低于约 13.2Hz 的新观测供数
能力，读取阶段不是限制模型达到 5.48Hz 的瓶颈；正式闭环是否达到该频率仍取决于
`--period-s`、模型请求以及动作执行/回读耗时。
