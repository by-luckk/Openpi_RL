#!/usr/bin/env bash
# Move both Arm-P7 arms to the fixed ready pose. Running this script moves hardware.
set -euo pipefail

cd "$(dirname "$0")/../.."

SDK_PYTHON="${SDK_PYTHON:-.venv-p7-sdk/bin/python}"
if [[ ! -x "$SDK_PYTHON" ]]; then
    echo "REFUSE: SDK python is not executable: $SDK_PYTHON" >&2
    exit 2
fi

exec "$SDK_PYTHON" examples/airbot/p7_move_to_joint_target.py \
    --host "${P7_HOST:-192.168.25.1}" \
    --side "${P7_SIDE:-both}" \
    --target "0,0.647,0,-0.933,0,0,-1.15" \
    --speed-rad-s "${P7_ARM_SPEED_RAD_S:-0.55}" \
    --effort "${P7_ARM_EFFORT:-8}" \
    --max-joint-delta-rad 3.0 \
    --open-grippers \
    --gripper-open-mm "${P7_GRIPPER_OPEN_MM:-95}" \
    --eef-speed-mm-s "${P7_EEF_SPEED_MM_S:-80}" \
    --eef-effort "${P7_EEF_EFFORT:-5}" \
    --execute \
    --allow-robot-motion
