#!/usr/bin/env bash
# Keyboard TCP teleoperation. Default is dry-run; pass motion flags explicitly.
set -euo pipefail

cd "$(dirname "$0")/../.."

SDK_PYTHON="${SDK_PYTHON:-.venv-p7-ros/bin/python}"
if [[ ! -x "$SDK_PYTHON" ]]; then
    echo "REFUSE: SDK python is not executable: $SDK_PYTHON" >&2
    exit 2
fi

exec "$SDK_PYTHON" examples/airbot/keyboard_dual_arm_teleop.py \
    --host "${P7_HOST:-192.168.25.1}" \
    --frame "${P7_TELEOP_FRAME:-world}" \
    --step-mm "${P7_TELEOP_STEP_MM:-5}" \
    --step-deg "${P7_TELEOP_STEP_DEG:-1}" \
    --arm-speed-rad-s "${P7_TELEOP_ARM_SPEED_RAD_S:-1.5}" \
    "$@"
