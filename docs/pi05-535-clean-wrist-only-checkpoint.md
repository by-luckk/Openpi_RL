# PI0.5 535 clean wrist-only checkpoint 验证

## 2026-07-18 16:12 CST（agent: Codex）

### 目的

验证以下 checkpoint 能否在本机完成参数恢复并返回策略动作：

```text
checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/
  vio_pi05_535_clean_wrist_only_80k_260717/20000
```

本轮只验证 policy server + mock observation 推理，没有连接或控制真机，也不评价任务成功率。

### 配置契约核对

checkpoint 目录共约 `12G`，包含完整 Orbax `params/` 分片、`_CHECKPOINT_METADATA`，以及：

```text
assets/vio_plant_collection_30hz_relpose_535_clean/norm_stats.json
```

本地原配置只有 `pi05_vio_plant_collection`，其 asset id 是旧数据集
`vio_plant_collection_30hz_relpose`，不能准确描述该模型。只读核对训练服务器：

```bash
ssh -o BatchMode=yes maxliu-h200-qinghua-1 \
  "cd /home/maxliu/projects/VIO_Test/Openpi_RL && \
   rg -n -C 12 '535_clean|wrist_only' src/openpi/training/config.py scripts/cmds"
```

确认训练 config 是 `pi05_vio_plant_collection_535_clean_wrist_only`：

- `model_type=PI05`，`action_horizon=50`，`action_dim=32`
- `repo_id/asset_id=vio_plant_collection_30hz_relpose_535_clean`
- 只有 `left_wrist_0_rgb`、`right_wrist_0_rgb` 是有效相机
- `base_0_rgb` 必须补零且 `mask=False`
- `include_advantage=False`

因此把训练端的最小必要输入契约同步到本地：

- `src/openpi/training/config.py`：新增 wrist-only config，并让 Airbot data config 支持 `image_keys` / `include_advantage`
- `src/openpi/policies/airbot_policy.py`：未配置的模型相机槽补零并设无效 mask
- `src/openpi/policies/airbot_policy_test.py`：覆盖补零/mask 和缺少配置相机的错误路径

### 服务恢复与推理

本机单张 RTX 4090 Laptop GPU（`16376 MiB`）原有旧 checkpoint 服务占用约
`12202 MiB`，只剩约 `1.2 GiB`，无法并行加载第二个 PI0.5。检查确认旧服务无客户端连接后，
临时停止旧服务，在 `8001` 验证目标模型；验证后停止目标模型并按原命令恢复旧服务到 `8000`。

目标服务命令：

```bash
env \
  TMPDIR=.tmp/serve_policy_535_wrist \
  TEMP=.tmp/serve_policy_535_wrist \
  TMP=.tmp/serve_policy_535_wrist \
  XDG_CACHE_HOME=.tmp/serve_policy_535_wrist/xdg_cache \
  JAX_COMPILATION_CACHE_DIR=.tmp/serve_policy_535_wrist/jax_cache \
  uv run scripts/serve_policy.py \
    --port 8001 \
    policy:checkpoint \
    --policy.config pi05_vio_plant_collection_535_clean_wrist_only \
    --policy.dir checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/vio_pi05_535_clean_wrist_only_80k_260717/20000
```

关键服务输出：

```text
Restoring checkpoint from .../20000/params.
/jax/checkpoint/read/bytes_per_sec: 1.7 GiB/s (total bytes: 6.2 GiB)
Finished restoring checkpoint in 3.57 seconds
Loaded norm stats from .../20000/assets/vio_plant_collection_30hz_relpose_535_clean
server listening on 0.0.0.0:8001
```

首次 mock 请求（包含 JAX 编译）结果：

```text
actions.shape = (50, 32)
dtype = float64
all_finite = true
min = -0.1997649285
max = 100.5851497633
infer_ms = 10670.95
```

第二次只发送左右腕图像、`state` 和 `prompt`，完全不发送 `base_0_rgb`：

```text
actions.shape = (50, 32)
all_finite = true
infer_ms = 179.78
wall_ms = 181.4
```

独立检查输入变换：

```text
image_mask = {'base_0_rgb': False, 'left_wrist_0_rgb': True, 'right_wrist_0_rgb': True}
base_sum = 0
```

### 测试

系统 ROS Jazzy 会自动注入一个与 Python 3.11 不兼容的 pytest plugin，因此禁用第三方 plugin 自动加载后执行：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
  src/openpi/policies/airbot_policy_test.py \
  src/openpi/shared/airbot_policy_bridge_test.py
# 8 passed in 2.39s

uv run ruff check --select E,F --ignore F401 \
  src/openpi/policies/airbot_policy.py \
  src/openpi/policies/airbot_policy_test.py \
  src/openpi/training/config.py
# All checks passed!

git diff --check
# exit 0
```

### 结论与影响

**该 checkpoint 可以跑通。** 已验证参数完整恢复、checkpoint 自带 norm stats 正确加载、
wrist-only 观测契约正确生效，并成功返回有限值的 `(50, 32)` actions。首次请求约 `10.67s`
（含 JAX 编译），编译后的本次 mock 请求约 `180ms`。

本轮没有使用真实相机观测、没有执行机械臂动作，因此“能跑通”仅代表模型服务和推理链路可用，
不代表真机抓放任务质量已经验证。收尾时目标 `8001` 服务已停止；原来的旧 checkpoint 服务已恢复，
继续监听 `0.0.0.0:8000`。

## 2026-07-18 16:20 CST — 真机辅助入口明确排除头相机

用户再次确认：该 checkpoint **只需要两路腕部相机，不需要头部相机**。服务端 config 已满足该
契约，但检查发现旧的通用真机脚本仍默认等待三路相机。为避免头相机掉线阻塞 wrist-only 模型，
以下入口新增 `--wrist-only`：

- `capture_ros2_openpi_observation.py`：只订阅、等待并写入左右腕相机
- `openpi_camera_capture_daemon.py`：常驻模式也只订阅左右腕相机
- `request_policy_from_observation_npz.py`：NPZ 不再要求 `base_0_rgb`，请求也不发送该 key
- `openpi_p7_persistent_loop.py`：把双腕模式同时传给采集和 policy 请求

单帧双腕采集：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
mamba run -n ros2-topic python examples/airbot/capture_ros2_openpi_observation.py \
  --wrist-only \
  --left_wrist_0_rgb-topic /robot/camera/left_wrist/left/image \
  --right_wrist_0_rgb-topic /robot/camera/right_wrist/left/image
```

请求 wrist-only policy：

```bash
uv run python examples/airbot/request_policy_from_observation_npz.py \
  --wrist-only \
  --no-advantage \
  --policy-port 8001
```

常驻相机模式需要 daemon 和闭环两侧都带 `--wrist-only`：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
mamba run -n ros2-topic python examples/airbot/openpi_camera_capture_daemon.py \
  --wrist-only \
  --left_wrist_0_rgb-topic /robot/camera/left_wrist/left/image \
  --right_wrist_0_rgb-topic /robot/camera/right_wrist/left/image

bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --wrist-only \
  --no-advantage \
  --capture-mode latest-file
```

验证证据：

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest ...
9 passed in 2.40s

request_policy_from_observation_npz.py --help  -> 有 --wrist-only
capture_ros2_openpi_observation.py --help      -> 有 --wrist-only
openpi_camera_capture_daemon.py --help         -> 有 --wrist-only
openpi_p7_persistent_loop.py --help            -> 有 --wrist-only
```

其中 ROS 两个 CLI 必须用 `mamba run -n ros2-topic python`（或等价 ROS Python 环境）；直接用系统
`python3` 检查时因该解释器缺 `numpy` 失败。`py_compile`、限定 E/F ruff 和 `git diff --check` 均通过。
本轮仍未订阅真实相机、未连接机械臂、未发送运动命令。

## 2026-07-18 16:32 CST — 真实双腕观测与 P7 端到端 dry-run

### 真实双腕单帧

使用当前机器人 ROS2 topic，只采左右腕相机：

```bash
ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
mamba run -n ros2-topic python examples/airbot/capture_ros2_openpi_observation.py \
  --wrist-only \
  --left_wrist_0_rgb-topic /robot/camera/left_wrist/left/image \
  --right_wrist_0_rgb-topic /robot/camera/right_wrist/left/image \
  --timeout-s 12 \
  --output /tmp/openpi_535_wrist_real_obs.npz \
  --metadata-output /tmp/openpi_535_wrist_real_obs.json
```

结果：

- 两路都是 `nv12 640x480`，转换后为 `uint8 RGB (480,640,3)`
- 左右时间戳相差约 `34us`
- NPZ keys 只有 `left_wrist_0_rgb`、`right_wrist_0_rgb`、`state`，没有 `base_0_rgb`
- 左腕像素 `min=0 max=255 mean=102.95 std=49.24 nonzero=95.58%`
- 右腕像素 `min=0 max=255 mean=107.15 std=51.29 nonzero=96.24%`

结论：双腕图像不是空帧，且采集层确实不依赖、不写入头相机。

### 真实观测 policy 请求

临时停止无客户端连接的旧 `:8000` 服务释放显存，目标 checkpoint 再次恢复到 `:8001`：

```text
Finished restoring checkpoint in 4.20 seconds
Loaded norm stats from .../assets/vio_plant_collection_30hz_relpose_535_clean
server listening on 0.0.0.0:8001
```

正式请求命令：

```bash
uv run python examples/airbot/request_policy_from_observation_npz.py \
  --observation-npz /tmp/openpi_535_wrist_real_obs.npz \
  --action-json /tmp/openpi_535_wrist_real_actions.json \
  --metadata-json /tmp/openpi_535_wrist_real_actions.meta.json \
  --policy-host 127.0.0.1 \
  --policy-port 8001 \
  --prompt 'put the plant into the collection box' \
  --wrist-only \
  --no-advantage
```

关键结果：

```text
observation_shapes = left/right (480,640,3), state (16)
actions.shape = (50,32)
all_finite = true
infer_ms = 1822.16
padding columns 14:32 max_abs = 4.33e-9
```

第一步有效 14 维 action：

```text
[0.0008695, 0.0003019, -0.0008984, 0.0041687, 0.0052931, -0.0000918, 51.3320,
 0.0023207, -0.0020357, -0.0016615, -0.0072652, 0.0047545, 0.0006681, 2.6077]
```

把该 action 接到 P7 SDK bridge 的默认 no-execute dry-run：左右臂前后均为
`IDLE/idle/valid`；左/右目标位移约 `1.286mm/3.506mm`，旋转约
`0.006738/0.008708rad`，夹爪目标约 `49.279/2.503mm`。输出明确：

```text
DRY_RUN: no acquire_control(), switch_controller(), move_end_pose(), or move_eef() was called
```

### 50 步 horizon 护栏扫描

每行 action 都相对同一观测位姿，不应把整段当连续增量无条件播放。按单步
`translation<=0.02m`、`rotation<=0.20rad` 扫描：

- 左位移：最大 `0.05368m @ index 49`，索引 `40..49` 超限
- 左旋转：最大 `0.22185rad @ index 49`，索引 `48..49` 超限
- 右位移：最大 `0.04787m @ index 49`，索引 `46..49` 超限
- 右旋转：最大 `0.31849rad @ index 49`，索引 `36..49` 超限
- 左夹爪范围 `51.33..74.89`，右夹爪范围 `1.57..2.61`（model 0..100）

影响：闭环继续使用短 chunk（本轮验证前 5 步），并保留现有单步/包络护栏；不能一次播放完整 50 步。

### wrist-only 常驻链路 dry-run

启动 `openpi_camera_capture_daemon.py --wrist-only` 后，约一分钟内写入 `544` 次，所有 heartbeat
均为 `have_all=True missing=[]`。然后运行一次：

```bash
bash scripts/cmds/openpi_p7_persistent_loop.sh \
  --iterations 1 \
  --period-s 0 \
  --capture-mode latest-file \
  --latest-obs-npz /tmp/openpi_535_wrist_daemon/latest.npz \
  --latest-obs-meta /tmp/openpi_535_wrist_daemon/latest.json \
  --latest-obs-max-age-s 2 \
  --wrist-only \
  --no-advantage \
  --policy-host 127.0.0.1 \
  --policy-port 8001 \
  --robot-host 192.168.25.1 \
  --controller servo \
  --chunk-steps 5 \
  --max-step-translation-m 0.02 \
  --max-step-rotation-rad 0.20
```

结果：真实双腕 latest NPZ -> policy `(50,32)` -> 前 5 步 relpose -> P7 只读状态全链路通过，
稳态 `infer_ms=190.95`。前 5 步左右单步最大位移和旋转均通过护栏；每步均打印 no-acquire/no-move，
结束时双臂仍为 `IDLE/idle/valid`。summary：

```text
/tmp/openpi_p7_persistent_loop/summary_20260718_162937.jsonl
```

停止 daemon 时发现外部信号可能已关闭 ROS context，而 `finally` 再次 shutdown 会抛
`rcl_shutdown already called`。已把清理改为仅在 `rclpy.ok()` 时 shutdown；重新运行双腕 daemon
并向子进程发送 `SIGINT` 后，持续 `have_all=True`，最终退出码 `0`、无 traceback。

最终验证：目标 `:8001` 和测试 daemon 均已停止；旧 checkpoint 已恢复并监听 `0.0.0.0:8000`
（restore `3.36s`）。`9 passed`、限定 E/F ruff、`py_compile`、`git diff --check` 全部通过。
本轮只读连接 P7，**没有获取控制权、没有发送任何机械臂或夹爪运动命令**。

## 2026-07-19 20:03 CST：停止当前真机推理并复核实际 checkpoint / 相机输入

检查人：Codex。目的：按用户要求停止正在运行的 OpenPI 真机控制，并确认本次推理实际加载的 checkpoint 与图像输入。

当前策略服务配置：

```text
POLICY_CONFIG=pi05_vio_plant_collection_535_clean_wrist_only
CHECKPOINT_DIR=checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/vio_pi05_535_clean_wrist_only_80k_260717/20000
```

本次真机请求命令和成功响应均证明使用 wrist-only：

```text
request_policy_from_observation_npz.py ... --no-advantage --wrist-only
observation_shapes={left_wrist_0_rgb:[480,640,3], right_wrist_0_rgb:[480,640,3], state:[16]}
```

因此头相机 `base_0_rgb` 没有被采集或发送。配置的 `image_keys` 只有左右腕；模型固定三图槽中的头相机槽由输入变换补零，并设置 `image_mask=False`，不参与视觉注意力。

停止操作先终止无限恢复 supervisor，再停止/等待其控制与单次 policy 请求子进程。最终进程检查：

```text
pgrep -af 'openpi_p7_unlimited_recovery|openpi_p7_persistent_loop|request_policy_from_observation_npz|serve_policy.py'
仅剩 serve_policy.py 的 uv/python 两个进程；没有 OpenPI P7 控制进程。
```

结论：当前真机推理已停止，不会继续下发动作或自动恢复；`:8000` 上只保留空闲策略服务，checkpoint 为上述 20k wrist-only 权重。

## 2026-07-20 16:46 CST：79999 checkpoint 完整恢复检查

检查人：Codex。目的：确认训练末尾的以下 checkpoint 是否完整，并实际加载一次：

```text
checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/
  vio_pi05_535_clean_wrist_only_80k_260717/79999
```

### 静态结构

检查命令：

```bash
du -sb checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/\
vio_pi05_535_clean_wrist_only_80k_260717/79999

find checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/\
vio_pi05_535_clean_wrist_only_80k_260717/79999 -type f | wc -l
```

结果：目录 apparent size 为 `12,439,585,620 bytes`（约 `12G`），共有 `19` 个普通文件。
顶层 `_CHECKPOINT_METADATA`，`params/_METADATA`、`params/_sharding`、主/进程 OCDBT
manifest、参数数据块和
`assets/vio_plant_collection_30hz_relpose_535_clean/norm_stats.json` 均存在。

归一化统计通过 JSON 解析检查，包含 `state` 和 `actions` 两组；每组的 `mean/std/q01/q99`
长度都是 `32`，所有值均为有限数，与该 config 的 `action_dim=32` 和固定 state padding 契约一致。

### 实际完整加载

当时 GPU 上已有 `20000` checkpoint 服务监听 `:8000`，占用 `12202 MiB`。为不停止现有服务，
本次强制 JAX 使用 CPU，但调用与正式服务相同的 `create_trained_policy()`，使 Orbax 读取完整参数树，
随后加载 checkpoint 自带 norm stats：

```bash
env JAX_PLATFORMS=cpu CUDA_VISIBLE_DEVICES='' \
  TMPDIR=.tmp/check_ckpt_79999 \
  XDG_CACHE_HOME=.tmp/check_ckpt_79999/xdg_cache \
  JAX_COMPILATION_CACHE_DIR=.tmp/check_ckpt_79999/jax_cache \
  uv run python - <<'PY'
from openpi.policies import policy_config
from openpi.training import config

ckpt = (
    "checkpoints/pi05_vio_plant_collection_535_clean_wrist_only/"
    "vio_pi05_535_clean_wrist_only_80k_260717/79999"
)
policy_config.create_trained_policy(
    config.get_config("pi05_vio_plant_collection_535_clean_wrist_only"),
    ckpt,
)
print("LOAD_OK")
PY
```

关键输出：

```text
jax_backend=cpu
Restoring checkpoint from .../79999/params.
/jax/checkpoint/read/bytes_per_sec: 1.5 GiB/s (total bytes: 6.2 GiB)
Finished restoring checkpoint in 4.25 seconds from .../79999/params.
Loaded norm stats from .../79999/assets/vio_plant_collection_30hz_relpose_535_clean
LOAD_OK
```

完整 `create_trained_policy()` 返回用时约 `4.657s`，退出码为 `0`。Orbax 没有报告缺失数据块、
manifest 不一致、参数树/shape 不匹配或反序列化错误，因此 `79999` checkpoint 的模型参数和
推理所需 norm stats **完整且能被当前本地 config 加载**。

两次预检查命令本身失败但不属于 checkpoint 故障：一次 `jq` 按错误 JSON 层级取值而退出码为
`5`；第一次加载命令的工具超时误设为 `1s`，在有效恢复前被终止。修正 JSON 路径和超时后，
上述完整检查均通过。

### 影响与收尾

本轮只验证 checkpoint 完整恢复，没有执行 action 推理，也没有连接或控制真机。原有
`20000` GPU 服务未被停止或替换，收尾复查仍由 PID `17756` 监听 `0.0.0.0:8000`，显存占用
`12202 MiB`；没有遗留 `79999` 服务进程。若要把正式服务切换到训练末尾权重，需另行把
`scripts/cmds/serve_policy.sh` 的 `CHECKPOINT_DIR` 从 `20000` 改为 `79999` 并重启服务。

## 2026-07-20 19:53 CST：当前实际加载模型的本机进程

检查人：Codex。

目的：确认本机当前哪个进程实际持有 OpenPI 模型，并区分启动器、相机进程和模型服务。

命令：

```bash
pgrep -af 'serve_policy.py|openpi_p7|request_policy|airbot_inference|python.*openpi'
ss -lntp 'sport = :8000'
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
awk '/^(Name|Pid|PPid|Threads|VmRSS|VmSize):/{print}' /proc/119852/status
tr '\0' ' ' </proc/119852/cmdline
```

关键输出：

```text
119848 uv run scripts/serve_policy.py ... --policy.dir .../79999
119852 .venv/bin/python3 scripts/serve_policy.py ... --policy.dir .../79999
0.0.0.0:8000 users:(("python3",pid=119852,fd=43))
119852, .venv/bin/python3, 12202 MiB
Pid: 119852  PPid: 119848  VmRSS: 4343344 kB  VmSize: 38753620 kB  Threads: 168
```

结论：真正加载并持有 OpenPI 模型的是 Python 进程 **PID 119852**；它加载
`pi05_vio_plant_collection_535_clean_wrist_only` 的 `79999` checkpoint，监听
`0.0.0.0:8000`，占用约 `12.2 GiB` GPU 显存和 `4.34 GB` RSS。PID `119848` 只是
`uv run` 父启动器，不持有主要模型显存。相机 daemon PID `119839` 和录像 PID `155462`
不加载模型。`119852` 有 168 个线程，因此 `top` 开启线程显示时会出现许多共享同一
`VIRT` 的 TID 行；这些 VIRT/RSS 不能逐行相加。

影响：16:46 CST 章节记录的“正式服务仍为 20000”只代表当时检查后的现场；截至本节时间，
正式 `:8000` 服务已经切换为 `79999`。
