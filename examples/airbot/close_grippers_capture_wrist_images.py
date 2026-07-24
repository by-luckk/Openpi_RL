#!/usr/bin/env python3
"""Close both P7 grippers, then save all four wrist stereo images as JPEGs.

The default mode is a dry-run. Real gripper motion requires both
``--execute`` and ``--allow-robot-motion``. The script does not move the arms;
it only commands the EEF position before taking the camera snapshot.

Run this in the combined ROS2/P7 environment, for example:

  .venv-p7-ros/bin/python examples/airbot/close_grippers_capture_wrist_images.py \
    --execute --allow-robot-motion --output-prefix ./data/closed_wrist
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import time

from arm_p7_sdk import AirbotClient
from arm_p7_sdk import EEFControlMode
from arm_p7_sdk import EEFMoveOptions
from capture_ros2_openpi_observation import CaptureNode
from capture_ros2_openpi_observation import capture_fresh_rgb
import cv2
import rclpy

PORTS = {"left": 50071, "right": 50072}
WRIST_TOPICS = {
    "left_wrist_left_rgb": "/robot/camera/left_wrist/left/image",
    "left_wrist_right_rgb": "/robot/camera/left_wrist/right/image",
    "right_wrist_left_rgb": "/robot/camera/right_wrist/left/image",
    "right_wrist_right_rgb": "/robot/camera/right_wrist/right/image",
}


def configure_direct_grpc(host: str) -> list[str]:
    """Keep SDK gRPC traffic off local HTTP/SOCKS proxies."""
    proxy_variables = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    removed = [name for name in proxy_variables if os.environ.pop(name, None) is not None]
    for name in ("no_proxy", "NO_PROXY"):
        entries = [entry.strip() for entry in os.environ.get(name, "").split(",") if entry.strip()]
        if host not in entries:
            entries.append(host)
        os.environ[name] = ",".join(entries)
    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.25.1")
    parser.add_argument("--backend", default="grpc")
    parser.add_argument("--left-port", type=int, default=PORTS["left"])
    parser.add_argument("--right-port", type=int, default=PORTS["right"])
    parser.add_argument("--close-mm", type=float, default=0.0, help="Closed EEF target in mm (default: 0).")
    parser.add_argument("--eef-speed-mm-s", type=float, default=80.0)
    parser.add_argument("--eef-effort", type=float, default=5.0)
    parser.add_argument("--eef-timeout-ms", type=int, default=10000)
    parser.add_argument("--settle-s", type=float, default=1.0)
    parser.add_argument("--capture-timeout-s", type=float, default=8.0)
    parser.add_argument("--qos-reliability", choices=["best_effort", "reliable"], default="best_effort")
    for key, topic in WRIST_TOPICS.items():
        parser.add_argument(f"--{key.replace('_', '-')}-topic", default=topic)
    parser.add_argument("--output-prefix", type=Path, default=Path("./data/closed_wrist"))
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-robot-motion", action="store_true")
    return parser.parse_args()


def object_field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def service_state_ok(state: object) -> bool:
    return (
        bool(object_field(state, "service_state", default=False))
        and bool(object_field(state, "valid", default=False))
        and str(object_field(state, "fsm_state", "")) == "IDLE"
        and str(object_field(state, "controller_state", "")) == "idle"
    )


def prepare_eef(client: AirbotClient, side: str, args: argparse.Namespace) -> int:
    mode = client.get_eef_mode()
    print(f"{side} eef_mode_before {mode}", flush=True)
    if mode is None or object_field(mode, "has_eef", default=True) is False:
        raise RuntimeError(f"{side}: SDK reports no usable EEF")

    state = client.get_eef_joint_state()
    print(f"{side} eef_joint_state_before {state}", flush=True)
    eef_pos = object_field(state, "eef_pos")
    if eef_pos is None or len(eef_pos) <= 0:
        raise RuntimeError(f"{side}: EEF joint state has no positive DOF")
    eef_dof = len(eef_pos)

    ok = client.switch_eef_control_mode(EEFControlMode.csp, timeout_ms=args.eef_timeout_ms)
    print(f"{side} switch_eef_csp {ok}", flush=True)
    if not ok:
        raise RuntimeError(f"{side}: switch_eef_control_mode(csp) returned False")
    ok = client.set_eef_speed(args.eef_speed_mm_s)
    print(f"{side} set_eef_speed {ok}", flush=True)
    if not ok:
        raise RuntimeError(f"{side}: set_eef_speed returned False")
    return eef_dof


def close_one(client: AirbotClient, side: str, eef_dof: int, args: argparse.Namespace) -> bool:
    target = [args.close_mm] * eef_dof
    options = EEFMoveOptions(eff=[args.eef_effort] * eef_dof, blocking=True)
    ok = client.move_eef(pos=target, options=options, timeout_ms=args.eef_timeout_ms)
    print(f"{side} close_gripper pos_mm={target} ok={ok}", flush=True)
    if not ok:
        raise RuntimeError(f"{side}: move_eef(close) returned False")
    return bool(ok)


def close_grippers(args: argparse.Namespace) -> None:
    clients: dict[str, AirbotClient] = {}
    acquired: set[str] = set()
    eef_switched: set[str] = set()
    try:
        removed_proxy_variables = configure_direct_grpc(args.host)
        print(f"grpc_direct_host={args.host} removed_proxy_variables={removed_proxy_variables}", flush=True)
        for side, port in (("left", args.left_port), ("right", args.right_port)):
            clients[side] = AirbotClient(host=args.host, port=port, backend=args.backend)
        for side, client in clients.items():
            state = client.get_service_state()
            print(f"{side} service_state_before {state}", flush=True)
            if not service_state_ok(state):
                raise RuntimeError(f"{side}: service is not IDLE/idle/valid")

        for side, client in clients.items():
            ok = client.acquire_control(lease_ms=60000, renew_period_s=5.0)
            print(f"{side} acquire_control {ok}", flush=True)
            if not ok:
                raise RuntimeError(f"{side}: acquire_control returned False")
            acquired.add(side)

        eef_dofs: dict[str, int] = {}
        for side, client in clients.items():
            # Register before setup so a partial CSP setup is cleaned up on failure.
            eef_switched.add(side)
            eef_dofs[side] = prepare_eef(client, side, args)

        print(f"closing both grippers at {args.close_mm:.3f} mm", flush=True)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="close-gripper") as executor:
            futures = {
                side: executor.submit(close_one, client, side, eef_dofs[side], args)
                for side, client in clients.items()
            }
            for future in futures.values():
                future.result()
        if args.settle_s > 0:
            time.sleep(args.settle_s)
    finally:
        for side in eef_switched:
            try:
                ok = clients[side].switch_eef_control_mode(EEFControlMode.idle, timeout_ms=args.eef_timeout_ms)
                print(f"{side} switch_eef_idle {ok}", flush=True)
            except Exception as exc:
                print(f"{side} switch_eef_idle_exception {exc!r}", file=sys.stderr, flush=True)
        for side in acquired:
            try:
                clients[side].release_control()
                print(f"{side} release_control done", flush=True)
            except Exception as exc:
                print(f"{side} release_control_exception {exc!r}", file=sys.stderr, flush=True)
        for client in clients.values():
            client.close()


def save_wrist_images(args: argparse.Namespace) -> dict[str, object]:
    topics = {key: getattr(args, f"{key}_topic") for key in WRIST_TOPICS}
    node = None
    rclpy.init()
    try:
        node = CaptureNode(topics, qos_reliability=args.qos_reliability)
        images, capture_metadata, _ = capture_fresh_rgb(
            node,
            tuple(WRIST_TOPICS),
            timeout_s=args.capture_timeout_s,
        )
        args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality]
        outputs: dict[str, str] = {}
        image_bgrs: dict[str, object] = {}
        for key, image_rgb in images.items():
            path = args.output_prefix.with_name(f"{args.output_prefix.name}_{key}.jpg")
            image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
            if not cv2.imwrite(str(path), image_bgr, encode_params):
                raise RuntimeError(f"failed to write image: {path}")
            outputs[key] = str(path)
            image_bgrs[key] = image_bgr
            print(f"saved {key} -> {path}", flush=True)

        left_bgr = image_bgrs["left_wrist_left_rgb"]
        right_bgr = image_bgrs["right_wrist_right_rgb"]
        if left_bgr.shape[:2] != right_bgr.shape[:2]:
            right_bgr = cv2.resize(right_bgr, (left_bgr.shape[1], left_bgr.shape[0]), interpolation=cv2.INTER_AREA)
        overlay = cv2.addWeighted(left_bgr, 0.5, right_bgr, 0.5, 0.0)
        overlay_path = args.output_prefix.with_name(f"{args.output_prefix.name}_wrist_overlay.jpg")
        if not cv2.imwrite(str(overlay_path), overlay, encode_params):
            raise RuntimeError(f"failed to write overlay image: {overlay_path}")
        outputs["wrist_overlay"] = str(overlay_path)
        print(f"saved wrist_overlay -> {overlay_path}", flush=True)

        metadata = {
            "closed_target_mm": args.close_mm,
            "topics": topics,
            "images": outputs,
            "frames": capture_metadata["frames"],
        }
        metadata_path = args.output_prefix.with_name(f"{args.output_prefix.name}_metadata.json")
        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"saved metadata -> {metadata_path}", flush=True)
        return metadata
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main() -> int:
    args = parse_args()
    if args.close_mm < 0.0 or args.close_mm > 95.0:
        raise SystemExit("--close-mm must be in [0, 95] mm")
    if args.eef_speed_mm_s <= 0.0 or args.eef_effort < 0.0 or args.eef_timeout_ms <= 0:
        raise SystemExit("EEF speed must be positive, effort non-negative, and timeout positive")
    if args.settle_s < 0.0 or args.capture_timeout_s <= 0.0:
        raise SystemExit("settle time must be non-negative and capture timeout positive")
    if not 0 <= args.jpeg_quality <= 100:
        raise SystemExit("--jpeg-quality must be in [0, 100]")
    if not args.execute or not args.allow_robot_motion:
        print("DRY_RUN: no acquire_control() or move_eef() was called", flush=True)
        print("DRY_RUN: use --execute --allow-robot-motion to close both grippers and capture images", flush=True)
        return 0

    try:
        close_grippers(args)
        save_wrist_images(args)
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
