#!/usr/bin/env bash
# 本机一键启动双机械臂 airbot_server 服务。
# 只启动左右臂服务，不启动相机检测、yaml 改写或数据采集进程。
set -euo pipefail

# 可用环境变量覆盖默认值，例如：
#   PORT_LEFT=50051 CAN_LEFT=can2 bash scripts/cmds/start_dual_robot_services.sh
CAN_LEFT="${CAN_LEFT:-can0}"
CAN_RIGHT="${CAN_RIGHT:-can1}"
PORT_LEFT="${PORT_LEFT:-50050}"
PORT_RIGHT="${PORT_RIGHT:-50052}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-60}"
EXTRA_SLEEP_AFTER_PORT="${EXTRA_SLEEP_AFTER_PORT:-4}"

if [[ -z "${DISPLAY:-}" ]]; then
    echo "[start] DISPLAY is empty; gnome-terminal needs a graphical session." >&2
    exit 1
fi

for cmd in gnome-terminal airbot_server nc; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[start] command not found in PATH: $cmd" >&2
        exit 1
    fi
done

check_port() {
    local port=$1
    nc -z localhost "$port" 2>/dev/null
}

wait_for_dual_ports() {
    local start_time
    start_time=$(date +%s)

    echo "[start] 正在等待 ${PORT_LEFT}、${PORT_RIGHT} 端口监听开启..."
    while true; do
        local now elapsed
        now=$(date +%s)
        elapsed=$((now - start_time))

        if [[ "$elapsed" -ge "$WAIT_TIMEOUT" ]]; then
            echo "[ERROR] 端口监听等待超时，请检查 CAN 设备和 airbot_server 窗口日志" >&2
            exit 1
        fi

        if check_port "$PORT_LEFT" && check_port "$PORT_RIGHT"; then
            echo "[OK] 两端端口已开启监听"
            break
        fi

        sleep 1
    done

    echo "[start] 额外等待 ${EXTRA_SLEEP_AFTER_PORT} 秒，留给机器人硬件初始化握手..."
    sleep "$EXTRA_SLEEP_AFTER_PORT"

    echo "[start] 二次校验机器人服务连接可用性..."
    while true; do
        local now elapsed
        now=$(date +%s)
        elapsed=$((now - start_time))

        if [[ "$elapsed" -ge "$WAIT_TIMEOUT" ]]; then
            echo "[ERROR] 机器人服务始终无法连接，超时退出" >&2
            exit 1
        fi

        if check_port "$PORT_LEFT" && check_port "$PORT_RIGHT"; then
            echo "[OK] 双机械臂服务全部就绪"
            break
        fi

        echo "[wait] 服务尚未就绪，继续等待..."
        sleep 1
    done
}

echo "[start] 启动左臂 airbot_server: ${CAN_LEFT} -> ${PORT_LEFT}"
gnome-terminal --title="airbot-${CAN_LEFT}-${PORT_LEFT}" -- bash -c "
  echo '[airbot left] airbot_server -i ${CAN_LEFT} -p ${PORT_LEFT}'
  airbot_server -i '${CAN_LEFT}' -p '${PORT_LEFT}'
  echo '[airbot left] 服务退出，按回车关闭窗口'
  read
" >/dev/null 2>&1 &

echo "[start] 启动右臂 airbot_server: ${CAN_RIGHT} -> ${PORT_RIGHT}"
gnome-terminal --title="airbot-${CAN_RIGHT}-${PORT_RIGHT}" -- bash -c "
  echo '[airbot right] airbot_server -i ${CAN_RIGHT} -p ${PORT_RIGHT}'
  airbot_server -i '${CAN_RIGHT}' -p '${PORT_RIGHT}'
  echo '[airbot right] 服务退出，按回车关闭窗口'
  read
" >/dev/null 2>&1 &

wait_for_dual_ports

echo "====================================="
echo "双机械臂服务已启动"
echo "左臂: ${CAN_LEFT}  localhost:${PORT_LEFT}"
echo "右臂: ${CAN_RIGHT} localhost:${PORT_RIGHT}"
echo "未启动相机检测、yaml 改写或数据采集进程"
echo "====================================="
