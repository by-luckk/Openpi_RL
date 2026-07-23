"""Capture one ROS2 camera observation in the OpenPI AIRBOT key format.

Run this in the ROS2 environment, for example:

  ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
    mamba run -n ros2-topic python examples/airbot/capture_ros2_openpi_observation.py

The capture node and RGB conversion helpers are also imported by the persistent
inference loop and the live camera preview.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import Image

DEFAULT_TOPICS = {
    "base_0_rgb": "/camera/head_left/image_rect",
    "left_wrist_0_rgb": "/camera/left_arm_left/image_rect",
    "right_wrist_0_rgb": "/camera/right_arm_left/image_rect",
}
WRIST_CAMERA_KEYS = ("left_wrist_0_rgb", "right_wrist_0_rgb")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/openpi_real_observation_latest.npz"))
    parser.add_argument("--metadata-output", type=Path, default=Path("/tmp/openpi_real_observation_latest.json"))
    parser.add_argument("--timeout-s", type=float, default=8.0)
    parser.add_argument("--qos-reliability", choices=["best_effort", "reliable"], default="best_effort")
    parser.add_argument("--state-dim", type=int, default=16)
    parser.add_argument(
        "--wrist-only",
        action="store_true",
        help="Capture only left/right wrist cameras; do not subscribe to or wait for the head camera.",
    )
    for key, topic in DEFAULT_TOPICS.items():
        parser.add_argument(f"--{key}-topic", default=topic)
    return parser.parse_args()


def nv12_to_rgb(data: bytes, height: int, width: int) -> np.ndarray:
    expected = height * width * 3 // 2
    if len(data) < expected:
        raise ValueError(f"NV12 payload too short: got {len(data)} bytes, expected at least {expected}")

    raw = np.frombuffer(data[:expected], dtype=np.uint8)
    y = raw[: height * width].reshape(height, width).astype(np.int32)
    uv = raw[height * width :].reshape(height // 2, width // 2, 2).astype(np.int32)
    u = np.repeat(np.repeat(uv[:, :, 0], 2, axis=0), 2, axis=1)
    v = np.repeat(np.repeat(uv[:, :, 1], 2, axis=0), 2, axis=1)

    c = y - 16
    d = u - 128
    e = v - 128
    r = (298 * c + 409 * e + 128) >> 8
    g = (298 * c - 100 * d - 208 * e + 128) >> 8
    b = (298 * c + 516 * d + 128) >> 8
    return np.stack((r, g, b), axis=-1).clip(0, 255).astype(np.uint8)


def image_to_rgb(msg: Image) -> np.ndarray:
    encoding = msg.encoding.lower()
    height = int(msg.height)
    width = int(msg.width)
    data = bytes(msg.data)
    if encoding == "nv12":
        return nv12_to_rgb(data, height, width)
    if encoding == "rgb8":
        return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3).copy()
    if encoding == "bgr8":
        return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)[:, :, ::-1].copy()
    if encoding == "mono8":
        mono = np.frombuffer(data, dtype=np.uint8).reshape(height, width)
        return np.repeat(mono[:, :, None], 3, axis=2)
    raise ValueError(f"Unsupported image encoding {msg.encoding!r} for topic frame_id={msg.header.frame_id!r}")


class CaptureNode(Node):
    def __init__(self, topics: dict[str, str], *, qos_reliability: str) -> None:
        super().__init__("openpi_observation_capture")
        self.messages: dict[str, Image] = {}
        self.message_counts: dict[str, int] = {}
        self.topics = topics
        reliability = (
            ReliabilityPolicy.RELIABLE if qos_reliability == "reliable" else ReliabilityPolicy.BEST_EFFORT
        )
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=reliability,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._subs = [
            self.create_subscription(Image, topic, self._make_callback(key), qos) for key, topic in topics.items()
        ]

    def _make_callback(self, key: str):
        def callback(msg: Image) -> None:
            if key not in self.messages:
                self.get_logger().info(f"captured {key} frame {msg.width}x{msg.height} encoding={msg.encoding}")
            self.messages[key] = msg
            self.message_counts[key] = self.message_counts.get(key, 0) + 1

        return callback


def capture_fresh_rgb(
    node: CaptureNode,
    camera_keys: tuple[str, ...],
    *,
    timeout_s: float,
    previous_counts: dict[str, int] | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, object], dict[str, int]]:
    """Wait until every camera advances, then decode the latest messages in memory."""
    previous_counts = previous_counts or {}
    deadline = time.monotonic() + timeout_s
    while rclpy.ok() and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=min(0.1, max(0.0, deadline - time.monotonic())))
        if all(node.message_counts.get(key, 0) > previous_counts.get(key, 0) for key in camera_keys):
            break

    missing = [key for key in camera_keys if key not in node.messages]
    stalled = [
        key
        for key in camera_keys
        if key in node.messages and node.message_counts.get(key, 0) <= previous_counts.get(key, 0)
    ]
    if missing or stalled:
        raise RuntimeError(f"timed out waiting for fresh camera frames: missing={missing} stalled={stalled}")

    messages = {key: node.messages[key] for key in camera_keys}
    counts = {key: node.message_counts[key] for key in camera_keys}
    arrays = {key: image_to_rgb(messages[key]) for key in camera_keys}
    metadata: dict[str, object] = {
        "topics": {key: node.topics[key] for key in camera_keys},
        "capture_monotonic": time.monotonic(),
        "frames": {
            key: {
                "encoding": messages[key].encoding,
                "height": int(messages[key].height),
                "width": int(messages[key].width),
                "frame_id": messages[key].header.frame_id,
                "stamp_sec": int(messages[key].header.stamp.sec),
                "stamp_nanosec": int(messages[key].header.stamp.nanosec),
                "receive_count": counts[key],
                "rgb_shape": list(arrays[key].shape),
                "rgb_dtype": str(arrays[key].dtype),
            }
            for key in camera_keys
        },
    }
    return arrays, metadata, counts


def main() -> int:
    args = parse_args()
    camera_keys = WRIST_CAMERA_KEYS if args.wrist_only else tuple(DEFAULT_TOPICS)
    topics = {key: getattr(args, f"{key}_topic") for key in camera_keys}
    if args.state_dim <= 0:
        raise SystemExit("--state-dim must be positive")

    rclpy.init()
    node = CaptureNode(topics, qos_reliability=args.qos_reliability)
    try:
        try:
            arrays, capture_metadata, _ = capture_fresh_rgb(
                node,
                camera_keys,
                timeout_s=args.timeout_s,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        arrays["state"] = np.zeros(args.state_dim, dtype=np.float32)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.output, **arrays)

        metadata = {
            "topics": topics,
            "output": str(args.output),
            "qos_reliability": args.qos_reliability,
            "state_dim": args.state_dim,
            "frames": capture_metadata["frames"],
        }
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_output.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

        print(json.dumps(metadata, indent=2, ensure_ascii=False))
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
