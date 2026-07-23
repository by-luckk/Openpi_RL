# 当前 IK 接入位置

## 2026-07-20 20:25（Codex）

- **目的**：确认当前 OpenPI 真机闭环中 IK 在哪一层接入。
- **检查命令**：

  ```bash
  rg -n -i '\bik\b|inverse.?kinemat|逆运动学|end.?effector|eef|cartesian' \
    --glob '!docs/VIO_Test/VIO_Test/**' .
  rg -n 'set_.*pose|set_.*joint|joint.*target|action|play_operator|airbot_ie|airdc' \
    examples/airbot scripts/cmds
  ```

- **关键证据**：
  - `examples/airbot/openpi_p7_persistent_loop.py` 导入 P7 SDK 的 `CartesianPose`、`CartesianMoveOptions`，执行侧使用末端笛卡尔目标。
  - `src/openpi/shared/airbot_p7_adapter.py` 和 `src/openpi/shared/airbot_policy_bridge.py` 是 policy action 到双臂 TCP target 的仓库侧转换层。
  - 已有 `docs/local-amd64-robot-app-simulator.md` 记录的实际调用链为 `get_end_pose()` -> action 转换 -> `move_end_pose()`；仓库只构造 SDK `CartesianPose`。
  - 全仓检索未找到仓库内显式 IK solver 或“笛卡尔目标到关节目标”的求解实现。
- **结论**：当前 IK 不在 OpenPI policy 或本仓库 adapter 中显式求解。仓库把模型相对末端动作积分为绝对 TCP pose，然后调用 `arm_p7_sdk.AirbotClient.move_end_pose()`；后续 pose 到关节命令的 IK 位于 P7 SDK 后面的机器人控制服务/控制栈中。仅凭当前仓库不能进一步确认该求解器在下位控制栈中的具体进程或源码模块名。
- **影响**：需要调整坐标系、相对动作积分或安全限幅时改仓库 bridge/adapter；需要调整 IK 算法、奇异点处理、关节限位或解支选择时，应查 P7 机器人控制服务，而不是策略服务。
