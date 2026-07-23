"""Sequential Arm-P7 servo precision probe for signed XYZ TCP moves.

Default mode is dry-run. In execute mode this script tests one SDK side and one
axis at a time, returns that side to its baseline pose, then proceeds. This is
safer than moving both arms in parallel when testing large 10cm targets.
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
PORTS = {"left": 50071, "right": 50072}


@dataclasses.dataclass(frozen=True)
class PoseSample:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]

    @classmethod
    def from_sdk(cls, pose: CartesianPose) -> PoseSample:
        return cls(tuple(float(v) for v in pose.position), tuple(float(v) for v in pose.orientation))

    def to_sdk(self) -> CartesianPose:
        return CartesianPose(position=self.position, orientation=self.orientation)

    def shifted(self, axis: str, step_m: float) -> PoseSample:
        pos = list(self.position)
        pos[AXES[axis]] += step_m
        return PoseSample(tuple(pos), self.orientation)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.25.1")
    parser.add_argument("--backend", default="grpc")
    parser.add_argument("--sides", default="left,right", help="Comma-separated SDK sides: left,right")
    parser.add_argument("--axes", default="x,y,z", help="Comma-separated axes: x,y,z")
    parser.add_argument("--step-m", type=float, default=0.10)
    parser.add_argument("--max-step-m", type=float, default=0.10)
    parser.add_argument("--arm-speed-rad-s", type=float, default=0.55)
    parser.add_argument("--eff", default="8,8,8,8,8,8,8")
    parser.add_argument("--motion-timeout-ms", type=int, default=60000)
    parser.add_argument("--settle-s", type=float, default=0.75)
    parser.add_argument("--pre-drift-samples", type=int, default=3)
    parser.add_argument("--sample-period-s", type=float, default=0.15)
    parser.add_argument("--pre-drift-guard-m", type=float, default=0.003)
    parser.add_argument("--blocking", action="store_true", help="Use blocking servo move_end_pose; default is non-blocking with settle.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-robot-motion", action="store_true")
    return parser.parse_args()


def parse_csv(value: str, allowed: set[str], name: str) -> list[str]:
    out = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not out or any(item not in allowed for item in out):
        raise ValueError(f"{name} must be comma-separated values from {sorted(allowed)}, got {value!r}")
    return out


def parse_eff(value: str) -> list[float]:
    out = [float(item.strip()) for item in value.split(",") if item.strip()]
    if len(out) != 7:
        raise ValueError(f"--eff must contain 7 floats, got {len(out)}")
    return out


def distance(a: Iterable[float], b: Iterable[float]) -> float:
    av = tuple(float(v) for v in a)
    bv = tuple(float(v) for v in b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(av, bv, strict=True)))


def read_pose(client: AirbotClient, side: str) -> PoseSample:
    pose = client.get_end_pose()
    if pose is None:
        raise RuntimeError(f"{side}: get_end_pose() returned None")
    return PoseSample.from_sdk(pose)


def read_stable_pose(client: AirbotClient, side: str, samples: int, period_s: float, guard_m: float) -> PoseSample:
    poses = []
    for idx in range(samples):
        poses.append(read_pose(client, side))
        if idx + 1 < samples:
            time.sleep(period_s)
    drift = max(distance(poses[0].position, pose.position) for pose in poses[1:]) if len(poses) > 1 else 0.0
    print(f"{side} pre_drift_m={drift:.6f}", flush=True)
    if drift > guard_m:
        raise RuntimeError(f"{side}: pre-motion drift {drift:.6f} exceeds guard {guard_m:.6f}")
    return poses[-1]


def state_ok(state: object) -> bool:
    return (
        bool(getattr(state, "service_state", False))
        and bool(getattr(state, "valid", False))
        and str(getattr(state, "fsm_state", "")) == "IDLE"
        and str(getattr(state, "controller_state", "")) == "idle"
    )


def delta_xyz(start: PoseSample, end: PoseSample) -> tuple[float, float, float]:
    return tuple(e - s for s, e in zip(start.position, end.position, strict=True))


def print_measurement(side: str, axis: str, step_m: float, start: PoseSample, end: PoseSample) -> None:
    delta = delta_xyz(start, end)
    axis_idx = AXES[axis]
    axis_delta = delta[axis_idx]
    axis_error = axis_delta - step_m
    cross = math.sqrt(sum(v * v for idx, v in enumerate(delta) if idx != axis_idx))
    total_error = distance(end.position, start.shifted(axis, step_m).position)
    print(
        f"{side} axis={axis} commanded_m={step_m:.6f} "
        f"delta_m=({delta[0]:.6f},{delta[1]:.6f},{delta[2]:.6f}) "
        f"axis_error_m={axis_error:.6f} cross_axis_m={cross:.6f} total_error_m={total_error:.6f}",
        flush=True,
    )


def move_pose(client: AirbotClient, side: str, target: PoseSample, options: CartesianMoveOptions, timeout_ms: int) -> None:
    ok = client.move_end_pose(target.to_sdk(), options, timeout_ms=timeout_ms)
    print(f"{side} move_servo ok={ok}", flush=True)
    if not ok:
        raise RuntimeError(f"{side}: move_end_pose returned False")


def main() -> int:
    args = parse_args()
    if args.execute and not args.allow_robot_motion:
        print("REFUSE: --execute requires --allow-robot-motion")
        return 2
    if abs(args.step_m) > args.max_step_m:
        print(f"REFUSE: abs(step_m)={abs(args.step_m):.6f} exceeds max_step_m={args.max_step_m:.6f}", file=sys.stderr)
        return 2
    sides = parse_csv(args.sides, set(PORTS), "--sides")
    axes = parse_csv(args.axes, set(AXES), "--axes")
    efforts = parse_eff(args.eff)
    options = CartesianMoveOptions(eff=efforts, motion_type="lin", blocking=bool(args.blocking))

    clients = {side: AirbotClient(host=args.host, port=PORTS[side], backend=args.backend) for side in sides}
    acquired: set[str] = set()
    switched: set[str] = set()
    try:
        baselines: dict[str, PoseSample] = {}
        for side, client in clients.items():
            state = client.get_service_state()
            print(f"{side} state_before {state}", flush=True)
            if not state_ok(state):
                print(f"REFUSE: {side} is not IDLE/idle/valid", file=sys.stderr)
                return 3
            baselines[side] = read_stable_pose(client, side, args.pre_drift_samples, args.sample_period_s, args.pre_drift_guard_m)
            print(f"{side} start_xyz={baselines[side].position} start_xyzw={baselines[side].orientation}", flush=True)

        if not args.execute:
            for sign in (1.0, -1.0):
                step = sign * abs(args.step_m)
                for axis in axes:
                    for side in sides:
                        print(f"DRY_RUN {side} axis={axis} step_m={step:.6f} target_xyz={baselines[side].shifted(axis, step).position}", flush=True)
            print("DRY_RUN: no acquire_control(), switch_controller(), or move_end_pose() was called", flush=True)
            return 0

        for side in sides:
            client = clients[side]
            ok = client.acquire_control(lease_ms=60000, renew_period_s=5.0)
            print(f"{side} acquire_control {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: acquire_control returned False")
            acquired.add(side)
            ok = client.switch_controller(Controller.servo_control, timeout_ms=args.motion_timeout_ms)
            print(f"{side} switch_servo {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: switch_controller(servo_control) returned False")
            switched.add(side)
            ok = client.set_arm_speed([float(args.arm_speed_rad_s)] * 7)
            print(f"{side} set_arm_speed {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: set_arm_speed returned False")

        for sign in (1.0, -1.0):
            step = sign * abs(args.step_m)
            for axis in axes:
                for side in sides:
                    client = clients[side]
                    baseline = baselines[side]
                    target = baseline.shifted(axis, step)
                    print(f"START {side} axis={axis} step_m={step:.6f}", flush=True)
                    move_pose(client, side, target, options, args.motion_timeout_ms)
                    time.sleep(args.settle_s)
                    measured = read_pose(client, side)
                    print_measurement(side, axis, step, baseline, measured)
                    print(f"RETURN {side} axis={axis}", flush=True)
                    move_pose(client, side, baseline, options, args.motion_timeout_ms)
                    time.sleep(args.settle_s)
                    returned = read_pose(client, side)
                    print(f"{side} return_error_m={distance(returned.position, baseline.position):.6f}", flush=True)
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        for side in list(switched):
            try:
                print(f"{side} switch_idle {clients[side].switch_controller(Controller.idle, timeout_ms=args.motion_timeout_ms)}", flush=True)
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


if __name__ == "__main__":
    raise SystemExit(main())
