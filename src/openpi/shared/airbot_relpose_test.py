import itertools

import numpy as np

from openpi.shared import airbot_relpose as relpose


def test_relative_action_round_trip_matches_training_formula():
    current_left = relpose.TcpPose.from_xyz_xyzw([0.4, -0.2, 0.3, 0.05, 0.1, -0.02, 0.993428])
    current_right = relpose.TcpPose.from_xyz_xyzw([-0.1, 0.2, 0.5, -0.1, 0.03, 0.08, 0.991])

    desired_left = relpose.integrate_tcp_local_delta(current_left, [0.02, -0.01, 0.03], [0.01, 0.02, -0.03])
    desired_right = relpose.integrate_tcp_local_delta(current_right, [-0.04, 0.01, 0.02], [-0.02, 0.04, 0.01])

    left_action = relpose.relative_action_from_poses(current_left, desired_left)
    right_action = relpose.relative_action_from_poses(current_right, desired_right)
    action = np.concatenate([left_action, [80.0], right_action, [25.0], np.zeros(18)])

    target = relpose.convert_action_step(action, {"left": current_left, "right": current_right})

    np.testing.assert_allclose(target.left.pose.position, desired_left.position, atol=1e-12)
    np.testing.assert_allclose(target.right.pose.position, desired_right.position, atol=1e-12)
    np.testing.assert_allclose(
        np.abs(np.dot(target.left.pose.quaternion_xyzw, desired_left.quaternion_xyzw)), 1.0, atol=1e-12
    )
    np.testing.assert_allclose(
        np.abs(np.dot(target.right.pose.quaternion_xyzw, desired_right.quaternion_xyzw)), 1.0, atol=1e-12
    )
    assert target.left.gripper.model_0_100 == 80.0
    assert target.left.gripper.ratio_0_1 == 0.8
    np.testing.assert_allclose(target.left.gripper.g2p_m, 0.0768)
    np.testing.assert_allclose(target.left.gripper.p7_mm, 76.8)
    assert target.right.gripper.model_0_100 == 25.0


def test_convert_chunk_rows_are_relative_to_same_observation_pose_not_chained():
    current = {
        "left": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "right": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    }
    actions = np.zeros((2, 32), dtype=np.float64)
    actions[0, 0] = 0.01
    actions[0, 7] = 0.10
    actions[1, 0] = 0.02
    actions[1, 7] = 0.20

    targets = relpose.convert_action_chunk(actions, current)

    np.testing.assert_allclose(targets[0].left.pose.position, [0.01, 0.0, 0.0])
    np.testing.assert_allclose(targets[1].left.pose.position, [0.02, 0.0, 0.0])
    np.testing.assert_allclose(targets[0].right.pose.position, [1.10, 0.0, 0.0])
    np.testing.assert_allclose(targets[1].right.pose.position, [1.20, 0.0, 0.0])


def test_split_dual_arm_action_accepts_padded_policy_output():
    action = np.arange(32, dtype=np.float64)

    split = relpose.split_dual_arm_action(action)

    np.testing.assert_allclose(split["left"].delta_position_local, [0.0, 1.0, 2.0])
    np.testing.assert_allclose(split["left"].delta_rotvec_local, [3.0, 4.0, 5.0])
    assert split["left"].gripper_model == 6.0
    np.testing.assert_allclose(split["right"].delta_position_local, [7.0, 8.0, 9.0])
    np.testing.assert_allclose(split["right"].delta_rotvec_local, [10.0, 11.0, 12.0])
    assert split["right"].gripper_model == 13.0


def test_gripper_conversion_clamps_by_default_and_can_be_unclamped():
    closed = relpose.gripper_target_from_model_value(-5.0)
    open_ = relpose.gripper_target_from_model_value(150.0)
    raw = relpose.gripper_target_from_model_value(150.0, clamp=False)

    assert closed.model_0_100 == 0.0
    assert closed.g2p_m == 0.0
    assert open_.model_0_100 == 100.0
    assert open_.g2p_m == relpose.G2P_MAX_M
    assert raw.model_0_100 == 150.0
    assert raw.g2p_m == relpose.G2P_MAX_M * 1.5


def test_quaternion_normalization_matches_training_positive_w_convention():
    quat = relpose.normalize_quat_xyzw([0.0, 0.0, 0.0, -2.0])

    np.testing.assert_allclose(quat, [0.0, 0.0, 0.0, 1.0])
    pose = relpose.TcpPose.from_xyz_xyzw([0.0, 0.0, 0.0, -0.0, -0.0, -0.5, -0.5])
    assert pose.quaternion_xyzw[3] >= 0.0


def test_invalid_shapes_raise_clear_errors():
    with np.testing.assert_raises_regex(ValueError, "at least 14"):
        relpose.split_dual_arm_action(np.zeros(13))
    with np.testing.assert_raises_regex(ValueError, "missing required"):
        relpose.convert_action_step(np.zeros(14), {"left": np.zeros(7)})


def test_interpolate_tcp_poses_limits_every_translation_to_five_mm():
    start = relpose.TcpPose.from_xyz_xyzw([0.1, -0.2, 0.3, 0.0, 0.0, 0.0, 1.0])
    target = relpose.TcpPose.from_xyz_xyzw([0.123, -0.2, 0.3, 0.0, 0.0, 0.0, 1.0])

    waypoints = relpose.interpolate_tcp_poses(
        start,
        target,
        max_translation_m=0.005,
        max_rotation_rad=0.02,
    )

    assert len(waypoints) == 5
    poses = [start, *waypoints]
    distances = [
        np.linalg.norm(current.position - previous.position)
        for previous, current in itertools.pairwise(poses)
    ]
    assert max(distances) <= 0.005 + 1e-12
    np.testing.assert_allclose(waypoints[-1].as_xyz_xyzw(), target.as_xyz_xyzw(), atol=1e-12)


def test_interpolate_tcp_poses_limits_rotation_and_uses_shortest_quaternion_arc():
    start = relpose.TcpPose.from_xyz_xyzw([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    target_quat = -relpose.rotvec_to_quat_xyzw([0.0, 0.0, 0.09])
    target = relpose.TcpPose(position=np.zeros(3), quaternion_xyzw=target_quat)

    waypoints = relpose.interpolate_tcp_poses(
        start,
        target,
        max_translation_m=0.005,
        max_rotation_rad=0.02,
    )

    assert len(waypoints) == 5
    poses = [start, *waypoints]
    rotations = [
        relpose.quat_angular_distance_xyzw(previous.quaternion_xyzw, current.quaternion_xyzw)
        for previous, current in itertools.pairwise(poses)
    ]
    assert max(rotations) <= 0.02 + 1e-12
    assert abs(float(np.dot(waypoints[-1].quaternion_xyzw, target.quaternion_xyzw))) >= 1.0 - 1e-12


def test_interpolate_tcp_poses_returns_no_command_for_identical_pose():
    pose = relpose.TcpPose.from_xyz_xyzw([0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 1.0])

    assert relpose.interpolate_tcp_poses(
        pose,
        pose,
        max_translation_m=0.005,
        max_rotation_rad=0.02,
    ) == []
