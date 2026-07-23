import numpy as np

from openpi.shared import airbot_policy_bridge as bridge


def test_select_action_step_accepts_single_action_row():
    row = np.zeros(14, dtype=np.float64)
    row[6] = 50

    action, shape = bridge.select_action_step(row)

    assert shape == (1, 14)
    assert action.shape == (14,)
    assert action[6] == 50


def test_select_action_step_rejects_bad_shape():
    with np.testing.assert_raises_regex(ValueError, "actions must be shape"):
        bridge.select_action_step(np.zeros((2, 13)))


def test_action_index_bounds_are_checked():
    with np.testing.assert_raises_regex(IndexError, "out of range"):
        bridge.select_action_step(np.zeros((2, 14)), action_index=2)
