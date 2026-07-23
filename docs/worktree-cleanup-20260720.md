# 工作树清理审计（2026-07-20）

检查人：Codex

## 目的

盘点当前主仓库相对 `master` 的改动，区分正式推理链路、可复现的实验工具和临时生成物，避免清理时误删真机安全逻辑或验证证据。

## 检查命令与证据

```bash
git status --short --untracked-files=all
git diff --stat
git diff -- scripts/cmds/serve_policy.sh src/openpi/policies/airbot_policy.py src/openpi/training/config.py
find . -path './.git' -prune -o -path './docs/VIO_Test/VIO_Test' -prune \
  -o \( -name '*.orig' -o -name '*.rej' -o -name 'node_modules' \) -print
rg -n 'pi05_vio_plant_collection|openpi_p7_persistent_loop|airbot_policy_bridge|airbot_relpose' \
  docs examples scripts src --glob '!docs/VIO_Test/VIO_Test/**'
```

关键输出：

- 已跟踪修改只有 3 个文件：`serve_policy.sh`、`airbot_policy.py`、`training/config.py`。
- `serve_policy.sh` 当前指向真实的 wrist-only checkpoint；对应 config、采集入口、policy loop 和测试均在文档中有验证记录。
- `airbot_policy.py` / `config.py` 的 `image_keys`、缺失相机 zero-fill + `mask=False`、`include_advantage=False` 是 wrist-only checkpoint 的输入契约，不是临时调试代码。
- `*.orig` / `*.rej` 与当前文件内容重叠；`node_modules/`、`package.json`、`package-lock.json` 只对应误装的 npm `lark-cli`，不属于 Python/ROS 项目。
- `docs/VIO_Test/VIO_Test/` 是另一个独立 openpi 仓库；Arm-P7 release 目录中的 `.deb`、`.whl` 是本地安装包，不应进入主仓库 Git 历史。

## 分类结论

### 已清理的临时残片

以下内容已删除：

- `docs/CHECKLOG.md.orig`
- `examples/airbot/openpi_p7_persistent_loop.py.orig`
- `examples/airbot/p7_move_to_joint_target.py.orig`
- `examples/airbot/p7_move_to_joint_target.py.rej`
- `scripts/cmds/openpi_p7_unlimited_recovery.sh.orig`
- 根目录 `package.json`、`package-lock.json` 和 `node_modules/`

`.gitignore` 现在会忽略 `*.orig`、`*.rej`、`node_modules/`、外部嵌套仓库，以及 `.deb` / `.whl` 安装包。保留 `docs/VIO_Test/VIO_Test/` 和 release 目录中的文字说明，便于复核；只阻止它们污染主仓库状态。

### 应保留的正式链路

- `src/openpi/policies/airbot_policy.py`、`src/openpi/training/config.py` 和其测试：模型输入契约。
- `src/openpi/shared/airbot_relpose.py`、`airbot_policy_bridge.py` 及测试：动作转换和 action chunk 选取。
- `examples/airbot/capture_ros2_openpi_observation.py`、`openpi_p7_persistent_loop.py`、
  `show_openpi_policy_inputs.py`：当前进程内采集到策略到 P7 的主链路。
- `scripts/cmds/openpi_p7_unlimited_recovery.sh`、`openpi_p7_persistent_loop.sh`、
  `move_p7_to_ready_joint_pose.sh`、`stop_openpi_p7_inference.sh`、`scripts/cmds/serve_policy.sh`：
  当前运行、复位和收尾入口。

### 实验/诊断面的工具

它们不是默认推理入口。可重复诊断工具仍有独立价值；一次性探针和历史路线的当前清理结论见
2026-07-23 复核：

- `p7_guarded_servo_step.py`、`p7_*precision_probe.py`、`p7_continuous_servo_smoke.py`、`p7_align_left_orientation_to_right.py`、`p7_servo_move_to_joint_target.py`：小步运动、精度或姿态验证。
- `p7_joint6_triangle_wave.py`、`monitor_x5_cpu.sh`、`move_p7_to_ready_joint_pose.sh`：现场专项操作/监控脚本。
- `openpi_fixed_observation_smoke.py`：冻结观测的策略吞吐/模拟命令基准；不导入 P7 SDK、不连接机器人，属于安全的诊断工具。
- `airbot_airrtm_servo.py`、`airrtm_servo_dryrun.py`、`policy_to_airrtm_bridge.py`：清理前的 AIRRTM
  历史/备选通道，已于 2026-07-23 删除。
- `p7_dds_proxy_server.py`、`ros2_arm_msgs_overlay/`：DDS/板端代理探索，当前没有接入默认 P7 gRPC loop。

这些工具若不再需要，可以单独移到 `examples/airbot/experimental/` 或另一个归档分支；本轮不做该语义变化。

## 影响

清理后 Git 状态不再被备份补丁、npm 依赖和本地安装包污染；正式推理代码与实验工具仍可复现，模型服务入口行为不变。删除动作未涉及 checkpoint、日志、外部仓库或运行中的服务。

## 2026-07-20 16:48 CST：清理后验证

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
  src/openpi/policies/airbot_policy_test.py \
  src/openpi/shared/airbot_relpose_test.py \
  src/openpi/shared/airbot_p7_adapter_test.py \
  src/openpi/shared/airbot_policy_bridge_test.py \
  src/openpi/shared/airbot_airrtm_servo_test.py \
  examples/airbot/request_policy_from_observation_npz_test.py
uv run ruff check <本轮涉及的 Python 文件>
uv run python -m py_compile <本轮涉及的 Python 文件>
bash -n <本轮涉及的 shell 入口>
git diff --check
```

结果：`31 passed in 2.44s`；目标 Python 文件 `ruff` 全部通过，新加入的 `openpi_fixed_observation_smoke.py` 也通过 `ruff` 和 `py_compile`；`py_compile`、shell `bash -n`、`git diff --check` 均返回 0。清理残片检查输出 `temporary artifacts absent`，未发现 `.orig`、`.rej`、`node_modules` 或 npm 清单残留。

## 2026-07-21 13:24 CST：当前工作树完整改动审计

### 范围与命令

```bash
git status --short --untracked-files=all
git diff --stat
git ls-files --others --exclude-standard | sort
git ls-files --others -i --exclude-standard
uv run python -m py_compile src/openpi/models/tokenizer.py src/openpi/policies/airbot_policy.py src/openpi/training/config.py $(git ls-files --others --exclude-standard '*.py')
bash -n scripts/cmds/serve_policy.sh scripts/cmds/airrtm_bridge_dryrun.sh scripts/cmds/move_p7_to_ready_joint_pose.sh scripts/cmds/openpi_p7_closed_loop.sh scripts/cmds/openpi_p7_persistent_loop.sh scripts/cmds/openpi_p7_unlimited_recovery.sh scripts/cmds/stop_openpi_p7_inference.sh scripts/cmds/test_openpi_observation_read.sh scripts/tools/monitor_x5_cpu.sh scripts/tools/start-arm-dual-app-2arm.sh
git diff --check
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q src/openpi/policies/airbot_policy_test.py src/openpi/shared/airbot_relpose_test.py src/openpi/shared/airbot_policy_bridge_test.py src/openpi/shared/airbot_airrtm_servo_test.py examples/airbot/request_policy_from_observation_npz_test.py
```

### 结果

- 相对 `HEAD` 有 5 个已跟踪修改、52 个未跟踪文件；没有 staged 修改。
- 所有修改/新增 Python 均通过 `py_compile`，相关 shell 均通过 `bash -n`，`git diff --check` 返回 0。
- 不依赖 Arm-P7 SDK 的 27 个单测通过。`openpi_p7_persistent_loop_test.py` 和 `p7_move_to_joint_target_test.py` 在收集阶段被当前 `.venv` 的 protobuf 依赖阻断：`ImportError: cannot import name 'runtime_version' from google.protobuf`；这不是断言失败，需在匹配 SDK 环境复测。
- 当时 `docs/` 有 35 个检查文档和 1 个独立 `VIO_Test/` 外部仓库；当时新增的 `.gitignore`
  `docs/*` 会隐藏这些文档，该规则已于 2026-07-23 删除。

### 一次性/已被主线替代的测试候选

以下文件没有被当前默认的 wrist-only P7 gRPC 常驻链路调用，属于现场探路、一次性校准或已被后续入口替代，合并前应删除或移到 `examples/airbot/experimental/`，不要与正式链路混在同一层：

- `examples/airbot/openpi_observation_read_probe.py`、`scripts/cmds/test_openpi_observation_read.sh`：只验证已退役的 camera-daemon latest-file 链路；当前 loop 直接进程内订阅 ROS2。
- `examples/airbot/p7_align_left_orientation_to_right.py`、`p7_all_joints_triangle_wave.py`、`p7_joint6_triangle_wave.py`：现场姿态校准/关节波形运动。
- `examples/airbot/p7_dual_planning_precision_probe.py`、`p7_sequential_planning_precision_probe.py`、`p7_dual_servo_precision_probe.py`：规划/伺服精度探针，不在生产 loop 调用链。
- `examples/airbot/p7_servo_move_to_joint_target.py`：旧的客户端拆步回位实现，已由 `p7_move_to_joint_target.py` 的 SDK blocking servo 取代。
- `examples/airbot/p7_dds_proxy_server.py` 与 `ros2_arm_msgs_overlay/`：DDS/板端代理探索；当前正式路线是 Arm-P7 SDK gRPC。
- `scripts/cmds/openpi_p7_closed_loop.sh`：旧的每轮新建 ROS2 participant 的入口，已由 `openpi_p7_persistent_loop.sh` / `openpi_p7_unlimited_recovery.sh` 取代。
- `examples/airbot/record_camera_clip.py`：与 `record_openpi_cameras.py` 重复的旧录像实现；二者应择一保留。

`examples/airbot/airrtm_servo_dryrun.py`、`policy_to_airrtm_bridge.py`、
`src/openpi/shared/airbot_airrtm_servo.py` 当时是历史/备选 AIRRTM 通道，已于 2026-07-23 删除；
`openpi_fixed_observation_smoke.py`、`p7_guarded_servo_step.py`、`p7_continuous_servo_smoke.py`、
`monitor_x5_cpu.sh`、`show_*` 属于可重复的诊断工具，不是一次性测试，但也不是默认推理入口。

### 正式/应保留项

`src/openpi/policies/airbot_policy.py`、`src/openpi/training/config.py`、
`src/openpi/shared/{airbot_relpose,airbot_policy_bridge}.py` 及其相关测试，以及
`capture_ros2_openpi_observation.py`、`openpi_p7_persistent_loop.py`、当前 recovery/persistent/reset/stop
wrapper、`p7_move_to_joint_target.py`、`p7_ensure_idle.py`、`show_openpi_policy_inputs.py`、
`show_ros2_camera_live.py` 和 `scripts/README.md` 构成当前主链路或其运行支持。
`airbot_policy_bridge.py` 已于 2026-07-23 精简为 action chunk 校验/选取，不再依赖 AIRRTM。
`record_openpi_cameras.py` 是保留价值明确的独立只读录像工具。`AGENTS.md` 与 `CLAUDE.md` 内容完全
相同（SHA-256 `df9bc381...`），属于协作说明，不是测试文件。

### 需要处理的风险

1. `src/openpi/models/tokenizer.py:24` 新增了无条件 `print`，每次 tokenize 都会把 prompt 写入 stdout；这是典型一次性调试残留，应在合并前删除或改为受控日志。
2. `.gitignore:83` 的 `docs/*` 会隐藏本仓库要求提交的所有检查记录；该规则已于 2026-07-23
   删除，检查文档恢复为可提交内容。

## 2026-07-23 12:57 CST：按 `scripts/README.md` 复核未提交代码

### 目的与范围

只读梳理 `scripts/README.md` 当前的 wrist-only 79999 真机推理流程，检查 5 个已跟踪修改和
52 个未跟踪文件，区分主链路依赖、已替代实现、历史传输路线和仍有独立诊断价值的工具。本轮
没有连接 X5、没有启动 policy、没有运行硬件脚本、没有下发运动，也没有删除或移动文件。

### 命令与依赖证据

```bash
git status --short --untracked-files=all
git diff -- .gitignore scripts/cmds/serve_policy.sh \
  src/openpi/models/tokenizer.py src/openpi/policies/airbot_policy.py \
  src/openpi/training/config.py
git ls-files --others --exclude-standard | rg '^(examples|scripts|src)/' | sort
rg -n --glob '!docs/**' --glob '!logs/**' \
  'openpi_p7_unlimited_recovery|openpi_p7_persistent_loop|capture_ros2_openpi_observation|show_openpi_policy_inputs|p7_move_to_joint_target|p7_ensure_idle' .
rg -n --glob '!docs/**' --glob '!logs/**' \
  'openpi_camera_capture_daemon|request_policy_from_observation_npz|policy_to_p7_sdk_bridge|p7_dds_proxy_server|airbot_p7_adapter' .
```

当前 README 的传递调用链为：

```text
serve_policy.sh
  -> config.py: pi05_vio_plant_collection_535_clean_wrist_only
  -> airbot_policy.py: 双腕真图 + 缺失 base mask=False

openpi_p7_unlimited_recovery.sh
  -> move_p7_to_ready_joint_pose.sh -> p7_move_to_joint_target.py
  -> openpi_p7_persistent_loop.sh -> openpi_p7_persistent_loop.py
       -> capture_ros2_openpi_observation.py
       -> show_openpi_policy_inputs.py
       -> airbot_policy_bridge.select_action_step()
       -> airbot_relpose.py

stop_openpi_p7_inference.sh -> p7_ensure_idle.py
show_ros2_camera_live.py -> capture_ros2_openpi_observation.image_to_rgb()
```

审计时 `airbot_policy_bridge.py` 顶层仍导入 `airbot_airrtm_servo.py`；2026-07-23 执行清理时已
移除只服务 AIRRTM 的 mock/message builder，当前模块仅保留 production 使用的
`normalize_action_chunk()` / `select_action_step()`。

### 明确已被当前流程替代或重复的候选（已于 2026-07-23 删除）

以下代码不在上述调用链，且已有当前实现取代；若提交目标仅是 README 所述生产流程，可不纳入：

| 文件 | 原作用 | 当前替代/判断 |
|---|---|---|
| `examples/airbot/openpi_camera_capture_daemon.py` | 长驻订阅 ROS2，相机帧落盘到 `latest.npz/json` | 当前 loop 在同一进程内长期订阅并直接用内存帧 |
| `examples/airbot/openpi_observation_read_probe.py` | 读取 daemon 的 latest-file 并读取双臂 TCP，做只读探针 | latest-file 链路已退役 |
| `scripts/cmds/test_openpi_observation_read.sh` | 上述 latest-file 探针的 wrapper | 随探针一起失去主线用途 |
| `scripts/cmds/openpi_p7_closed_loop.sh` | 每轮采集 NPZ、请求 policy、再单步下发的旧闭环 | 被 persistent loop + unlimited recovery 取代 |
| `examples/airbot/request_policy_from_observation_npz.py` | 从落盘 NPZ 请求一次 policy 并写 action JSON | 只被旧 closed-loop 调用；当前直接以内存 observation 请求 |
| `examples/airbot/request_policy_from_observation_npz_test.py` | 测试上述 NPZ 请求脚本 | 仅服务已替代入口 |
| `examples/airbot/policy_to_p7_sdk_bridge.py` | 从 action JSON 向 P7 下发单个 action row | 只被旧 closed-loop 调用；当前 loop 内部转换并流式下发 |
| `examples/airbot/p7_servo_move_to_joint_target.py` | 客户端拆成许多 non-blocking 小步回 ready pose | 已由 `p7_move_to_joint_target.py` 的 SDK blocking servo 单目标调用取代 |
| `examples/airbot/record_camera_clip.py` | 订阅相机并录制 MP4 | 与较新的 `record_openpi_cameras.py` 功能重复 |
| `scripts/tools/start-arm-dual-app-2arm.sh` | 在旧部署启动 `/opt/arm_dual_app`，可选启动 remote robot_app | README 当前明确启动 `/opt/arm_app` 左右实例和独立 `/opt/robot_app` |
| `src/openpi/shared/airbot_p7_adapter.py` | 通用的单步 guarded P7 SDK adapter | 仅其测试导入；当前 persistent loop 使用自身的双臂流式控制实现 |
| `src/openpi/shared/airbot_p7_adapter_test.py` | 测试上述未接入 adapter | 仅服务未接入实现 |

`src/openpi/models/tokenizer.py` 新增的无条件 `print(f"[PaligemmaTokenizer] ...")` 也是明确的调试
残留：只打印每次推理 prompt，不参与计算，并会污染 serve 日志。候选是删除这一行，不是删除 tokenizer 文件。

### 已放弃路线或一次性现场探针候选

这些代码同样不属于 README 流程，但“无用”取决于是否还要保留历史实验能力：

| 文件/组 | 作用 | 当前判断 |
|---|---|---|
| `examples/airbot/airrtm_servo_dryrun.py` | 生成/可选发布 AIRRTM `arm_servo_json` | 当前控制路线为 P7 SDK gRPC |
| `examples/airbot/policy_to_airrtm_bridge.py` | policy action 转 AIRRTM/ZMQ sender 消息 | 当前控制路线为 P7 SDK gRPC |
| `scripts/cmds/airrtm_bridge_dryrun.sh` | 上述 AIRRTM bridge 的 smoke wrapper | 当前生产流程不调用 |
| `examples/airbot/p7_dds_proxy_server.py` | X5 上用 DDS SDK、向工作站暴露 JSON/TCP 代理 | 当前工作站直接连 50071/50072 gRPC |
| `examples/airbot/ros2_arm_msgs_overlay/arm_msgs/` | 为早期 DDS topic 探索补 `CartesianState.msg` | 当前 gRPC 流程不构建也不 source 该 overlay |
| `examples/airbot/p7_align_left_orientation_to_right.py` | 一次性把左臂末端姿态对齐右臂 | 校准探针，不在启动/复位/推理链路 |
| `examples/airbot/p7_all_joints_triangle_wave.py` | 双臂全部关节三角波跟踪测试 | 现场运动测试，不在生产链路 |
| `examples/airbot/p7_joint6_triangle_wave.py` | 单关节三角波测试，并给 all-joints 脚本提供 helper | 仅服务三角波测试组 |
| `examples/airbot/p7_dual_planning_precision_probe.py` | 双臂并发 planning XYZ 精度测试 | 当前 production 使用 servo，不使用 planning |
| `examples/airbot/p7_sequential_planning_precision_probe.py` | 逐臂逐轴 planning 精度测试 | 当前 production 使用 servo，不使用 planning |
| `examples/airbot/p7_dual_servo_precision_probe.py` | 逐臂逐轴大步 servo 精度测试 | 已完成的现场能力探针，不被 production 调用 |

AIRRTM 路线已确认放弃。`airbot_policy_bridge.py` 已保留当前实际使用的
`normalize_action_chunk()` / `select_action_step()`，只服务 AIRRTM 的 mock/message builder、
`airbot_airrtm_servo.py` 及对应测试均已删除，P7 loop 不再有 AIRRTM import-time 依赖。

### 不应因“README 未点名”而判废的代码

- `capture_ros2_openpi_observation.py`、`show_openpi_policy_inputs.py` 是 persistent loop 的间接依赖。
- `p7_move_to_joint_target.py` / test、`p7_ensure_idle.py` 分别支撑复位和停止收尾。
- `airbot_relpose.py`、`airbot_policy_bridge.py` 及相关测试支撑 action 选取与 relpose 转换。
- `airbot_policy.py`、`LeRobotAirbotDataConfig` 的 `image_keys/include_advantage` 改造、535 clean
  wrist-only config 和 `serve_policy.sh` 是当前 checkpoint 的输入契约。
- `openpi_fixed_observation_smoke.py`、`p7_guarded_servo_step.py`、`p7_continuous_servo_smoke.py`、
  `record_openpi_cameras.py`、`monitor_x5_cpu.sh` 虽不在日常启动链，但仍是可重复的无硬件/小步/
  连续控制/录像/性能诊断工具，不能仅凭 README 未引用认定无用。

`config.py` 中本轮新增的 `pi06_rl_vf_vio_plant_collection`、
`pi06_rl_pretrain_vio_plant_collection`、`pi05_vio_plant_collection` 三个配置不被当前 79999 serve
引用，分别用于 VIO value function、PI0.6 RL 预训练和旧三相机 PI0.5 训练。它们对当前部署非必要，
但属于训练历史/远端训练入口，是否删除需要先确认训练侧不再复用，不能仅据 README 判为废代码。

### 额外发现

`.gitignore` 曾新增的 `docs/*` 与仓库“每次检查必须把结论写进 docs”约定冲突；该规则已于
2026-07-23 删除，本节与 `CHECKLOG.md` 已恢复为可提交内容。

## 2026-07-23 14:17 CST：执行清理并保留三个专项验证工具

### 删除结果

按用户确认，删除以下未提交代码：

- latest-file/旧逐轮闭环：`openpi_camera_capture_daemon.py`、`openpi_observation_read_probe.py`、
  `test_openpi_observation_read.sh`、`openpi_p7_closed_loop.sh`、
  `request_policy_from_observation_npz.py` 及测试、`policy_to_p7_sdk_bridge.py`。
- 已替代/重复实现：`p7_servo_move_to_joint_target.py`、`record_camera_clip.py`、
  `start-arm-dual-app-2arm.sh`、`airbot_p7_adapter.py` 及测试。
- AIRRTM 路线：`airrtm_servo_dryrun.py`、`policy_to_airrtm_bridge.py`、
  `airrtm_bridge_dryrun.sh`、`airbot_airrtm_servo.py` 及测试；同步精简
  `airbot_policy_bridge.py` 和测试，只保留 action chunk 校验/选取。
- DDS/一次性探针：`p7_dds_proxy_server.py`、`ros2_arm_msgs_overlay/arm_msgs/`、
  `p7_align_left_orientation_to_right.py`、`p7_joint6_triangle_wave.py`、
  `p7_sequential_planning_precision_probe.py`。
- 删除 `tokenizer.py` 的无条件 prompt 调试输出；该文件因此恢复为相对 HEAD 无修改。

保留 `p7_all_joints_triangle_wave.py`、`p7_dual_planning_precision_probe.py`、
`p7_dual_servo_precision_probe.py`。全关节三角波原本从已删除的单关节脚本导入 9 个 helper/常量，
现已将关节限制校验、波形计算、状态/关节读取等最小依赖内聚到保留脚本。

### README 与验证

`scripts/README.md` 新增三个工具的前置条件、只读/离线命令、真实运动命令、动作顺序、回位和
退出行为。实际执行以下离线检查，未连接机器人、未 acquire control、未下发动作：

```bash
uv run ruff check <本次直接修改的 6 个 Python 文件>
uv run python -m py_compile <保留工具、bridge、relpose、persistent loop>
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
  src/openpi/policies/airbot_policy_test.py \
  src/openpi/shared/airbot_relpose_test.py \
  src/openpi/shared/airbot_policy_bridge_test.py
.venv-p7-ros/bin/python -m pytest -q \
  examples/airbot/openpi_p7_persistent_loop_test.py \
  examples/airbot/p7_move_to_joint_target_test.py
bash -n <当前 serve/recovery/persistent/reset/stop/monitor wrappers>
.venv-p7-ros/bin/python examples/airbot/p7_all_joints_triangle_wave.py \
  --side both --cycles 1 --amplitude-rad 0.1 --period-s 10 --rate-hz 20
.venv-p7-ros/bin/python <三个保留工具> --help
rg -n '<已删除模块和入口>' examples src scripts
git diff --check
```

结果：定向 ruff、Python 编译、shell 语法和 `git diff --check` 均通过；policy/relpose/bridge
`14 passed`，P7 persistent/reset mock `4 passed`；三角波 dry-run 正确打印
`0 -> +0.1 -> 0 -> -0.1 -> 0rad` 一个周期；三个 `--help` 均退出 0；删除引用搜索无输出。
