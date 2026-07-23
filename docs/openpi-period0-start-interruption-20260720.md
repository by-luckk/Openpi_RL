# 2026-07-20 17:26 period=0 启动中断复盘

## 结论

这次停止**不是 OpenPI、相机、79999 checkpoint、gRPC 控制命令或 X5 队列报错**，
而是启动命令调用终端工具时错误设置了 `timeout_ms=1000`。工具在约 1.008 秒后强制
结束前台 supervisor，返回：

```text
Exit code: 124
command timed out after 1008 milliseconds
```

推理尚未开始：没有进入 camera capture、policy request 或 action execution。随后发现
内层 `openpi_p7_persistent_loop.py` 因 supervisor 使用 `setsid` 而短暂成为孤立进程；
终止该孤立进程后，左臂自动回到 idle，但右臂因清理状态记录顺序问题残留在 CSP。
17:28 CST 已由独立 SDK 客户端成功把右臂切回 idle 并释放控制。最终左右臂均为
`ServiceState(True, IDLE, idle, valid=True)`，且没有真机控制进程残留。

## 时间线

| 时间 | 事件 |
|---|---|
| 17:26:17 | unlimited-recovery supervisor 启动，attempt=1 |
| 17:26:18.109 | X5 left 收到 ARM `0 -> 2`，成功进入 servo CSP |
| 17:26:18.615 | X5 right 收到 ARM `0 -> 2`，成功进入 servo CSP |
| 约 17:26:18 | 终端工具达到错误设置的 1000 ms 硬超时，返回 exit 124，supervisor 输出通道中断 |
| 17:26:19.121 | left 被清理为 ARM `2 -> 0` / IDLE |
| 17:27:45 | 只读检查：left IDLE，right 仍为 `SERVO_CONTROL/csp/valid` |
| 17:28:10 | 独立恢复客户端获得 right 控制权，`switch_controller(idle)=True` |
| 17:28:11 | right release_control 完成，最终两侧均 IDLE/idle/valid |

## 为什么可以排除模型与动作错误

主日志：

```text
/home/discover/Desktop/recording/openpi_wrist_79999_period0_20260720_1726/
  openpi_p7_recovery_20260720_172617.log
```

日志只到：

```text
left acquire_control True
right acquire_control True
left switch_servo True
```

目录检查只有这一份 `2211 bytes` 的日志，mtime 为 `17:26:18.620`；`work/` 下没有
observation NPZ、action JSON、summary JSONL。因此脚本停在控制器初始化阶段，尚未打印
`[persistent-loop] iteration=1 capture`，更不可能执行 policy 或动作。

X5 当前日志：

```text
/userdata/arm_app_logs/20260720_162226/left_arm.log
/userdata/arm_app_logs/20260720_162226/right_arm.log
```

17:26 相关行只有成功的模式切换和 `confirmed_rate=250`，没有本轮
`UNKNOWN_ERROR`、`queue_drop`、RPC rejection 或 CAN 错误。79999 policy server 和
wrist-only 相机守护进程在整个过程中也没有退出。

## 右臂为什么会残留 CSP

内层通过 `setsid` 启动，所以前台 supervisor 被工具强制结束时，内层进程没有同步
消失。源码中 controller 切换完成后的顺序是：

```python
ok = client.switch_controller(controller, ...)
print(f"{side} switch_{args.controller} {ok}", flush=True)
...
switched.add(side)
```

而 `finally` 只遍历 `switched` 集合切回 idle。主日志在 `left switch_servo True` 后
突然结束，但 X5 证明 right 的模式切换在随后成功；这说明 supervisor 输出管道消失
时，right 的成功打印/后续记录阶段被打断，right 未可靠加入 `switched`，所以清理只
覆盖 left。这是根据源码顺序、主日志截断点和 X5 时间线得到的高置信重构；由于输出
通道已被硬超时关闭，没有保存到 Python traceback，不能声称看到了具体
`BrokenPipeError` 文本。

恢复命令结果：

```text
before ServiceState(... fsm_state='SERVO_CONTROL', controller_state='csp', valid=True)
acquire_control True
switch_idle True
release_control done
after ServiceState(... fsm_state='IDLE', controller_state='idle', valid=True)
```

## 影响

- 本次没有执行任何 OpenPI action，不属于“推理运行到一半停止”。
- 400 秒任务没有开始计时，也没有产出有效 episode。
- 后续重启必须让命令以持久会话或真正后台 supervisor 运行，不能把工具硬超时当作
  “先返回 session”的机制。
- 在再次运行前，还应调整 controller/EEF 清理状态的登记顺序，避免输出异常发生在
  硬件状态改变与 `switched.add()` 之间时遗漏清理。
