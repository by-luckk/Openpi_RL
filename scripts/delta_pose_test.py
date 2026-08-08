from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from examples.airbot.dagger_controller import DaggerConfig
from examples.airbot.dagger_controller import DaggerController
from examples.airbot.dagger_controller import DaggerMode
from examples.airbot.delta_pose import LeaderState
from examples.airbot.delta_pose import TakeoverReference
from examples.airbot.delta_pose import advance_takeover_deadline
from examples.airbot.delta_pose import delta_pose_target


def test_zero_delta_keeps_follower_pose() -> None:
    reference = TakeoverReference(
        leader_position=(0.1, 0.2, 0.3),
        leader_orientation=(0.0, 0.0, 0.0, 1.0),
        follower_position=(0.4, 0.5, 0.6),
        follower_orientation=(0.0, 0.0, 0.0, 1.0),
    )
    target = delta_pose_target(
        reference,
        LeaderState(
            position=reference.leader_position,
            orientation=reference.leader_orientation,
            eef_position=0.0471,
        ),
    )
    assert np.allclose(target.position, reference.follower_position)
    assert np.allclose(target.orientation, reference.follower_orientation)
    assert target.eef_position == 0.072


def test_translation_and_rotation_delta_are_applied() -> None:
    half_turn_z = (0.0, 0.0, np.sqrt(0.5), np.sqrt(0.5))
    reference = TakeoverReference(
        leader_position=(0.0, 0.0, 0.0),
        leader_orientation=(0.0, 0.0, 0.0, 1.0),
        follower_position=(1.0, 2.0, 3.0),
        follower_orientation=(0.0, 0.0, 0.0, 1.0),
    )
    target = delta_pose_target(
        reference,
        LeaderState(position=(0.1, -0.2, 0.3), orientation=half_turn_z, eef_position=-1.0),
    )
    assert np.allclose(target.position, (1.1, 1.8, 3.3))
    assert np.allclose(target.orientation, half_turn_z)
    assert target.eef_position == 0.0


def test_quaternion_sign_flip_does_not_change_target() -> None:
    reference = TakeoverReference(
        leader_position=(0.0, 0.0, 0.0),
        leader_orientation=(0.0, 0.0, 0.0, 1.0),
        follower_position=(0.0, 0.0, 0.0),
        follower_orientation=(0.0, 0.0, 0.0, 1.0),
    )
    target = delta_pose_target(
        reference,
        LeaderState(position=(0.0, 0.0, 0.0), orientation=(0.0, 0.0, 0.0, -1.0), eef_position=0.0),
    )
    assert np.allclose(target.orientation, (0.0, 0.0, 0.0, 1.0))


def test_delta_takeover_state_flow() -> None:
    controller = DaggerController(DaggerConfig(takeover_mode="delta_pose"))
    controller.request_intervention()
    assert controller.mode == DaggerMode.ZEROING
    assert controller.inference_paused

    controller.request_zero_reference()
    assert controller.consume_zero_request()
    assert not controller.consume_zero_request()
    controller.begin_delta_demonstration()
    assert controller.mode == DaggerMode.DEMONSTRATING

    controller.request_resume()
    assert controller.mode == DaggerMode.RESUMING
    controller.complete_resume()
    assert controller.mode == DaggerMode.INFERENCE
    assert not controller.inference_paused


def test_takeover_deadline_does_not_accumulate_steady_overrun() -> None:
    period = 1.0 / 30.0
    deadline = 0.0
    now = 0.0
    worst_lag = 0.0

    for _ in range(1_000):
        now += 0.040
        deadline, lag = advance_takeover_deadline(deadline, now, period)
        worst_lag = max(worst_lag, lag)

    assert worst_lag < 2 * period
    assert worst_lag < 0.250


def test_takeover_deadline_exposes_a_real_stall() -> None:
    period = 1.0 / 30.0
    deadline = 10.0
    now = deadline + period + 0.251

    _next_deadline, lag = advance_takeover_deadline(deadline, now, period)

    assert lag > 0.250


def test_takeover_deadline_skips_expired_ticks_monotonically() -> None:
    period = 1.0 / 30.0
    deadline = 10.0
    now = 10.140

    next_deadline, lag = advance_takeover_deadline(deadline, now, period)

    assert lag >= period
    assert next_deadline > deadline
    assert 0.0 <= now - next_deadline < period


def main() -> None:
    tests = (
        test_zero_delta_keeps_follower_pose,
        test_translation_and_rotation_delta_are_applied,
        test_quaternion_sign_flip_does_not_change_target,
        test_delta_takeover_state_flow,
        test_takeover_deadline_does_not_accumulate_steady_overrun,
        test_takeover_deadline_exposes_a_real_stall,
        test_takeover_deadline_skips_expired_ticks_monotonically,
    )
    for test in tests:
        test()
    print(f"{len(tests)} delta-pose tests passed")


if __name__ == "__main__":
    main()
