"""Persistent OpenPI camera-policy-P7 control loop.

Run this script with the combined ROS2 + Arm-P7 SDK + OpenPI client environment.
It keeps the ROS2 camera subscriptions, policy WebSocket, P7 SDK clients,
control leases, arm controller mode, and optional EEF controller mode alive
across loop iterations. Camera RGB is passed to policy directly from memory.

Default mode is dry-run: it captures images, requests policy actions, reads TCP
poses, prints guarded targets, and does not acquire control or move the robot.
Add both ``--execute`` and ``--allow-robot-motion`` to command the arms.
"""

from __future__ import annotations

import argparse
import ctypes
import dataclasses
import json
import math
import os
from collections.abc import Callable
from pathlib import Path
import signal
import shlex
import subprocess
import sys
import threading
import time

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
OPENPI_CLIENT_SRC = REPO_ROOT / "packages" / "openpi-client" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(OPENPI_CLIENT_SRC) not in sys.path:
    sys.path.insert(0, str(OPENPI_CLIENT_SRC))

from arm_p7_sdk import AirbotClient  # noqa: E402
from arm_p7_sdk import CartesianMoveOptions  # noqa: E402
from arm_p7_sdk import CartesianPose  # noqa: E402
from arm_p7_sdk import Controller  # noqa: E402
from arm_p7_sdk import EEFControlMode  # noqa: E402
from arm_p7_sdk import EEFMoveOptions  # noqa: E402
from openpi.shared import airbot_policy_bridge as policy_bridge  # noqa: E402
from openpi.shared import airbot_relpose as relpose  # noqa: E402


SIDES = ("left", "right")
UNSAFE_MOTION_EXIT_CODE = 3
DEFAULT_CHUNK_STEPS = 15
MIN_MOTION_COMMAND_INTERVAL_S = 0.004


class UnsafeMotionError(RuntimeError):
    """Motion guard violation that must stop automatic recovery/retry."""


def configure_parent_death_signal(supervisor_pid: int | None) -> None:
    """Ask Linux to terminate this process if its supervisor disappears."""
    if supervisor_pid is None or not sys.platform.startswith("linux"):
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM) != 0:  # PR_SET_PDEATHSIG
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != supervisor_pid:
        os.kill(os.getpid(), signal.SIGTERM)


class MotionCommandRateLimiter:
    """Keep aggregate motion-command start times below the configured rate."""

    def __init__(self, min_interval_s: float) -> None:
        self._min_interval_s = float(min_interval_s)
        self._last_start_s = 0.0
        self._lock = threading.Lock()

    def call(self, command: Callable[[], bool]) -> bool:
        if self._min_interval_s <= 0:
            return bool(command())
        with self._lock:
            wait_s = self._min_interval_s - (time.monotonic() - self._last_start_s)
            if wait_s > 0:
                time.sleep(wait_s)
            self._last_start_s = time.monotonic()
            return bool(command())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations", type=int, default=0, help="Loop iterations. 0 means use --duration-s or one shot."
    )
    parser.add_argument(
        "--duration-s", type=float, default=0.0, help="Run until this duration elapses. 0 disables duration mode."
    )
    parser.add_argument("--period-s", type=float, default=1.0, help="Minimum period between policy observations.")
    parser.add_argument("--prompt", default="collect plant observations with dual-arm wrist cameras")
    parser.add_argument("--advantage", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--policy-host", default="127.0.0.1")
    parser.add_argument("--policy-port", type=int, default=8000)
    parser.add_argument("--policy-connect-timeout-s", type=float, default=3.0)
    parser.add_argument("--robot-host", default="192.168.25.1")
    parser.add_argument("--left-port", type=int, default=50071)
    parser.add_argument("--right-port", type=int, default=50072)
    parser.add_argument("--backend", default="grpc")
    parser.add_argument(
        "--active-sides",
        default="left,right",
        help="Comma-separated sides to actually acquire/switch/move. Inactive sides are read-only for pose context.",
    )
    parser.add_argument("--controller", choices=["servo", "planning"], default="servo")
    parser.add_argument(
        "--servo-blocking",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Wait for each servo target to finish. Model inference defaults to non-blocking commands.",
    )
    parser.add_argument("--chunk-start-index", type=int, default=0)
    parser.add_argument("--chunk-steps", type=int, default=DEFAULT_CHUNK_STEPS)
    parser.add_argument(
        "--stream-action-chunk",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Send at most one non-blocking servo target per side for each selected action row (default: enabled).",
    )
    parser.add_argument(
        "--action-step-interval-s",
        type=float,
        default=0.0,
        help="Minimum start-to-start interval between selected action rows; 0 disables pacing.",
    )
    parser.add_argument(
        "--max-step-translation-m",
        type=float,
        default=0.005,
        help="Maximum commanded TCP translation per interpolated substep.",
    )
    parser.add_argument(
        "--max-step-rotation-rad",
        type=float,
        default=0.02,
        help="Maximum commanded TCP rotation per interpolated substep.",
    )
    parser.add_argument(
        "--max-measured-translation-m",
        type=float,
        default=0.03,
        help="Maximum measured TCP substep before stopping; 0 records readback without a hard stop.",
    )
    parser.add_argument("--target-translation-tolerance-m", type=float, default=0.001)
    parser.add_argument("--target-rotation-tolerance-rad", type=float, default=0.005)
    parser.add_argument("--max-interpolation-substeps", type=int, default=64)
    parser.add_argument("--max-envelope-m", type=float, default=0.05)
    parser.add_argument("--arm-speed-rad-s", type=float, default=0.55)
    parser.add_argument("--eff", default="8,8,8,8,8,8,8")
    parser.add_argument("--motion-timeout-ms", type=int, default=30000)
    parser.add_argument(
        "--cleanup-timeout-ms",
        type=int,
        default=3000,
        help="Per-arm timeout used only while returning controllers to idle during shutdown.",
    )
    parser.add_argument(
        "--min-motion-command-interval-s",
        type=float,
        default=MIN_MOTION_COMMAND_INTERVAL_S,
        help="Minimum aggregate interval between motion gRPC command starts; must be at least 0.004s.",
    )
    parser.add_argument("--lease-ms", type=int, default=120000)
    parser.add_argument("--settle-s", type=float, default=0.05)
    parser.add_argument("--enable-gripper", action="store_true", help="Execute gripper targets through move_eef().")
    parser.add_argument("--eef-speed-mm-s", type=float, default=100.0)
    parser.add_argument("--eef-effort", type=float, default=5.0)
    parser.add_argument("--eef-timeout-ms", type=int, default=3000)
    parser.add_argument("--eef-min-mm", type=float, default=0.0)
    parser.add_argument("--eef-max-mm", type=float, default=95.0)
    parser.add_argument("--gripper-blocking", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--force-gripper-sides",
        default="left,right",
        help="Comma-separated sides whose gripper target may be overridden by force-gripper timing.",
    )
    parser.add_argument("--force-gripper-close-after-s", type=float, default=0.0)
    parser.add_argument("--force-gripper-close-mm", type=float, default=0.0)
    parser.add_argument("--force-gripper-open-after-s", type=float, default=0.0)
    parser.add_argument("--force-gripper-open-mm", type=float, default=95.0)
    parser.add_argument("--capture-timeout-s", type=float, default=10.0)
    parser.add_argument("--camera-qos-reliability", choices=["best_effort", "reliable"], default="best_effort")
    parser.add_argument(
        "--wrist-only",
        action="store_true",
        help="Use only left/right wrist cameras for capture and policy requests.",
    )
    parser.add_argument(
        "--capture-mode",
        choices=["ros2", "subprocess", "latest-file"],
        default="ros2",
        help="ros2: subscribe in this process and pass RGB to policy from memory. Other values are retired.",
    )
    parser.add_argument(
        "--latest-obs-npz",
        type=Path,
        default=Path("/tmp/openpi_cam_daemon/latest.npz"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--latest-obs-meta",
        type=Path,
        default=Path("/tmp/openpi_cam_daemon/latest.json"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--latest-obs-max-age-s",
        type=float,
        default=2.0,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--base-0-rgb-topic", default="/robot/camera/head/left/image")
    parser.add_argument("--left-wrist-0-rgb-topic", default="/robot/camera/left_wrist/left/image")
    parser.add_argument("--right-wrist-0-rgb-topic", default="/robot/camera/right_wrist/left/image")
    parser.add_argument("--state-dim", type=int, default=16)
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/openpi_p7_persistent_loop"))
    parser.add_argument("--ros-python", default="/usr/bin/python3", help=argparse.SUPPRESS)
    parser.add_argument("--openpi-python", default="uv run python", help=argparse.SUPPRESS)
    parser.add_argument(
        "--show-policy-input",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show persistent OpenCV windows with the final 224x224 left/right policy input images.",
    )
    parser.add_argument(
        "--policy-input-preview-python",
        default="/usr/bin/python3",
        help="Python with a GUI-enabled cv2 build used by the policy input preview process.",
    )
    parser.add_argument("--ros-domain-id", default="0")
    parser.add_argument("--rmw-implementation", default="rmw_fastrtps_cpp")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-robot-motion", action="store_true")
    return parser.parse_args()


def parse_eff(value: str) -> list[float]:
    out = [float(item.strip()) for item in value.split(",") if item.strip()]
    if len(out) != 7:
        raise ValueError(f"--eff must contain 7 floats, got {len(out)}")
    if not all(math.isfinite(v) for v in out):
        raise ValueError("--eff contains non-finite values")
    return out


def distance(a: np.ndarray | tuple[float, ...], b: np.ndarray | tuple[float, ...]) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b, strict=True)))


def object_field(value: object, field: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def parse_side_set(value: str) -> set[str]:
    sides = {item.strip() for item in value.split(",") if item.strip()}
    unknown = sides - set(SIDES)
    if unknown:
        raise ValueError(f"unknown side(s): {sorted(unknown)}")
    return sides


def state_ok_for_motion(state: object) -> bool:
    return (
        bool(getattr(state, "service_state", False))
        and bool(getattr(state, "valid", False))
        and str(getattr(state, "fsm_state", "")) == "IDLE"
        and str(getattr(state, "controller_state", "")) == "idle"
    )


def read_pose(client: AirbotClient, side: str) -> relpose.TcpPose:
    pose = client.get_end_pose()
    if pose is None:
        raise RuntimeError(f"{side}: get_end_pose() returned None")
    return relpose.TcpPose(position=np.asarray(pose.position), quaternion_xyzw=np.asarray(pose.orientation))


def run_in_threads(tasks: dict[str, Callable[[], object]]) -> dict[str, object]:
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    def runner(name: str, fn: Callable[[], object]) -> None:
        try:
            results[name] = fn()
        except BaseException as exc:
            errors[name] = exc

    threads = [threading.Thread(target=runner, args=(name, fn), daemon=True) for name, fn in tasks.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        detail = "; ".join(f"{name}: {exc!r}" for name, exc in errors.items())
        raise RuntimeError(detail)
    return results


def clamp_gripper_mm(target: relpose.ArmTcpTarget, *, min_mm: float, max_mm: float) -> float:
    return min(max(float(target.gripper.p7_mm), min_mm), max_mm)


def gripper_target_from_p7_mm(mm: float, *, args: argparse.Namespace) -> relpose.GripperTarget:
    target_mm = min(max(float(mm), float(args.eef_min_mm)), float(args.eef_max_mm))
    ratio = 0.0 if args.eef_max_mm <= 0 else target_mm / float(args.eef_max_mm)
    return relpose.GripperTarget(
        model_0_100=100.0 * ratio,
        ratio_0_1=ratio,
        g2p_m=target_mm / 1000.0,
        p7_mm=target_mm,
    )


def forced_gripper_target(elapsed_s: float, args: argparse.Namespace) -> relpose.GripperTarget | None:
    if args.force_gripper_open_after_s > 0 and elapsed_s >= args.force_gripper_open_after_s:
        return gripper_target_from_p7_mm(args.force_gripper_open_mm, args=args)
    if args.force_gripper_close_after_s > 0 and elapsed_s >= args.force_gripper_close_after_s:
        return gripper_target_from_p7_mm(args.force_gripper_close_mm, args=args)
    return None


def prepare_gripper_control(client: AirbotClient, side: str, args: argparse.Namespace) -> int:
    mode = client.get_eef_mode()
    print(f"{side} eef_mode_before {mode}", flush=True)
    if mode is None:
        raise RuntimeError(f"{side}: get_eef_mode() returned None")
    has_eef = object_field(mode, "has_eef", True)
    if has_eef is False:
        raise RuntimeError(f"{side}: SDK reports no EEF")

    state = client.get_eef_joint_state()
    print(f"{side} eef_joint_state_before {state}", flush=True)
    if state is None:
        raise RuntimeError(f"{side}: get_eef_joint_state() returned None")
    eef_pos = object_field(state, "eef_pos", None)
    if eef_pos is None:
        raise RuntimeError(f"{side}: EEF joint state has no eef_pos field")
    eef_dof = len(eef_pos)
    if eef_dof <= 0:
        raise RuntimeError(f"{side}: EEF DOF must be positive, got {eef_dof}")

    ok = client.switch_eef_control_mode(EEFControlMode.csp, timeout_ms=args.eef_timeout_ms)
    print(f"{side} switch_eef_csp {ok}", flush=True)
    if not ok:
        raise RuntimeError(f"{side}: switch_eef_control_mode(csp) returned False")
    ok = client.set_eef_speed(float(args.eef_speed_mm_s))
    print(f"{side} set_eef_speed {ok}", flush=True)
    if not ok:
        raise RuntimeError(f"{side}: set_eef_speed returned False")
    return eef_dof


def move_gripper(
    client: AirbotClient,
    side: str,
    target: relpose.ArmTcpTarget,
    *,
    eef_dof: int,
    args: argparse.Namespace,
    rate_limiter: MotionCommandRateLimiter,
) -> bool:
    target_mm = clamp_gripper_mm(target, min_mm=args.eef_min_mm, max_mm=args.eef_max_mm)
    pos = [target_mm] * eef_dof
    options = EEFMoveOptions(eff=[float(args.eef_effort)] * eef_dof, blocking=bool(args.gripper_blocking))
    ok = rate_limiter.call(
        lambda: client.move_eef(pos=pos, options=options, timeout_ms=args.eef_timeout_ms)
    )
    print(
        f"{side} move_eef pos_mm={pos} model_0_100={target.gripper.model_0_100:.3f} "
        f"raw_p7_mm={target.gripper.p7_mm:.3f} ok={ok}",
        flush=True,
    )
    if not ok:
        raise RuntimeError(f"{side}: move_eef returned False")
    return ok


def make_sdk_pose(target: relpose.ArmTcpTarget) -> CartesianPose:
    return CartesianPose(
        position=tuple(float(v) for v in target.pose.position),
        orientation=tuple(float(v) for v in target.pose.quaternion_xyzw),
    )


def move_servo(
    client: AirbotClient,
    side: str,
    target: relpose.ArmTcpTarget,
    options: CartesianMoveOptions,
    timeout_ms: int,
    rate_limiter: MotionCommandRateLimiter,
) -> bool:
    ok = rate_limiter.call(
        lambda: client.move_end_pose(make_sdk_pose(target), options, timeout_ms=timeout_ms)
    )
    print(f"{side} move_end_pose ok={ok}", flush=True)
    return bool(ok)


def move_planning(
    client: AirbotClient,
    side: str,
    start: relpose.TcpPose,
    target: relpose.ArmTcpTarget,
    options: CartesianMoveOptions,
    timeout_ms: int,
    rate_limiter: MotionCommandRateLimiter,
) -> bool:
    start_pose = CartesianPose(
        position=tuple(float(v) for v in start.position),
        orientation=tuple(float(v) for v in start.quaternion_xyzw),
    )
    ok = rate_limiter.call(
        lambda: client.move_end_pose_linear(
            start=start_pose,
            target=make_sdk_pose(target),
            options=options,
            timeout_ms=timeout_ms,
        )
    )
    print(f"{side} move_end_pose_linear ok={ok}", flush=True)
    return bool(ok)


def validate_target(
    side: str,
    reference: relpose.TcpPose,
    initial: relpose.TcpPose,
    target: relpose.ArmTcpTarget,
    args: argparse.Namespace,
) -> None:
    policy_translation = distance(reference.position, target.pose.position)
    policy_rotation = relpose.quat_angular_distance_xyzw(reference.quaternion_xyzw, target.pose.quaternion_xyzw)
    envelope = distance(initial.position, target.pose.position)
    delta = target.pose.position - reference.position
    waypoints = relpose.interpolate_tcp_poses(
        reference,
        target.pose,
        max_translation_m=args.max_step_translation_m,
        max_rotation_rad=args.max_step_rotation_rad,
    )
    print(
        f"{side} target_delta_m=({delta[0]:.6f},{delta[1]:.6f},{delta[2]:.6f}) "
        f"policy_translation_m={policy_translation:.6f} policy_rotation_rad={policy_rotation:.6f} "
        f"interpolation_substeps={len(waypoints)} envelope_m={envelope:.6f} "
        f"gripper_model={target.gripper.model_0_100:.3f} gripper_p7_mm={target.gripper.p7_mm:.3f}",
        flush=True,
    )
    if args.max_envelope_m > 0 and envelope > args.max_envelope_m:
        raise UnsafeMotionError(
            f"{side}: target envelope {envelope:.6f} exceeds limit {args.max_envelope_m:.6f}"
        )


def execute_interpolated_motion(
    clients: dict[str, AirbotClient],
    final_targets: dict[str, relpose.ArmTcpTarget],
    *,
    efforts: list[float],
    args: argparse.Namespace,
    rate_limiter: MotionCommandRateLimiter,
) -> tuple[dict[str, relpose.TcpPose], list[dict[str, object]]]:
    """Execute adaptive waypoints computed from fresh TCP readback before every command."""

    records: list[dict[str, object]] = []
    completed_sides: set[str] = set()
    for substep_index in range(1, int(args.max_interpolation_substeps) + 2):
        starts: dict[str, relpose.TcpPose] = {}
        command_targets: dict[str, relpose.ArmTcpTarget] = {}
        command_meta: dict[str, dict[str, object]] = {}
        for side in sorted(args.active_side_set):
            if side in completed_sides:
                continue
            start = read_pose(clients[side], side)
            starts[side] = start
            final_pose = final_targets[side].pose
            remaining_translation = distance(start.position, final_pose.position)
            remaining_rotation = relpose.quat_angular_distance_xyzw(
                start.quaternion_xyzw,
                final_pose.quaternion_xyzw,
            )
            if (
                remaining_translation <= args.target_translation_tolerance_m
                and remaining_rotation <= args.target_rotation_tolerance_rad
            ):
                continue
            if substep_index > args.max_interpolation_substeps:
                raise UnsafeMotionError(
                    f"interpolation did not converge after {args.max_interpolation_substeps} substeps"
                )
            waypoints = relpose.interpolate_tcp_poses(
                start,
                final_pose,
                max_translation_m=args.max_step_translation_m,
                max_rotation_rad=args.max_step_rotation_rad,
            )
            waypoint_pose = waypoints[0]
            command_translation = distance(start.position, waypoint_pose.position)
            command_rotation = relpose.quat_angular_distance_xyzw(
                start.quaternion_xyzw,
                waypoint_pose.quaternion_xyzw,
            )
            if command_translation > args.max_step_translation_m + 1e-9:
                raise UnsafeMotionError(
                    f"{side}: interpolated command {command_translation:.6f}m exceeds "
                    f"{args.max_step_translation_m:.6f}m"
                )
            if command_rotation > args.max_step_rotation_rad + 1e-9:
                raise UnsafeMotionError(
                    f"{side}: interpolated rotation {command_rotation:.6f}rad exceeds "
                    f"{args.max_step_rotation_rad:.6f}rad"
                )
            command_targets[side] = dataclasses.replace(final_targets[side], pose=waypoint_pose)
            command_meta[side] = {
                "remaining_translation_before_m": remaining_translation,
                "remaining_rotation_before_rad": remaining_rotation,
                "command_translation_m": command_translation,
                "command_rotation_rad": command_rotation,
                "planned_remaining_substeps": len(waypoints),
                "final_waypoint": len(waypoints) == 1,
                "start_xyz": start.position.tolist(),
                "command_xyz": waypoint_pose.position.tolist(),
            }
            print(
                f"{side} interpolation_substep={substep_index} "
                f"command_translation_m={command_translation:.6f} "
                f"command_rotation_rad={command_rotation:.6f} "
                f"remaining_translation_m={remaining_translation:.6f} "
                f"planned_remaining_substeps={len(waypoints)}",
                flush=True,
            )

        if not command_targets:
            measured = {side: read_pose(client, side) for side, client in clients.items()}
            return measured, records

        if args.controller == "servo":
            options = CartesianMoveOptions(
                eff=efforts,
                motion_type="lin",
                blocking=bool(args.servo_blocking),
            )
            results = run_in_threads(
                {
                    side: (
                        lambda side=side, client=clients[side], target=target: move_servo(
                            client,
                            side,
                            target,
                            options,
                            args.motion_timeout_ms,
                            rate_limiter,
                        )
                    )
                    for side, target in command_targets.items()
                }
            )
        else:
            options = CartesianMoveOptions(
                eff=efforts,
                motion_type="lin",
                velocity_scaling_factor=0.1,
                acceleration_scaling_factor=0.1,
                allow_planning_time=5.0,
                blocking=True,
            )
            results = run_in_threads(
                {
                    side: (
                        lambda side=side, client=clients[side], start=starts[side], target=target: move_planning(
                            client,
                            side,
                            start,
                            target,
                            options,
                            args.motion_timeout_ms,
                            rate_limiter,
                        )
                    )
                    for side, target in command_targets.items()
                }
            )

        time.sleep(args.settle_s)
        measured_after = {side: read_pose(clients[side], side) for side in command_targets}
        for side in sorted(command_targets):
            measured_translation = distance(starts[side].position, measured_after[side].position)
            target_error = distance(measured_after[side].position, final_targets[side].pose.position)
            record = {
                "substep": substep_index,
                "side": side,
                **command_meta[side],
                "command_ok": bool(results[side]),
                "measured_xyz": measured_after[side].position.tolist(),
                "measured_translation_m": measured_translation,
                "final_target_error_m": target_error,
                "service_state_after": repr(clients[side].get_service_state()),
            }
            records.append(record)
            print(
                f"{side} interpolation_readback={substep_index} "
                f"measured_translation_m={measured_translation:.6f} "
                f"final_target_error_m={target_error:.6f} command_ok={bool(results[side])}",
                flush=True,
            )
            if (
                args.max_measured_translation_m > 0
                and measured_translation > args.max_measured_translation_m + 1e-9
            ):
                raise UnsafeMotionError(
                    f"{side}: measured substep {measured_translation:.6f}m exceeds hard limit "
                    f"{args.max_measured_translation_m:.6f}m"
                )
        failed = [side for side, ok in results.items() if not ok]
        if failed:
            raise RuntimeError(f"move_end_pose returned False for side(s): {failed}")
        for side in command_targets:
            if bool(command_meta[side]["final_waypoint"]):
                completed_sides.add(side)
                print(f"{side} interpolation_final_waypoint_complete", flush=True)


    raise AssertionError("unreachable interpolation loop")


def execute_stream_action_step(
    clients: dict[str, AirbotClient],
    reference_poses: dict[str, relpose.TcpPose],
    final_targets: dict[str, relpose.ArmTcpTarget],
    *,
    efforts: list[float],
    args: argparse.Namespace,
    rate_limiter: MotionCommandRateLimiter,
) -> tuple[dict[str, relpose.TcpPose], list[dict[str, object]]]:
    """Send one bounded, non-blocking servo target per active side without readback."""

    command_targets: dict[str, relpose.ArmTcpTarget] = {}
    records: list[dict[str, object]] = []
    updated_references = dict(reference_poses)
    for side in sorted(args.active_side_set):
        start = reference_poses[side]
        final_target = final_targets[side]
        remaining_translation = distance(start.position, final_target.pose.position)
        remaining_rotation = relpose.quat_angular_distance_xyzw(
            start.quaternion_xyzw,
            final_target.pose.quaternion_xyzw,
        )
        if (
            remaining_translation <= args.target_translation_tolerance_m
            and remaining_rotation <= args.target_rotation_tolerance_rad
        ):
            records.append(
                {
                    "side": side,
                    "command_skipped": True,
                    "remaining_translation_before_m": remaining_translation,
                    "remaining_rotation_before_rad": remaining_rotation,
                }
            )
            continue

        waypoint = relpose.interpolate_tcp_poses(
            start,
            final_target.pose,
            max_translation_m=args.max_step_translation_m,
            max_rotation_rad=args.max_step_rotation_rad,
        )[0]
        command_translation = distance(start.position, waypoint.position)
        command_rotation = relpose.quat_angular_distance_xyzw(start.quaternion_xyzw, waypoint.quaternion_xyzw)
        if command_translation > args.max_step_translation_m + 1e-9:
            raise UnsafeMotionError(
                f"{side}: streamed command {command_translation:.6f}m exceeds "
                f"{args.max_step_translation_m:.6f}m"
            )
        if command_rotation > args.max_step_rotation_rad + 1e-9:
            raise UnsafeMotionError(
                f"{side}: streamed rotation {command_rotation:.6f}rad exceeds "
                f"{args.max_step_rotation_rad:.6f}rad"
            )
        command_target = dataclasses.replace(final_target, pose=waypoint)
        command_targets[side] = command_target
        updated_references[side] = waypoint
        records.append(
            {
                "side": side,
                "command_skipped": False,
                "remaining_translation_before_m": remaining_translation,
                "remaining_rotation_before_rad": remaining_rotation,
                "command_translation_m": command_translation,
                "command_rotation_rad": command_rotation,
                "start_xyz": start.position.tolist(),
                "final_target_xyz": final_target.pose.position.tolist(),
                "command_xyz": waypoint.position.tolist(),
            }
        )
        print(
            f"{side} stream_command_translation_m={command_translation:.6f} "
            f"stream_command_rotation_rad={command_rotation:.6f} "
            f"remaining_translation_m={remaining_translation:.6f}",
            flush=True,
        )

    options = CartesianMoveOptions(eff=efforts, motion_type="lin", blocking=False)
    results = run_in_threads(
        {
            side: (
                lambda side=side, client=clients[side], target=target: move_servo(
                    client,
                    side,
                    target,
                    options,
                    args.motion_timeout_ms,
                    rate_limiter,
                )
            )
            for side, target in command_targets.items()
        }
    )
    failed = [side for side, ok in results.items() if not ok]
    if failed:
        raise RuntimeError(f"move_end_pose returned False for side(s): {failed}")
    for record in records:
        side = str(record["side"])
        record["command_ok"] = None if record["command_skipped"] else bool(results[side])
    return updated_references, records


def write_policy_input_preview(path: Path, images: dict[str, np.ndarray], image_tools: object) -> None:
    resized = {key: image_tools.resize_with_pad(image, 224, 224) for key, image in images.items()}
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("wb") as file:
        np.savez_compressed(file, **resized)
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp, path)


def request_policy(policy: object, args: argparse.Namespace, images: dict[str, np.ndarray]) -> tuple[np.ndarray, float]:
    observation = {
        "state": np.zeros(args.state_dim, dtype=np.float32),
        "prompt": args.prompt,
        "advantage": bool(args.advantage),
        **images,
    }
    started = time.perf_counter()
    response = policy.infer(observation)
    infer_ms = (time.perf_counter() - started) * 1000.0
    if "actions" not in response:
        raise RuntimeError(f"policy response is missing actions: keys={sorted(response)}")
    return np.asarray(response["actions"], dtype=np.float64), infer_ms


def selected_action_indices(actions: np.ndarray, args: argparse.Namespace) -> list[int]:
    if actions.ndim == 1:
        count = 1
    elif actions.ndim == 2:
        count = int(actions.shape[0])
    else:
        raise RuntimeError(f"actions must be 1D or 2D, got shape={actions.shape}")
    start = int(args.chunk_start_index)
    stop = min(start + int(args.chunk_steps), count)
    if start < 0 or stop <= start:
        raise RuntimeError(f"invalid chunk range start={start} stop={stop} action_count={count}")
    return list(range(start, stop))


def should_continue(iteration: int, start_time: float, args: argparse.Namespace) -> bool:
    if args.iterations > 0 and iteration >= args.iterations:
        return False
    if args.duration_s > 0 and time.monotonic() - start_time >= args.duration_s:
        return False
    return True


def validate_args(args: argparse.Namespace) -> None:
    if args.capture_mode != "ros2":
        raise RuntimeError(
            f"--capture-mode {args.capture_mode} is retired; use --capture-mode ros2 and do not run the camera daemon"
        )
    if args.execute and not args.allow_robot_motion:
        raise RuntimeError("--execute requires --allow-robot-motion")
    if args.iterations < 0 or args.duration_s < 0 or args.period_s < 0:
        raise RuntimeError("--iterations, --duration-s, and --period-s must be non-negative")
    if args.iterations == 0 and args.duration_s == 0:
        args.iterations = 1
    if args.chunk_steps <= 0 or args.chunk_start_index < 0:
        raise RuntimeError("--chunk-steps must be positive and --chunk-start-index must be non-negative")
    if args.action_step_interval_s < 0:
        raise RuntimeError("--action-step-interval-s must be non-negative")
    if args.max_step_translation_m <= 0 or args.max_step_rotation_rad <= 0:
        raise RuntimeError("interpolated translation and rotation limits must be positive")
    if args.max_measured_translation_m < 0:
        raise RuntimeError("--max-measured-translation-m must be non-negative")
    if 0 < args.max_measured_translation_m <= args.max_step_translation_m:
        raise RuntimeError("--max-measured-translation-m must be 0 or greater than --max-step-translation-m")
    if args.max_envelope_m < 0:
        raise RuntimeError("--max-envelope-m must be non-negative")
    if args.target_translation_tolerance_m < 0 or args.target_rotation_tolerance_rad < 0:
        raise RuntimeError("target convergence tolerances must be non-negative")
    if args.target_translation_tolerance_m >= args.max_step_translation_m:
        raise RuntimeError("translation tolerance must be smaller than the interpolated translation limit")
    if args.target_rotation_tolerance_rad >= args.max_step_rotation_rad:
        raise RuntimeError("rotation tolerance must be smaller than the interpolated rotation limit")
    if args.max_interpolation_substeps <= 0:
        raise RuntimeError("--max-interpolation-substeps must be positive")
    if args.min_motion_command_interval_s < MIN_MOTION_COMMAND_INTERVAL_S:
        raise RuntimeError(
            "--min-motion-command-interval-s must be at least "
            f"{MIN_MOTION_COMMAND_INTERVAL_S:.3f}s"
        )
    if args.cleanup_timeout_ms <= 0:
        raise RuntimeError("--cleanup-timeout-ms must be positive")
    if args.stream_action_chunk:
        if args.controller != "servo":
            raise RuntimeError("--stream-action-chunk requires --controller servo")
        if args.servo_blocking:
            raise RuntimeError("--stream-action-chunk requires --no-servo-blocking")
        if args.enable_gripper and args.gripper_blocking:
            raise RuntimeError("--stream-action-chunk with gripper requires --no-gripper-blocking")
    args.active_side_set = parse_side_set(args.active_sides)
    if not args.active_side_set:
        raise RuntimeError("--active-sides must include at least one side")
    args.force_gripper_side_set = parse_side_set(args.force_gripper_sides)
    args.force_gripper_side_set &= args.active_side_set
    force_gripper_enabled = args.force_gripper_close_after_s > 0 or args.force_gripper_open_after_s > 0
    if any(
        value < 0
        for value in (
            args.force_gripper_close_after_s,
            args.force_gripper_open_after_s,
            args.force_gripper_close_mm,
            args.force_gripper_open_mm,
        )
    ):
        raise RuntimeError("force-gripper timing and mm values must be non-negative")
    if force_gripper_enabled and not args.enable_gripper:
        raise RuntimeError("force-gripper options require --enable-gripper")
    if force_gripper_enabled and not args.force_gripper_side_set:
        raise RuntimeError("force-gripper requires at least one side")
    if args.force_gripper_open_after_s > 0 and args.force_gripper_close_after_s > 0:
        if args.force_gripper_open_after_s <= args.force_gripper_close_after_s:
            raise RuntimeError("--force-gripper-open-after-s must be greater than close-after when both are set")
    if args.enable_gripper:
        if args.eef_min_mm < 0 or args.eef_max_mm <= args.eef_min_mm:
            raise RuntimeError("--eef-min-mm/--eef-max-mm must define a non-negative increasing range")
        if args.eef_speed_mm_s <= 0 or args.eef_effort <= 0:
            raise RuntimeError("--eef-speed-mm-s and --eef-effort must be positive")


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
        efforts = parse_eff(args.eff)
    except Exception as exc:
        print(f"REFUSE: {exc}", file=sys.stderr, flush=True)
        return 2
    args.work_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d_%H%M%S")
    summary_path = args.work_dir / f"summary_{run_id}.jsonl"
    preview_path = args.work_dir / "policy_input_preview.npz"
    motion_rate_limiter = MotionCommandRateLimiter(args.min_motion_command_interval_s)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "execute": args.execute,
                "controller": args.controller,
                "servo_blocking": args.servo_blocking,
                "policy": f"{args.policy_host}:{args.policy_port}",
                "robot_host": args.robot_host,
                "iterations": args.iterations,
                "duration_s": args.duration_s,
                "period_s": args.period_s,
                "camera_qos_reliability": args.camera_qos_reliability,
                "chunk_steps": args.chunk_steps,
                "stream_action_chunk": args.stream_action_chunk,
                "action_step_interval_s": args.action_step_interval_s,
                "max_step_translation_m": args.max_step_translation_m,
                "max_step_rotation_rad": args.max_step_rotation_rad,
                "max_measured_translation_m": args.max_measured_translation_m,
                "target_translation_tolerance_m": args.target_translation_tolerance_m,
                "target_rotation_tolerance_rad": args.target_rotation_tolerance_rad,
                "max_interpolation_substeps": args.max_interpolation_substeps,
                "max_envelope_m": args.max_envelope_m,
                "arm_speed_rad_s": args.arm_speed_rad_s,
                "min_motion_command_interval_s": args.min_motion_command_interval_s,
                "active_sides": sorted(args.active_side_set),
                "enable_gripper": args.enable_gripper,
                "force_gripper_sides": sorted(args.force_gripper_side_set),
                "force_gripper_close_after_s": args.force_gripper_close_after_s,
                "force_gripper_close_mm": args.force_gripper_close_mm,
                "force_gripper_open_after_s": args.force_gripper_open_after_s,
                "force_gripper_open_mm": args.force_gripper_open_mm,
                "show_policy_input": args.show_policy_input,
                "summary": str(summary_path),
            },
            indent=2,
            ensure_ascii=False,
        ),
        flush=True,
    )

    clients: dict[str, AirbotClient] = {}
    acquired: set[str] = set()
    switched: set[str] = set()
    eef_switched: set[str] = set()
    eef_dofs: dict[str, int] = {}
    preview_process: subprocess.Popen | None = None
    camera_node: object | None = None
    rclpy_module: object | None = None
    exit_code = 0

    def handle_termination(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_termination)

    supervisor_pid = os.environ.get("OPENPI_P7_SUPERVISOR_PID")
    configure_parent_death_signal(None if supervisor_pid is None else int(supervisor_pid))
    try:
        os.environ["ROS_DOMAIN_ID"] = str(args.ros_domain_id)
        os.environ["RMW_IMPLEMENTATION"] = str(args.rmw_implementation)
        import rclpy  # noqa: I001
        from capture_ros2_openpi_observation import CaptureNode
        from capture_ros2_openpi_observation import capture_fresh_rgb
        from openpi_client import image_tools
        from openpi_client import websocket_client_policy

        rclpy_module = rclpy
        camera_keys = (
            ("left_wrist_0_rgb", "right_wrist_0_rgb")
            if args.wrist_only
            else ("base_0_rgb", "left_wrist_0_rgb", "right_wrist_0_rgb")
        )
        camera_topics = {
            "base_0_rgb": args.base_0_rgb_topic,
            "left_wrist_0_rgb": args.left_wrist_0_rgb_topic,
            "right_wrist_0_rgb": args.right_wrist_0_rgb_topic,
        }
        rclpy.init()
        camera_node = CaptureNode(
            {key: camera_topics[key] for key in camera_keys},
            qos_reliability=args.camera_qos_reliability,
        )
        print(f"[persistent-loop] in-process ROS2 cameras={camera_node.topics}", flush=True)
        print("[persistent-loop] waiting for initial fresh camera frames before robot control", flush=True)
        initial_images, initial_observation_metadata, camera_counts = capture_fresh_rgb(
            camera_node,
            camera_keys,
            timeout_s=args.capture_timeout_s,
        )
        policy = websocket_client_policy.WebsocketClientPolicy(host=args.policy_host, port=args.policy_port)

        if args.show_policy_input:
            preview_path.unlink(missing_ok=True)
            preview_cmd = shlex.split(args.policy_input_preview_python) + [
                "examples/airbot/show_openpi_policy_inputs.py",
                "--input",
                str(preview_path),
            ]
            print("$ " + shlex.join(preview_cmd), flush=True)
            preview_process = subprocess.Popen(preview_cmd, cwd=REPO_ROOT)
            time.sleep(0.25)
            if preview_process.poll() is not None:
                raise RuntimeError(
                    f"policy input preview exited during startup rc={preview_process.returncode}; "
                    "use --no-show-policy-input only when running without a desktop display"
                )
            write_policy_input_preview(preview_path, initial_images, image_tools)

        print("[persistent-loop] initial policy inference before robot control", flush=True)
        initial_actions, initial_infer_ms = request_policy(policy, args, initial_images)
        print(
            f"[persistent-loop] initial policy action_shape={list(initial_actions.shape)} "
            f"infer_ms={initial_infer_ms:.2f}",
            flush=True,
        )

        clients = {
            "left": AirbotClient(host=args.robot_host, port=args.left_port, backend=args.backend),
            "right": AirbotClient(host=args.robot_host, port=args.right_port, backend=args.backend),
        }
        for side, client in clients.items():
            state = client.get_service_state()
            print(f"{side} state_before {state}", flush=True)
            if side in args.active_side_set and not state_ok_for_motion(state):
                raise RuntimeError(f"{side}: not IDLE/idle/valid")

        initial_pose = {side: read_pose(client, side) for side, client in clients.items()}
        for side in SIDES:
            print(
                f"{side} initial_xyz={initial_pose[side].position.tolist()} "
                f"initial_xyzw={initial_pose[side].quaternion_xyzw.tolist()}",
                flush=True,
            )

        if args.execute:
            for side in SIDES:
                if side not in args.active_side_set:
                    continue
                client = clients[side]
                ok = client.acquire_control(lease_ms=args.lease_ms, renew_period_s=5.0)
                if not ok:
                    print(f"{side} acquire_control {ok}", flush=True)
                    raise RuntimeError(f"{side}: acquire_control returned False")
                acquired.add(side)
                print(f"{side} acquire_control {ok}", flush=True)

            controller = Controller.servo_control if args.controller == "servo" else Controller.planning_control
            for side in SIDES:
                if side not in args.active_side_set:
                    continue
                client = clients[side]
                ok = client.switch_controller(controller, timeout_ms=args.motion_timeout_ms)
                if not ok:
                    print(f"{side} switch_{args.controller} {ok}", flush=True)
                    raise RuntimeError(f"{side}: switch_controller({args.controller}) returned False")
                switched.add(side)
                print(f"{side} switch_{args.controller} {ok}", flush=True)
            if args.controller == "servo":
                for side in SIDES:
                    if side not in args.active_side_set:
                        continue
                    client = clients[side]
                    ok = client.set_arm_speed([float(args.arm_speed_rad_s)] * 7)
                    print(f"{side} set_arm_speed {ok}", flush=True)
                    if not ok:
                        raise RuntimeError(f"{side}: set_arm_speed returned False")
            if args.enable_gripper:
                for side in SIDES:
                    if side not in args.active_side_set:
                        continue
                    client = clients[side]
                    # Cleanup is idempotent; register before setup in case setup raises after switching EEF mode.
                    eef_switched.add(side)
                    eef_dofs[side] = prepare_gripper_control(client, side, args)

        iteration = 0
        pending_observation = (
            initial_actions,
            initial_infer_ms,
            initial_observation_metadata,
        )
        start_time = time.monotonic()
        while should_continue(iteration, start_time, args):
            iteration += 1
            iteration_start = time.monotonic()
            if pending_observation is not None:
                actions, infer_ms, observation_metadata = pending_observation
                pending_observation = None
            else:
                print(f"[persistent-loop] iteration={iteration} capture", flush=True)
                images, observation_metadata, camera_counts = capture_fresh_rgb(
                    camera_node,
                    camera_keys,
                    timeout_s=args.capture_timeout_s,
                    previous_counts=camera_counts,
                )
                if args.show_policy_input:
                    write_policy_input_preview(preview_path, images, image_tools)
                print(f"[persistent-loop] iteration={iteration} policy", flush=True)
                actions, infer_ms = request_policy(policy, args, images)
            indices = selected_action_indices(actions, args)
            observation_pose = {side: read_pose(client, side) for side, client in clients.items()}
            reference_pose = dict(observation_pose)
            print(
                f"[persistent-loop] iteration={iteration} action_shape={list(actions.shape)} indices={indices}",
                flush=True,
            )

            previous_action_step_start: float | None = None
            for chunk_position, action_index in enumerate(indices):
                action, _chunk_shape = policy_bridge.select_action_step(actions, action_index=action_index)
                adopted_action_2x7 = np.asarray(action[:14], dtype=np.float64).reshape(2, 7)
                print(
                    f"[persistent-loop] iteration={iteration} chunk_position={chunk_position} "
                    f"action_index={action_index} adopted_action_2x7="
                    f"{json.dumps(adopted_action_2x7.tolist(), separators=(',', ':'))}",
                    flush=True,
                )
                targets = relpose.convert_action_step(action, observation_pose)
                target_map = {"left": targets.left, "right": targets.right}
                forced_gripper = (
                    forced_gripper_target(time.monotonic() - start_time, args) if args.enable_gripper else None
                )
                forced_gripper_sides: set[str] = set()
                if forced_gripper is not None:
                    for side in args.force_gripper_side_set:
                        target_map[side] = dataclasses.replace(target_map[side], gripper=forced_gripper)
                        forced_gripper_sides.add(side)
                    print(
                        f"force_gripper sides={sorted(forced_gripper_sides)} pos_mm={forced_gripper.p7_mm:.3f}",
                        flush=True,
                    )
                for side in args.active_side_set:
                    validate_target(side, reference_pose[side], initial_pose[side], target_map[side], args)
                    if args.enable_gripper:
                        target_mm = clamp_gripper_mm(target_map[side], min_mm=args.eef_min_mm, max_mm=args.eef_max_mm)
                        print(
                            f"{side} gripper_execute_target_mm={target_mm:.3f} "
                            f"clamp_range_mm=[{args.eef_min_mm:.3f},{args.eef_max_mm:.3f}]",
                            flush=True,
                        )

                if previous_action_step_start is not None and args.action_step_interval_s > 0:
                    wait_s = previous_action_step_start + args.action_step_interval_s - time.monotonic()
                    if wait_s > 0:
                        time.sleep(wait_s)
                action_step_start = time.monotonic()
                action_step_gap_s = (
                    None if previous_action_step_start is None else action_step_start - previous_action_step_start
                )
                previous_action_step_start = action_step_start
                print(
                    f"[persistent-loop] iteration={iteration} chunk_position={chunk_position} "
                    f"action_index={action_index} action_step_gap_s={action_step_gap_s}",
                    flush=True,
                )
                interpolation_records: list[dict[str, object]] = []
                if args.execute:
                    if args.stream_action_chunk:
                        reference_pose, interpolation_records = execute_stream_action_step(
                            clients,
                            reference_pose,
                            target_map,
                            efforts=efforts,
                            args=args,
                            rate_limiter=motion_rate_limiter,
                        )
                        measured = None
                    else:
                        measured, interpolation_records = execute_interpolated_motion(
                            clients,
                            target_map,
                            efforts=efforts,
                            args=args,
                            rate_limiter=motion_rate_limiter,
                        )
                    if args.enable_gripper:
                        run_in_threads(
                            {
                                side: (
                                    lambda side=side, client=clients[side], target=target_map[side]: move_gripper(
                                        client,
                                        side,
                                        target,
                                        eef_dof=eef_dofs[side],
                                        args=args,
                                        rate_limiter=motion_rate_limiter,
                                    )
                                )
                                for side in sorted(args.active_side_set)
                            }
                        )
                else:
                    print(
                        "DRY_RUN: no acquire_control(), switch_controller(), move_end_pose(), or move_eef() was called",
                        flush=True,
                    )
                    time.sleep(args.settle_s)
                    measured = {side: read_pose(client, side) for side, client in clients.items()}
                record = {
                    "run_id": run_id,
                    "iteration": iteration,
                    "chunk_position": chunk_position,
                    "action_index": action_index,
                    "action_step_interval_target_s": args.action_step_interval_s,
                    "action_step_gap_s": action_step_gap_s,
                    "adopted_action_2x7": adopted_action_2x7.tolist(),
                    "elapsed_s": time.monotonic() - start_time,
                    "execute": bool(args.execute),
                    "controller": args.controller,
                    "camera_frames": observation_metadata["frames"],
                    "policy_infer_ms": infer_ms,
                    "sides": {},
                    "interpolation_substeps": interpolation_records,
                }
                for side in SIDES:
                    target = target_map[side]
                    measured_pose = None if measured is None else measured[side]
                    err = None if measured_pose is None else distance(measured_pose.position, target.pose.position)
                    moved_from_observation = (
                        None
                        if measured_pose is None
                        else distance(measured_pose.position, observation_pose[side].position)
                    )
                    record["sides"][side] = {
                        "active": side in args.active_side_set,
                        "target_xyz": target.pose.position.tolist(),
                        "measured_xyz": None if measured_pose is None else measured_pose.position.tolist(),
                        "commanded_reference_xyz": reference_pose[side].position.tolist(),
                        "target_error_m": err,
                        "moved_from_observation_m": moved_from_observation,
                        "gripper_model_0_100": target.gripper.model_0_100,
                        "gripper_p7_mm_raw": target.gripper.p7_mm,
                        "gripper_p7_mm_command": clamp_gripper_mm(
                            target, min_mm=args.eef_min_mm, max_mm=args.eef_max_mm
                        ),
                        "gripper_forced": side in forced_gripper_sides,
                    }
                    if measured_pose is not None:
                        print(
                            f"{side} measured_target_error_m={err:.6f} "
                            f"moved_from_observation_m={moved_from_observation:.6f}",
                            flush=True,
                        )
                with summary_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                if args.execute and not args.stream_action_chunk:
                    reference_pose = measured
                elif not args.execute:
                    reference_pose = {side: target_map[side].pose for side in SIDES}

            if args.execute and args.stream_action_chunk:
                chunk_measured = {side: read_pose(client, side) for side, client in clients.items()}
                chunk_record = {
                    "run_id": run_id,
                    "iteration": iteration,
                    "record_type": "stream_chunk_readback",
                    "elapsed_s": time.monotonic() - start_time,
                    "sides": {},
                }
                for side in SIDES:
                    moved = distance(chunk_measured[side].position, observation_pose[side].position)
                    commanded_error = distance(chunk_measured[side].position, reference_pose[side].position)
                    chunk_record["sides"][side] = {
                        "measured_xyz": chunk_measured[side].position.tolist(),
                        "commanded_reference_xyz": reference_pose[side].position.tolist(),
                        "moved_from_observation_m": moved,
                        "commanded_reference_error_m": commanded_error,
                    }
                    print(
                        f"{side} stream_chunk_moved_m={moved:.6f} "
                        f"stream_chunk_commanded_error_m={commanded_error:.6f}",
                        flush=True,
                    )
                with summary_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(chunk_record, ensure_ascii=False) + "\n")

            sleep_s = max(0.0, float(args.period_s) - (time.monotonic() - iteration_start))
            if sleep_s > 0 and should_continue(iteration, start_time, args):
                time.sleep(sleep_s)

        print(f"[persistent-loop] completed iterations={iteration} summary={summary_path}", flush=True)

    except KeyboardInterrupt:
        print("STOP_REQUESTED: SIGTERM received; cleaning up robot control", file=sys.stderr, flush=True)
        exit_code = 130
    except UnsafeMotionError as exc:
        print(f"UNSAFE_MOTION_STOP: {exc}", file=sys.stderr, flush=True)
        exit_code = UNSAFE_MOTION_EXIT_CODE
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        exit_code = 1
    finally:
        if preview_process is not None and preview_process.poll() is None:
            preview_process.terminate()
            try:
                preview_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                preview_process.kill()
                preview_process.wait()
        for side in list(eef_switched):
            try:
                ok = clients[side].switch_eef_control_mode(EEFControlMode.idle, timeout_ms=args.eef_timeout_ms)
                print(f"{side} switch_eef_idle {ok}", flush=True)
            except Exception as exc:
                print(f"{side} switch_eef_idle_exception {exc!r}", file=sys.stderr, flush=True)
        for side in list(switched):
            try:
                ok = clients[side].switch_controller(Controller.idle, timeout_ms=args.cleanup_timeout_ms)
                print(f"{side} switch_idle {ok}", flush=True)
            except Exception as exc:
                print(f"{side} switch_idle_exception {exc!r}", file=sys.stderr, flush=True)
        for side in list(acquired):
            try:
                clients[side].release_control()
                print(f"{side} release_control done", flush=True)
            except Exception as exc:
                print(f"{side} release_control_exception {exc!r}", file=sys.stderr, flush=True)
        for side, client in clients.items():
            try:
                print(f"{side} state_final {client.get_service_state()}", flush=True)
            except Exception as exc:
                print(f"{side} state_final_exception {exc!r}", file=sys.stderr, flush=True)
            client.close()
        if camera_node is not None:
            camera_node.destroy_node()
        if rclpy_module is not None and rclpy_module.ok():
            rclpy_module.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
