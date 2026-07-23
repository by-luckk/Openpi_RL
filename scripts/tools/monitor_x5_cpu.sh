#!/usr/bin/env bash
# 持续只读采样 AIRBOT X5 的整机 CPU、load average 和高 CPU 进程。
set -euo pipefail

HOST="${HOST:-root@192.168.25.1}"
INTERVAL_S="${INTERVAL_S:-5}"
OUTPUT="${OUTPUT:-}"
PID_FILE="${PID_FILE:-}"
MAX_SAMPLES=0

usage() {
    cat <<'EOF'
Usage: monitor_x5_cpu.sh [options]

Options:
  --host USER@HOST    SSH 目标（默认 root@192.168.25.1）
  --interval SEC      采样间隔秒数（默认 5）
  --output FILE       CSV 输出文件
  --pid-file FILE     PID 文件（默认与 CSV 同名，后缀为 .pid）
  --samples COUNT     写入 COUNT 条后退出（默认 0，持续运行）
  -h, --help          显示帮助

环境变量 HOST、INTERVAL_S、OUTPUT、PID_FILE 可作为同名参数的默认值。
EOF
}

while (($#)); do
    case "$1" in
        --host)
            HOST="$2"
            shift 2
            ;;
        --interval)
            INTERVAL_S="$2"
            shift 2
            ;;
        --output)
            OUTPUT="$2"
            shift 2
            ;;
        --pid-file)
            PID_FILE="$2"
            shift 2
            ;;
        --samples)
            MAX_SAMPLES="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "[x5-cpu] 未知参数: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! [[ "$INTERVAL_S" =~ ^[0-9]+([.][0-9]+)?$ ]] || ! awk -v value="$INTERVAL_S" 'BEGIN { exit !(value > 0) }'; then
    echo "[x5-cpu] --interval 必须大于 0: $INTERVAL_S" >&2
    exit 2
fi
if ! [[ "$MAX_SAMPLES" =~ ^[0-9]+$ ]]; then
    echo "[x5-cpu] --samples 必须是非负整数: $MAX_SAMPLES" >&2
    exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
if [[ -z "$OUTPUT" ]]; then
    OUTPUT="$REPO_ROOT/logs/x5_cpu/x5_cpu_$(date '+%Y%m%d_%H%M%S').csv"
fi
if [[ -z "$PID_FILE" ]]; then
    PID_FILE="${OUTPUT%.csv}.pid"
fi
EVENT_LOG="${OUTPUT%.csv}.events.log"

mkdir -p "$(dirname -- "$OUTPUT")" "$(dirname -- "$PID_FILE")"

if [[ -f "$PID_FILE" ]]; then
    read -r old_pid <"$PID_FILE" || true
    if [[ "${old_pid:-}" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
        echo "[x5-cpu] 已有监控进程运行: pid=$old_pid pid_file=$PID_FILE" >&2
        exit 1
    fi
fi
printf '%s\n' "$$" >"$PID_FILE"

cleanup() {
    if [[ -f "$PID_FILE" ]]; then
        read -r recorded_pid <"$PID_FILE" || true
        if [[ "${recorded_pid:-}" == "$$" ]]; then
            : >"$PID_FILE"
        fi
    fi
    printf '%s monitor_stopped pid=%s\n' "$(date -Iseconds)" "$$" >>"$EVENT_LOG"
}
trap cleanup EXIT INT TERM

if [[ ! -s "$OUTPUT" ]]; then
    printf '%s\n' \
        'timestamp,cpu_busy_pct,cpu_user_pct,cpu_nice_pct,cpu_system_pct,cpu_iowait_pct,cpu_irq_pct,cpu_softirq_pct,cpu_steal_pct,load1,load5,load15,runnable_tasks,total_tasks,top_processes_lifetime_pcpu' \
        >"$OUTPUT"
fi

printf '%s monitor_started pid=%s host=%s interval_s=%s output=%s\n' \
    "$(date -Iseconds)" "$$" "$HOST" "$INTERVAL_S" "$OUTPUT" >>"$EVENT_LOG"
echo "[x5-cpu] monitor_started pid=$$ host=$HOST interval_s=$INTERVAL_S"
echo "[x5-cpu] csv=$OUTPUT"
echo "[x5-cpu] events=$EVENT_LOG"

collect_sample() {
    ssh \
        -o BatchMode=yes \
        -o ConnectTimeout=5 \
        -o ServerAliveInterval=10 \
        -o ServerAliveCountMax=2 \
        "$HOST" \
        'LC_ALL=C; date "+%Y-%m-%dT%H:%M:%S%z"; head -n 1 /proc/stat; cat /proc/loadavg; ps -eo pid=,comm=,pcpu= --sort=-pcpu | head -n 6'
}

have_previous=0
previous_user=0
previous_nice=0
previous_system=0
previous_idle=0
previous_iowait=0
previous_irq=0
previous_softirq=0
previous_steal=0
written_samples=0

while :; do
    if ! sample="$(collect_sample 2>>"$EVENT_LOG")"; then
        printf '%s sample_error host=%s; retrying_in_s=%s\n' \
            "$(date -Iseconds)" "$HOST" "$INTERVAL_S" >>"$EVENT_LOG"
        have_previous=0
        sleep "$INTERVAL_S"
        continue
    fi

    mapfile -t sample_lines <<<"$sample"
    if ((${#sample_lines[@]} < 3)) || [[ "${sample_lines[1]}" != cpu\ * ]]; then
        printf '%s invalid_sample host=%s line_count=%s\n' \
            "$(date -Iseconds)" "$HOST" "${#sample_lines[@]}" >>"$EVENT_LOG"
        have_previous=0
        sleep "$INTERVAL_S"
        continue
    fi

    timestamp="${sample_lines[0]}"
    read -r _ user nice system idle iowait irq softirq steal _ <<<"${sample_lines[1]}"
    user="${user:-0}"
    nice="${nice:-0}"
    system="${system:-0}"
    idle="${idle:-0}"
    iowait="${iowait:-0}"
    irq="${irq:-0}"
    softirq="${softirq:-0}"
    steal="${steal:-0}"

    read -r load1 load5 load15 run_queue _ <<<"${sample_lines[2]}"
    runnable_tasks="${run_queue%/*}"
    total_tasks="${run_queue#*/}"

    top_processes=""
    for ((line_index = 3; line_index < ${#sample_lines[@]}; line_index++)); do
        read -r process_pid process_name process_pcpu <<<"${sample_lines[$line_index]}"
        [[ -n "${process_pid:-}" ]] || continue
        process_name="${process_name//\"/\'}"
        if [[ -n "$top_processes" ]]; then
            top_processes+=";"
        fi
        top_processes+="${process_pid}:${process_name}:${process_pcpu}%"
    done

    if ((have_previous)); then
        delta_user=$((user - previous_user))
        delta_nice=$((nice - previous_nice))
        delta_system=$((system - previous_system))
        delta_idle=$((idle - previous_idle))
        delta_iowait=$((iowait - previous_iowait))
        delta_irq=$((irq - previous_irq))
        delta_softirq=$((softirq - previous_softirq))
        delta_steal=$((steal - previous_steal))
        delta_total=$((delta_user + delta_nice + delta_system + delta_idle + delta_iowait + delta_irq + delta_softirq + delta_steal))

        if ((delta_total > 0)); then
            percentages="$(awk \
                -v total="$delta_total" \
                -v user="$delta_user" \
                -v nice="$delta_nice" \
                -v system_ticks="$delta_system" \
                -v idle="$delta_idle" \
                -v iowait="$delta_iowait" \
                -v irq="$delta_irq" \
                -v softirq="$delta_softirq" \
                -v steal="$delta_steal" \
                'BEGIN {
                    busy = total - idle - iowait
                    printf "%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f", \
                        100 * busy / total, 100 * user / total, 100 * nice / total, \
                        100 * system_ticks / total, 100 * iowait / total, 100 * irq / total, \
                        100 * softirq / total, 100 * steal / total
                }')"
            printf '%s,%s,%s,%s,%s,%s,%s,"%s"\n' \
                "$timestamp" "$percentages" "$load1" "$load5" "$load15" \
                "$runnable_tasks" "$total_tasks" "$top_processes" >>"$OUTPUT"
            written_samples=$((written_samples + 1))
            if ((MAX_SAMPLES > 0 && written_samples >= MAX_SAMPLES)); then
                break
            fi
        fi
    fi

    previous_user="$user"
    previous_nice="$nice"
    previous_system="$system"
    previous_idle="$idle"
    previous_iowait="$iowait"
    previous_irq="$irq"
    previous_softirq="$softirq"
    previous_steal="$steal"
    have_previous=1
    sleep "$INTERVAL_S"
done
