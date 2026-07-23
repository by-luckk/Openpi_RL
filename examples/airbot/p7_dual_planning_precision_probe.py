"""Dual-arm Arm-P7 planning precision probe.

The script defaults to a read-only probe that connects to both arm services and
prints planned targets without acquiring control. Add ``--execute`` only after
the workspace is clear and both ``arm_app`` gRPC services are running.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
import dataclasses
import math
import sys
import threading
import time

from arm_p7_sdk import AirbotClient
from arm_p7_sdk import CartesianMoveOptions
from arm_p7_sdk import CartesianPose
from arm_p7_sdk import Controller

AXES = {"x": 0, "y": 1, "z": 2}


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
    parser.add_argument("--left-port", type=int, default=50071)
    parser.add_argument("--right-port", type=int, default=50072)
    parser.add_argument("--backend", default="grpc")
    parser.add_argument("--axes", default="x,y,z", help="Comma-separated subset/order of x,y,z.")
    parser.add_argument("--step-m", type=float, default=0.08, help="Signed planning step in meters.")
    parser.add_argument("--max-step-m", type=float, default=0.10, help="Refuse abs(step) above this value.")
    parser.add_argument("--velocity-scaling", type=float, default=0.1)
    parser.add_argument("--acceleration-scaling", type=float, default=0.1)
    parser.add_argument("--allow-planning-time-s", type=float, default=5.0)
    parser.add_argument("--motion-timeout-ms", type=int, default=30000)
    parser.add_argument("--settle-s", type=float, default=0.5)
    parser.add_argument("--pre-drift-samples", type=int, default=3)
    parser.add_argument("--sample-period-s", type=float, default=0.15)
    parser.add_argument("--pre-drift-guard-m", type=float, default=0.002)
    parser.add_argument("--no-return-between-axes", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Actually acquire control and send planning moves.")
    return parser.parse_args()


def distance(a: Iterable[float], b: Iterable[float]) -> float:
    av = tuple(float(v) for v in a)
    bv = tuple(float(v) for v in b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(av, bv, strict=True)))


def delta_xyz(start: PoseSample, end: PoseSample) -> tuple[float, float, float]:
    return tuple(e - s for s, e in zip(start.position, end.position, strict=True))


def read_pose_or_raise(client: AirbotClient, side: str) -> PoseSample:
    pose = client.get_end_pose()
    if pose is None:
        raise RuntimeError(f"{side}: get_end_pose() returned None")
    return PoseSample.from_sdk(pose)


def read_stable_pose(client: AirbotClient, side: str, samples: int, period_s: float, guard_m: float) -> PoseSample:
    poses = []
    for idx in range(samples):
        poses.append(read_pose_or_raise(client, side))
        if idx + 1 < samples:
            time.sleep(period_s)
    drift = max(distance(poses[0].position, pose.position) for pose in poses[1:]) if len(poses) > 1 else 0.0
    print(f"{side} pre_drift_m={drift:.6f}", flush=True)
    if drift > guard_m:
        raise RuntimeError(f"{side}: pre-motion drift {drift:.6f} exceeds guard {guard_m:.6f}")
    return poses[-1]


def state_ok_for_motion(state: object) -> bool:
    fsm = str(getattr(state, "fsm_state", ""))
    controller = str(getattr(state, "controller_state", ""))
    valid = bool(getattr(state, "valid", False))
    service = bool(getattr(state, "service_state", False))
    return service and valid and fsm == "IDLE" and controller == "idle"


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


def move_linear(
    client: AirbotClient,
    *,
    side: str,
    start: PoseSample,
    target: PoseSample,
    options: CartesianMoveOptions,
    timeout_ms: int,
) -> bool:
    ok = client.move_end_pose_linear(
        start=start.to_sdk(),
        target=target.to_sdk(),
        options=options,
        timeout_ms=timeout_ms,
    )
    print(f"{side} move_linear ok={ok}", flush=True)
    if not ok:
        raise RuntimeError(f"{side}: move_end_pose_linear returned False")
    return ok


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


def main() -> int:
    args = parse_args()
    axes = [item.strip().lower() for item in args.axes.split(",") if item.strip()]
    if not axes or any(axis not in AXES for axis in axes):
        print(f"REFUSE: axes must be comma-separated x/y/z values, got {args.axes!r}", file=sys.stderr)
        return 2
    if abs(args.step_m) > args.max_step_m:
        print(f"REFUSE: abs(step_m)={abs(args.step_m):.6f} exceeds max_step_m={args.max_step_m:.6f}", file=sys.stderr)
        return 2

    options = CartesianMoveOptions(
        velocity_scaling_factor=args.velocity_scaling,
        acceleration_scaling_factor=args.acceleration_scaling,
        allow_planning_time=args.allow_planning_time_s,
        blocking=True,
    )
    clients: dict[str, AirbotClient] = {}
    acquired: set[str] = set()
    switched: set[str] = set()
    exit_code = 0

    try:
        clients = {
            "left": AirbotClient(host=args.host, port=args.left_port, backend=args.backend),
            "right": AirbotClient(host=args.host, port=args.right_port, backend=args.backend),
        }

        for side, client in clients.items():
            state = client.get_service_state()
            print(f"{side} state_before {state}", flush=True)
            if not state_ok_for_motion(state):
                print(f"REFUSE: {side} is not IDLE/idle/valid; no motion will be sent", file=sys.stderr)
                return 3

        starts = {
            side: read_stable_pose(
                client,
                side,
                args.pre_drift_samples,
                args.sample_period_s,
                args.pre_drift_guard_m,
            )
            for side, client in clients.items()
        }
        for side, pose in starts.items():
            print(f"{side} start_xyz={pose.position} start_xyzw={pose.orientation}", flush=True)

        if not args.execute:
            for axis in axes:
                for side, pose in starts.items():
                    target = pose.shifted(axis, args.step_m)
                    print(f"DRY_RUN {side} axis={axis} target_xyz={target.position}", flush=True)
            print("DRY_RUN: no acquire_control(), switch_controller(), or move_end_pose_linear() was called", flush=True)
            return 0

        for side, client in clients.items():
            ok = client.acquire_control()
            print(f"{side} acquire_control {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: acquire_control returned False")
            acquired.add(side)

        for side, client in clients.items():
            ok = client.switch_controller(Controller.planning_control, timeout_ms=args.motion_timeout_ms)
            print(f"{side} switch_planning {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: switch_controller(planning_control) returned False")
            switched.add(side)

        current = starts.copy()
        for axis in axes:
            targets = {side: pose.shifted(axis, args.step_m) for side, pose in current.items()}
            print(f"START axis={axis} step_m={args.step_m:.6f}", flush=True)
            run_in_threads(
                {
                    side: (
                        lambda side=side, client=clients[side], start=current[side], target=targets[side]: move_linear(
                            client,
                            side=side,
                            start=start,
                            target=target,
                            options=options,
                            timeout_ms=args.motion_timeout_ms,
                        )
                    )
                    for side in clients
                }
            )
            time.sleep(args.settle_s)
            measured = {side: read_pose_or_raise(client, side) for side, client in clients.items()}
            for side in clients:
                print_measurement(side, axis, args.step_m, current[side], measured[side])

            if args.no_return_between_axes:
                current = measured
                continue

            print(f"RETURN axis={axis}", flush=True)
            run_in_threads(
                {
                    side: (
                        lambda side=side, client=clients[side], start=measured[side], target=current[side]: move_linear(
                            client,
                            side=side,
                            start=start,
                            target=target,
                            options=options,
                            timeout_ms=args.motion_timeout_ms,
                        )
                    )
                    for side in clients
                }
            )
            time.sleep(args.settle_s)
            returned = {side: read_pose_or_raise(client, side) for side, client in clients.items()}
            for side in clients:
                return_error = distance(returned[side].position, current[side].position)
                print(f"{side} return_error_m={return_error:.6f}", flush=True)

    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        exit_code = 1
    finally:
        for side in list(switched):
            try:
                ok = clients[side].switch_controller(Controller.idle, timeout_ms=args.motion_timeout_ms)
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

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
