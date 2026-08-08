#!/usr/bin/env python3
"""Replay the two follower-arm trajectories stored in an AIRDC MCAP file."""

from __future__ import annotations

import argparse
import json
import logging
import os
import select
import sys
import termios
import time
import tty
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeVar

import numpy as np
from mcap.reader import make_reader
from mcap_data_loader.schemas.airbot_fbs import FloatArray

from airdc.common.utils.transformations import (
    quaternion_inverse,
    quaternion_multiply,
)

if TYPE_CHECKING:
    from airdc.common.systems.basis import SystemMode
    from airbot_ie.robots.airbot_play import AIRBOTPlay


PROJECT_DIR = Path(__file__).resolve().parents[2]
LOGGER = logging.getLogger("dual_arm_replay")

LEFT_ARM_TOPIC = "left/follow/arm/joint_state/position"
LEFT_EEF_TOPIC = "left/follow/eef/joint_state/position"
RIGHT_ARM_TOPIC = "right/follow/arm/joint_state/position"
RIGHT_EEF_TOPIC = "right/follow/eef/joint_state/position"
REQUIRED_TOPICS = {
    LEFT_ARM_TOPIC: 6,
    LEFT_EEF_TOPIC: 1,
    RIGHT_ARM_TOPIC: 6,
    RIGHT_EEF_TOPIC: 1,
}

# A large scheduling delay usually means the robot service or network is unhealthy.
# Stop instead of sending delayed frames in a burst.
MAX_REPLAY_LAG_SECONDS = 0.25
LEADER_EEF_RANGE = 0.0471
FOLLOWER_EEF_RANGE = 0.072


class ReplayError(RuntimeError):
    """A trajectory validation or replay error."""


@dataclass(frozen=True)
class TrajectoryFrame:
    log_time_ns: int
    left_arm: tuple[float, ...]
    left_eef: tuple[float, ...]
    right_arm: tuple[float, ...]
    right_eef: tuple[float, ...]


@dataclass(frozen=True)
class Trajectory:
    source: Path
    frames: tuple[TrajectoryFrame, ...]
    recorded_serials: dict[str, str]
    recorded_leader_serials: dict[str, str] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if len(self.frames) < 2:
            return 0.0
        return (self.frames[-1].log_time_ns - self.frames[0].log_time_ns) / 1e9

    @property
    def average_rate_hz(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return (len(self.frames) - 1) / self.duration_seconds


def resolve_mcap_path(relative_path: str) -> Path:
    """Resolve an MCAP path while keeping it inside the project directory."""
    raw_path = Path(relative_path).expanduser()
    if raw_path.is_absolute():
        raise ReplayError(f"请输入相对路径，不能使用绝对路径: {relative_path}")

    path = (PROJECT_DIR / raw_path).resolve()
    try:
        path.relative_to(PROJECT_DIR)
    except ValueError as exc:
        raise ReplayError(f"MCAP 路径不能超出项目目录: {relative_path}") from exc

    if path.suffix.lower() != ".mcap":
        raise ReplayError(f"文件扩展名必须是 .mcap: {relative_path}")
    if not path.is_file():
        raise ReplayError(f"MCAP 文件不存在: {path}")
    return path


def _find_required_topics(summary) -> dict[str, str]:
    """Map normalized required topic names to their actual MCAP names."""
    if summary is None:
        raise ReplayError("MCAP 没有 summary，无法检查 topic")

    topic_mapping: dict[str, str] = {}
    for channel in summary.channels.values():
        normalized = channel.topic.lstrip("/")
        if normalized not in REQUIRED_TOPICS:
            continue
        if normalized in topic_mapping:
            raise ReplayError(
                f"MCAP 中有多个 topic 对应 {normalized}: "
                f"{topic_mapping[normalized]}, {channel.topic}"
            )
        topic_mapping[normalized] = channel.topic

    missing = sorted(set(REQUIRED_TOPICS) - set(topic_mapping))
    if missing:
        available = sorted(
            channel.topic for channel in summary.channels.values()
        )
        raise ReplayError(
            "MCAP 缺少从动臂位置 topic: "
            f"{', '.join(missing)}\n可用 topic: {', '.join(available)}"
        )
    return topic_mapping


def _decode_position(topic: str, data: bytes) -> tuple[float, ...]:
    array = FloatArray.FloatArray.GetRootAs(data, 0).ValuesAsNumpy()
    values = np.asarray(array, dtype=np.float64)
    expected_length = REQUIRED_TOPICS[topic]
    if values.ndim != 1 or len(values) != expected_length:
        raise ReplayError(
            f"topic {topic} 应包含 {expected_length} 个数值，"
            f"实际 shape={values.shape}"
        )
    if not np.all(np.isfinite(values)):
        raise ReplayError(f"topic {topic} 包含 NaN 或无穷大")
    return tuple(float(value) for value in values)


def _read_recorded_serials(
    path: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """Read robot serial numbers when the optional component_info exists."""
    with path.open("rb") as stream:
        reader = make_reader(stream)
        for attachment in reader.iter_attachments():
            if attachment.name != "component_info":
                continue
            try:
                component_info = json.loads(attachment.data)
            except (TypeError, ValueError, UnicodeDecodeError) as exc:
                raise ReplayError("component_info 附件不是有效 JSON") from exc

            serials = {"follow": {}, "lead": {}}
            for role in serials:
                for side in ("left", "right"):
                    info = component_info.get(f"{side}/{role}", {})
                    serial = info.get("sn")
                    if serial:
                        serials[role][side] = str(serial)
            return serials["follow"], serials["lead"]
    return {}, {}


def load_trajectory(path: Path) -> Trajectory:
    """Load only the two follower arms and preserve the MCAP log timestamps."""
    grouped: dict[int, dict[str, tuple[float, ...]]] = {}
    with path.open("rb") as stream:
        reader = make_reader(stream)
        topic_mapping = _find_required_topics(reader.get_summary())
        actual_to_normalized = {
            actual: normalized for normalized, actual in topic_mapping.items()
        }

        for schema, channel, message in reader.iter_messages(
            topics=set(actual_to_normalized)
        ):
            if schema is None or schema.name != "airbot_fbs.FloatArray":
                schema_name = schema.name if schema is not None else "<none>"
                raise ReplayError(
                    f"topic {channel.topic} 的 schema 不受支持: {schema_name}"
                )

            normalized_topic = actual_to_normalized[channel.topic]
            frame = grouped.setdefault(message.log_time, {})
            if normalized_topic in frame:
                raise ReplayError(
                    f"topic {channel.topic} 在 log_time={message.log_time} 重复"
                )
            frame[normalized_topic] = _decode_position(
                normalized_topic, message.data
            )

    if not grouped:
        raise ReplayError("MCAP 中没有可重放的从动臂数据")

    frames = []
    for log_time_ns in sorted(grouped):
        values = grouped[log_time_ns]
        missing = sorted(set(REQUIRED_TOPICS) - set(values))
        if missing:
            raise ReplayError(
                f"log_time={log_time_ns} 的帧数据不完整，缺少: "
                f"{', '.join(missing)}"
            )
        frames.append(
            TrajectoryFrame(
                log_time_ns=log_time_ns,
                left_arm=values[LEFT_ARM_TOPIC],
                left_eef=values[LEFT_EEF_TOPIC],
                right_arm=values[RIGHT_ARM_TOPIC],
                right_eef=values[RIGHT_EEF_TOPIC],
            )
        )

    follower_serials, leader_serials = _read_recorded_serials(path)
    return Trajectory(
        source=path,
        frames=tuple(frames),
        recorded_serials=follower_serials,
        recorded_leader_serials=leader_serials,
    )


def _max_joint_step(frames: tuple[TrajectoryFrame, ...], field: str) -> float:
    if len(frames) < 2:
        return 0.0
    return max(
        max(abs(current - previous) for current, previous in zip(b, a))
        for a, b in zip(
            (getattr(frame, field) for frame in frames),
            (getattr(frame, field) for frame in frames[1:]),
        )
    )


def print_trajectory_summary(trajectory: Trajectory) -> None:
    first = trajectory.frames[0]
    print(f"MCAP: {trajectory.source.relative_to(PROJECT_DIR)}")
    print(
        f"帧数: {len(trajectory.frames)}, 时长: {trajectory.duration_seconds:.3f} s, "
        f"平均频率: {trajectory.average_rate_hz:.2f} Hz"
    )
    print(
        "首帧左臂: "
        f"{[round(value, 5) for value in first.left_arm]}, "
        f"夹爪: {first.left_eef[0]:.5f}"
    )
    print(
        "首帧右臂: "
        f"{[round(value, 5) for value in first.right_arm]}, "
        f"夹爪: {first.right_eef[0]:.5f}"
    )
    print(
        "相邻帧最大关节变化: "
        f"左臂 {_max_joint_step(trajectory.frames, 'left_arm'):.5f} rad, "
        f"右臂 {_max_joint_step(trajectory.frames, 'right_arm'):.5f} rad"
    )
    if trajectory.recorded_serials:
        print(
            "录制从臂: "
            + ", ".join(
                f"{side}={serial}"
                for side, serial in sorted(trajectory.recorded_serials.items())
            )
        )
    if trajectory.recorded_leader_serials:
        print(
            "录制主臂: "
            + ", ".join(
                f"{side}={serial}"
                for side, serial in sorted(
                    trajectory.recorded_leader_serials.items()
                )
            )
        )


T = TypeVar("T")


class KeyboardMonitor:
    """Read single keys from the terminal and restore its settings on exit."""

    def __init__(self) -> None:
        self._fd = sys.stdin.fileno()
        self.enabled = sys.stdin.isatty()
        self._original_settings = None

    def __enter__(self) -> "KeyboardMonitor":
        if self.enabled:
            self._original_settings = termios.tcgetattr(self._fd)
            termios.tcflush(self._fd, termios.TCIFLUSH)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        if self._original_settings is not None:
            termios.tcsetattr(
                self._fd, termios.TCSADRAIN, self._original_settings
            )

    def read_available(self) -> bytes:
        if not self.enabled:
            return b""
        ready, _, _ = select.select([self._fd], [], [], 0)
        if not ready:
            return b""
        return os.read(self._fd, 32)

    def space_pressed(self) -> bool:
        return b" " in self.read_available()

    def wait_for_enter(self) -> None:
        if not self.enabled:
            raise ReplayError("当前终端不支持回车接管确认")
        while True:
            ready, _, _ = select.select([self._fd], [], [], 0.1)
            if not ready:
                continue
            key = os.read(self._fd, 1)
            if key in {b"\r", b"\n"}:
                return


class DualArmController:
    """Operate independent left and right AIRBOT services concurrently."""

    def __init__(
        self,
        left_url: str,
        left_port: int,
        right_url: str,
        right_port: int,
        left_lead_url: str,
        left_lead_port: int,
        right_lead_url: str,
        right_lead_port: int,
    ) -> None:
        from airdc.common.systems.basis import SystemMode
        from airbot_ie.robots.airbot_play import AIRBOTPlay
        from airbot_ie.robots.airbot_play import AIRBOTPlayConfig
        from airbot_ie.robots.airbot_play import RobotMode

        self._system_mode = SystemMode
        self._robot_mode = RobotMode
        self.robots = {
            "left": AIRBOTPlay(
                AIRBOTPlayConfig(
                    url=left_url, port=left_port, components=["arm", "eef"]
                )
            ),
            "right": AIRBOTPlay(
                AIRBOTPlayConfig(
                    url=right_url, port=right_port, components=["arm", "eef"]
                )
            ),
        }
        self.leaders = {
            "left": AIRBOTPlay(
                AIRBOTPlayConfig(
                    url=left_lead_url,
                    port=left_lead_port,
                    components=["arm", "eef"],
                )
            ),
            "right": AIRBOTPlay(
                AIRBOTPlayConfig(
                    url=right_lead_url,
                    port=right_lead_port,
                    components=["arm", "eef"],
                )
            ),
        }
        self._pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="airbot-replay"
        )
        self._closed = False
        self._leaders_configured = False

    def _run_parallel_for(
        self,
        robots: dict[str, AIRBOTPlay],
        operation: Callable[[str, AIRBOTPlay], T],
    ) -> dict[str, T]:
        futures = {
            side: self._pool.submit(operation, side, robot)
            for side, robot in robots.items()
        }
        return {side: future.result() for side, future in futures.items()}

    def _run_parallel(
        self, operation: Callable[[str, AIRBOTPlay], T]
    ) -> dict[str, T]:
        return self._run_parallel_for(self.robots, operation)

    def configure(self) -> None:
        results = self._run_parallel(lambda _side, robot: robot.configure())
        failed = [side for side, result in results.items() if not result]
        if failed:
            raise ReplayError(f"机械臂连接失败: {', '.join(failed)}")

    def connected_serials(self) -> dict[str, str]:
        infos = self._run_parallel(lambda _side, robot: robot.get_info())
        return {
            side: str(info["sn"])
            for side, info in infos.items()
            if info.get("sn")
        }

    def configure_leaders(self) -> None:
        # Ensure partially connected leaders are also cleaned up on failure.
        self._leaders_configured = True
        results = self._run_parallel_for(
            self.leaders, lambda _side, robot: robot.configure()
        )
        failed = [side for side, result in results.items() if not result]
        if failed:
            raise ReplayError(f"主臂连接失败: {', '.join(failed)}")

    def connected_leader_serials(self) -> dict[str, str]:
        infos = self._run_parallel_for(
            self.leaders, lambda _side, robot: robot.get_info()
        )
        return {
            side: str(info["sn"])
            for side, info in infos.items()
            if info.get("sn")
        }

    def _switch_mode(self, mode: SystemMode) -> None:
        results = self._run_parallel(
            lambda _side, robot: robot.switch_mode(mode)
        )
        failed = [side for side, result in results.items() if not result]
        if failed:
            raise ReplayError(
                f"机械臂切换到 {mode.name} 模式失败: {', '.join(failed)}"
            )

    @staticmethod
    def _frame_action(side: str, frame: TrajectoryFrame) -> dict:
        if side == "left":
            arm, eef = frame.left_arm, frame.left_eef
        else:
            arm, eef = frame.right_arm, frame.right_eef
        return {
            f"{side}/follow/arm/joint_state/position": {
                "t": frame.log_time_ns,
                "data": list(arm),
            },
            f"{side}/follow/eef/joint_state/position": {
                "t": frame.log_time_ns,
                "data": list(eef),
            },
        }

    def send_frame(self, frame: TrajectoryFrame) -> None:
        self._run_parallel(
            lambda side, robot: robot.send_action(
                self._frame_action(side, frame)
            )
        )

    def move_to_start(self, first_frame: TrajectoryFrame) -> None:
        self._switch_mode(self._system_mode.RESETTING)
        self.send_frame(first_frame)
        self._switch_mode(self._system_mode.SAMPLING)

    def enable_leader_manual_mode(self) -> None:
        results = self._run_parallel_for(
            self.leaders,
            lambda _side, robot: robot.switch_mode(self._system_mode.PASSIVE),
        )
        failed = [side for side, result in results.items() if not result]
        if failed:
            raise ReplayError(
                f"主臂切换到重力补偿模式失败: {', '.join(failed)}"
            )

    def capture_takeover_references(self) -> dict[str, "TakeoverReference"]:
        def capture(side: str, leader: AIRBOTPlay) -> TakeoverReference:
            lead_position, lead_orientation = leader.interface.get_end_pose()
            follow_position, follow_orientation = self.robots[
                side
            ].interface.get_end_pose()
            return TakeoverReference(
                leader_position=_position_tuple(lead_position),
                leader_orientation=_quaternion_tuple(lead_orientation),
                follower_position=_position_tuple(follow_position),
                follower_orientation=_quaternion_tuple(follow_orientation),
            )

        return self._run_parallel_for(self.leaders, capture)

    def capture_leader_states(self) -> dict[str, "LeaderState"]:
        def capture(_side: str, leader: AIRBOTPlay) -> LeaderState:
            position, orientation = leader.interface.get_end_pose()
            eef_position = leader.interface.get_eef_pos()
            if not eef_position:
                raise ReplayError("无法读取主臂夹爪位置")
            return LeaderState(
                position=_position_tuple(position),
                orientation=_quaternion_tuple(orientation),
                eef_position=float(eef_position[0]),
            )

        return self._run_parallel_for(self.leaders, capture)

    def enable_follower_pose_servo(self) -> None:
        results = self._run_parallel(
            lambda _side, robot: robot.interface.switch_mode(
                self._robot_mode.SERVO_CART_POSE
            )
        )
        failed = [side for side, result in results.items() if not result]
        if failed:
            raise ReplayError(
                f"从臂切换到笛卡尔伺服模式失败: {', '.join(failed)}"
            )

    def send_takeover_targets(
        self, targets: dict[str, "FollowerTarget"]
    ) -> None:
        def send(side: str, follower: AIRBOTPlay) -> None:
            target = targets[side]
            follower.interface.servo_cart_pose(
                [list(target.position), list(target.orientation)]
            )
            follower.interface.servo_eef_pos([target.eef_position])

        self._run_parallel(send)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        def disconnect(_side: str, robot: AIRBOTPlay) -> bool:
            if getattr(robot, "interface", None) is None:
                return True
            try:
                robot.interface.switch_mode(self._robot_mode.PLANNING_POS)
            except Exception:
                LOGGER.exception("机械臂切换到规划模式时出错")
            return robot.shutdown()

        try:
            self._run_parallel(disconnect)
        except Exception:
            LOGGER.exception("关闭从臂连接时出错")
        try:
            if self._leaders_configured:
                self._run_parallel_for(self.leaders, disconnect)
        except Exception:
            LOGGER.exception("关闭主臂连接时出错")
        finally:
            self._pool.shutdown(wait=True)


@dataclass(frozen=True)
class TakeoverReference:
    leader_position: tuple[float, float, float]
    leader_orientation: tuple[float, float, float, float]
    follower_position: tuple[float, float, float]
    follower_orientation: tuple[float, float, float, float]


@dataclass(frozen=True)
class LeaderState:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]
    eef_position: float


@dataclass(frozen=True)
class FollowerTarget:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]
    eef_position: float


def _position_tuple(values) -> tuple[float, float, float]:
    position = np.asarray(values, dtype=np.float64)
    if position.shape != (3,) or not np.all(np.isfinite(position)):
        raise ReplayError(f"无效的末端位置: {values}")
    return tuple(float(value) for value in position)


def _quaternion_tuple(values) -> tuple[float, float, float, float]:
    quaternion = np.asarray(values, dtype=np.float64)
    if quaternion.shape != (4,) or not np.all(np.isfinite(quaternion)):
        raise ReplayError(f"无效的末端四元数: {values}")
    norm = float(np.linalg.norm(quaternion))
    if norm < 1e-8:
        raise ReplayError(f"末端四元数模长过小: {values}")
    quaternion /= norm
    return tuple(float(value) for value in quaternion)


def delta_pose_target(
    reference: TakeoverReference, state: LeaderState
) -> FollowerTarget:
    """Apply the leader's translation and rotation deltas to the follower base pose."""
    leader_position = np.asarray(state.position, dtype=np.float64)
    leader_reference_position = np.asarray(
        reference.leader_position, dtype=np.float64
    )
    follower_reference_position = np.asarray(
        reference.follower_position, dtype=np.float64
    )
    target_position = (
        follower_reference_position
        + leader_position
        - leader_reference_position
    )

    leader_orientation = np.asarray(state.orientation, dtype=np.float64)
    leader_reference_orientation = np.asarray(
        reference.leader_orientation, dtype=np.float64
    )
    # q and -q represent the same rotation. Keep the representation continuous.
    if np.dot(leader_orientation, leader_reference_orientation) < 0:
        leader_orientation = -leader_orientation
    delta_orientation = quaternion_multiply(
        leader_orientation,
        quaternion_inverse(leader_reference_orientation),
    )
    target_orientation = quaternion_multiply(
        delta_orientation,
        np.asarray(reference.follower_orientation, dtype=np.float64),
    )

    eef_position = float(
        np.clip(
            state.eef_position * FOLLOWER_EEF_RANGE / LEADER_EEF_RANGE,
            0.0,
            FOLLOWER_EEF_RANGE,
        )
    )
    return FollowerTarget(
        position=_position_tuple(target_position),
        orientation=_quaternion_tuple(target_orientation),
        eef_position=eef_position,
    )


def verify_device_serials(
    recorded: dict[str, str], connected: dict[str, str]
) -> None:
    mismatches = []
    for side, expected in recorded.items():
        actual = connected.get(side)
        if actual and actual != expected:
            mismatches.append(f"{side}: 录制={expected}, 当前={actual}")
    if mismatches:
        raise ReplayError(
            "机械臂序列号与录制数据不一致，为避免左右臂或机型用错已终止:\n"
            + "\n".join(mismatches)
            + "\n确认设备无误后可使用 --skip-device-check."
        )


def _sleep_until(
    deadline_ns: int, keyboard: KeyboardMonitor | None = None
) -> bool:
    while True:
        if keyboard is not None and keyboard.space_pressed():
            return True
        remaining_ns = deadline_ns - time.perf_counter_ns()
        if remaining_ns <= 0:
            return False
        time.sleep(min(remaining_ns / 1e9, 0.01))


def replay_trajectory(
    controller: DualArmController,
    trajectory: Trajectory,
    keyboard: KeyboardMonitor | None = None,
) -> bool:
    """Replay until completion or Space. Return True when takeover is requested."""
    first_log_time = trajectory.frames[0].log_time_ns
    replay_start = time.perf_counter_ns()
    worst_lag = 0.0

    for index, frame in enumerate(trajectory.frames, start=1):
        offset_ns = frame.log_time_ns - first_log_time
        deadline_ns = replay_start + offset_ns
        if _sleep_until(deadline_ns, keyboard):
            LOGGER.info("第 %d/%d 帧处收到接管请求", index, len(trajectory.frames))
            return True

        lag_seconds = max(0.0, (time.perf_counter_ns() - deadline_ns) / 1e9)
        worst_lag = max(worst_lag, lag_seconds)
        if lag_seconds > MAX_REPLAY_LAG_SECONDS:
            raise ReplayError(
                f"第 {index} 帧延迟 {lag_seconds:.3f} s，超过 "
                f"{MAX_REPLAY_LAG_SECONDS:.2f} s，已停止重放"
            )

        controller.send_frame(frame)
        if keyboard is not None and keyboard.space_pressed():
            LOGGER.info("第 %d/%d 帧后收到接管请求", index, len(trajectory.frames))
            return True
        if index % 100 == 0 or index == len(trajectory.frames):
            LOGGER.info("重放进度: %d/%d", index, len(trajectory.frames))

    actual_duration = (time.perf_counter_ns() - replay_start) / 1e9
    LOGGER.info(
        "重放完成，实际用时 %.3f s，最大调度延迟 %.4f s",
        actual_duration,
        worst_lag,
    )
    return False


def run_delta_pose_takeover(
    controller: DualArmController,
    trajectory: Trajectory,
    keyboard: KeyboardMonitor,
    rate_hz: float,
    skip_device_check: bool,
) -> None:
    LOGGER.info("重放已暂停，正在连接左右主臂...")
    controller.configure_leaders()
    if not skip_device_check:
        verify_device_serials(
            trajectory.recorded_leader_serials,
            controller.connected_leader_serials(),
        )

    controller.enable_leader_manual_mode()
    print(
        "\n已进入接管准备模式：主臂已开启重力补偿，"
        "请手动移动左右主臂到合适位置。\n"
        "就位后按回车，当前主/从臂位姿将被设为 delta 零点。"
    )
    keyboard.wait_for_enter()

    references = controller.capture_takeover_references()
    controller.enable_follower_pose_servo()
    period_ns = int(1e9 / rate_hz)
    next_deadline_ns = time.perf_counter_ns()
    worst_lag = 0.0
    cycle = 0
    LOGGER.info(
        "已开始 %.1f Hz delta pose 接管（位移+旋转），Ctrl-C 停止",
        rate_hz,
    )

    while True:
        states = controller.capture_leader_states()
        targets = {
            side: delta_pose_target(references[side], state)
            for side, state in states.items()
        }
        controller.send_takeover_targets(targets)
        cycle += 1

        next_deadline_ns += period_ns
        _sleep_until(next_deadline_ns)
        lag_seconds = max(
            0.0, (time.perf_counter_ns() - next_deadline_ns) / 1e9
        )
        worst_lag = max(worst_lag, lag_seconds)
        if lag_seconds > MAX_REPLAY_LAG_SECONDS:
            raise ReplayError(
                f"delta pose 接管延迟 {lag_seconds:.3f} s，超过 "
                f"{MAX_REPLAY_LAG_SECONDS:.2f} s，已停止控制"
            )
        if cycle % int(rate_hz * 10) == 0:
            LOGGER.info(
                "delta pose 接管中，最大调度延迟 %.4f s", worst_lag
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "按 MCAP 原始时间戳重放左右从动臂关节和夹爪轨迹，"
            "按空格可转为主臂 delta pose 在线接管。"
        )
    )
    parser.add_argument(
        "mcap_path",
        help="相对于项目根目录的 MCAP 路径",
    )
    parser.add_argument(
        "--left-url",
        default=os.environ.get("AIRBOT_LEFT_URL", "192.168.209.101"),
        help="左从动臂服务地址",
    )
    parser.add_argument(
        "--left-port",
        default=int(os.environ.get("AIRBOT_LEFT_PORT", "50051")),
        type=int,
        help="左从动臂服务端口",
    )
    parser.add_argument(
        "--right-url",
        default=os.environ.get("AIRBOT_RIGHT_URL", "192.168.209.102"),
        help="右从动臂服务地址",
    )
    parser.add_argument(
        "--right-port",
        default=int(os.environ.get("AIRBOT_RIGHT_PORT", "50051")),
        type=int,
        help="右从动臂服务端口",
    )
    parser.add_argument(
        "--left-lead-url",
        default=os.environ.get("AIRBOT_LEFT_LEAD_URL", "localhost"),
        help="左主臂服务地址",
    )
    parser.add_argument(
        "--left-lead-port",
        default=int(os.environ.get("AIRBOT_LEFT_LEAD_PORT", "50050")),
        type=int,
        help="左主臂服务端口",
    )
    parser.add_argument(
        "--right-lead-url",
        default=os.environ.get("AIRBOT_RIGHT_LEAD_URL", "localhost"),
        help="右主臂服务地址",
    )
    parser.add_argument(
        "--right-lead-port",
        default=int(os.environ.get("AIRBOT_RIGHT_LEAD_PORT", "50052")),
        type=int,
        help="右主臂服务端口",
    )
    parser.add_argument(
        "--takeover-rate",
        default=30.0,
        type=float,
        help="delta pose 接管控制频率，默认 30 Hz",
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="只检查 MCAP 轨迹，不连接机械臂",
    )
    parser.add_argument(
        "--skip-device-check",
        action="store_true",
        help="允许当前机械臂序列号与 MCAP 记录不同",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="跳过开始重放前的 YES 确认",
    )
    args = parser.parse_args(argv)
    if args.takeover_rate < 1.0:
        parser.error("--takeover-rate 必须大于等于 1 Hz")
    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args(argv)

    try:
        mcap_path = resolve_mcap_path(args.mcap_path)
        trajectory = load_trajectory(mcap_path)
        print_trajectory_summary(trajectory)

        if args.inspect_only:
            print("检查完成，未连接机械臂。")
            return 0

        print(
            "将连接左臂 "
            f"{args.left_url}:{args.left_port} 和右臂 "
            f"{args.right_url}:{args.right_port}。"
        )
        if not args.yes:
            answer = input(
                "确保机械臂周围无人且无障碍物，"
                "输入 YES 开始连接和重放: "
            ).strip()
            if answer != "YES":
                print("已取消。")
                return 0

        controller = DualArmController(
            args.left_url,
            args.left_port,
            args.right_url,
            args.right_port,
            args.left_lead_url,
            args.left_lead_port,
            args.right_lead_url,
            args.right_lead_port,
        )
        try:
            LOGGER.info("正在连接两条从动臂...")
            controller.configure()
            connected_serials = controller.connected_serials()
            if not args.skip_device_check:
                verify_device_serials(
                    trajectory.recorded_serials, connected_serials
                )

            LOGGER.info("正在使用规划模式同步到首帧位置...")
            controller.move_to_start(trajectory.frames[0])
            for seconds in (3, 2, 1):
                LOGGER.info("%d 秒后开始原速重放", seconds)
                time.sleep(1.0)
            with KeyboardMonitor() as keyboard:
                if keyboard.enabled:
                    print("原速重放中，按空格进入主臂接管模式。")
                else:
                    LOGGER.warning(
                        "标准输入不是交互式终端，空格接管已禁用"
                    )
                takeover_requested = replay_trajectory(
                    controller, trajectory, keyboard
                )
                if takeover_requested:
                    run_delta_pose_takeover(
                        controller,
                        trajectory,
                        keyboard,
                        args.takeover_rate,
                        args.skip_device_check,
                    )
        finally:
            LOGGER.info("正在断开机械臂连接...")
            controller.close()
        return 0
    except KeyboardInterrupt:
        LOGGER.warning("用户中断重放")
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
