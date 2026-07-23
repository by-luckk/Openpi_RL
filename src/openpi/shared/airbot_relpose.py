"""Utilities for deploying AIRBOT TCP-local relpose actions.

The VIO checkpoint predicts one action chunk in the same representation used by
``scripts/vio_preview_converter.py`` on the training server:

- left arm: local TCP delta position (3), local TCP delta rotvec (3), gripper
- right arm: same 7 values

Every row in a predicted chunk is relative to the observation TCP pose at the
chunk start. The rows are not chained together.
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
import math
from typing import Any

import numpy as np

ARM_ORDER = ("left", "right")
DUAL_ARM_ACTION_DIM = 14
MODEL_ACTION_DIM = 32
POSE_DIM = 7
GRIPPER_MODEL_MAX = 100.0
G2P_MAX_M = 0.096


@dataclasses.dataclass(frozen=True)
class TcpPose:
    """TCP pose with position in meters and quaternion in xyzw order."""

    position: np.ndarray
    quaternion_xyzw: np.ndarray

    def __post_init__(self) -> None:
        position = _as_vector(self.position, 3, "position")
        quaternion = normalize_quat_xyzw(self.quaternion_xyzw)
        object.__setattr__(self, "position", position)
        object.__setattr__(self, "quaternion_xyzw", quaternion)

    @classmethod
    def from_xyz_xyzw(cls, value: np.ndarray | list[float] | tuple[float, ...]) -> TcpPose:
        arr = _as_vector(value, POSE_DIM, "pose")
        return cls(position=arr[:3], quaternion_xyzw=arr[3:])

    def as_xyz_xyzw(self) -> np.ndarray:
        return np.concatenate([self.position, self.quaternion_xyzw]).astype(np.float64)


@dataclasses.dataclass(frozen=True)
class ArmRelposeAction:
    """One arm's model action in TCP-local relpose coordinates."""

    delta_position_local: np.ndarray
    delta_rotvec_local: np.ndarray
    gripper_model: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "delta_position_local", _as_vector(self.delta_position_local, 3, "delta_position_local"))
        object.__setattr__(self, "delta_rotvec_local", _as_vector(self.delta_rotvec_local, 3, "delta_rotvec_local"))
        gripper = float(self.gripper_model)
        if not math.isfinite(gripper):
            raise ValueError(f"gripper_model must be finite, got {self.gripper_model!r}")
        object.__setattr__(self, "gripper_model", gripper)


@dataclasses.dataclass(frozen=True)
class GripperTarget:
    """Gripper target represented in all units used by current candidate transports."""

    model_0_100: float
    ratio_0_1: float
    g2p_m: float
    p7_mm: float


@dataclasses.dataclass(frozen=True)
class ArmTcpTarget:
    """Transport-independent target for one arm."""

    pose: TcpPose
    gripper: GripperTarget


@dataclasses.dataclass(frozen=True)
class DualArmTcpTarget:
    """Transport-independent target for both AIRBOT arms."""

    left: ArmTcpTarget
    right: ArmTcpTarget

    def as_pose_arrays(self) -> dict[str, np.ndarray]:
        return {"left": self.left.pose.as_xyz_xyzw(), "right": self.right.pose.as_xyz_xyzw()}


def normalize_quat_xyzw(quat: np.ndarray | list[float] | tuple[float, ...]) -> np.ndarray:
    quat_arr = _as_vector(quat, 4, "quaternion_xyzw")
    norm = float(np.linalg.norm(quat_arr))
    if norm < 1e-12:
        raise ValueError(f"Invalid near-zero quaternion: {quat_arr}")
    normalized = quat_arr / norm
    if normalized[3] < 0:
        normalized = -normalized
    return normalized


def quat_conjugate_xyzw(quat: np.ndarray | list[float] | tuple[float, ...]) -> np.ndarray:
    q = normalize_quat_xyzw(quat)
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype=np.float64)


def quat_multiply_xyzw(
    left: np.ndarray | list[float] | tuple[float, ...],
    right: np.ndarray | list[float] | tuple[float, ...],
) -> np.ndarray:
    """Compose two active rotations represented as xyzw quaternions."""

    x1, y1, z1, w1 = normalize_quat_xyzw(left)
    x2, y2, z2, w2 = normalize_quat_xyzw(right)
    return normalize_quat_xyzw(
        np.array(
            [
                w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
                w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            ],
            dtype=np.float64,
        )
    )


def quat_rotate_xyzw(quat: np.ndarray | list[float] | tuple[float, ...], vector: np.ndarray | list[float]) -> np.ndarray:
    """Apply an xyzw quaternion rotation to a 3D vector."""

    q = normalize_quat_xyzw(quat)
    v = _as_vector(vector, 3, "vector")
    q_xyz = q[:3]
    q_w = q[3]
    # Equivalent to q * [v, 0] * conj(q), without constructing two quaternions.
    t = 2.0 * np.cross(q_xyz, v)
    return v + q_w * t + np.cross(q_xyz, t)


def rotvec_to_quat_xyzw(rotvec: np.ndarray | list[float]) -> np.ndarray:
    rv = _as_vector(rotvec, 3, "rotvec")
    angle = float(np.linalg.norm(rv))
    scale = 0.5 if angle < 1e-12 else math.sin(angle * 0.5) / angle
    return normalize_quat_xyzw(np.array([rv[0] * scale, rv[1] * scale, rv[2] * scale, math.cos(angle * 0.5)]))


def quat_to_rotvec_xyzw(quat: np.ndarray | list[float] | tuple[float, ...]) -> np.ndarray:
    q = normalize_quat_xyzw(quat)
    # Match scipy Rotation.as_rotvec() principal-rotation behavior for q and -q.
    if q[3] < 0:
        q = -q
    sin_half = float(np.linalg.norm(q[:3]))
    if sin_half < 1e-12:
        return 2.0 * q[:3]
    angle = 2.0 * math.atan2(sin_half, float(q[3]))
    return q[:3] * (angle / sin_half)


def quat_angular_distance_xyzw(
    left: np.ndarray | list[float] | tuple[float, ...],
    right: np.ndarray | list[float] | tuple[float, ...],
) -> float:
    """Return the shortest angular distance between two orientations."""

    q0 = normalize_quat_xyzw(left)
    q1 = normalize_quat_xyzw(right)
    dot = min(1.0, max(-1.0, float(np.dot(q0, q1))))
    return 2.0 * math.acos(abs(dot))


def slerp_quat_xyzw(
    start: np.ndarray | list[float] | tuple[float, ...],
    target: np.ndarray | list[float] | tuple[float, ...],
    fraction: float,
) -> np.ndarray:
    """Spherically interpolate xyzw quaternions along the shortest arc."""

    t = float(fraction)
    if not math.isfinite(t) or not 0.0 <= t <= 1.0:
        raise ValueError(f"fraction must be finite and in [0, 1], got {fraction!r}")
    q0 = normalize_quat_xyzw(start)
    q1 = normalize_quat_xyzw(target)
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        return normalize_quat_xyzw(q0 + t * (q1 - q0))
    angle = math.acos(dot)
    sin_angle = math.sin(angle)
    start_scale = math.sin((1.0 - t) * angle) / sin_angle
    target_scale = math.sin(t * angle) / sin_angle
    return normalize_quat_xyzw(start_scale * q0 + target_scale * q1)


def interpolate_tcp_poses(
    start: TcpPose | np.ndarray | list[float] | tuple[float, ...],
    target: TcpPose | np.ndarray | list[float] | tuple[float, ...],
    *,
    max_translation_m: float,
    max_rotation_rad: float,
) -> list[TcpPose]:
    """Generate bounded TCP waypoints, excluding start and including target."""

    start_pose = as_tcp_pose(start)
    target_pose = as_tcp_pose(target)
    translation_limit = float(max_translation_m)
    rotation_limit = float(max_rotation_rad)
    if not math.isfinite(translation_limit) or translation_limit <= 0.0:
        raise ValueError(f"max_translation_m must be finite and positive, got {max_translation_m!r}")
    if not math.isfinite(rotation_limit) or rotation_limit <= 0.0:
        raise ValueError(f"max_rotation_rad must be finite and positive, got {max_rotation_rad!r}")

    translation = float(np.linalg.norm(target_pose.position - start_pose.position))
    rotation = quat_angular_distance_xyzw(start_pose.quaternion_xyzw, target_pose.quaternion_xyzw)
    if translation < 1e-12 and rotation < 1e-12:
        return []
    segment_count = max(
        1,
        math.ceil(translation / translation_limit),
        math.ceil(rotation / rotation_limit),
    )
    return [
        TcpPose(
            position=start_pose.position + (target_pose.position - start_pose.position) * (index / segment_count),
            quaternion_xyzw=slerp_quat_xyzw(
                start_pose.quaternion_xyzw,
                target_pose.quaternion_xyzw,
                index / segment_count,
            ),
        )
        for index in range(1, segment_count + 1)
    ]


def integrate_tcp_local_delta(
    current_pose: TcpPose | np.ndarray | list[float] | tuple[float, ...],
    delta_position_local: np.ndarray | list[float],
    delta_rotvec_local: np.ndarray | list[float],
) -> TcpPose:
    """Convert one TCP-local delta into an absolute target TCP pose.

    This is the inverse of the training converter's relpose formula:
    ``dp_local = cur_R.inv().apply(fut_p - cur_p)`` and
    ``dr_local = (cur_R.inv() * fut_R).as_rotvec()``.
    """

    current = as_tcp_pose(current_pose)
    dp_local = _as_vector(delta_position_local, 3, "delta_position_local")
    dr_local = _as_vector(delta_rotvec_local, 3, "delta_rotvec_local")
    target_position = current.position + quat_rotate_xyzw(current.quaternion_xyzw, dp_local)
    target_quat = quat_multiply_xyzw(current.quaternion_xyzw, rotvec_to_quat_xyzw(dr_local))
    return TcpPose(target_position, target_quat)


def relative_action_from_poses(current_pose: TcpPose, future_pose: TcpPose) -> np.ndarray:
    """Return the 6D TCP-local relpose action used during VIO training."""

    current = as_tcp_pose(current_pose)
    future = as_tcp_pose(future_pose)
    inv_current = quat_conjugate_xyzw(current.quaternion_xyzw)
    dp_local = quat_rotate_xyzw(inv_current, future.position - current.position)
    dq_local = quat_multiply_xyzw(inv_current, future.quaternion_xyzw)
    dr_local = quat_to_rotvec_xyzw(dq_local)
    return np.concatenate([dp_local, dr_local]).astype(np.float64)


def split_dual_arm_action(action: np.ndarray | list[float] | tuple[float, ...]) -> dict[str, ArmRelposeAction]:
    """Split one padded or unpadded model action row into left/right arm actions."""

    arr = np.asarray(action, dtype=np.float64)
    if arr.ndim != 1 or arr.shape[0] < DUAL_ARM_ACTION_DIM:
        raise ValueError(f"action must be a 1D array with at least {DUAL_ARM_ACTION_DIM} values, got shape {arr.shape}")
    if not np.all(np.isfinite(arr[:DUAL_ARM_ACTION_DIM])):
        raise ValueError("action contains non-finite values in the first 14 dimensions")
    return {
        "left": ArmRelposeAction(arr[0:3], arr[3:6], float(arr[6])),
        "right": ArmRelposeAction(arr[7:10], arr[10:13], float(arr[13])),
    }


def gripper_target_from_model_value(
    value: float,
    *,
    g2p_max_m: float = G2P_MAX_M,
    clamp: bool = True,
) -> GripperTarget:
    """Convert model gripper value to ratio, G2P meters, and P7 SDK millimeters.

    Model convention: 0 is closed, 100 is maximally open.
    """

    model_value = float(value)
    if not math.isfinite(model_value):
        raise ValueError(f"gripper value must be finite, got {value!r}")
    if clamp:
        model_value = min(max(model_value, 0.0), GRIPPER_MODEL_MAX)
    ratio = model_value / GRIPPER_MODEL_MAX
    return GripperTarget(
        model_0_100=model_value,
        ratio_0_1=ratio,
        g2p_m=float(g2p_max_m) * ratio,
        p7_mm=float(g2p_max_m) * 1000.0 * ratio,
    )


def convert_action_step(
    action: np.ndarray | list[float] | tuple[float, ...],
    current_tcp_poses: Mapping[str, TcpPose | np.ndarray | list[float] | tuple[float, ...]],
    *,
    g2p_max_m: float = G2P_MAX_M,
    clamp_gripper: bool = True,
) -> DualArmTcpTarget:
    """Convert one model action row into absolute TCP targets for both arms."""

    poses = _normalize_pose_mapping(current_tcp_poses)
    arm_actions = split_dual_arm_action(action)
    targets: dict[str, ArmTcpTarget] = {}
    for arm in ARM_ORDER:
        arm_action = arm_actions[arm]
        target_pose = integrate_tcp_local_delta(
            poses[arm], arm_action.delta_position_local, arm_action.delta_rotvec_local
        )
        targets[arm] = ArmTcpTarget(
            pose=target_pose,
            gripper=gripper_target_from_model_value(
                arm_action.gripper_model, g2p_max_m=g2p_max_m, clamp=clamp_gripper
            ),
        )
    return DualArmTcpTarget(left=targets["left"], right=targets["right"])


def convert_action_chunk(
    actions: np.ndarray | list[list[float]],
    current_tcp_poses: Mapping[str, TcpPose | np.ndarray | list[float] | tuple[float, ...]],
    *,
    g2p_max_m: float = G2P_MAX_M,
    clamp_gripper: bool = True,
) -> list[DualArmTcpTarget]:
    """Convert a model action chunk into absolute targets.

    All rows are interpreted relative to the same current observation pose. This
    matches the training converter, which builds every future horizon step from
    the sample-time TCP pose rather than chaining row i onto row i-1.
    """

    arr = np.asarray(actions, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] < DUAL_ARM_ACTION_DIM:
        raise ValueError(
            f"actions must be a 2D array with at least {DUAL_ARM_ACTION_DIM} columns, got shape {arr.shape}"
        )
    poses = _normalize_pose_mapping(current_tcp_poses)
    return [
        convert_action_step(row, poses, g2p_max_m=g2p_max_m, clamp_gripper=clamp_gripper)
        for row in arr
    ]


def as_tcp_pose(value: TcpPose | np.ndarray | list[float] | tuple[float, ...] | Mapping[str, Any]) -> TcpPose:
    if isinstance(value, TcpPose):
        return value
    if isinstance(value, Mapping):
        if "position" not in value:
            raise ValueError("pose mapping must contain 'position'")
        quat = value.get("quaternion_xyzw", value.get("orientation"))
        if quat is None:
            raise ValueError("pose mapping must contain 'quaternion_xyzw' or 'orientation'")
        return TcpPose(position=np.asarray(value["position"], dtype=np.float64), quaternion_xyzw=np.asarray(quat, dtype=np.float64))
    return TcpPose.from_xyz_xyzw(value)


def _normalize_pose_mapping(
    current_tcp_poses: Mapping[str, TcpPose | np.ndarray | list[float] | tuple[float, ...]],
) -> dict[str, TcpPose]:
    missing = [arm for arm in ARM_ORDER if arm not in current_tcp_poses]
    if missing:
        raise ValueError(f"current_tcp_poses missing required arm(s): {missing}")
    return {arm: as_tcp_pose(current_tcp_poses[arm]) for arm in ARM_ORDER}


def _as_vector(value: np.ndarray | list[float] | tuple[float, ...], size: int, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},), got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains non-finite values: {arr}")
    return arr.copy()
