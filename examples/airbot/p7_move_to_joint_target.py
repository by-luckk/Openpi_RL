"""Move Arm-P7 arm(s) to a guarded 7-DoF joint target in radians.

Default mode is dry-run. Add ``--execute --allow-robot-motion`` only after the
workspace is clear. This script submits one blocking move_joint command to the
SDK servo controller; the SDK owns the closed loop and returns after completion.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

from arm_p7_sdk import ARM_JOINT_LIMITS
from arm_p7_sdk import AirbotClient
from arm_p7_sdk import Controller
from arm_p7_sdk import EEFControlMode
from arm_p7_sdk import EEFMoveOptions
from arm_p7_sdk import JointMoveOptions
import numpy as np

DEFAULT_TARGET = [0.0, 0.647, 0.0, -0.933, 0.0, 0.0, 0.0]
PORTS = {"left": 50071, "right": 50072}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.25.1")
    parser.add_argument("--backend", default="grpc")
    parser.add_argument("--side", choices=["left", "right", "both"], default="both")
    parser.add_argument("--target", default=",".join(str(v) for v in DEFAULT_TARGET))
    parser.add_argument("--speed-rad-s", type=float, default=0.55)
    parser.add_argument("--effort", type=float, default=8.0)
    parser.add_argument("--motion-timeout-ms", type=int, default=60000)
    parser.add_argument("--max-joint-delta-rad", type=float, default=1.5)
    parser.add_argument("--settle-s", type=float, default=1.0)
    parser.add_argument("--open-grippers", action="store_true")
    parser.add_argument("--gripper-open-mm", type=float, default=95.0)
    parser.add_argument("--eef-speed-mm-s", type=float, default=80.0)
    parser.add_argument("--eef-effort", type=float, default=5.0)
    parser.add_argument("--eef-timeout-ms", type=int, default=10000)
    parser.add_argument("--trajectory-dir", type=Path, default=Path("logs/p7_joint_motion"))
    parser.add_argument("--trajectory-sample-period-s", type=float, default=0.05)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-robot-motion", action="store_true")
    return parser.parse_args()


def parse_target(value: str) -> list[float]:
    target = [float(item.strip()) for item in value.split(",") if item.strip()]
    if len(target) != 7:
        raise ValueError(f"--target must contain 7 floats, got {len(target)}")
    if not all(math.isfinite(v) for v in target):
        raise ValueError("--target contains non-finite values")
    return target


def selected_sides(side: str) -> list[str]:
    if side == "both":
        return ["left", "right"]
    return [side]


def state_ok(state: object) -> bool:
    return (
        bool(getattr(state, "service_state", False))
        and bool(getattr(state, "valid", False))
        and str(getattr(state, "fsm_state", "")) == "IDLE"
        and str(getattr(state, "controller_state", "")) == "idle"
    )


def check_limits(target: Iterable[float]) -> None:
    for idx, (value, (low, high)) in enumerate(zip(target, ARM_JOINT_LIMITS, strict=True), start=1):
        if not (float(low) <= float(value) <= float(high)):
            raise ValueError(f"joint{idx} target {value:.6f} outside SDK limit [{low:.6f}, {high:.6f}]")


def read_angles(client: AirbotClient, side: str) -> np.ndarray:
    state = client.get_arm_joint_state()
    if state is None:
        raise RuntimeError(f"{side}: get_arm_joint_state() returned None")
    return np.asarray(state.angles, dtype=np.float64)


def print_pose(client: AirbotClient, side: str, label: str) -> None:
    pose = client.get_end_pose()
    print(f"{side} {label}_pose {pose}", flush=True)


def prepare_gripper_control(
    client: AirbotClient,
    side: str,
    args: argparse.Namespace,
    eef_switched: set[str] | None = None,
) -> int:
    mode = client.get_eef_mode()
    print(f"{side} eef_mode_before {mode}", flush=True)
    if mode is None:
        raise RuntimeError(f"{side}: get_eef_mode() returned None")
    if getattr(mode, "has_eef", True) is False:
        raise RuntimeError(f"{side}: SDK reports no EEF")

    state = client.get_eef_joint_state()
    print(f"{side} eef_joint_state_before {state}", flush=True)
    if state is None or getattr(state, "eef_pos", None) is None:
        raise RuntimeError(f"{side}: invalid EEF joint state")
    eef_dof = len(state.eef_pos)
    if eef_dof <= 0:
        raise RuntimeError(f"{side}: EEF DOF must be positive, got {eef_dof}")

    ok = client.switch_eef_control_mode(EEFControlMode.csp, timeout_ms=args.eef_timeout_ms)
    print(f"{side} switch_eef_csp {ok}", flush=True)
    if not ok:
        raise RuntimeError(f"{side}: switch_eef_control_mode(csp) returned False")
    if eef_switched is not None:
        eef_switched.add(side)
    ok = client.set_eef_speed(float(args.eef_speed_mm_s))
    print(f"{side} set_eef_speed {ok}", flush=True)
    if not ok:
        raise RuntimeError(f"{side}: set_eef_speed returned False")
    return eef_dof


def open_gripper(
    client: AirbotClient,
    side: str,
    *,
    eef_dof: int,
    args: argparse.Namespace,
    recorder: TrajectoryRecorder,
) -> None:
    pos = [float(args.gripper_open_mm)] * eef_dof
    options = EEFMoveOptions(eff=[float(args.eef_effort)] * eef_dof, blocking=True)
    recorder.write("gripper_command_sent", side=side, target_mm=pos)
    ok = client.move_eef(pos=pos, options=options, timeout_ms=args.eef_timeout_ms)
    print(f"{side} open_gripper pos_mm={pos} ok={ok}", flush=True)
    recorder.write("gripper_command_result", side=side, target_mm=pos, ok=bool(ok))
    if not ok:
        raise RuntimeError(f"{side}: move_eef(open) returned False")


def open_grippers_concurrently(
    clients: dict[str, AirbotClient],
    eef_dofs: dict[str, int],
    args: argparse.Namespace,
    recorder: TrajectoryRecorder,
) -> None:
    with ThreadPoolExecutor(max_workers=len(clients), thread_name_prefix="gripper-open") as executor:
        futures = {
            side: executor.submit(
                open_gripper,
                client,
                side,
                eef_dof=eef_dofs[side],
                args=args,
                recorder=recorder,
            )
            for side, client in clients.items()
        }
        for side, future in futures.items():
            try:
                future.result()
            except Exception as exc:
                raise RuntimeError(f"{side}: failed to open gripper") from exc


class TrajectoryRecorder:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._start_monotonic = time.monotonic()
        self._lock = threading.Lock()
        self._file = path.open("x", encoding="utf-8")

    def write(self, event: str, **fields: object) -> None:
        record = {
            "event": event,
            "wall_time_s": time.time(),
            "elapsed_s": time.monotonic() - self._start_monotonic,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            self._file.close()


def sample_joint_trajectory(
    client: AirbotClient,
    side: str,
    recorder: TrajectoryRecorder,
    stop_event: threading.Event,
    period_s: float,
) -> None:
    while True:
        try:
            angles = read_angles(client, side)
            recorder.write("trajectory_sample", side=side, angles_rad=angles.tolist())
        except Exception as exc:
            recorder.write("trajectory_sample_error", side=side, error=repr(exc))
        if stop_event.wait(period_s):
            return


def main() -> int:
    args = parse_args()
    if args.execute and not args.allow_robot_motion:
        print("REFUSE: --execute requires --allow-robot-motion")
        return 2
    target = np.asarray(parse_target(args.target), dtype=np.float64)
    check_limits(target)
    if args.trajectory_sample_period_s <= 0:
        print("REFUSE: --trajectory-sample-period-s must be positive")
        return 2
    sides = selected_sides(args.side)

    if args.speed_rad_s <= 0 or args.effort < 0:
        print("REFUSE: arm speed must be positive and effort must be non-negative")
        return 2
    if args.open_grippers:
        if not (0.0 <= args.gripper_open_mm <= 95.0):
            print("REFUSE: --gripper-open-mm must be in [0, 95]")
            return 2
        if args.eef_speed_mm_s <= 0 or args.eef_effort < 0 or args.eef_timeout_ms <= 0:
            print("REFUSE: EEF speed/timeout must be positive and effort must be non-negative")
            return 2

    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 1_000_000_000:09d}_{os.getpid()}"
    trajectory_path = args.trajectory_dir / f"joint_motion_{run_id}.jsonl"
    recorder = TrajectoryRecorder(trajectory_path)
    recorder.write(
        "run_start",
        execute=bool(args.execute),
        host=args.host,
        backend=args.backend,
        sides=sides,
        target_angles_rad=target.tolist(),
        speed_rad_s=float(args.speed_rad_s),
        effort=float(args.effort),
        open_grippers=bool(args.open_grippers),
        gripper_open_mm=float(args.gripper_open_mm),
        sample_period_s=float(args.trajectory_sample_period_s),
    )
    print(f"trajectory_log={trajectory_path}", flush=True)

    clients: dict[str, AirbotClient] = {}
    acquired: set[str] = set()
    switched: set[str] = set()
    eef_switched: set[str] = set()
    run_status = "failed"
    try:
        clients = {side: AirbotClient(host=args.host, port=PORTS[side], backend=args.backend) for side in sides}
        for side, client in clients.items():
            service_state = client.get_service_state()
            print(f"{side} state_before {service_state}", flush=True)
            if not state_ok(service_state):
                raise RuntimeError(f"{side}: not IDLE/idle/valid")
            angles = read_angles(client, side)
            delta = target - angles
            print(f"{side} current_angles_rad={angles.tolist()}", flush=True)
            print(f"{side} target_angles_rad={target.tolist()}", flush=True)
            print(f"{side} delta_rad={delta.tolist()} max_abs_delta_rad={float(np.max(np.abs(delta))):.6f}", flush=True)
            print_pose(client, side, "before")
            recorder.write(
                "state_before",
                side=side,
                service_state=repr(service_state),
                angles_rad=angles.tolist(),
                delta_to_target_rad=delta.tolist(),
            )
            if float(np.max(np.abs(delta))) > args.max_joint_delta_rad:
                raise RuntimeError(f"{side}: max joint delta exceeds guard {args.max_joint_delta_rad:.6f} rad")

        print(
            f"plan: controller=servo_control blocking=True speed_rad_s={args.speed_rad_s} "
            f"effort={args.effort}",
            flush=True,
        )
        if args.open_grippers:
            print(
                f"plan: concurrently open {sides} grippers to {args.gripper_open_mm:.3f} mm "
                f"at {args.eef_speed_mm_s:.3f} mm/s",
                flush=True,
            )
        if not args.execute:
            print(
                "DRY_RUN: no acquire_control(), switch_controller(), move_joint(), or move_eef() was called",
                flush=True,
            )
            run_status = "dry_run"
            return 0

        options = JointMoveOptions(eff=[float(args.effort)] * 7, blocking=True)
        for side, client in clients.items():
            ok = client.acquire_control(lease_ms=60000, renew_period_s=5.0)
            print(f"{side} acquire_control {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: acquire_control returned False")
            acquired.add(side)

        if args.open_grippers:
            eef_dofs = {}
            for side, client in clients.items():
                eef_dofs[side] = prepare_gripper_control(client, side, args, eef_switched)
            open_grippers_concurrently(clients, eef_dofs, args, recorder)

        for side in sides:
            client = clients[side]
            ok = client.switch_controller(Controller.servo_control, timeout_ms=args.motion_timeout_ms)
            print(f"{side} switch_servo {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: switch_controller(servo_control) returned False")
            switched.add(side)

            ok = client.set_arm_speed([float(args.speed_rad_s)] * 7)
            print(f"{side} set_arm_speed {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: set_arm_speed returned False")

            recorder.write(
                "command_sent",
                side=side,
                target_angles_rad=target.tolist(),
                controller="servo_control",
                blocking=True,
            )
            monitor_client = AirbotClient(host=args.host, port=PORTS[side], backend=args.backend)
            stop_event = threading.Event()
            sampler = threading.Thread(
                target=sample_joint_trajectory,
                args=(monitor_client, side, recorder, stop_event, float(args.trajectory_sample_period_s)),
                daemon=True,
            )
            sampler.start()
            try:
                ok = client.move_joint(target.tolist(), options=options, timeout_ms=args.motion_timeout_ms)
            finally:
                stop_event.set()
                sampler.join(timeout=max(1.0, 2.0 * float(args.trajectory_sample_period_s)))
                monitor_client.close()
            print(f"{side} move_joint_servo_blocking {ok}", flush=True)
            recorder.write("command_result", side=side, ok=bool(ok))
            if not ok:
                raise RuntimeError(f"{side}: move_joint returned False")
            time.sleep(args.settle_s)

            final_angles = read_angles(client, side)
            final_delta = target - final_angles
            print(f"{side} final_angles_rad={final_angles.tolist()}", flush=True)
            print(f"{side} final_error_rad={final_delta.tolist()} max_abs_error_rad={float(np.max(np.abs(final_delta))):.6f}", flush=True)
            print_pose(client, side, "after")
            recorder.write(
                "state_after",
                side=side,
                angles_rad=final_angles.tolist(),
                error_to_target_rad=final_delta.tolist(),
                max_abs_error_rad=float(np.max(np.abs(final_delta))),
            )

        run_status = "success"
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        recorder.write("error", error=repr(exc))
        return 1
    finally:
        for side in list(eef_switched):
            try:
                ok = clients[side].switch_eef_control_mode(EEFControlMode.idle, timeout_ms=args.eef_timeout_ms)
                print(f"{side} switch_eef_idle {ok}", flush=True)
            except Exception as exc:
                print(f"{side} switch_eef_idle_exception {exc!r}", file=sys.stderr, flush=True)
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
                state_final = client.get_service_state()
                print(f"{side} state_final {state_final}", flush=True)
                recorder.write("state_final", side=side, service_state=repr(state_final))
            except Exception as exc:
                print(f"{side} state_final_exception {exc!r}", file=sys.stderr, flush=True)
            client.close()
        recorder.write("run_end", status=run_status)
        recorder.close()


if __name__ == "__main__":
    raise SystemExit(main())
