#!/usr/bin/env python3
"""Replay a VIO-derived dual-arm TCP trajectory through Arm-P7 Cartesian servo.

The input NPZ contains TCP poses relative to the recording segment start, not
joint targets. During execution each relative pose is composed with the
measured TCP pose at replay start. The default is an offline dry-run; actual
motion requires both --execute and --allow-robot-motion.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import dataclasses
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

from arm_p7_sdk import AirbotClient
from arm_p7_sdk import CartesianMoveOptions
from arm_p7_sdk import CartesianPose
from arm_p7_sdk import Controller
from arm_p7_sdk import EEFControlMode
from arm_p7_sdk import EEFMoveOptions
from arm_p7_sdk import JointMoveOptions
import numpy as np

SIDES = ("left", "right")
PORTS = {"left": 50071, "right": 50072}
EXPECTED_SCHEMA = "vio_dual_arm_trajectory_v1"
READY_JOINT_TARGET_RAD = (0.0, 0.78, 0.0, 0.0, 0.0, 0.0, 1.04)
# The VIO source labels are reversed relative to the physical AIRBOT arms.
SOURCE_ARM_OFFSETS = {"left": 7, "right": 0}


class StopState:
    def __init__(self) -> None:
        self.requested = False


STOP_STATE = StopState()


class UnsafeReplayError(RuntimeError):
    """A guard rejected the trajectory before or during hardware motion."""


@dataclasses.dataclass(frozen=True)
class TcpPose:
    position_m: np.ndarray
    quaternion_xyzw: np.ndarray


@dataclasses.dataclass(frozen=True)
class Trajectory:
    source: Path
    time_s: np.ndarray
    commands_14d: np.ndarray
    metadata: dict[str, object]


@dataclasses.dataclass(frozen=True)
class ReplayFrame:
    elapsed_s: float
    source_index: int
    relative_poses: dict[str, TcpPose]
    raw_grippers: dict[str, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, default=Path("data/vio_dual_arm_trajectory_10s.replay.npz"))
    parser.add_argument("--host", default="192.168.25.1")
    parser.add_argument("--backend", default="grpc")
    parser.add_argument("--left-port", type=int, default=PORTS["left"])
    parser.add_argument("--right-port", type=int, default=PORTS["right"])
    parser.add_argument("--time-scale", type=float, default=5.0, help="Replay duration multiplier; 5 means 5x slower.")
    parser.add_argument("--max-step-translation-m", type=float, default=0.010)
    parser.add_argument("--max-step-rotation-rad", type=float, default=0.10)
    parser.add_argument("--min-command-interval-s", type=float, default=0.020)
    parser.add_argument("--max-envelope-m", type=float, default=0.050)
    parser.add_argument("--max-frames", type=int, default=5000)
    parser.add_argument("--pre-samples", type=int, default=3)
    parser.add_argument("--sample-period-s", type=float, default=0.10)
    parser.add_argument("--pre-drift-guard-m", type=float, default=0.003)
    parser.add_argument("--arm-speed-rad-s", type=float, default=0.55)
    parser.add_argument("--eff", default="8,8,8,8,8,8,8")
    parser.add_argument("--motion-timeout-ms", type=int, default=3000)
    parser.add_argument("--lease-ms", type=int, default=120000)
    parser.add_argument("--feedback-hz", type=float, default=5.0)
    parser.add_argument(
        "--max-measured-envelope-m",
        type=float,
        default=0.0,
        help="Stop if measured TCP leaves this radius from replay start; 0 records without this hard guard.",
    )
    parser.add_argument("--replay-grippers", action="store_true", help="Also stream recorded gripper values.")
    parser.add_argument("--eef-min-mm", type=float, default=0.0)
    parser.add_argument("--eef-max-mm", type=float, default=95.0)
    parser.add_argument("--eef-speed-mm-s", type=float, default=80.0)
    parser.add_argument("--eef-effort", type=float, default=5.0)
    parser.add_argument("--eef-timeout-ms", type=int, default=3000)
    parser.add_argument("--gripper-deadband-mm", type=float, default=0.5)
    parser.add_argument(
        "--skip-ready-pose",
        action="store_true",
        help="Skip the default move to the recovery ready joint pose and opening both grippers.",
    )
    parser.add_argument("--ready-timeout-ms", type=int, default=60000)
    parser.add_argument("--ready-settle-s", type=float, default=1.0)
    parser.add_argument("--ready-max-joint-delta-rad", type=float, default=3.0)
    parser.add_argument("--summary", type=Path, default=Path("/tmp/p7_vio_dual_arm_replay_latest.json"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-robot-motion", action="store_true")
    return parser.parse_args()


def parse_eff(value: str) -> list[float]:
    efforts = [float(item.strip()) for item in value.split(",") if item.strip()]
    if len(efforts) != 7 or not all(math.isfinite(item) and item > 0.0 for item in efforts):
        raise ValueError("--eff must contain seven positive finite values")
    return efforts


def normalize_quaternion(quaternion_xyzw: np.ndarray) -> np.ndarray:
    value = np.asarray(quaternion_xyzw, dtype=np.float64)
    norm = float(np.linalg.norm(value))
    if value.shape != (4,) or not math.isfinite(norm) or norm <= 1e-12:
        raise ValueError(f"invalid quaternion {value.tolist()}")
    return value / norm


def quaternion_from_rotvec(rotvec_rad: np.ndarray) -> np.ndarray:
    rotvec = np.asarray(rotvec_rad, dtype=np.float64)
    angle = float(np.linalg.norm(rotvec))
    if not math.isfinite(angle):
        raise ValueError("rotation vector is not finite")
    if angle <= 1e-12:
        return np.asarray([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
    axis = rotvec / angle
    half = 0.5 * angle
    return normalize_quaternion(np.concatenate((axis * math.sin(half), [math.cos(half)])))


def quaternion_multiply_xyzw(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    x1, y1, z1, w1 = normalize_quaternion(first)
    x2, y2, z2, w2 = normalize_quaternion(second)
    return normalize_quaternion(
        np.asarray(
            [
                w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
                w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            ],
            dtype=np.float64,
        )
    )


def quaternion_to_rotation_matrix(quaternion_xyzw: np.ndarray) -> np.ndarray:
    x, y, z, w = normalize_quaternion(quaternion_xyzw)
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def quaternion_angle_rad(first: np.ndarray, second: np.ndarray) -> float:
    dot = abs(float(np.dot(normalize_quaternion(first), normalize_quaternion(second))))
    return 2.0 * math.acos(min(1.0, max(-1.0, dot)))


def quaternion_slerp(first: np.ndarray, second: np.ndarray, fraction: float) -> np.ndarray:
    start = normalize_quaternion(first)
    end = normalize_quaternion(second)
    dot = float(np.dot(start, end))
    if dot < 0.0:
        end = -end
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        return normalize_quaternion(start + fraction * (end - start))
    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    return normalize_quaternion(
        (math.sin((1.0 - fraction) * theta) / sin_theta) * start
        + (math.sin(fraction * theta) / sin_theta) * end
    )


def relative_pose_from_row(row: np.ndarray, side: str) -> tuple[TcpPose, float]:
    offset = SOURCE_ARM_OFFSETS[side]
    return (
        TcpPose(
            position_m=np.asarray(row[offset : offset + 3], dtype=np.float64),
            quaternion_xyzw=quaternion_from_rotvec(row[offset + 3 : offset + 6]),
        ),
        float(row[offset + 6]),
    )


def compose_pose(start: TcpPose, relative: TcpPose) -> TcpPose:
    return TcpPose(
        position_m=start.position_m + quaternion_to_rotation_matrix(start.quaternion_xyzw) @ relative.position_m,
        quaternion_xyzw=quaternion_multiply_xyzw(start.quaternion_xyzw, relative.quaternion_xyzw),
    )


def interpolate_pose(first: TcpPose, second: TcpPose, fraction: float) -> TcpPose:
    return TcpPose(
        position_m=(1.0 - fraction) * first.position_m + fraction * second.position_m,
        quaternion_xyzw=quaternion_slerp(first.quaternion_xyzw, second.quaternion_xyzw, fraction),
    )


def load_trajectory(path: Path) -> Trajectory:
    if not path.is_file():
        raise ValueError(f"trajectory does not exist: {path}")
    with np.load(path, allow_pickle=False) as payload:
        required = {"time_s", "tcp_pose_command_14d", "metadata_json"}
        missing = sorted(required - set(payload.files))
        if missing:
            raise ValueError(f"trajectory missing keys: {missing}")
        time_s = np.asarray(payload["time_s"], dtype=np.float64)
        commands = np.asarray(payload["tcp_pose_command_14d"], dtype=np.float64)
        metadata = json.loads(str(payload["metadata_json"].item()))
    if time_s.ndim != 1 or len(time_s) < 2 or not np.all(np.isfinite(time_s)) or not np.all(np.diff(time_s) > 0.0):
        raise ValueError("time_s must contain at least two strictly increasing finite values")
    if commands.shape != (len(time_s), 14) or not np.all(np.isfinite(commands)):
        raise ValueError(f"tcp_pose_command_14d must be finite [{len(time_s)},14], got {commands.shape}")
    if metadata.get("schema_version") != EXPECTED_SCHEMA:
        raise ValueError(f"unexpected schema_version: {metadata.get('schema_version')!r}")
    if metadata.get("replay", {}).get("is_direct_airbot_joint_command") is not False:
        raise ValueError("trajectory is not marked as a relative TCP replay")
    return Trajectory(path, time_s - time_s[0], commands, metadata)


def build_relative_frames(trajectory: Trajectory, args: argparse.Namespace) -> list[ReplayFrame]:
    frames: list[ReplayFrame] = []
    first_poses = {}
    first_grippers = {}
    for side in SIDES:
        first_poses[side], first_grippers[side] = relative_pose_from_row(trajectory.commands_14d[0], side)
    frames.append(ReplayFrame(0.0, 0, first_poses, first_grippers))
    elapsed_s = 0.0
    for source_index in range(1, len(trajectory.time_s)):
        previous_poses = {}
        current_poses = {}
        previous_grippers = {}
        current_grippers = {}
        substeps = 1
        for side in SIDES:
            previous_poses[side], previous_grippers[side] = relative_pose_from_row(
                trajectory.commands_14d[source_index - 1], side
            )
            current_poses[side], current_grippers[side] = relative_pose_from_row(
                trajectory.commands_14d[source_index], side
            )
            translation = float(np.linalg.norm(current_poses[side].position_m - previous_poses[side].position_m))
            rotation = quaternion_angle_rad(previous_poses[side].quaternion_xyzw, current_poses[side].quaternion_xyzw)
            substeps = max(
                substeps,
                math.ceil(translation / args.max_step_translation_m),
                math.ceil(rotation / args.max_step_rotation_rad),
            )
        segment_s = max(
            float(trajectory.time_s[source_index] - trajectory.time_s[source_index - 1]) * args.time_scale,
            substeps * args.min_command_interval_s,
        )
        for substep in range(1, substeps + 1):
            fraction = substep / substeps
            frames.append(
                ReplayFrame(
                    elapsed_s + fraction * segment_s,
                    source_index,
                    {side: interpolate_pose(previous_poses[side], current_poses[side], fraction) for side in SIDES},
                    {
                        side: (1.0 - fraction) * previous_grippers[side] + fraction * current_grippers[side]
                        for side in SIDES
                    },
                )
            )
        elapsed_s += segment_s
    if len(frames) > args.max_frames:
        raise UnsafeReplayError(f"interpolated frame count {len(frames)} exceeds --max-frames {args.max_frames}")
    return frames


def state_ok(state: object) -> bool:
    return (
        bool(getattr(state, "service_state", False))
        and bool(getattr(state, "valid", False))
        and str(getattr(state, "fsm_state", "")) == "IDLE"
        and str(getattr(state, "controller_state", "")) == "idle"
    )


def read_pose(client: AirbotClient, side: str) -> TcpPose:
    pose = client.get_end_pose()
    if pose is None:
        raise RuntimeError(f"{side}: get_end_pose() returned None")
    return TcpPose(
        position_m=np.asarray(pose.position, dtype=np.float64),
        quaternion_xyzw=normalize_quaternion(np.asarray(pose.orientation, dtype=np.float64)),
    )


def read_stable_pose(client: AirbotClient, side: str, args: argparse.Namespace) -> TcpPose:
    samples = []
    for index in range(args.pre_samples):
        samples.append(read_pose(client, side))
        if index + 1 < args.pre_samples:
            time.sleep(args.sample_period_s)
    drift = max(float(np.linalg.norm(sample.position_m - samples[0].position_m)) for sample in samples[1:])
    print(f"{side} pre_drift_m={drift:.6f}", flush=True)
    if drift > args.pre_drift_guard_m:
        raise UnsafeReplayError(f"{side}: pre-motion drift {drift:.6f} exceeds {args.pre_drift_guard_m:.6f}")
    return samples[-1]


def make_sdk_pose(pose: TcpPose) -> CartesianPose:
    return CartesianPose(
        position=tuple(float(value) for value in pose.position_m),
        orientation=tuple(float(value) for value in pose.quaternion_xyzw),
    )


def prepare_gripper(client: AirbotClient, side: str, args: argparse.Namespace) -> int:
    mode = client.get_eef_mode()
    state = client.get_eef_joint_state()
    eef_pos = getattr(state, "eef_pos", None)
    if mode is None or getattr(mode, "has_eef", True) is False or eef_pos is None or len(eef_pos) <= 0:
        raise RuntimeError(f"{side}: no usable EEF")
    if not client.switch_eef_control_mode(EEFControlMode.csp, timeout_ms=args.eef_timeout_ms):
        raise RuntimeError(f"{side}: switch_eef_control_mode(csp) returned False")
    if not client.set_eef_speed(args.eef_speed_mm_s):
        raise RuntimeError(f"{side}: set_eef_speed returned False")
    return len(eef_pos)


def move_to_ready_pose(
    clients: dict[str, AirbotClient],
    acquired: set[str],
    switched: set[str],
    eef_switched: set[str],
    args: argparse.Namespace,
    efforts: list[float],
) -> None:
    target = np.asarray(READY_JOINT_TARGET_RAD, dtype=np.float64)
    print(f"ready_joint_target_rad={target.tolist()} ready_gripper_open_mm=95.0", flush=True)
    for side, client in clients.items():
        if side not in acquired:
            ok = client.acquire_control(lease_ms=args.lease_ms, renew_period_s=5.0)
            print(f"{side} ready_acquire_control {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: acquire_control returned False before ready pose")
            acquired.add(side)

        arm_state = client.get_arm_joint_state()
        angles = getattr(arm_state, "angles", None)
        if angles is None or len(angles) != len(target):
            raise RuntimeError(f"{side}: ready pose requires seven readable arm joint angles")
        max_delta = float(np.max(np.abs(target - np.asarray(angles, dtype=np.float64))))
        print(f"{side} ready_max_joint_delta_rad={max_delta:.6f}", flush=True)
        if max_delta > args.ready_max_joint_delta_rad:
            raise UnsafeReplayError(
                f"{side}: ready joint delta {max_delta:.6f} exceeds {args.ready_max_joint_delta_rad:.6f}"
            )

        eef_dof = prepare_gripper(client, side, args)
        eef_switched.add(side)
        eef_options = EEFMoveOptions(eff=[args.eef_effort] * eef_dof, blocking=True)
        ok = client.move_eef([95.0] * eef_dof, eef_options, args.eef_timeout_ms)
        print(f"{side} ready_open_gripper ok={ok}", flush=True)
        if not ok:
            raise RuntimeError(f"{side}: move_eef(open) returned False before ready pose")

        ok = client.switch_controller(Controller.servo_control, timeout_ms=args.ready_timeout_ms)
        print(f"{side} ready_switch_servo {ok}", flush=True)
        if not ok:
            raise RuntimeError(f"{side}: switch_controller(servo_control) returned False before ready pose")
        switched.add(side)
        if not client.set_arm_speed([args.arm_speed_rad_s] * 7):
            raise RuntimeError(f"{side}: set_arm_speed returned False before ready pose")
        options = JointMoveOptions(eff=efforts, blocking=True)
        ok = client.move_joint(target.tolist(), options, args.ready_timeout_ms)
        print(f"{side} ready_move_joint ok={ok}", flush=True)
        if not ok:
            raise RuntimeError(f"{side}: move_joint returned False before ready pose")
    if args.ready_settle_s > 0.0:
        time.sleep(args.ready_settle_s)


def map_gripper(raw_value: float, args: argparse.Namespace) -> float:
    if not math.isfinite(raw_value):
        raise UnsafeReplayError(f"recorded gripper value is not finite: {raw_value!r}")
    return min(max(raw_value, args.eef_min_mm), args.eef_max_mm)


def write_summary(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def configure_direct_grpc(host: str) -> list[str]:
    """Keep this hardware-control process off any HTTP/SOCKS proxy."""
    proxy_variables = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    removed = [name for name in proxy_variables if os.environ.pop(name, None) is not None]
    for name in ("no_proxy", "NO_PROXY"):
        entries = [entry.strip() for entry in os.environ.get(name, "").split(",") if entry.strip()]
        if host not in entries:
            entries.append(host)
        os.environ[name] = ",".join(entries)
    return removed


def request_stop(_signum: int, _frame: object) -> None:
    STOP_STATE.requested = True


def validate_args(args: argparse.Namespace) -> None:
    if args.execute and not args.allow_robot_motion:
        raise ValueError("--execute requires --allow-robot-motion")
    positive = {
        "--time-scale": args.time_scale,
        "--max-step-translation-m": args.max_step_translation_m,
        "--max-step-rotation-rad": args.max_step_rotation_rad,
        "--min-command-interval-s": args.min_command_interval_s,
        "--pre-samples": args.pre_samples,
        "--sample-period-s": args.sample_period_s,
        "--arm-speed-rad-s": args.arm_speed_rad_s,
        "--motion-timeout-ms": args.motion_timeout_ms,
        "--lease-ms": args.lease_ms,
        "--feedback-hz": args.feedback_hz,
        "--max-frames": args.max_frames,
    }
    if any(not math.isfinite(float(value)) or float(value) <= 0.0 for value in positive.values()):
        raise ValueError("all timing, speed, step, frame, and sample arguments must be positive")
    if args.pre_samples < 2:
        raise ValueError("--pre-samples must be at least 2")
    if args.max_envelope_m <= 0.0 or args.pre_drift_guard_m < 0.0 or args.max_measured_envelope_m < 0.0:
        raise ValueError("envelope guards must be non-negative, and --max-envelope-m must be positive")
    if args.replay_grippers and (
        args.eef_min_mm < 0.0
        or args.eef_max_mm <= args.eef_min_mm
        or args.eef_speed_mm_s <= 0.0
        or args.eef_effort <= 0.0
        or args.eef_timeout_ms <= 0
        or args.gripper_deadband_mm < 0.0
    ):
        raise ValueError("invalid gripper range, speed, effort, timeout, or deadband")
    if not args.skip_ready_pose and (
        args.ready_timeout_ms <= 0
        or args.ready_settle_s < 0.0
        or args.ready_max_joint_delta_rad <= 0.0
    ):
        raise ValueError("ready pose timeout and joint delta must be positive, and settle time must be non-negative")


def main() -> int:
    STOP_STATE.requested = False
    args = parse_args()
    summary: dict[str, object] = {"trajectory": str(args.trajectory), "execute": bool(args.execute)}
    clients: dict[str, AirbotClient] = {}
    acquired: set[str] = set()
    switched: set[str] = set()
    eef_switched: set[str] = set()
    exit_code = 0
    try:
        validate_args(args)
        efforts = parse_eff(args.eff)
        trajectory = load_trajectory(args.trajectory)
        frames = build_relative_frames(trajectory, args)
        max_envelope = {
            side: max(float(np.linalg.norm(frame.relative_poses[side].position_m)) for frame in frames) for side in SIDES
        }
        min_raw_gripper = {side: min(frame.raw_grippers[side] for frame in frames) for side in SIDES}
        max_raw_gripper = {side: max(frame.raw_grippers[side] for frame in frames) for side in SIDES}
        summary.update(
            {
                "input_samples": len(trajectory.time_s),
                "source_duration_s": float(trajectory.time_s[-1]),
                "planned_frames": len(frames),
                "planned_duration_s": float(frames[-1].elapsed_s),
                "max_relative_envelope_m": max_envelope,
                "min_raw_gripper": min_raw_gripper,
                "max_raw_gripper": max_raw_gripper,
                "time_scale": args.time_scale,
                "replay_grippers": bool(args.replay_grippers),
                "move_to_ready_pose": not args.skip_ready_pose,
            }
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
        exceeded = {side: value for side, value in max_envelope.items() if value > args.max_envelope_m}
        if exceeded:
            raise UnsafeReplayError(f"relative envelope {exceeded} exceeds --max-envelope-m {args.max_envelope_m:.6f}")
        if args.replay_grippers:
            for side in SIDES:
                map_gripper(min_raw_gripper[side], args)
                map_gripper(max_raw_gripper[side], args)
        if not args.execute:
            for index in sorted({0, len(frames) // 2, len(frames) - 1}):
                frame = frames[index]
                print(
                    f"DRY_RUN frame={index} t_s={frame.elapsed_s:.3f} source_index={frame.source_index} "
                    f"left_rel_xyz={frame.relative_poses['left'].position_m.tolist()} "
                    f"right_rel_xyz={frame.relative_poses['right'].position_m.tolist()}",
                    flush=True,
                )
            print("DRY_RUN: no SDK client, control lease, controller switch, arm, or gripper command was used", flush=True)
            summary["status"] = "dry_run"
            return 0

        removed_proxy_variables = configure_direct_grpc(args.host)
        print(f"grpc_direct_host={args.host} removed_proxy_variables={removed_proxy_variables}", flush=True)
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        clients = {
            "left": AirbotClient(host=args.host, port=args.left_port, backend=args.backend),
            "right": AirbotClient(host=args.host, port=args.right_port, backend=args.backend),
        }
        for side, client in clients.items():
            state = client.get_service_state()
            print(f"{side} state_before {state}", flush=True)
            if not state_ok(state):
                raise RuntimeError(f"{side}: not IDLE/idle/valid")
        if not args.skip_ready_pose:
            move_to_ready_pose(clients, acquired, switched, eef_switched, args, efforts)
        starts = {side: read_stable_pose(client, side, args) for side, client in clients.items()}
        for side, pose in starts.items():
            print(f"{side} replay_start_xyz={pose.position_m.tolist()} replay_start_xyzw={pose.quaternion_xyzw.tolist()}", flush=True)

        for side, client in clients.items():
            if side in acquired:
                continue
            ok = client.acquire_control(lease_ms=args.lease_ms, renew_period_s=5.0)
            print(f"{side} acquire_control {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: acquire_control returned False")
            acquired.add(side)
        for side, client in clients.items():
            if side not in switched:
                ok = client.switch_controller(Controller.servo_control, timeout_ms=args.motion_timeout_ms)
                print(f"{side} switch_servo {ok}", flush=True)
                if not ok:
                    raise RuntimeError(f"{side}: switch_controller(servo_control) returned False")
                switched.add(side)
                if not client.set_arm_speed([args.arm_speed_rad_s] * 7):
                    raise RuntimeError(f"{side}: set_arm_speed returned False")
        eef_dofs: dict[str, int] = {}
        if args.replay_grippers:
            for side, client in clients.items():
                eef_dofs[side] = prepare_gripper(client, side, args)
                eef_switched.add(side)

        arm_options = CartesianMoveOptions(eff=efforts, motion_type="lin", blocking=False)
        last_gripper_mm: dict[str, float | None] = dict.fromkeys(SIDES)
        feedback_period_s = 1.0 / args.feedback_hz
        next_feedback_s = 0.0
        loop_start = time.monotonic()
        frames_sent = 0
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="vio-replay") as executor:
            for index, frame in enumerate(frames):
                if STOP_STATE.requested:
                    raise KeyboardInterrupt
                deadline = loop_start + frame.elapsed_s
                sleep_s = deadline - time.monotonic()
                if sleep_s > 0.0:
                    time.sleep(sleep_s)
                targets = {side: compose_pose(starts[side], frame.relative_poses[side]) for side in SIDES}
                futures = {
                    side: executor.submit(
                        clients[side].move_end_pose,
                        make_sdk_pose(targets[side]),
                        arm_options,
                        args.motion_timeout_ms,
                    )
                    for side in SIDES
                }
                failures = [side for side, future in futures.items() if not future.result()]
                if failures:
                    raise RuntimeError(f"move_end_pose returned False for {failures}")
                if args.replay_grippers:
                    for side in SIDES:
                        target_mm = map_gripper(frame.raw_grippers[side], args)
                        if last_gripper_mm[side] is None or abs(target_mm - last_gripper_mm[side]) >= args.gripper_deadband_mm:
                            options = EEFMoveOptions(eff=[args.eef_effort] * eef_dofs[side], blocking=False)
                            if not clients[side].move_eef([target_mm] * eef_dofs[side], options, args.eef_timeout_ms):
                                raise RuntimeError(f"{side}: move_eef returned False")
                            last_gripper_mm[side] = target_mm
                frames_sent += 1
                elapsed_s = time.monotonic() - loop_start
                if elapsed_s >= next_feedback_s or index == len(frames) - 1:
                    measured = {side: read_pose(clients[side], side) for side in SIDES}
                    measured_envelope = {
                        side: float(np.linalg.norm(measured[side].position_m - starts[side].position_m)) for side in SIDES
                    }
                    print(
                        f"frame={index}/{len(frames) - 1} elapsed_s={elapsed_s:.3f} "
                        f"left_measured_envelope_m={measured_envelope['left']:.4f} "
                        f"right_measured_envelope_m={measured_envelope['right']:.4f}",
                        flush=True,
                    )
                    if args.max_measured_envelope_m > 0.0 and any(
                        value > args.max_measured_envelope_m for value in measured_envelope.values()
                    ):
                        raise UnsafeReplayError(
                            f"measured envelope {measured_envelope} exceeds {args.max_measured_envelope_m:.6f}"
                        )
                    next_feedback_s = elapsed_s + feedback_period_s
        summary.update({"frames_sent": frames_sent, "elapsed_s": time.monotonic() - loop_start, "status": "success"})
        return 0
    except KeyboardInterrupt:
        print("STOP: signal received; stopping replay and returning controllers to idle", file=sys.stderr, flush=True)
        summary["status"] = "interrupted"
        exit_code = 130
    except UnsafeReplayError as exc:
        print(f"REFUSE: {exc}", file=sys.stderr, flush=True)
        summary.update({"status": "refused", "error": str(exc)})
        exit_code = 3
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        summary.update({"status": "failed", "error": repr(exc)})
        exit_code = 1
    finally:
        for side in eef_switched:
            try:
                print(f"{side} switch_eef_idle {clients[side].switch_eef_control_mode(EEFControlMode.idle, timeout_ms=args.eef_timeout_ms)}", flush=True)
            except Exception as exc:
                print(f"{side} switch_eef_idle_exception {exc!r}", file=sys.stderr, flush=True)
        for side in switched:
            try:
                print(f"{side} switch_idle {clients[side].switch_controller(Controller.idle, timeout_ms=args.motion_timeout_ms)}", flush=True)
            except Exception as exc:
                print(f"{side} switch_idle_exception {exc!r}", file=sys.stderr, flush=True)
        for side in acquired:
            try:
                clients[side].release_control()
                print(f"{side} release_control done", flush=True)
            except Exception as exc:
                print(f"{side} release_control_exception {exc!r}", file=sys.stderr, flush=True)
        for client in clients.values():
            client.close()
        try:
            write_summary(args.summary, summary)
            print(f"summary={args.summary}", flush=True)
        except Exception as exc:
            print(f"summary_write_exception {exc!r}", file=sys.stderr, flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
