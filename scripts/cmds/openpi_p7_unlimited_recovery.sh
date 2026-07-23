#!/usr/bin/env bash
# Run OpenPI -> P7 and recover transient controller errors through the P7 SDK.
# This supervisor never starts or restarts robot-side applications. Each retry
# starts a new persistent-loop process, so actions from a failed run are never
# replayed. The initial attempt resets to the ready pose; recovered attempts
# resume from the current pose with a fresh observation and policy request.
set -uo pipefail

cd "$(dirname "$0")/../.."

ROBOT_HOST="${ROBOT_HOST:-192.168.25.1}"
SDK_PYTHON="${SDK_PYTHON:-.venv-p7-ros/bin/python}"
INNER_RUNNER="${INNER_RUNNER:-scripts/cmds/openpi_p7_persistent_loop.sh}"
RESET_RUNNER="${RESET_RUNNER:-scripts/cmds/move_p7_to_ready_joint_pose.sh}"
RESET_ARM_SPEED_RAD_S="${RESET_ARM_SPEED_RAD_S:-0.55}"
RESET_ARM_EFFORT="${RESET_ARM_EFFORT:-8}"
RECOVERY_DELAY_S="${RECOVERY_DELAY_S:-1}"
QUICK_RECOVERY_TIMEOUT_S="${QUICK_RECOVERY_TIMEOUT_S:-10}"
GRACEFUL_STOP_TIMEOUT_S="${GRACEFUL_STOP_TIMEOUT_S:-25}"
LOCAL_LOG_DIR="${LOCAL_LOG_DIR:-logs}"
SUPERVISOR_LOCK_FILE="${SUPERVISOR_LOCK_FILE:-/tmp/openpi_p7_unlimited_recovery.lock}"

mkdir -p "$LOCAL_LOG_DIR"
run_id="$(date +%Y%m%d_%H%M%S)"
log_file="$LOCAL_LOG_DIR/openpi_p7_recovery_${run_id}.log"
exec > >(tee "$log_file") 2>&1

runner_args=("$@")
duration_value_index=-1
duration_option_index=-1
duration_budget_s=""
for ((arg_index = 0; arg_index < ${#runner_args[@]}; arg_index++)); do
    if [[ "${runner_args[$arg_index]}" == "--duration-s" ]] && ((arg_index + 1 < ${#runner_args[@]})); then
        duration_value_index=$((arg_index + 1))
        duration_budget_s="${runner_args[$duration_value_index]}"
        break
    elif [[ "${runner_args[$arg_index]}" == --duration-s=* ]]; then
        duration_option_index=$arg_index
        duration_budget_s="${runner_args[$arg_index]#--duration-s=}"
        break
    fi
done

overall_deadline_epoch=0
if [[ -n "$duration_budget_s" ]] && awk -v value="$duration_budget_s" 'BEGIN { exit !(value > 0) }'; then
    duration_budget_ceil="$(awk -v value="$duration_budget_s" \
        'BEGIN { printf "%d", value == int(value) ? value : int(value) + 1 }')"
    overall_deadline_epoch=$(( $(date +%s) + duration_budget_ceil ))
fi

log() {
    printf '[openpi-p7-recovery] %s %s\n' "$(date '+%F %T %Z')" "$*"
}

exec {supervisor_lock_fd}>"$SUPERVISOR_LOCK_FILE"
if ! flock -n "$supervisor_lock_fd"; then
    log "REFUSE: another OpenPI P7 supervisor/control process still holds $SUPERVISOR_LOCK_FILE"
    exit 2
fi

existing_control_pids="$(pgrep -f '[o]penpi_p7_persistent_loop.py' || true)"
if [[ -n "$existing_control_pids" ]]; then
    log "REFUSE: existing OpenPI P7 control process(es) must be stopped first: ${existing_control_pids//$'\n'/,}"
    exit 2
fi

active_run_pid=""
keyboard_control_enabled=0

stop_active_run() {
    if [[ -n "$active_run_pid" ]] && kill -0 "$active_run_pid" 2>/dev/null; then
        # The persistent Python loop converts SIGTERM into a cleanup request.
        kill -TERM -- "-$active_run_pid" 2>/dev/null || true
        local deadline=$(( $(date +%s) + GRACEFUL_STOP_TIMEOUT_S ))
        while kill -0 "$active_run_pid" 2>/dev/null && (( $(date +%s) < deadline )); do
            sleep 0.1
        done
        if kill -0 "$active_run_pid" 2>/dev/null; then
            log "active robot-control process did not exit after ${GRACEFUL_STOP_TIMEOUT_S}s; sending SIGKILL"
            kill -KILL -- "-$active_run_pid" 2>/dev/null || true
        fi
        wait "$active_run_pid" 2>/dev/null || true
    fi
    active_run_pid=""
}

stop_supervisor() {
    trap - INT TERM
    log "stop requested; terminating the active robot-control process group"
    stop_active_run
    if ! quick_clear_robot_errors; then
        log "stop cleanup could not reach IDLE/idle/valid; robot-side applications were left untouched"
        exit 1
    fi
    log "graceful stop completed; both arm and EEF controllers are idle"
    exit 0
}

trap stop_supervisor INT TERM

quick_clear_robot_errors() {
    log "attempting quick SDK error clear"
    NO_PROXY="$ROBOT_HOST" no_proxy="$ROBOT_HOST" \
        timeout "${QUICK_RECOVERY_TIMEOUT_S}s" "$SDK_PYTHON" - "$ROBOT_HOST" <<'PY'
import sys
import time

from arm_p7_sdk import AirbotClient
from arm_p7_sdk import Controller
from arm_p7_sdk import EEFControlMode


def ready(state: object) -> bool:
    return (
        state is not None
        and bool(state.service_state)
        and bool(state.valid)
        and str(state.fsm_state) == "IDLE"
        and str(state.controller_state) == "idle"
    )


def eef_ready(mode: object) -> bool:
    if isinstance(mode, dict):
        return not mode.get("has_eef", True) or str(mode.get("current_mode_name", "")) == "idle"
    return not getattr(mode, "has_eef", True) or str(getattr(mode, "current_mode_name", "")) == "idle"


host = sys.argv[1]
clients = {}
try:
    for side, port in (("left", 50071), ("right", 50072)):
        client = AirbotClient(host=host, port=port, backend="grpc")
        clients[side] = client
        before = client.get_service_state()
        print(f"{side} quick_recovery_before {before}", flush=True)
        # IDLE does not prove that a killed client released its control lease.
        # Acquire and release once so a stale owner cannot trigger a retry loop.
        acquired = client.acquire_control(lease_ms=15000, renew_period_s=5.0)
        print(f"{side} quick_recovery_acquire_control {acquired}", flush=True)
        if not acquired:
            raise RuntimeError(f"{side}: quick recovery could not acquire control")
        try:
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                state = client.get_service_state()
                print(f"{side} quick_recovery_poll {state}", flush=True)
                eef_mode = client.get_eef_mode()
                if not eef_ready(eef_mode):
                    try:
                        result = client.switch_eef_control_mode(EEFControlMode.idle, timeout_ms=3000)
                        print(f"{side} quick_recovery_switch_eef_idle {result}", flush=True)
                    except Exception as exc:
                        print(f"{side} quick_recovery_switch_eef_idle_exception {exc!r}", flush=True)
                if ready(state) and eef_ready(client.get_eef_mode()):
                    break
                if str(state.fsm_state) == "UNKNOWN_ERROR":
                    try:
                        print(f"{side} quick_recovery_clear_error {client.clear_error()}", flush=True)
                    except Exception as exc:
                        print(f"{side} quick_recovery_clear_error_exception {exc!r}", flush=True)
                elif (
                    str(state.controller_state) != "idle"
                    or str(state.fsm_state) in {"SERVO_CONTROL", "PLANNING_CONTROL"}
                ):
                    try:
                        result = client.switch_controller(Controller.idle, timeout_ms=3000)
                        print(f"{side} quick_recovery_switch_arm_idle {result}", flush=True)
                    except Exception as exc:
                        print(f"{side} quick_recovery_switch_arm_idle_exception {exc!r}", flush=True)
                time.sleep(0.2)
            if not (ready(client.get_service_state()) and eef_ready(client.get_eef_mode())):
                raise RuntimeError(f"{side}: quick recovery did not reach arm/eef idle")
        finally:
            try:
                client.release_control()
                print(f"{side} quick_recovery_release_control done", flush=True)
            except Exception as exc:
                print(f"{side} quick_recovery_release_control_exception {exc!r}", flush=True)

    deadline = time.monotonic() + 4.0
    states = {}
    eef_modes = {}
    while time.monotonic() < deadline:
        states = {side: client.get_service_state() for side, client in clients.items()}
        eef_modes = {side: client.get_eef_mode() for side, client in clients.items()}
        if all(ready(state) for state in states.values()) and all(eef_ready(mode) for mode in eef_modes.values()):
            break
        time.sleep(0.1)

    for side, state in states.items():
        print(f"{side} quick_recovery_after {state}", flush=True)
        print(f"{side} quick_recovery_eef_after {eef_modes.get(side)}", flush=True)
    if (
        not states
        or not all(ready(state) for state in states.values())
        or not all(eef_ready(mode) for mode in eef_modes.values())
    ):
        raise RuntimeError("quick recovery did not reach arm/eef idle on both sides")
finally:
    for client in clients.values():
        client.close()
PY
}

reset_to_initial_joint_pose() {
    log "resetting both arms and opening both grippers before inference target_rad=[0,0.647,0,-0.933,0,0,-1.15]"
    P7_HOST="$ROBOT_HOST" \
        P7_SIDE=both \
        P7_ARM_SPEED_RAD_S="$RESET_ARM_SPEED_RAD_S" \
        P7_ARM_EFFORT="$RESET_ARM_EFFORT" \
        setsid "$RESET_RUNNER" &
    active_run_pid=$!
    if wait "$active_run_pid"; then
        active_run_pid=""
        log "pre-inference joint reset completed"
        return 0
    else
        local rc=$?
        active_run_pid=""
        log "pre-inference joint reset failed rc=$rc; policy inference was not started"
        return "$rc"
    fi
}

return_to_initial_pose() {
    log "space pressed; stopping inference before returning to the initial pose"
    stop_active_run
    if ! quick_clear_robot_errors; then
        log "space-key cleanup could not reach IDLE/idle/valid; refusing to start the reset motion"
        return 1
    fi
    if reset_to_initial_joint_pose; then
        log "space-key return completed; recapturing observation and continuing inference"
        return 0
    fi
    log "space-key return failed; inference remains stopped"
    return 1
}

configure_keyboard_control() {
    if [[ ! -t 0 ]]; then
        log "stdin is not an interactive terminal; keyboard controls are disabled"
        return
    fi
    keyboard_control_enabled=1
    log "keyboard control enabled: Space returns home and continues; Q gracefully stops in IDLE"
}

wait_for_inference() {
    if (( ! keyboard_control_enabled )); then
        wait "$active_run_pid"
        return $?
    fi

    while kill -0 "$active_run_pid" 2>/dev/null; do
        local key=""
        if IFS= read -rsn1 -t 0.1 key; then
            case "$key" in
                " ") return 200 ;;
                q|Q) return 201 ;;
            esac
        fi
    done
    wait "$active_run_pid"
}

configure_keyboard_control

attempt=0
resume_in_place=0
log "starting unlimited-recovery supervisor; log=$log_file"
if ((overall_deadline_epoch > 0)); then
    log "overall duration budget=${duration_budget_s}s includes reset and recovery time"
fi
while true; do
    if ((overall_deadline_epoch > 0 && $(date +%s) >= overall_deadline_epoch)); then
        log "overall duration budget completed before the next attempt"
        exit 0
    fi
    attempt=$(( attempt + 1 ))
    log "preparing inference attempt=$attempt"
    if ((resume_in_place)); then
        log "recovered controller is IDLE/idle/valid; skipping reset and resuming from the current pose"
        resume_in_place=0
    else
        if ! reset_to_initial_joint_pose; then
            if quick_clear_robot_errors; then
                log "quick recovery reached IDLE/idle/valid; next attempt will resume from the current pose"
                resume_in_place=1
                sleep "$RECOVERY_DELAY_S"
                continue
            fi
            log "pre-inference reset recovery failed; robot-side applications were left untouched; manual recovery is required"
            exit 1
        fi
    fi
    log "inference attempt=$attempt"
    if ((overall_deadline_epoch > 0)); then
        remaining_s=$((overall_deadline_epoch - $(date +%s)))
        if ((remaining_s <= 0)); then
            log "overall duration budget completed before inference"
            exit 0
        fi
        if ((duration_value_index >= 0)); then
            runner_args[$duration_value_index]="$remaining_s"
        else
            runner_args[$duration_option_index]="--duration-s=$remaining_s"
        fi
        log "inference remaining_duration_s=$remaining_s"
    fi
    OPENPI_P7_SUPERVISOR_PID=$$ NO_PROXY="$ROBOT_HOST" no_proxy="$ROBOT_HOST" \
        setsid "$INNER_RUNNER" "${runner_args[@]}" &
    active_run_pid=$!
    if wait_for_inference; then
        active_run_pid=""
        log "inference completed successfully on attempt=$attempt; confirming idle before exit"
        if quick_clear_robot_errors; then
            log "graceful stop completed; both arm and EEF controllers are idle"
            exit 0
        fi
        log "inference completed, but shutdown could not confirm IDLE/idle/valid"
        exit 1
    else
        rc=$?
        if (( rc == 200 )); then
            if return_to_initial_pose; then
                resume_in_place=1
                continue
            fi
            exit 1
        fi
        if (( rc == 201 )); then
            log "Q pressed; gracefully stopping inference"
            stop_active_run
            if quick_clear_robot_errors; then
                log "graceful stop completed; both arm and EEF controllers are idle"
                exit 0
            fi
            log "graceful stop could not confirm IDLE/idle/valid"
            exit 1
        fi
        active_run_pid=""
    fi

    # The failed inner process is gone, so its in-memory action chunk cannot be
    # replayed. Keep JSON files only as diagnostics; the next attempt captures
    # a fresh observation and requests a new policy chunk.
    log "inference failed rc=$rc; discarded the failed attempt's local policy action chunk"
    if (( rc == 130 )); then
        log "inner process requested a graceful stop"
        if quick_clear_robot_errors; then
            log "graceful stop completed; both arm and EEF controllers are idle"
            exit 0
        fi
        log "graceful stop could not confirm IDLE/idle/valid"
        exit 1
    fi
    if (( rc == 3 )); then
        log "unsafe measured motion/guard violation; stopping without automatic recovery"
        exit "$rc"
    fi

    if quick_clear_robot_errors; then
        log "quick recovery reached IDLE/idle/valid; next attempt will resume in place, recapture observation, and re-infer"
        resume_in_place=1
        sleep "$RECOVERY_DELAY_S"
        continue
    fi
    log "quick recovery failed; robot-side applications were left untouched; manual recovery is required"
    exit "$rc"
done
