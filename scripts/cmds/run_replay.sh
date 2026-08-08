#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${REPLAY_PYTHON_BIN:-$project_dir/.venv/bin/python}"
turbojpeg_lib="$project_dir/.venv/local/usr/lib/x86_64-linux-gnu"
replay_script="$project_dir/scripts/cmds/replay_dual_arm.py"

if [[ ! -x "$python_bin" ]]; then
    echo "AIRDC Python environment not found: $python_bin" >&2
    exit 1
fi

if [[ -d "$turbojpeg_lib" ]]; then
    export LIBRARY_PATH="$turbojpeg_lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
    export LD_LIBRARY_PATH="$turbojpeg_lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

cd "$project_dir"
exec "$python_bin" "$replay_script" "$@"
