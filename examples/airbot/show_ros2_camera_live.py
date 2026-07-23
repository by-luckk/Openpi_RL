"""Show AIRBOT ROS2 cameras directly from memory and report receive/display Hz.

This tool subscribes to ``sensor_msgs/Image``, decodes the latest messages, and
passes them directly to OpenCV. It does not create a daemon or write images.
Press Q or Escape to stop before ``--duration-s`` expires.
"""

from __future__ import annotations

import argparse
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import Image

from capture_ros2_openpi_observation import image_to_rgb


DEFAULT_TOPICS = {
    "left_wrist": "/robot/camera/left_wrist/left/image",
    "right_wrist": "/robot/camera/right_wrist/left/image",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-s", type=float, default=15.0, help="0 runs until Q/Escape.")
    parser.add_argument("--reliability", choices=["best_effort", "reliable"], default="best_effort")
    parser.add_argument("--left-topic", default=DEFAULT_TOPICS["left_wrist"])
    parser.add_argument("--right-topic", default=DEFAULT_TOPICS["right_wrist"])
    return parser.parse_args()


class LiveCameraNode(Node):
    def __init__(self, topics: dict[str, str], reliability: str) -> None:
        super().__init__("airbot_camera_live_view")
        self.messages: dict[str, Image] = {}
        self.counts = {key: 0 for key in topics}
        self.first_received: dict[str, float] = {}
        self.last_received: dict[str, float] = {}
        rel = ReliabilityPolicy.RELIABLE if reliability == "reliable" else ReliabilityPolicy.BEST_EFFORT
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=rel,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._subscriptions = [
            self.create_subscription(Image, topic, self._callback(key), qos) for key, topic in topics.items()
        ]

    def _callback(self, key: str):
        def callback(msg: Image) -> None:
            now = time.monotonic()
            self.messages[key] = msg
            self.counts[key] += 1
            self.first_received.setdefault(key, now)
            self.last_received[key] = now

        return callback

    def receive_hz(self, key: str) -> float:
        count = self.counts[key]
        span = self.last_received.get(key, 0.0) - self.first_received.get(key, 0.0)
        return (count - 1) / span if count > 1 and span > 0 else 0.0


def add_label(rgb: np.ndarray, label: str) -> np.ndarray:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    cv2.putText(bgr, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 230, 20), 2, cv2.LINE_AA)
    return bgr


def main() -> int:
    args = parse_args()
    topics = {"left_wrist": args.left_topic, "right_wrist": args.right_topic}
    rclpy.init()
    node = LiveCameraNode(topics, args.reliability)
    started = time.monotonic()
    deadline = started + args.duration_s if args.duration_s > 0 else float("inf")
    last_display_counts = {key: 0 for key in topics}
    display_count = 0
    first_display = 0.0
    last_display = 0.0
    last_report = started
    window = "AIRBOT wrist cameras (Q/Esc to stop)"

    print(f"[camera-live] topics={topics} duration_s={args.duration_s:g}", flush=True)
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.02)
            if not all(key in node.messages for key in topics):
                continue
            if not all(node.counts[key] > last_display_counts[key] for key in topics):
                continue

            panels = []
            for key in topics:
                rgb = image_to_rgb(node.messages[key])
                panels.append(add_label(rgb, f"{key}  recv {node.receive_hz(key):.1f} Hz"))
                last_display_counts[key] = node.counts[key]
            tiled = np.concatenate(panels, axis=1)
            cv2.imshow(window, tiled)

            now = time.monotonic()
            display_count += 1
            first_display = first_display or now
            last_display = now
            if now - last_report >= 1.0:
                display_span = last_display - first_display
                display_hz = (display_count - 1) / display_span if display_count > 1 and display_span > 0 else 0.0
                rates = " ".join(f"{key}={node.receive_hz(key):.2f}Hz" for key in topics)
                print(f"[camera-live] {rates} display={display_hz:.2f}Hz", flush=True)
                last_report = now
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q"), 27):
                break
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()

    display_span = last_display - first_display
    display_hz = (display_count - 1) / display_span if display_count > 1 and display_span > 0 else 0.0
    print(
        "[camera-live] summary "
        + " ".join(f"{key}={node.counts[key]}frames/{node.receive_hz(key):.2f}Hz" for key in topics)
        + f" display={display_count}frames/{display_hz:.2f}Hz",
        flush=True,
    )
    return 0 if all(node.counts[key] > 0 for key in topics) else 1


if __name__ == "__main__":
    raise SystemExit(main())
