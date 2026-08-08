"""Pure helpers shared by AIRBOT delta-pose takeover paths."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

LEADER_EEF_RANGE = 0.0471
FOLLOWER_EEF_RANGE = 0.072


@dataclass(frozen=True)
class TakeoverReference:
    leader_position: tuple[float, float, float]
    leader_orientation: tuple[float, float, float, float]
    follower_position: tuple[float, float, float]
    follower_orientation: tuple[float, float, float, float]


@dataclass(frozen=True)
class LeaderState:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]
    eef_position: float


@dataclass(frozen=True)
class FollowerTarget:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]
    eef_position: float


def advance_takeover_deadline(deadline: float, now: float, period: float) -> tuple[float, float]:
    """Advance one takeover tick and skip any fully elapsed extra ticks."""
    if period <= 0:
        raise ValueError("Takeover period must be positive")

    deadline += period
    lag = max(0.0, now - deadline)
    if lag >= period:
        deadline += int(lag // period) * period
    return deadline, lag


def position_tuple(values) -> tuple[float, float, float]:
    position = np.asarray(values, dtype=np.float64)
    if position.shape != (3,) or not np.all(np.isfinite(position)):
        raise ValueError(f"Invalid end-effector position: {values}")
    return tuple(float(value) for value in position)


def quaternion_tuple(values) -> tuple[float, float, float, float]:
    quaternion = np.asarray(values, dtype=np.float64)
    if quaternion.shape != (4,) or not np.all(np.isfinite(quaternion)):
        raise ValueError(f"Invalid end-effector quaternion: {values}")
    norm = float(np.linalg.norm(quaternion))
    if norm < 1e-8:
        raise ValueError(f"End-effector quaternion norm is too small: {values}")
    quaternion /= norm
    return tuple(float(value) for value in quaternion)


def quaternion_multiply(quaternion1, quaternion0) -> np.ndarray:
    """Multiply xyzw quaternions using the AIRDC convention."""
    x0, y0, z0, w0 = quaternion0
    x1, y1, z1, w1 = quaternion1
    return np.asarray(
        (
            x1 * w0 + y1 * z0 - z1 * y0 + w1 * x0,
            -x1 * z0 + y1 * w0 + z1 * x0 + w1 * y0,
            x1 * y0 - y1 * x0 + z1 * w0 + w1 * z0,
            -x1 * x0 - y1 * y0 - z1 * z0 + w1 * w0,
        ),
        dtype=np.float64,
    )


def quaternion_inverse(quaternion) -> np.ndarray:
    quaternion = np.asarray(quaternion, dtype=np.float64)
    norm_squared = float(np.dot(quaternion, quaternion))
    if norm_squared < 1e-16:
        raise ValueError("Cannot invert a zero quaternion")
    conjugate = np.asarray((-quaternion[0], -quaternion[1], -quaternion[2], quaternion[3]))
    return conjugate / norm_squared


def delta_pose_target(reference: TakeoverReference, state: LeaderState) -> FollowerTarget:
    """Apply leader translation and rotation deltas to the follower zero pose."""
    leader_position = np.asarray(state.position, dtype=np.float64)
    leader_reference_position = np.asarray(reference.leader_position, dtype=np.float64)
    follower_reference_position = np.asarray(reference.follower_position, dtype=np.float64)
    target_position = follower_reference_position + leader_position - leader_reference_position

    leader_orientation = np.asarray(state.orientation, dtype=np.float64)
    leader_reference_orientation = np.asarray(reference.leader_orientation, dtype=np.float64)
    if np.dot(leader_orientation, leader_reference_orientation) < 0:
        leader_orientation = -leader_orientation
    delta_orientation = quaternion_multiply(
        leader_orientation,
        quaternion_inverse(leader_reference_orientation),
    )
    target_orientation = quaternion_multiply(delta_orientation, reference.follower_orientation)

    eef_position = float(
        np.clip(
            state.eef_position * FOLLOWER_EEF_RANGE / LEADER_EEF_RANGE,
            0.0,
            FOLLOWER_EEF_RANGE,
        )
    )
    return FollowerTarget(
        position=position_tuple(target_position),
        orientation=quaternion_tuple(target_orientation),
        eef_position=eef_position,
    )
