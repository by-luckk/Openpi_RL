#!/usr/bin/env bash
# One-click PTK async inference with delta-pose DAgger takeover.
set -euo pipefail
cd "$(dirname "$0")/../.."

HOST=127.0.0.1
PORT=8000
PROMPT="make_coffee"
MAX_INFERENCE_RATE=2
STEP_RATE=200
INITIAL_ACTION_WAIT_S=1.0
TCS_MIN_OVERLAP=3
TCS_DROP_MAX=12
TAKEOVER_RATE=30
PROJECT_DIR=$(pwd)
RECORD_DIR="$PROJECT_DIR/inference_data/ptk_dagger"
PYTHON_BIN="${PTK_PYTHON_BIN:-python}"
AIRBOT_RUNTIME_IMAGE="${AIRBOT_RUNTIME_IMAGE:-registry.cn-shanghai.aliyuncs.com/discover-robotics/airbot-runtime:5.1.6}"

LEFT_LEADER_PORT=50050
RIGHT_LEADER_PORT=50052
LEFT_FOLLOWER_URL=192.168.209.101
RIGHT_FOLLOWER_URL=192.168.209.102
FOLLOWER_PORT=50051
WAIT_TIMEOUT=60
STARTED_SERVER_PIDS=()
STARTED_SERVER_CONTAINERS=()

mkdir -p logs "$RECORD_DIR"
LOG_FILE="logs/infer_async_ptk_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

for command_name in docker nc udevadm "$PYTHON_BIN"; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required command not found: $command_name" >&2
        exit 1
    fi
done

cleanup() {
    for container_name in "${STARTED_SERVER_CONTAINERS[@]}"; do
        docker kill "$container_name" >/dev/null 2>&1 || true
    done
    for pid in "${STARTED_SERVER_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT INT TERM

wait_for_port() {
    local host=$1
    local port=$2
    local label=$3
    local process_pid=${4:-}
    local process_log=${5:-}
    local deadline=$((SECONDS + WAIT_TIMEOUT))
    until nc -z -w 1 "$host" "$port" 2>/dev/null; do
        if [[ -n "$process_pid" ]] && ! kill -0 "$process_pid" 2>/dev/null; then
            echo "$label exited before opening $host:$port" >&2
            if [[ -n "$process_log" && -f "$process_log" ]]; then
                echo "Last lines from $process_log:" >&2
                tail -n 20 "$process_log" >&2
            fi
            return 1
        fi
        if ((SECONDS >= deadline)); then
            echo "Timed out waiting for $label at $host:$port" >&2
            return 1
        fi
        sleep 1
    done
}

start_leader_server() {
    local can_interface=$1
    local port=$2
    if nc -z -w 1 localhost "$port" 2>/dev/null; then
        echo "Reusing leader service on localhost:$port"
        return
    fi
    local launch_id
    launch_id=$(date +%Y%m%d_%H%M%S)
    local server_log="logs/airbot_${can_interface}_${port}_${launch_id}.log"
    local server_data_dir="$PROJECT_DIR/airbot_logs/${launch_id}_${can_interface}_${port}"
    local container_name="openpi-airbot-${can_interface}-${port}-$$"
    mkdir -p "$server_data_dir"
    echo "Starting leader service: $can_interface -> localhost:$port"
    # /usr/local/bin/airbot_server hard-codes `docker run -it`, which fails
    # as soon as it is backgrounded.  Run the same image without allocating a
    # TTY and give the container a stable name so cleanup is exact.
    docker run -i --rm \
        --name "$container_name" \
        --network=host \
        -v "$server_data_dir:/userdata" \
        "$AIRBOT_RUNTIME_IMAGE" \
        ros2 run fsm fsm_node -i "$can_interface" -p "$port" \
        >"$server_log" 2>&1 &
    local server_pid=$!
    STARTED_SERVER_PIDS+=("$server_pid")
    STARTED_SERVER_CONTAINERS+=("$container_name")
    wait_for_port localhost "$port" "leader service" "$server_pid" "$server_log"
}

start_leader_server can0 "$LEFT_LEADER_PORT"
start_leader_server can1 "$RIGHT_LEADER_PORT"
sleep 4
wait_for_port "$LEFT_FOLLOWER_URL" "$FOLLOWER_PORT" "left follower"
wait_for_port "$RIGHT_FOLLOWER_URL" "$FOLLOWER_PORT" "right follower"

mapfile -t CAMERA_DEVICES < <("$PYTHON_BIN" examples/airbot/ptk_camera_detect.py --format lines)
if [[ ${#CAMERA_DEVICES[@]} -ne 3 ]]; then
    echo "Camera detector did not return env/left/right devices" >&2
    exit 1
fi

echo "Camera mapping: base=${CAMERA_DEVICES[0]}, left=${CAMERA_DEVICES[1]}, right=${CAMERA_DEVICES[2]}"
echo "Logging to $LOG_FILE"

cd examples/airbot
"$PYTHON_BIN" airbot_inference_async.py \
    --policy-config.host "$HOST" \
    --policy-config.port "$PORT" \
    --prompt "$PROMPT" \
    --step-rate "$STEP_RATE" \
    --max-inference-rate "$MAX_INFERENCE_RATE" \
    --tcs-drop-max "$TCS_DROP_MAX" \
    --tcs-min-overlap "$TCS_MIN_OVERLAP" \
    --initial-action-wait-s "$INITIAL_ACTION_WAIT_S" \
    --record.record-data \
    --record.save-dir "$RECORD_DIR" \
    --dagger.enable \
    --dagger.takeover-mode delta_pose \
    --dagger.takeover-rate "$TAKEOVER_RATE" \
    --robot-config.robot-urls "$LEFT_FOLLOWER_URL" "$RIGHT_FOLLOWER_URL" \
    --robot-config.robot-ports "$FOLLOWER_PORT" "$FOLLOWER_PORT" \
    --robot-config.leader-urls localhost localhost \
    --robot-config.leader-ports "$LEFT_LEADER_PORT" "$RIGHT_LEADER_PORT" \
    --robot-config.camera-index "${CAMERA_DEVICES[0]}" "${CAMERA_DEVICES[1]}" "${CAMERA_DEVICES[2]}" \
    --robot-config.camera-fps 25 25 25
