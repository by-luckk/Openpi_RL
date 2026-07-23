import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

MODULE_PATH = Path(__file__).with_name("openpi_p7_persistent_loop.py")
SPEC = importlib.util.spec_from_file_location("openpi_p7_persistent_loop", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
persistent_loop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(persistent_loop)


def parse_args(monkeypatch, *args: str):
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), *args])
    return persistent_loop.parse_args()


def test_default_chunk_executes_first_15_actions_in_streaming_mode(monkeypatch):
    args = parse_args(monkeypatch)
    actions = np.zeros((50, 32), dtype=np.float64)

    persistent_loop.validate_args(args)
    assert args.chunk_start_index == 0
    assert args.chunk_steps == 15
    assert args.stream_action_chunk is True
    assert persistent_loop.selected_action_indices(actions, args) == list(range(15))


def test_motion_command_interval_cannot_be_less_than_four_ms(monkeypatch):
    args = parse_args(monkeypatch, "--min-motion-command-interval-s", "0.0039")

    with pytest.raises(RuntimeError, match="must be at least 0.004s"):
        persistent_loop.validate_args(args)


def test_rate_limiter_spaces_four_commands_by_at_least_four_ms(monkeypatch):
    now = 10.0
    starts: list[float] = []

    def monotonic() -> float:
        return now

    def sleep(duration: float) -> None:
        nonlocal now
        now += duration

    monkeypatch.setattr(persistent_loop.time, "monotonic", monotonic)
    monkeypatch.setattr(persistent_loop.time, "sleep", sleep)
    limiter = persistent_loop.MotionCommandRateLimiter(0.004)

    for _ in range(4):
        limiter.call(lambda: starts.append(now) is None)

    assert len(starts) == 4
    assert starts == pytest.approx([10.0, 10.004, 10.008, 10.012])
