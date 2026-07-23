"""Benchmark OpenPI with one frozen observation and simulated P7 commands.

This script never imports the P7 SDK and never opens a robot connection. It
loads one observation into memory, repeatedly sends that same observation to a
local policy server, and counts the motion commands that the current
chunk_steps=1 interpolation path would have produced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from openpi.shared import airbot_policy_bridge as policy_bridge  # noqa: E402
from openpi.shared import airbot_relpose as relpose  # noqa: E402

WRIST_CAMERA_KEYS = ("left_wrist_0_rgb", "right_wrist_0_rgb")


def parse_pose(value: str) -> relpose.TcpPose:
    fields = [float(part.strip()) for part in value.split(",")]
    if len(fields) != 7:
        raise argparse.ArgumentTypeError("pose must contain x,y,z,qx,qy,qz,qw")
    return relpose.TcpPose.from_xyz_xyzw(fields)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation-npz", type=Path, required=True)
    parser.add_argument("--left-tcp", type=parse_pose, required=True)
    parser.add_argument("--right-tcp", type=parse_pose, required=True)
    parser.add_argument("--policy-host", default="127.0.0.1")
    parser.add_argument("--policy-port", type=int, default=8000)
    parser.add_argument("--prompt", default="put the plant into the collection box")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup-iterations", type=int, default=3)
    parser.add_argument("--chunk-steps", type=int, default=1)
    parser.add_argument("--max-step-translation-m", type=float, default=0.009)
    parser.add_argument("--max-step-rotation-rad", type=float, default=math.pi)
    parser.add_argument("--target-translation-tolerance-m", type=float, default=0.001)
    parser.add_argument("--target-rotation-tolerance-rad", type=float, default=0.005)
    parser.add_argument("--min-command-interval-s", type=float, default=0.004)
    parser.add_argument("--enable-gripper", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--report-every", type=int, default=10)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("/tmp/openpi_fixed_observation_smoke.json"),
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.iterations <= 0 or args.warmup_iterations < 0:
        raise ValueError("iterations must be positive and warmup-iterations must be non-negative")
    if args.chunk_steps <= 0:
        raise ValueError("chunk-steps must be positive")
    if args.max_step_translation_m <= 0 or args.max_step_rotation_rad <= 0:
        raise ValueError("interpolation limits must be positive")
    if args.min_command_interval_s < 0:
        raise ValueError("min-command-interval-s must be non-negative")
    if args.report_every < 0:
        raise ValueError("report-every must be non-negative")


def load_frozen_observation(path: Path, *, prompt: str) -> dict[str, Any]:
    with np.load(path) as data:
        missing = [key for key in (*WRIST_CAMERA_KEYS, "state") if key not in data]
        if missing:
            raise ValueError(f"{path} is missing keys: {missing}")
        observation: dict[str, Any] = {
            "state": np.asarray(data["state"], dtype=np.float32).copy(),
            "prompt": prompt,
            "advantage": False,
        }
        for key in WRIST_CAMERA_KEYS:
            image = np.asarray(data[key])
            if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
                raise ValueError(f"{key} must be uint8 HxWx3 RGB, got {image.shape} {image.dtype}")
            observation[key] = image.copy()
    return observation


def observation_sha256(observation: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for key in (*WRIST_CAMERA_KEYS, "state"):
        array = np.ascontiguousarray(observation[key])
        digest.update(key.encode("ascii"))
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
        digest.update(array.tobytes())
    digest.update(str(observation["prompt"]).encode("utf-8"))
    digest.update(str(bool(observation["advantage"])).encode("ascii"))
    return digest.hexdigest()


def command_count_for_target(
    start: relpose.TcpPose,
    target: relpose.ArmTcpTarget,
    args: argparse.Namespace,
) -> int:
    translation = float(np.linalg.norm(target.pose.position - start.position))
    rotation = relpose.quat_angular_distance_xyzw(start.quaternion_xyzw, target.pose.quaternion_xyzw)
    if (
        translation <= args.target_translation_tolerance_m
        and rotation <= args.target_rotation_tolerance_rad
    ):
        return 0
    return len(
        relpose.interpolate_tcp_poses(
            start,
            target.pose,
            max_translation_m=args.max_step_translation_m,
            max_rotation_rad=args.max_step_rotation_rad,
        )
    )


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def main() -> int:
    args = parse_args()
    validate_args(args)
    observation = load_frozen_observation(args.observation_npz, prompt=args.prompt)
    frozen_hash = observation_sha256(observation)
    frozen_poses = {"left": args.left_tcp, "right": args.right_tcp}

    from openpi_client import websocket_client_policy

    policy = websocket_client_policy.WebsocketClientPolicy(host=args.policy_host, port=args.policy_port)
    for warmup_index in range(args.warmup_iterations):
        response = policy.infer(observation)
        actions = np.asarray(response.get("actions"))
        if actions.ndim != 2 or actions.shape[1] < relpose.DUAL_ARM_ACTION_DIM:
            raise RuntimeError(f"invalid warmup action shape: {actions.shape}")
        print(f"warmup={warmup_index + 1} action_shape={list(actions.shape)}", flush=True)

    wall_latencies_s: list[float] = []
    server_latencies_ms: list[float] = []
    arm_command_counts: list[int] = []
    gripper_command_counts: list[int] = []
    action_shapes: set[tuple[int, ...]] = set()
    simulated_timeline_s = 0.0
    last_simulated_command_s = -math.inf
    benchmark_start = time.perf_counter()

    for iteration in range(1, args.iterations + 1):
        infer_start = time.perf_counter()
        response = policy.infer(observation)
        infer_elapsed_s = time.perf_counter() - infer_start
        actions = np.asarray(response.get("actions"), dtype=np.float64)
        if actions.ndim != 2 or actions.shape[1] < relpose.DUAL_ARM_ACTION_DIM:
            raise RuntimeError(f"invalid action shape: {actions.shape}")
        action_shapes.add(tuple(int(value) for value in actions.shape))

        selected_count = min(args.chunk_steps, int(actions.shape[0]))
        arm_commands = 0
        gripper_commands = 0
        for action_index in range(selected_count):
            action, _ = policy_bridge.select_action_step(actions, action_index=action_index)
            targets = relpose.convert_action_step(action, frozen_poses)
            arm_commands += command_count_for_target(frozen_poses["left"], targets.left, args)
            arm_commands += command_count_for_target(frozen_poses["right"], targets.right, args)
            if args.enable_gripper:
                gripper_commands += 2

        total_commands = arm_commands + gripper_commands
        simulated_timeline_s += infer_elapsed_s
        for _ in range(total_commands):
            command_time_s = max(
                simulated_timeline_s,
                last_simulated_command_s + args.min_command_interval_s,
            )
            last_simulated_command_s = command_time_s
            simulated_timeline_s = command_time_s

        wall_latencies_s.append(infer_elapsed_s)
        timing = response.get("server_timing") or {}
        if timing.get("infer_ms") is not None:
            server_latencies_ms.append(float(timing["infer_ms"]))
        arm_command_counts.append(arm_commands)
        gripper_command_counts.append(gripper_commands)

        if args.report_every and (iteration == 1 or iteration % args.report_every == 0):
            print(
                f"iteration={iteration} infer_ms={infer_elapsed_s * 1000:.3f} "
                f"arm_commands={arm_commands} gripper_commands={gripper_commands} "
                f"action_shape={list(actions.shape)}",
                flush=True,
            )

    benchmark_wall_s = time.perf_counter() - benchmark_start
    total_arm_commands = sum(arm_command_counts)
    total_gripper_commands = sum(gripper_command_counts)
    total_commands = total_arm_commands + total_gripper_commands
    avg_commands_per_iteration = total_commands / args.iterations
    inference_hz = args.iterations / benchmark_wall_s
    output_rows_per_second = (
        inference_hz * next(iter(action_shapes))[0] if len(action_shapes) == 1 else None
    )
    paced_one_hz_command_rate = avg_commands_per_iteration
    rate_limited_upper_bound_hz = (
        total_commands / simulated_timeline_s if simulated_timeline_s > 0 else 0.0
    )

    final_hash = observation_sha256(observation)
    if final_hash != frozen_hash:
        raise RuntimeError("the in-memory observation changed during the benchmark")

    result = {
        "safety": {
            "robot_sdk_imported": False,
            "robot_connection_opened": False,
            "control_commands_sent": 0,
            "simulation_only": True,
        },
        "policy": {
            "server": f"{args.policy_host}:{args.policy_port}",
            "server_metadata": policy.get_server_metadata(),
            "action_shapes": [list(shape) for shape in sorted(action_shapes)],
        },
        "frozen_input": {
            "observation_npz": str(args.observation_npz),
            "sha256_before": frozen_hash,
            "sha256_after": final_hash,
            "observation_shapes": {
                key: list(np.asarray(observation[key]).shape)
                for key in (*WRIST_CAMERA_KEYS, "state")
            },
            "left_tcp_xyz_xyzw": args.left_tcp.as_xyz_xyzw().tolist(),
            "right_tcp_xyz_xyzw": args.right_tcp.as_xyz_xyzw().tolist(),
        },
        "benchmark": {
            "warmup_iterations": args.warmup_iterations,
            "iterations": args.iterations,
            "wall_s": benchmark_wall_s,
            "inference_hz": inference_hz,
            "client_latency_ms": {
                "mean": statistics.fmean(wall_latencies_s) * 1000,
                "p50": percentile(wall_latencies_s, 50) * 1000,
                "p95": percentile(wall_latencies_s, 95) * 1000,
                "min": min(wall_latencies_s) * 1000,
                "max": max(wall_latencies_s) * 1000,
            },
            "server_infer_ms": {
                "mean": statistics.fmean(server_latencies_ms) if server_latencies_ms else None,
                "p50": percentile(server_latencies_ms, 50) if server_latencies_ms else None,
                "p95": percentile(server_latencies_ms, 95) if server_latencies_ms else None,
                "min": min(server_latencies_ms) if server_latencies_ms else None,
                "max": max(server_latencies_ms) if server_latencies_ms else None,
            },
            "predicted_action_rows_per_second_not_commands": output_rows_per_second,
        },
        "simulated_control": {
            "chunk_steps": args.chunk_steps,
            "max_step_translation_m": args.max_step_translation_m,
            "max_step_rotation_rad": args.max_step_rotation_rad,
            "min_command_interval_s": args.min_command_interval_s,
            "total_arm_commands": total_arm_commands,
            "total_gripper_commands": total_gripper_commands,
            "total_commands": total_commands,
            "average_commands_per_policy_iteration": avg_commands_per_iteration,
            "arm_commands_per_iteration": arm_command_counts,
            "gripper_commands_per_iteration": gripper_command_counts,
            "unpaced_command_demand_hz": total_commands / benchmark_wall_s,
            "rate_limited_zero_duration_rpc_upper_bound_hz": rate_limited_upper_bound_hz,
            "current_loop_period_1s_expected_command_hz": paced_one_hz_command_rate,
            "note": "Actual blocking P7 RPCs would make the command frequency lower than this simulated upper bound.",
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
