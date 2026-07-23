#!/usr/bin/env bash
# Gracefully stop all local OpenPI P7 inference processes and verify robot idle.
set -uo pipefail

cd "$(dirname "$0")/../.."

ROBOT_HOST="${ROBOT_HOST:-192.168.25.1}"
SDK_PYTHON="${SDK_PYTHON:-.venv-p7-sdk/bin/python}"
STOP_TIMEOUT_S="${STOP_TIMEOUT_S:-25}"

mapfile -t supervisor_pids < <(pgrep -f '[o]penpi_p7_unlimited_recovery.sh' || true)
mapfile -t control_pids < <(pgrep -f '[o]penpi_p7_persistent_loop.py' || true)

printf '[openpi-p7-stop] supervisors=%s controls=%s\n' \
    "${supervisor_pids[*]:-none}" "${control_pids[*]:-none}"

for pid in "${supervisor_pids[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
done
for pid in "${control_pids[@]}"; do
    parent_pid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
    if [[ " ${supervisor_pids[*]} " == *" $parent_pid "* ]]; then
        continue
    fi
    pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
    if [[ -n "$pgid" ]]; then
        kill -TERM -- "-$pgid" 2>/dev/null || true
    fi
done

deadline=$(( $(date +%s) + STOP_TIMEOUT_S ))
while (( $(date +%s) < deadline )); do
    if ! pgrep -f '[o]penpi_p7_unlimited_recovery.sh|[o]penpi_p7_persistent_loop.py' >/dev/null; then
        break
    fi
    sleep 0.1
done

mapfile -t remaining_pids < <(pgrep -f '[o]penpi_p7_unlimited_recovery.sh|[o]penpi_p7_persistent_loop.py' || true)
if ((${#remaining_pids[@]})); then
    printf '[openpi-p7-stop] graceful timeout; force-stopping remaining pids=%s\n' "${remaining_pids[*]}" >&2
    for pid in "${remaining_pids[@]}"; do
        command_line="$(ps -o args= -p "$pid" 2>/dev/null)"
        if [[ "$command_line" == *openpi_p7_persistent_loop.py* ]]; then
            pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
            if [[ -n "$pgid" ]]; then
                kill -KILL -- "-$pgid" 2>/dev/null || true
            fi
        else
            kill -KILL "$pid" 2>/dev/null || true
        fi
    done
fi

if ! NO_PROXY="$ROBOT_HOST" no_proxy="$ROBOT_HOST" \
    "$SDK_PYTHON" examples/airbot/p7_ensure_idle.py --host "$ROBOT_HOST"; then
    printf '[openpi-p7-stop] failed: could not confirm both arm and EEF controllers are idle\n' >&2
    exit 1
fi
printf '[openpi-p7-stop] complete: both arm and EEF controllers are idle\n'
