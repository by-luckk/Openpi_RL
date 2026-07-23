"""Show the exact 224x224 left/right wrist images prepared for OpenPI inference."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal

import cv2
import numpy as np


WINDOWS = {
    "left_wrist_0_rgb": "OpenPI Left Wrist Input",
    "right_wrist_0_rgb": "OpenPI Right Wrist Input",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--poll-period-s", type=float, default=0.02)
    parser.add_argument("--window-size", type=int, default=448)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.poll_period_s <= 0 or args.window_size <= 0:
        raise SystemExit("--poll-period-s and --window-size must be positive")

    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    for index, title in enumerate(WINDOWS.values()):
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(title, args.window_size, args.window_size)
        cv2.moveWindow(title, 20 + index * (args.window_size + 20), 60)

    last_mtime_ns = -1
    try:
        while running:
            try:
                mtime_ns = args.input.stat().st_mtime_ns
                if mtime_ns != last_mtime_ns:
                    with np.load(args.input) as data:
                        frames = {key: np.asarray(data[key]).copy() for key in WINDOWS}
                    for key, title in WINDOWS.items():
                        frame = frames[key]
                        if frame.shape != (224, 224, 3) or frame.dtype != np.uint8:
                            raise ValueError(f"{key} must be uint8 224x224x3 RGB, got {frame.shape} {frame.dtype}")
                        cv2.imshow(title, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                    last_mtime_ns = mtime_ns
            except FileNotFoundError:
                pass
            key = cv2.waitKey(max(1, int(args.poll_period_s * 1000))) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                os.kill(os.getppid(), signal.SIGTERM)
                running = False
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
