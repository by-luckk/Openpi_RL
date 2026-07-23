"""Guarded Arm-P7 SDK SERVO tiny-step probe for one arm.

This script is intentionally conservative and defaults to read-only dry-run.
Use ``--execute`` only when the physical robot workspace is clear and a human is
ready to stop the robot.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import dataclasses
import math
import sys
import time

from arm_p7_sdk import AirbotClient
from arm_p7_sdk import CartesianMoveOptions
from arm_p7_sdk import CartesianPose
from arm_p7_sdk import Controller

AXES = {"x": 0, "y": 1, "z": 2}
DEFAULT_EFFORTS = [8.0] * 7
# SDK validation lower bound is 0.17507044*pi - 1e-4 ~= 0.5499 rad/s.
DEFAULT_ARM_SPEED_RAD_S = 0.55


@dataclasses.dataclass(frozen=True)
class PoseSample:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]

    @classmethod
    def from_sdk(cls, pose: CartesianPose) -> PoseSample:
        return cls(tuple(float(v) for v in pose.position), tuple(float(v) for v in pose.orientation))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.25.1")
    parser.add_argument("--port", type=int, default=50071)
    parser.add_argument("--backend", default="grpc")
    parser.add_argument("--axis", choices=sorted(AXES), default="x")
    parser.add_argument("--step-m", type=float, default=0.0002, help="Signed Cartesian step in meters; default 0.2mm.")
    parser.add_argument("--max-step-m", type=float, default=0.0005, help="Refuse abs(step) above this value.")
    parser.add_argument("--arm-speed-rad-s", type=float, default=DEFAULT_ARM_SPEED_RAD_S)
    parser.add_argument("--eff", default=",".join(str(v) for v in DEFAULT_EFFORTS), help="Comma-separated 7D current thresholds.")
    parser.add_argument("--lease-ms", type=int, default=15000)
    parser.add_argument("--renew-period-s", type=float, default=5.0)
    parser.add_argument("--motion-timeout-ms", type=int, default=3000)
    parser.add_argument("--pre-samples", type=int, default=5)
    parser.add_argument("--post-samples", type=int, default=8)
    parser.add_argument("--sample-period-s", type=float, default=0.2)
    parser.add_argument("--pre-drift-guard-m", type=float, default=0.0010)
    parser.add_argument("--move-distance-guard-m", type=float, default=0.0015)
    parser.add_argument("--final-distance-guard-m", type=float, default=0.0015)
    parser.add_argument("--execute", action="store_true", help="Actually send the SERVO move. Omit for read-only dry-run.")
    return parser.parse_args()


def parse_float_list(value: str, *, expected_len: int, name: str) -> list[float]:
    out = [float(item.strip()) for item in value.split(",") if item.strip()]
    if len(out) != expected_len:
        raise ValueError(f"{name} must contain {expected_len} floats, got {len(out)}: {value!r}")
    if not all(math.isfinite(v) for v in out):
        raise ValueError(f"{name} contains non-finite values: {out!r}")
    return out


def distance(a: Iterable[float], b: Iterable[float]) -> float:
    av = tuple(float(v) for v in a)
    bv = tuple(float(v) for v in b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(av, bv, strict=True)))


def max_position_drift(samples: list[PoseSample]) -> float:
    if len(samples) < 2:
        return 0.0
    first = samples[0].position
    return max(distance(first, sample.position) for sample in samples[1:])


def read_pose_or_raise(client: AirbotClient) -> PoseSample:
    pose = client.get_end_pose()
    if pose is None:
        raise RuntimeError("get_end_pose() returned None")
    return PoseSample.from_sdk(pose)


def read_pose_samples(client: AirbotClient, count: int, period_s: float) -> list[PoseSample]:
    samples: list[PoseSample] = []
    for idx in range(count):
        samples.append(read_pose_or_raise(client))
        if idx + 1 < count:
            time.sleep(period_s)
    return samples


def print_pose(label: str, pose: PoseSample) -> None:
    xyz = ", ".join(f"{v:.6f}" for v in pose.position)
    xyzw = ", ".join(f"{v:.6f}" for v in pose.orientation)
    print(f"{label} xyz=({xyz}) xyzw=({xyzw})", flush=True)


def state_ok_for_motion(state: object) -> bool:
    fsm = str(getattr(state, "fsm_state", ""))
    controller = str(getattr(state, "controller_state", ""))
    valid = bool(getattr(state, "valid", False))
    service = bool(getattr(state, "service_state", False))
    return service and valid and fsm == "IDLE" and controller == "idle"


def main() -> int:
    args = parse_args()
    if abs(args.step_m) > args.max_step_m:
        print(f"REFUSE: abs(step_m)={abs(args.step_m):.6f} exceeds max_step_m={args.max_step_m:.6f}", file=sys.stderr)
        return 2
    if args.pre_samples < 2 or args.post_samples < 2:
        print("REFUSE: pre-samples and post-samples must be >= 2", file=sys.stderr)
        return 2

    efforts = parse_float_list(args.eff, expected_len=7, name="eff")
    speed = float(args.arm_speed_rad_s)
    if not math.isfinite(speed) or speed <= 0:
        print(f"REFUSE: invalid arm speed {args.arm_speed_rad_s!r}", file=sys.stderr)
        return 2

    client = AirbotClient(host=args.host, port=args.port, backend=args.backend)
    controller_switched = False
    control_acquired = False
    start_pose: PoseSample | None = None
    exit_code = 0

    try:
        state_before = client.get_service_state()
        print("state_before", state_before, flush=True)
        if not state_ok_for_motion(state_before):
            print("REFUSE: service state is not IDLE/idle/valid; no motion will be sent", file=sys.stderr)
            return 3

        pre_samples = read_pose_samples(client, args.pre_samples, args.sample_period_s)
        start_pose = pre_samples[-1]
        pre_drift = max_position_drift(pre_samples)
        print_pose("pose_start", start_pose)
        print(f"pre_drift_m {pre_drift:.6f}", flush=True)
        if pre_drift > args.pre_drift_guard_m:
            print(
                f"REFUSE: pre-motion drift {pre_drift:.6f} exceeds guard {args.pre_drift_guard_m:.6f}; no motion will be sent",
                file=sys.stderr,
            )
            return 4

        target_position = list(start_pose.position)
        target_position[AXES[args.axis]] += args.step_m
        target_pose = PoseSample(tuple(target_position), start_pose.orientation)
        print_pose("target_pose", target_pose)
        print(f"planned_step_m {args.step_m:.6f} axis {args.axis}", flush=True)
        print(f"arm_speed_rad_s {speed:.6f}", flush=True)
        print(f"eff {efforts}", flush=True)

        if not args.execute:
            print("DRY_RUN: no acquire_control(), switch_controller(), or move_end_pose() was called", flush=True)
            return 0

        ok = client.acquire_control(lease_ms=args.lease_ms, renew_period_s=args.renew_period_s)
        print("acquire_control", ok, flush=True)
        if not ok:
            print("FAIL: acquire_control returned False", file=sys.stderr)
            return 5
        control_acquired = True

        ok = client.switch_controller(Controller.servo_control, timeout_ms=args.motion_timeout_ms)
        print("switch_servo", ok, flush=True)
        if not ok:
            print("FAIL: switch_controller(servo_control) returned False", file=sys.stderr)
            return 6
        controller_switched = True

        ok = client.set_arm_speed([speed] * 7)
        print("set_arm_speed", ok, flush=True)
        if not ok:
            print("FAIL: set_arm_speed returned False", file=sys.stderr)
            return 7

        sdk_target = CartesianPose(position=target_pose.position, orientation=target_pose.orientation)
        options = CartesianMoveOptions(eff=efforts, blocking=True)
        ok = client.move_end_pose(sdk_target, options, timeout_ms=args.motion_timeout_ms)
        print("move_end_pose", ok, flush=True)
        if not ok:
            print("FAIL: move_end_pose returned False", file=sys.stderr)
            exit_code = 8

        pose_after_move = read_pose_or_raise(client)
        print_pose("pose_after_move", pose_after_move)
        move_distance = distance(start_pose.position, pose_after_move.position)
        target_error = distance(target_pose.position, pose_after_move.position)
        print(f"move_distance_m {move_distance:.6f}", flush=True)
        print(f"target_error_m {target_error:.6f}", flush=True)
        if move_distance > args.move_distance_guard_m:
            print(
                f"GUARD_FAIL: move distance {move_distance:.6f} exceeds guard {args.move_distance_guard_m:.6f}",
                file=sys.stderr,
            )
            exit_code = max(exit_code, 9)

    finally:
        if controller_switched:
            try:
                ok = client.switch_controller(Controller.idle, timeout_ms=args.motion_timeout_ms)
                print("switch_idle", ok, flush=True)
            except Exception as exc:
                print(f"switch_idle_exception {exc!r}", file=sys.stderr, flush=True)
        if control_acquired:
            try:
                client.release_control()
                print("release_control done", flush=True)
            except Exception as exc:
                print(f"release_control_exception {exc!r}", file=sys.stderr, flush=True)

    try:
        post_samples = read_pose_samples(client, args.post_samples, args.sample_period_s)
        final_pose = post_samples[-1]
        print_pose("final_pose", final_pose)
        post_drift = max_position_drift(post_samples)
        print(f"post_drift_m {post_drift:.6f}", flush=True)
        if start_pose is not None:
            final_distance = distance(start_pose.position, final_pose.position)
            print(f"final_distance_m {final_distance:.6f}", flush=True)
            if final_distance > args.final_distance_guard_m:
                print(
                    f"GUARD_FAIL: final distance {final_distance:.6f} exceeds guard {args.final_distance_guard_m:.6f}",
                    file=sys.stderr,
                )
                exit_code = max(exit_code, 10)
        state_final = client.get_service_state()
        print("state_final", state_final, flush=True)
    finally:
        client.close()
        print("client_closed", flush=True)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
