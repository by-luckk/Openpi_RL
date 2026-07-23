#!/usr/bin/env python3
"""Record the three OpenPI camera topics to mp4 files.

This script is intentionally read-only: it subscribes to ROS2 image topics and
writes one mp4 per camera plus a side-by-side triptych video. It never talks to
the robot control SDK.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image


DEFAULT_TOPICS = {
    "base_0_rgb": "/robot/camera/head/left/image",
    "left_wrist_0_rgb": "/robot/camera/left_wrist/left/image",
    "right_wrist_0_rgb": "/robot/camera/right_wrist/left/image",
}


def nv12_to_rgb(data: bytes, height: int, width: int) -> np.ndarray:
    expected = height * width * 3 // 2
    if len(data) < expected:
        raise RuntimeError(f"NV12 payload too small: got {len(data)}, expected {expected}")
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
    raise RuntimeError(f"unsupported encoding: {msg.encoding}")


class Recorder(Node):
    def __init__(self, topics: dict[str, str]) -> None:
        super().__init__("openpi_camera_video_recorder")
        self.messages: dict[str, Image] = {}
        self.counts = {key: 0 for key in topics}
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._subs = [self.create_subscription(Image, topic, self._callback(key), qos) for key, topic in topics.items()]

    def _callback(self, key: str):
        def callback(msg: Image) -> None:
            if key not in self.messages:
                self.get_logger().info(f"first {key}: {msg.width}x{msg.height} {msg.encoding} frame_id={msg.header.frame_id}")
            self.messages[key] = msg
            self.counts[key] += 1

        return callback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-s", type=float, default=180.0)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--warmup-timeout-s", type=float, default=10.0)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--wrist-only", action="store_true")
    for key, topic in DEFAULT_TOPICS.items():
        parser.add_argument(f"--{key}-topic", default=topic)
    return parser.parse_args()


def release_writers(writers: dict[str, cv2.VideoWriter]) -> None:
    for writer in writers.values():
        writer.release()


def main() -> int:
    args = parse_args()
    topics = {key: getattr(args, f"{key}_topic") for key in DEFAULT_TOPICS}
    if args.wrist_only:
        topics = {key: topic for key, topic in topics.items() if key != "base_0_rgb"}
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    rclpy.init()
    node = Recorder(topics)
    writers: dict[str, cv2.VideoWriter] = {}
    frames_written = 0
    interrupted = False

    try:
        deadline = time.monotonic() + args.warmup_timeout_s
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if all(key in node.messages for key in topics):
                break
        missing = [key for key in topics if key not in node.messages]
        if missing:
            raise SystemExit(f"missing camera topics: {missing}")

        first = {key: image_to_rgb(node.messages[key]) for key in topics}
        height, width = next(iter(first.values())).shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        for key in topics:
            path = args.output_prefix.with_name(args.output_prefix.name + f"_{key}.mp4")
            writers[key] = cv2.VideoWriter(str(path), fourcc, args.fps, (width, height))
            if not writers[key].isOpened():
                raise SystemExit(f"failed to open writer for {key}: {path}")
        tiled_path = args.output_prefix.with_name(args.output_prefix.name + "_tiled.mp4")
        writers["tiled"] = cv2.VideoWriter(str(tiled_path), fourcc, args.fps, (width * len(topics), height))
        if not writers["tiled"].isOpened():
            raise SystemExit(f"failed to open tiled writer: {tiled_path}")

        next_write = time.monotonic()
        end = time.monotonic() + args.duration_s
        while rclpy.ok() and time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.002)
            now = time.monotonic()
            if now < next_write:
                continue
            rgbs = {key: image_to_rgb(node.messages[key]) for key in topics}
            bgrs = {key: cv2.cvtColor(rgbs[key], cv2.COLOR_RGB2BGR) for key in topics}
            for key in topics:
                writers[key].write(bgrs[key])
            writers["tiled"].write(np.concatenate([bgrs[key] for key in topics], axis=1))
            frames_written += 1
            next_write += 1.0 / args.fps
    except KeyboardInterrupt:
        interrupted = True
    finally:
        release_writers(writers)
        meta = {
            "duration_s": args.duration_s,
            "fps": args.fps,
            "frames_written": frames_written,
            "interrupted": interrupted,
            "raw_message_counts": node.counts,
            "topics": topics,
            "streams": {
                key: {
                    "encoding": node.messages[key].encoding,
                    "width": int(node.messages[key].width),
                    "height": int(node.messages[key].height),
                    "frame_id": node.messages[key].header.frame_id,
                }
                for key in topics if key in node.messages
            },
            "output_prefix": str(args.output_prefix),
        }
        meta_path = args.output_prefix.with_name(args.output_prefix.name + "_metadata.json")
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        print(json.dumps(meta, indent=2, ensure_ascii=False), flush=True)
        node.destroy_node()
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass
    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
