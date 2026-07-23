"""Run a bounded continuous Arm-P7 TCP servo smoke test.

Default mode is dry-run. Add ``--execute --allow-robot-motion`` only after the
workspace is clear. The executed path keeps each arm within ``--max-envelope-m``
of its start TCP position and returns to the start pose before releasing control.
The gripper is not commanded.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import math
from pathlib import Path
import sys
import threading
import time

import numpy as np

from arm_p7_sdk import AirbotClient
from arm_p7_sdk import CartesianMoveOptions
from arm_p7_sdk import CartesianPose
from arm_p7_sdk import Controller


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.25.1")
    parser.add_argument("--left-port", type=int, default=50071)
    parser.add_argument("--right-port", type=int, default=50072)
    parser.add_argument("--backend", default="grpc")
    parser.add_argument("--duration-s", type=float, default=25.0)
    parser.add_argument("--rate-hz", type=float, default=4.0)
    parser.add_argument("--radius-m", type=float, default=0.015)
    parser.add_argument("--max-envelope-m", type=float, default=0.05)
    parser.add_argument("--arm-speed-rad-s", type=float, default=0.55)
    parser.add_argument("--eff", default="8,8,8,8,8,8,8")
    parser.add_argument("--motion-timeout-ms", type=int, default=30000)
    parser.add_argument("--pre-samples", type=int, default=3)
    parser.add_argument("--sample-period-s", type=float, default=0.15)
    parser.add_argument("--pre-drift-guard-m", type=float, default=0.003)
    parser.add_argument("--settle-s", type=float, default=1.0)
    parser.add_argument("--blocking", action="store_true", help="Use blocking move_end_pose; default is non-blocking streaming.")
    parser.add_argument("--summary-json", type=Path, default=Path("/tmp/p7_continuous_servo_smoke_latest.json"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-robot-motion", action="store_true")
    return parser.parse_args()


def parse_eff(value: str) -> list[float]:
    efforts = [float(item.strip()) for item in value.split(",") if item.strip()]
    if len(efforts) != 7:
        raise ValueError(f"--eff must contain 7 floats, got {len(efforts)}")
    if not all(math.isfinite(v) for v in efforts):
        raise ValueError("--eff contains non-finite values")
    return efforts


def distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)))


def state_ok(state: object) -> bool:
    return (
        bool(getattr(state, "service_state", False))
        and bool(getattr(state, "valid", False))
        and str(getattr(state, "fsm_state", "")) == "IDLE"
        and str(getattr(state, "controller_state", "")) == "idle"
    )


def read_pose(client: AirbotClient, side: str) -> tuple[np.ndarray, np.ndarray]:
    pose = client.get_end_pose()
    if pose is None:
        raise RuntimeError(f"{side}: get_end_pose() returned None")
    return np.asarray(pose.position, dtype=np.float64), np.asarray(pose.orientation, dtype=np.float64)


def read_stable_pose(
    client: AirbotClient,
    side: str,
    *,
    samples: int,
    period_s: float,
    guard_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    poses = []
    for idx in range(samples):
        poses.append(read_pose(client, side))
        if idx + 1 < samples:
            time.sleep(period_s)
    drift = max(distance(poses[0][0], pose[0]) for pose in poses[1:]) if len(poses) > 1 else 0.0
    print(f"{side} pre_drift_m={drift:.6f}", flush=True)
    if drift > guard_m:
        raise RuntimeError(f"{side}: pre-motion drift {drift:.6f} exceeds guard {guard_m:.6f}")
    return poses[-1]


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


def offset_at(t: float, duration_s: float, radius_m: float) -> np.ndarray:
    phase = 2.0 * math.pi * max(0.0, min(1.0, t / duration_s))
    return np.asarray(
        [
            radius_m * math.sin(phase),
            0.5 * radius_m * math.sin(2.0 * phase),
            0.5 * radius_m * math.sin(3.0 * phase),
        ],
        dtype=np.float64,
    )


def make_pose(position: np.ndarray, orientation: np.ndarray) -> CartesianPose:
    return CartesianPose(
        position=tuple(float(v) for v in position),
        orientation=tuple(float(v) for v in orientation),
    )


def move_pose(client: AirbotClient, side: str, pose: CartesianPose, options: CartesianMoveOptions, timeout_ms: int) -> bool:
    ok = client.move_end_pose(pose, options, timeout_ms=timeout_ms)
    if not ok:
        raise RuntimeError(f"{side}: move_end_pose returned False")
    return ok


def main() -> int:
    args = parse_args()
    if args.execute and not args.allow_robot_motion:
        print("REFUSE: --execute requires --allow-robot-motion")
        return 2
    if args.duration_s <= 20.0:
        print("REFUSE: duration must be > 20s for this smoke test")
        return 2
    if args.rate_hz <= 0.0 or args.radius_m <= 0.0:
        print("REFUSE: rate and radius must be positive")
        return 2
    if args.max_envelope_m > 0.05:
        print("REFUSE: max envelope must be <= 0.05m")
        return 2

    offsets = [offset_at(i / args.rate_hz, args.duration_s, args.radius_m) for i in range(int(math.ceil(args.duration_s * args.rate_hz)) + 1)]
    max_cmd_envelope = max(float(np.linalg.norm(offset)) for offset in offsets)
    if max_cmd_envelope > args.max_envelope_m:
        print(f"REFUSE: command envelope {max_cmd_envelope:.6f}m exceeds {args.max_envelope_m:.6f}m")
        return 2

    efforts = parse_eff(args.eff)
    clients: dict[str, AirbotClient] = {}
    acquired: set[str] = set()
    switched: set[str] = set()
    summary: dict[str, object] = {
        "duration_s": args.duration_s,
        "rate_hz": args.rate_hz,
        "radius_m": args.radius_m,
        "max_cmd_envelope_m": max_cmd_envelope,
        "execute": bool(args.execute),
        "blocking": bool(args.blocking),
    }
    exit_code = 0

    try:
        clients = {
            "left": AirbotClient(host=args.host, port=args.left_port, backend=args.backend),
            "right": AirbotClient(host=args.host, port=args.right_port, backend=args.backend),
        }
        for side, client in clients.items():
            state = client.get_service_state()
            print(f"{side} state_before {state}", flush=True)
            if not state_ok(state):
                raise RuntimeError(f"{side}: not IDLE/idle/valid")

        start = {
            side: read_stable_pose(
                client,
                side,
                samples=args.pre_samples,
                period_s=args.sample_period_s,
                guard_m=args.pre_drift_guard_m,
            )
            for side, client in clients.items()
        }
        for side, (pos, quat) in start.items():
            print(f"{side} start_xyz={pos.tolist()} start_xyzw={quat.tolist()}", flush=True)

        print(
            f"planned_frames={len(offsets)} planned_duration_s={args.duration_s:.3f} "
            f"rate_hz={args.rate_hz:.3f} max_cmd_envelope_m={max_cmd_envelope:.6f}",
            flush=True,
        )

        if not args.execute:
            for idx in [0, len(offsets) // 4, len(offsets) // 2, 3 * len(offsets) // 4, len(offsets) - 1]:
                print(f"DRY_RUN frame={idx} offset_m={offsets[idx].tolist()}", flush=True)
            print("DRY_RUN: no acquire_control(), switch_controller(), or move_end_pose() was called", flush=True)
            summary["dry_run_ok"] = True
            args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            return 0

        for side, client in clients.items():
            ok = client.acquire_control(lease_ms=max(45000, int(args.duration_s * 2000)), renew_period_s=5.0)
            print(f"{side} acquire_control {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: acquire_control returned False")
            acquired.add(side)

        for side, client in clients.items():
            ok = client.switch_controller(Controller.servo_control, timeout_ms=args.motion_timeout_ms)
            print(f"{side} switch_servo {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: switch_controller(servo_control) returned False")
            switched.add(side)

        for side, client in clients.items():
            ok = client.set_arm_speed([float(args.arm_speed_rad_s)] * 7)
            print(f"{side} set_arm_speed {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: set_arm_speed returned False")

        options = CartesianMoveOptions(eff=efforts, motion_type="lin", blocking=bool(args.blocking))
        loop_start = time.monotonic()
        max_measured: dict[str, float] = {"left": 0.0, "right": 0.0}
        frames_sent = 0
        for idx, offset in enumerate(offsets):
            target_poses = {
                side: make_pose(start[side][0] + offset, start[side][1])
                for side in clients
            }
            run_in_threads(
                {
                    side: (
                        lambda side=side, client=clients[side], pose=target_poses[side]: move_pose(
                            client, side, pose, options, args.motion_timeout_ms
                        )
                    )
                    for side in clients
                }
            )
            frames_sent += 1

            measured = {side: read_pose(client, side)[0] for side, client in clients.items()}
            for side in clients:
                max_measured[side] = max(max_measured[side], distance(measured[side], start[side][0]))
                if max_measured[side] > args.max_envelope_m:
                    raise RuntimeError(f"{side}: measured envelope {max_measured[side]:.6f} exceeds {args.max_envelope_m:.6f}")

            if idx == 0 or idx == len(offsets) - 1 or idx % max(1, int(args.rate_hz * 5.0)) == 0:
                elapsed = time.monotonic() - loop_start
                print(
                    f"frame={idx}/{len(offsets)-1} elapsed_s={elapsed:.3f} "
                    f"cmd_offset_m={offset.tolist()} left_measured_m={max_measured['left']:.6f} "
                    f"right_measured_m={max_measured['right']:.6f}",
                    flush=True,
                )

            target_time = loop_start + ((idx + 1) / args.rate_hz)
            sleep_s = target_time - time.monotonic()
            if sleep_s > 0.0:
                time.sleep(sleep_s)

        center_poses = {side: make_pose(start[side][0], start[side][1]) for side in clients}
        run_in_threads(
            {
                side: (
                    lambda side=side, client=clients[side], pose=center_poses[side]: move_pose(
                        client, side, pose, options, args.motion_timeout_ms
                    )
                )
                for side in clients
            }
        )
        time.sleep(args.settle_s)

        elapsed_total = time.monotonic() - loop_start
        final = {side: read_pose(client, side)[0] for side, client in clients.items()}
        final_error = {side: distance(final[side], start[side][0]) for side in clients}
        print(
            f"continuous_servo_done frames_sent={frames_sent} elapsed_s={elapsed_total:.3f} "
            f"left_max_measured_m={max_measured['left']:.6f} right_max_measured_m={max_measured['right']:.6f}",
            flush=True,
        )
        for side in clients:
            print(f"{side} final_xyz={final[side].tolist()} final_return_error_m={final_error[side]:.6f}", flush=True)

        summary.update(
            {
                "frames_sent": frames_sent,
                "elapsed_s": elapsed_total,
                "max_measured_m": max_measured,
                "final_return_error_m": final_error,
            }
        )
        args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        summary["error"] = str(exc)
        try:
            args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        except Exception:
            pass
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
