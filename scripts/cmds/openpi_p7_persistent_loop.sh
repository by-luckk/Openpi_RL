#!/usr/bin/env bash
# Persistent OpenPI -> AIRBOT P7 runner.
#
# This keeps ROS2 camera subscriptions, the policy WebSocket client, P7 SDK
# clients, and control leases alive inside one Python process. Default is dry-run.
set -euo pipefail

cd "$(dirname "$0")/../.."

SDK_PYTHON="${SDK_PYTHON:-.venv-p7-ros/bin/python}"
if [[ ! -x "$SDK_PYTHON" ]]; then
    echo "REFUSE: SDK python is not executable: $SDK_PYTHON" >&2
    exit 2
fi

exec "$SDK_PYTHON" examples/airbot/openpi_p7_persistent_loop.py "$@"
