"""Move both Arm-P7 arms with all joints following one bounded triangle wave.

The default mode is an offline dry-run. Add ``--execute
--allow-robot-motion`` only after both arm workspaces are clear. Each joint
stays within ``start_joint +/- amplitude`` during the periodic phase.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import math
import signal
import sys
import time

from arm_p7_sdk import ARM_JOINT_LIMITS
from arm_p7_sdk import AirbotClient
from arm_p7_sdk import Controller
from arm_p7_sdk import JointMoveOptions

DEFAULT_START = [0.0, 0.647, 0.0, -0.933, 0.0, 0.0, -1.15]
DEFAULT_EFFORTS = [70.0, 70.0, 40.0, 40.0, 12.0, 12.0, 12.0]
PORTS = {"left": 50071, "right": 50072}


class StopState:
    def __init__(self) -> None:
        self.signum: int | None = None

    def reset(self) -> None:
        self.signum = None

    @property
    def requested(self) -> bool:
        return self.signum is not None


STOP_STATE = StopState()


def parse_vector(value: str, name: str) -> list[float]:
    result = [float(item.strip()) for item in value.split(",") if item.strip()]
    if len(result) != 7:
        raise ValueError(f"{name} must contain 7 floats, got {len(result)}")
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} contains non-finite values")
    return result


def check_joint_limits(target: list[float], name: str) -> None:
    for index, (value, limits) in enumerate(zip(target, ARM_JOINT_LIMITS, strict=True), start=1):
        low, high = (float(limit) for limit in limits)
        if not low <= value <= high:
            raise ValueError(f"{name} joint{index}={value:.6f} outside SDK limit [{low:.6f}, {high:.6f}]")


def state_is_idle(state: object) -> bool:
    return (
        bool(getattr(state, "service_state", False))
        and bool(getattr(state, "valid", False))
        and str(getattr(state, "fsm_state", "")) == "IDLE"
        and str(getattr(state, "controller_state", "")) == "idle"
    )


def read_angles(client: AirbotClient) -> list[float]:
    state = client.get_arm_joint_state()
    if state is None:
        raise RuntimeError("get_arm_joint_state() returned None")
    angles = [float(value) for value in state.angles]
    if len(angles) != 7 or not all(math.isfinite(value) for value in angles):
        raise RuntimeError(f"expected 7 finite arm joint angles, got {angles}")
    return angles


def triangle_position(t_s: float, low: float, high: float, period_s: float) -> float:
    """Return a center-starting triangle wave with a full period of period_s."""
    center = 0.5 * (low + high)
    phase = (t_s % period_s) / period_s
    if phase < 0.25:
        return center + (high - center) * (phase / 0.25)
    if phase < 0.75:
        return high + (low - high) * ((phase - 0.25) / 0.5)
    return low + (center - low) * ((phase - 0.75) / 0.25)


def sleep_until(deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining > 0.0:
        time.sleep(remaining)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.25.1")
    parser.add_argument("--backend", default="grpc")
    parser.add_argument("--side", choices=["left", "right", "both"], default="both")
    parser.add_argument("--start", default=",".join(str(value) for value in DEFAULT_START))
    parser.add_argument("--amplitude-rad", type=float, default=0.1)
    parser.add_argument("--period-s", type=float, default=10.0)
    parser.add_argument("--rate-hz", type=float, default=20.0)
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Number of complete periods; 0 runs until stopped.",
    )
    parser.add_argument("--approach-speed-rad-s", type=float, default=0.1)
    parser.add_argument("--sdk-speed-rad-s", type=float, default=0.55)
    parser.add_argument("--max-start-delta-rad", type=float, default=1.5)
    parser.add_argument("--start-tolerance-rad", type=float, default=0.1)
    parser.add_argument("--max-tracking-error-rad", type=float, default=0.25)
    parser.add_argument("--feedback-period-s", type=float, default=1.0)
    parser.add_argument("--eff", default=",".join(str(value) for value in DEFAULT_EFFORTS))
    parser.add_argument("--motion-timeout-ms", type=int, default=3000)
    parser.add_argument("--lease-ms", type=int, default=120000)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-robot-motion", action="store_true")
    return parser.parse_args()


def selected_sides(side: str) -> list[str]:
    return ["left", "right"] if side == "both" else [side]


def request_stop(signum: int, _frame: object) -> None:
    STOP_STATE.signum = signum
    print(f"SIGNAL: received {signal.Signals(signum).name}; stopping at the next frame", flush=True)


def validate_args(args: argparse.Namespace, start: list[float], efforts: list[float]) -> None:
    numeric_positive = {
        "--amplitude-rad": args.amplitude_rad,
        "--period-s": args.period_s,
        "--rate-hz": args.rate_hz,
        "--approach-speed-rad-s": args.approach_speed_rad_s,
        "--sdk-speed-rad-s": args.sdk_speed_rad_s,
        "--max-start-delta-rad": args.max_start_delta_rad,
        "--start-tolerance-rad": args.start_tolerance_rad,
        "--max-tracking-error-rad": args.max_tracking_error_rad,
        "--feedback-period-s": args.feedback_period_s,
    }
    for name, value in numeric_positive.items():
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be positive and finite")
    if args.cycles < 0:
        raise ValueError("--cycles must be >= 0")
    if args.motion_timeout_ms <= 0 or args.lease_ms <= 0:
        raise ValueError("timeouts must be positive")
    if any(value <= 0.0 for value in efforts):
        raise ValueError("--eff values must be positive")

    check_joint_limits(start, "start")
    check_joint_limits([value - args.amplitude_rad for value in start], "low target")
    check_joint_limits([value + args.amplitude_rad for value in start], "high target")


def send_targets(
    executor: ThreadPoolExecutor,
    clients: dict[str, AirbotClient],
    targets: dict[str, list[float]],
    options: JointMoveOptions,
    timeout_ms: int,
) -> None:
    futures = {
        side: executor.submit(client.move_joint, targets[side], options, timeout_ms)
        for side, client in clients.items()
    }
    for side, future in futures.items():
        if not future.result():
            raise RuntimeError(f"{side}: move_joint() returned False")


def approach_start(
    executor: ThreadPoolExecutor,
    clients: dict[str, AirbotClient],
    current: dict[str, list[float]],
    start: list[float],
    options: JointMoveOptions,
    args: argparse.Namespace,
) -> None:
    deltas = {
        side: [goal - actual for goal, actual in zip(start, angles, strict=True)]
        for side, angles in current.items()
    }
    max_delta = max(abs(value) for side_delta in deltas.values() for value in side_delta)
    if max_delta > args.max_start_delta_rad:
        raise RuntimeError(
            f"start delta {max_delta:.6f}rad exceeds guard {args.max_start_delta_rad:.6f}rad"
        )

    duration_s = max_delta / args.approach_speed_rad_s
    steps = max(1, math.ceil(duration_s * args.rate_hz))
    actual_duration_s = steps / args.rate_hz
    print(
        f"approach_start max_delta_rad={max_delta:.6f} steps={steps} "
        f"duration_s={actual_duration_s:.3f}",
        flush=True,
    )
    loop_start = time.monotonic()
    for index in range(1, steps + 1):
        if STOP_STATE.requested:
            return
        alpha = index / steps
        targets = {
            side: [actual + value * alpha for actual, value in zip(current[side], deltas[side], strict=True)]
            for side in clients
        }
        send_targets(executor, clients, targets, options, args.motion_timeout_ms)
        sleep_until(loop_start + index / args.rate_hz)

    for side, client in clients.items():
        measured = read_angles(client)
        max_error = max(abs(goal - actual) for goal, actual in zip(start, measured, strict=True))
        print(f"{side} start_measured_rad={measured} max_error_rad={max_error:.6f}", flush=True)
        if max_error > args.start_tolerance_rad:
            raise RuntimeError(
                f"{side}: start tracking error {max_error:.6f}rad exceeds "
                f"{args.start_tolerance_rad:.6f}rad"
            )


def run_triangle_wave(
    executor: ThreadPoolExecutor,
    clients: dict[str, AirbotClient],
    start: list[float],
    options: JointMoveOptions,
    args: argparse.Namespace,
) -> None:
    run_duration_s = None if args.cycles == 0 else args.cycles * args.period_s
    velocity_rad_s = 4.0 * args.amplitude_rad / args.period_s
    print(
        f"triangle_start all_joints_amplitude_rad={args.amplitude_rad:.3f} "
        f"period_s={args.period_s:.3f} commanded_speed_rad_s={velocity_rad_s:.3f} "
        f"cycles={'until stopped' if args.cycles == 0 else args.cycles}",
        flush=True,
    )

    frame = 0
    next_feedback_s = 0.0
    loop_start = time.monotonic()
    while not STOP_STATE.requested:
        scheduled_s = frame / args.rate_hz
        if run_duration_s is not None and scheduled_s > run_duration_s:
            break

        offset = triangle_position(scheduled_s, -args.amplitude_rad, args.amplitude_rad, args.period_s)
        target = [value + offset for value in start]
        targets = {side: target.copy() for side in clients}
        send_targets(executor, clients, targets, options, args.motion_timeout_ms)

        if scheduled_s >= next_feedback_s:
            feedback = []
            for side, client in clients.items():
                measured = read_angles(client)
                max_error = max(abs(goal - actual) for goal, actual in zip(target, measured, strict=True))
                feedback.append(f"{side}_max_error_rad={max_error:.6f}")
                if max_error > args.max_tracking_error_rad:
                    raise RuntimeError(
                        f"{side}: tracking error {max_error:.6f}rad exceeds "
                        f"{args.max_tracking_error_rad:.6f}rad"
                    )
            print(
                f"elapsed_s={scheduled_s:.3f} target_offset_rad={offset:.6f} " + " ".join(feedback),
                flush=True,
            )
            next_feedback_s = scheduled_s + args.feedback_period_s

        frame += 1
        elapsed_s = time.monotonic() - loop_start
        frame = max(frame, math.floor(elapsed_s * args.rate_hz) + 1)
        sleep_until(loop_start + frame / args.rate_hz)

    if not STOP_STATE.requested:
        send_targets(
            executor,
            clients,
            {side: start.copy() for side in clients},
            options,
            args.motion_timeout_ms,
        )


def print_dry_run(args: argparse.Namespace, start: list[float], sides: list[str]) -> None:
    velocity_rad_s = 4.0 * args.amplitude_rad / args.period_s
    print(f"DRY_RUN sides={sides} start_rad={start}")
    print(
        f"DRY_RUN all_joints_range_rad=+/-{args.amplitude_rad:.3f} "
        f"period_s={args.period_s:.3f} commanded_speed_rad_s={velocity_rad_s:.3f} "
        f"rate_hz={args.rate_hz:.3f}"
    )
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        t_s = fraction * args.period_s
        offset = triangle_position(t_s, -args.amplitude_rad, args.amplitude_rad, args.period_s)
        print(f"DRY_RUN t_s={t_s:.3f} all_joints_offset_rad={offset:.6f}")
    print("DRY_RUN: no robot connection or motion command was attempted")


def main() -> int:
    STOP_STATE.reset()
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    args = parse_args()
    try:
        start = parse_vector(args.start, "--start")
        efforts = parse_vector(args.eff, "--eff")
        validate_args(args, start, efforts)
    except ValueError as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 2

    sides = selected_sides(args.side)
    if not args.execute:
        print_dry_run(args, start, sides)
        return 0
    if not args.allow_robot_motion:
        print("REFUSE: --execute requires --allow-robot-motion", file=sys.stderr)
        return 2

    clients: dict[str, AirbotClient] = {}
    acquired: set[str] = set()
    switched: set[str] = set()
    exit_code = 1
    try:
        clients = {
            side: AirbotClient(host=args.host, port=PORTS[side], backend=args.backend)
            for side in sides
        }
        current: dict[str, list[float]] = {}
        for side, client in clients.items():
            state = client.get_service_state()
            print(f"{side} state_before {state}", flush=True)
            if not state_is_idle(state):
                raise RuntimeError(f"{side}: not IDLE/idle/valid")
            current[side] = read_angles(client)
            print(f"{side} current_angles_rad={current[side]}", flush=True)
        print(f"start_angles_rad={start}", flush=True)

        for side, client in clients.items():
            if not client.acquire_control(lease_ms=args.lease_ms, renew_period_s=5.0):
                raise RuntimeError(f"{side}: acquire_control() returned False")
            acquired.add(side)
            print(f"{side} acquire_control True", flush=True)

        for side, client in clients.items():
            if not client.switch_controller(Controller.servo_control, timeout_ms=args.motion_timeout_ms):
                raise RuntimeError(f"{side}: switch_controller(servo_control) returned False")
            switched.add(side)
            print(f"{side} switch_servo True", flush=True)

        for side, client in clients.items():
            if not client.set_arm_speed([float(args.sdk_speed_rad_s)] * 7):
                raise RuntimeError(f"{side}: set_arm_speed() returned False")
            print(f"{side} set_arm_speed {args.sdk_speed_rad_s:.6f}", flush=True)

        options = JointMoveOptions(eff=efforts, blocking=False)
        with ThreadPoolExecutor(max_workers=len(clients), thread_name_prefix="p7-joint-wave") as executor:
            approach_start(executor, clients, current, start, options, args)
            if not STOP_STATE.requested:
                run_triangle_wave(executor, clients, start, options, args)
        exit_code = 0 if STOP_STATE.signum is None else 128 + STOP_STATE.signum
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
    finally:
        for side in reversed(sides):
            if side in switched:
                try:
                    print(
                        f"{side} switch_idle "
                        f"{clients[side].switch_controller(Controller.idle, timeout_ms=args.motion_timeout_ms)}",
                        flush=True,
                    )
                except Exception as exc:
                    print(f"{side} switch_idle_exception {exc!r}", file=sys.stderr, flush=True)
        for side in reversed(sides):
            if side in acquired:
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
