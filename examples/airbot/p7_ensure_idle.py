"""Best-effort P7 cleanup followed by strict IDLE/idle/valid verification."""

from __future__ import annotations

import argparse
import time

from arm_p7_sdk import AirbotClient
from arm_p7_sdk import Controller
from arm_p7_sdk import EEFControlMode


PORTS = {"left": 50071, "right": 50072}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.25.1")
    parser.add_argument("--acquire-timeout-s", type=float, default=10.0)
    parser.add_argument("--controller-timeout-ms", type=int, default=3000)
    return parser.parse_args()


def ready(state: object) -> bool:
    return (
        state is not None
        and bool(getattr(state, "service_state", False))
        and bool(getattr(state, "valid", False))
        and str(getattr(state, "fsm_state", "")) == "IDLE"
        and str(getattr(state, "controller_state", "")) == "idle"
    )


def eef_ready(mode: object) -> bool:
    if isinstance(mode, dict):
        return not mode.get("has_eef", True) or str(mode.get("current_mode_name", "")) == "idle"
    return not getattr(mode, "has_eef", True) or str(getattr(mode, "current_mode_name", "")) == "idle"


def acquire_with_retry(client: AirbotClient, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if client.acquire_control(lease_ms=15000, renew_period_s=5.0):
            return True
        time.sleep(0.25)
    return False


def main() -> int:
    args = parse_args()
    if args.acquire_timeout_s <= 0 or args.controller_timeout_ms <= 0:
        raise SystemExit("cleanup timeouts must be positive")

    clients: dict[str, AirbotClient] = {}
    try:
        for side, port in PORTS.items():
            client = AirbotClient(host=args.host, port=port, backend="grpc")
            clients[side] = client
            before = client.get_service_state()
            print(f"{side} ensure_idle_before {before}", flush=True)
            if not acquire_with_retry(client, args.acquire_timeout_s):
                raise RuntimeError(f"{side}: could not acquire control after {args.acquire_timeout_s:.1f}s")
            try:
                state = client.get_service_state()
                if str(getattr(state, "fsm_state", "")) == "UNKNOWN_ERROR":
                    print(f"{side} ensure_idle_clear_error {client.clear_error()}", flush=True)
                try:
                    result = client.switch_eef_control_mode(
                        EEFControlMode.idle,
                        timeout_ms=args.controller_timeout_ms,
                    )
                    print(f"{side} ensure_eef_idle {result}", flush=True)
                except Exception as exc:
                    print(f"{side} ensure_eef_idle_exception {exc!r}", flush=True)
                state = client.get_service_state()
                if not ready(state):
                    result = client.switch_controller(Controller.idle, timeout_ms=args.controller_timeout_ms)
                    print(f"{side} ensure_arm_idle {result}", flush=True)
            finally:
                client.release_control()
                print(f"{side} ensure_idle_release_control done", flush=True)

        deadline = time.monotonic() + 3.0
        states = {}
        eef_modes = {}
        while time.monotonic() < deadline:
            states = {side: client.get_service_state() for side, client in clients.items()}
            eef_modes = {side: client.get_eef_mode() for side, client in clients.items()}
            if all(ready(state) for state in states.values()) and all(
                eef_ready(mode) for mode in eef_modes.values()
            ):
                break
            time.sleep(0.1)
        for side, state in states.items():
            print(f"{side} ensure_idle_after {state}", flush=True)
            print(f"{side} ensure_eef_idle_after {eef_modes.get(side)}", flush=True)
        if (
            not states
            or not all(ready(state) for state in states.values())
            or not all(eef_ready(mode) for mode in eef_modes.values())
        ):
            raise RuntimeError("both arm and EEF controllers did not reach idle")
    finally:
        for client in clients.values():
            client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
