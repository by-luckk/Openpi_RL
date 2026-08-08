#!/usr/bin/env python3
"""Resolve PTK camera roles to current V4L2 devices.

The kernel-assigned ``/dev/videoN`` number is not stable across USB
disconnects.  We therefore keep the role cache in terms of the physical
udev path, and return the corresponding V4L2 USB bus-info string.  The
AIRBOT V4L2 wrapper resolves that string to the current capture node.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

CACHE_DIR = Path.home() / ".cache" / "start_dual_robot_collection"
ROLE_CACHE = CACHE_DIR / "role_paths.txt"
BLACKLIST_CACHE = CACHE_DIR / "blacklist_paths.txt"
ROLE_ORDER = ("left", "right", "env")
INTERNAL_VENDOR_KEYS = (
    "HP_True_Vision_FHD_Camera",
    "Quanta",
    "Sonix_Technology_Co.__Ltd.",
)
INTERNAL_MODEL_KEYS = ("USB2.0_HD_UVC_WebCam",)


def video_index(path: Path) -> int:
    match = re.search(r"\d+", path.name)
    return int(match.group()) if match else -1


def list_video_devices() -> list[Path]:
    return sorted(
        (Path("/dev") / name for name in os.listdir("/dev") if re.fullmatch(r"video\d+", name)),
        key=video_index,
    )


def udev_properties(device: Path) -> dict[str, str]:
    try:
        output = subprocess.check_output(
            ["udevadm", "info", "--query=property", f"--name={device}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return {}
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def is_internal(properties: dict[str, str]) -> bool:
    vendor = properties.get("ID_VENDOR", "")
    model = properties.get("ID_MODEL", "")
    return any(key in vendor for key in INTERNAL_VENDOR_KEYS) or any(
        key in model for key in INTERNAL_MODEL_KEYS
    )


def bus_info(properties: dict[str, str]) -> str | None:
    """Convert a udev USB path to linuxpy's stable V4L2 bus-info format."""
    path = properties.get("ID_PATH", "")
    match = re.fullmatch(r"pci-(.+)-usb-0:([^:]+):\d+\.\d+", path)
    if match:
        return f"usb-{match.group(1)}-{match.group(2)}"
    return None


def grouped_cameras() -> tuple[list[dict], list[dict]]:
    external: dict[str, dict] = {}
    internal: dict[str, dict] = {}
    for index, device in enumerate(list_video_devices()):
        properties = udev_properties(device)
        path_tag = properties.get("ID_PATH_TAG") or properties.get("ID_PATH")
        camera_bus_info = bus_info(properties)
        if not path_tag or not camera_bus_info:
            continue
        record = {
            "path_tag": path_tag,
            "bus_info": camera_bus_info,
            "device": device,
            "index": index,
        }
        target = internal if is_internal(properties) else external
        previous = target.get(path_tag)
        if previous is None or video_index(device) < video_index(previous["device"]):
            target[path_tag] = record
    return (
        sorted(external.values(), key=lambda item: item["index"]),
        sorted(internal.values(), key=lambda item: item["index"]),
    )


def load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


def load_role_cache() -> dict[str, str]:
    return dict(line.split("=", 1) for line in load_lines(ROLE_CACHE) if "=" in line)


def save_role_cache(mapping: dict[str, str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Auto-generated. Delete this file to rediscover camera roles."]
    lines.extend(f"{role}={mapping[role]}" for role in ROLE_ORDER)
    ROLE_CACHE.write_text("\n".join(lines) + "\n")


def resolve_camera_roles() -> dict[str, str]:
    external, internal = grouped_cameras()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Keep this file as a diagnostic record, but never use old entries to
    # filter current devices. A camera can be moved to a different USB port,
    # making an old path that was internal belong to an external camera now.
    current_internal = sorted(camera["path_tag"] for camera in internal)
    BLACKLIST_CACHE.write_text(
        "\n".join(current_internal) + ("\n" if current_internal else "")
    )

    def rediscover() -> dict[str, str]:
        if len(external) != len(ROLE_ORDER):
            raise RuntimeError(f"Expected 3 external cameras, found {len(external)}")
        discovered = {role: camera["path_tag"] for role, camera in zip(ROLE_ORDER, external, strict=True)}
        save_role_cache(discovered)
        return discovered

    by_path = {camera["path_tag"]: camera["bus_info"] for camera in external}
    role_paths = load_role_cache()
    if not all(role in role_paths for role in ROLE_ORDER):
        role_paths = rediscover()
    missing = [role for role in ROLE_ORDER if role_paths[role] not in by_path]
    if missing:
        role_paths = rediscover()
    return {role: by_path[role_paths[role]] for role in ROLE_ORDER}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=("json", "lines"), default="json")
    args = parser.parse_args()
    try:
        mapping = resolve_camera_roles()
    except RuntimeError as exc:
        print(f"Camera detection failed: {exc}", file=sys.stderr)
        return 1
    if args.format == "lines":
        print(mapping["env"])
        print(mapping["left"])
        print(mapping["right"])
    else:
        print(json.dumps(mapping))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
