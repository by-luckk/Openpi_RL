#!/usr/bin/env python3
"""Keyboard teleoperation for both AIRBOT TCP end-effectors.

Each key press sends one bounded Cartesian increment to the selected arm(s).
The script is dry-run by default. Real motion requires both ``--execute`` and
``--allow-robot-motion``.

Controls (Linux terminal, no Enter required):
  1 / 2 / b       select left / right / both arms
  w / s           world +X / -X
  a / d           world +Y / -Y
  r / f           world +Z / -Z
  i / k           roll + / -
  j / l           pitch + / -
  u / o           yaw + / -
  h               print this help
  q or Ctrl-C     stop and release control

The default increment frame is world. Use ``--frame local`` to interpret the
translation and RPY increments in each TCP's local frame.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import dataclasses
import math
import os
import select
import sys
import termios
import threading
import time
import tty

import numpy as np

SIDES = ("left", "right")
ZERO3 = np.zeros(3, dtype=np.float64)


@dataclasses.dataclass(frozen=True)
class Pose:
    position: np.ndarray
    quaternion_xyzw: np.ndarray


@dataclasses.dataclass(frozen=True)
class Increment:
    translation_m: np.ndarray
    rpy_rad: np.ndarray


def normalize_quaternion(value: np.ndarray | list[float] | tuple[float, ...]) -> np.ndarray:
    quaternion = np.asarray(value, dtype=np.float64)
    if quaternion.shape != (4,):
        raise ValueError(f"quaternion must have shape (4,), got {quaternion.shape}")
    norm = float(np.linalg.norm(quaternion))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise ValueError(f"invalid quaternion {quaternion.tolist()}")
    quaternion = quaternion / norm
    if quaternion[3] < 0.0:
        quaternion = -quaternion
    return quaternion


def quaternion_multiply(first: np.ndarray, second: np.ndarray) -> np.ndarray:
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


def quaternion_from_rpy(rpy_rad: np.ndarray) -> np.ndarray:
    """Return the standard roll-pitch-yaw quaternion in xyzw order."""
    roll, pitch, yaw = (float(value) * 0.5 for value in rpy_rad)
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return normalize_quaternion(
        np.asarray(
            [
                sr * cp * cy - cr * sp * sy,
                cr * sp * cy + sr * cp * sy,
                cr * cp * sy - sr * sp * cy,
                cr * cp * cy + sr * sp * sy,
            ],
            dtype=np.float64,
        )
    )


def quaternion_to_rotation_matrix(quaternion: np.ndarray) -> np.ndarray:
    x, y, z, w = normalize_quaternion(quaternion)
    return np.asarray(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def quaternion_angle(first: np.ndarray, second: np.ndarray) -> float:
    dot = abs(float(np.dot(normalize_quaternion(first), normalize_quaternion(second))))
    return 2.0 * math.acos(min(1.0, max(-1.0, dot)))


def apply_increment(pose: Pose, increment: Increment, frame: str) -> Pose:
    delta_quaternion = quaternion_from_rpy(increment.rpy_rad)
    if frame == "world":
        position = pose.position + increment.translation_m
        orientation = quaternion_multiply(delta_quaternion, pose.quaternion_xyzw)
    elif frame == "local":
        position = pose.position + quaternion_to_rotation_matrix(pose.quaternion_xyzw) @ increment.translation_m
        orientation = quaternion_multiply(pose.quaternion_xyzw, delta_quaternion)
    else:
        raise ValueError(f"unsupported frame: {frame}")
    return Pose(position=np.asarray(position, dtype=np.float64), quaternion_xyzw=orientation)


def command_for_key(key: str, step_m: float, step_rad: float) -> Increment | None:
    translation = {
        "w": np.asarray([step_m, 0.0, 0.0]),
        "s": np.asarray([-step_m, 0.0, 0.0]),
        "a": np.asarray([0.0, step_m, 0.0]),
        "d": np.asarray([0.0, -step_m, 0.0]),
        "r": np.asarray([0.0, 0.0, step_m]),
        "f": np.asarray([0.0, 0.0, -step_m]),
    }
    rotations = {
        "i": np.asarray([step_rad, 0.0, 0.0]),
        "k": np.asarray([-step_rad, 0.0, 0.0]),
        "j": np.asarray([0.0, step_rad, 0.0]),
        "l": np.asarray([0.0, -step_rad, 0.0]),
        "u": np.asarray([0.0, 0.0, step_rad]),
        "o": np.asarray([0.0, 0.0, -step_rad]),
    }
    if key in translation:
        return Increment(translation_m=translation[key], rpy_rad=ZERO3.copy())
    if key in rotations:
        return Increment(translation_m=ZERO3.copy(), rpy_rad=rotations[key])
    return None


def state_ok(state: object) -> bool:
    return (
        bool(getattr(state, "service_state", False))
        and bool(getattr(state, "valid", False))
        and str(getattr(state, "fsm_state", "")) == "IDLE"
        and str(getattr(state, "controller_state", "")) == "idle"
    )


def read_pose(client: object, side: str) -> Pose:
    value = client.get_end_pose()
    if value is None:
        raise RuntimeError(f"{side}: get_end_pose() returned None")
    return Pose(
        position=np.asarray(value.position, dtype=np.float64),
        quaternion_xyzw=normalize_quaternion(value.orientation),
    )


def make_sdk_pose(pose: Pose, pose_type: type) -> object:
    return pose_type(
        position=tuple(float(value) for value in pose.position),
        orientation=tuple(float(value) for value in pose.quaternion_xyzw),
    )


def parse_eff(value: str) -> list[float]:
    efforts = [float(item.strip()) for item in value.split(",") if item.strip()]
    if len(efforts) != 7 or not all(math.isfinite(item) and item > 0.0 for item in efforts):
        raise ValueError("--eff must contain seven positive finite values")
    return efforts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="192.168.25.1")
    parser.add_argument("--left-port", type=int, default=50071)
    parser.add_argument("--right-port", type=int, default=50072)
    parser.add_argument("--backend", default="grpc")
    parser.add_argument("--frame", choices=("world", "local"), default="world")
    parser.add_argument("--step-mm", type=float, default=2.0, help="Translation per key press.")
    parser.add_argument("--step-deg", type=float, default=2.0, help="Roll/pitch/yaw per key press.")
    parser.add_argument("--command-interval-s", type=float, default=0.04)
    parser.add_argument("--arm-speed-rad-s", type=float, default=1.5, help="P7 SDK accepts 0.55 to 7.85 rad/s.")
    parser.add_argument("--eff", default="8,8,8,8,8,8,8")
    parser.add_argument("--motion-timeout-ms", type=int, default=3000)
    parser.add_argument("--lease-ms", type=int, default=120000)
    parser.add_argument("--blocking", action="store_true", help="Wait for each Cartesian command to finish.")
    parser.add_argument("--execute", action="store_true", help="Enable robot motion; dry-run is the default.")
    parser.add_argument("--allow-robot-motion", action="store_true")
    return parser.parse_args()


def print_help(selected: set[str], frame: str, step_m: float, step_rad: float) -> None:
    print(
        "\nSelected: "
        + ",".join(sorted(selected))
        + f" | frame={frame} | step={step_m * 1000.0:.1f}mm/{math.degrees(step_rad):.1f}deg\n"
        "1/2/b select left/right/both; w/s x; a/d y; r/f z; "
        "i/k roll; j/l pitch; u/o yaw; h help; q quit.",
        flush=True,
    )


def run_concurrently(tasks: dict[str, Callable[[], object]]) -> dict[str, object]:
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    def worker(name: str, task: Callable[[], object]) -> None:
        try:
            results[name] = task()
        except BaseException as exc:
            errors[name] = exc

    threads = [threading.Thread(target=worker, args=(name, task), daemon=True) for name, task in tasks.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        detail = "; ".join(f"{name}: {error!r}" for name, error in errors.items())
        raise RuntimeError(detail)
    return results


def configure_direct_grpc(host: str) -> list[str]:
    """Match replay: keep SDK gRPC traffic off local HTTP/SOCKS proxies."""
    proxy_variables = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    removed = [name for name in proxy_variables if os.environ.pop(name, None) is not None]
    for name in ("no_proxy", "NO_PROXY"):
        entries = [entry.strip() for entry in os.environ.get(name, "").split(",") if entry.strip()]
        if host not in entries:
            entries.append(host)
        os.environ[name] = ",".join(entries)
    return removed


def keyboard_loop(
    clients: dict[str, object],
    args: argparse.Namespace,
    *,
    pose_type: type,
    move_options: object,
) -> None:
    selected = set(SIDES)
    last_command_s = 0.0
    print_help(selected, args.frame, args.step_mm / 1000.0, math.radians(args.step_deg))
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        while True:
            readable, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not readable:
                continue
            key = sys.stdin.read(1)
            lowered = key.lower()
            if lowered in {"q", "\x03"}:
                break
            if lowered == "1":
                selected = {"left"}
                print_help(selected, args.frame, args.step_mm / 1000.0, math.radians(args.step_deg))
                continue
            if lowered == "2":
                selected = {"right"}
                print_help(selected, args.frame, args.step_mm / 1000.0, math.radians(args.step_deg))
                continue
            if lowered == "b":
                selected = set(SIDES)
                print_help(selected, args.frame, args.step_mm / 1000.0, math.radians(args.step_deg))
                continue
            if lowered == "h":
                print_help(selected, args.frame, args.step_mm / 1000.0, math.radians(args.step_deg))
                continue
            increment = command_for_key(lowered, args.step_mm / 1000.0, math.radians(args.step_deg))
            if increment is None:
                continue
            now = time.monotonic()
            if now - last_command_s < args.command_interval_s:
                continue
            last_command_s = now
            current = {side: read_pose(clients[side], side) for side in selected}
            targets = {side: apply_increment(current[side], increment, args.frame) for side in selected}
            for side, target in targets.items():
                print(f"{side} target_xyz={[round(float(value), 5) for value in target.position]}", flush=True)
            if not args.execute:
                print("DRY_RUN: no move_end_pose() called", flush=True)
                continue
            failures = []
            results = run_concurrently(
                {
                    side: (
                        lambda side=side, target=target: clients[side].move_end_pose(
                            make_sdk_pose(target, pose_type), move_options, timeout_ms=args.motion_timeout_ms
                        )
                    )
                    for side, target in targets.items()
                }
            )
            failures.extend(side for side, result in results.items() if not result)
            if failures:
                raise RuntimeError(f"move_end_pose returned False for {failures}")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def main() -> int:
    args = parse_args()
    if args.execute and not args.allow_robot_motion:
        print("REFUSE: --execute requires --allow-robot-motion", file=sys.stderr)
        return 2
    if args.step_mm <= 0.0 or args.step_deg <= 0.0:
        print("REFUSE: step sizes must be positive", file=sys.stderr)
        return 2
    if (
        args.command_interval_s < 0.0
        or args.motion_timeout_ms <= 0
        or args.lease_ms <= 0
    ):
        print("REFUSE: timing and lease values must be positive", file=sys.stderr)
        return 2
    if not 0.55 <= args.arm_speed_rad_s <= 7.85:
        print("REFUSE: --arm-speed-rad-s must be within [0.55, 7.85]", file=sys.stderr)
        return 2

    try:
        efforts = parse_eff(args.eff)
        from arm_p7_sdk import AirbotClient
        from arm_p7_sdk import CartesianMoveOptions
        from arm_p7_sdk import CartesianPose
        from arm_p7_sdk import Controller
    except Exception as exc:
        print(f"FAILED: import arm_p7_sdk: {exc}", file=sys.stderr)
        return 2

    clients: dict[str, object] = {}
    acquired: set[str] = set()
    switched: set[str] = set()
    try:
        removed_proxy_variables = configure_direct_grpc(args.host)
        print(f"grpc_direct_host={args.host} removed_proxy_variables={removed_proxy_variables}", flush=True)
        clients = {
            "left": AirbotClient(host=args.host, port=args.left_port, backend=args.backend),
            "right": AirbotClient(host=args.host, port=args.right_port, backend=args.backend),
        }
        for side, client in clients.items():
            state = client.get_service_state()
            print(f"{side} state_before {state}", flush=True)
            if not state_ok(state):
                raise RuntimeError(f"{side}: service is not IDLE/idle/valid")
        starts = {side: read_pose(client, side) for side, client in clients.items()}
        for side, pose in starts.items():
            print(f"{side} start_xyz={pose.position.tolist()} start_xyzw={pose.quaternion_xyzw.tolist()}", flush=True)

        if args.execute:
            for side, client in clients.items():
                if not client.acquire_control(lease_ms=args.lease_ms, renew_period_s=5.0):
                    raise RuntimeError(f"{side}: acquire_control returned False")
                acquired.add(side)
                if not client.switch_controller(Controller.servo_control, timeout_ms=args.motion_timeout_ms):
                    raise RuntimeError(f"{side}: switch_controller(servo_control) returned False")
                switched.add(side)
                if not client.set_arm_speed([float(args.arm_speed_rad_s)] * 7):
                    raise RuntimeError(f"{side}: set_arm_speed returned False")
            print("EXECUTE: robot motion enabled; press q or Ctrl-C to stop", flush=True)
        else:
            print("DRY_RUN: robot control is disabled; press q to exit", flush=True)

        options = CartesianMoveOptions(eff=efforts, motion_type="lin", blocking=bool(args.blocking))
        keyboard_loop(clients, args, pose_type=CartesianPose, move_options=options)
        return 0
    except KeyboardInterrupt:
        print("\nstop requested", flush=True)
        return 0
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
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
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    close()
                except Exception as exc:
                    print(f"client close exception {exc!r}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
