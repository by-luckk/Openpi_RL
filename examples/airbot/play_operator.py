import logging
import time

from airbot_ie.robots.airbot_play import AIRBOTPlay
from airbot_ie.robots.airbot_play import AIRBOTPlayConfig
from airbot_ie.robots.airbot_play import RobotMode
from airdc.common.devices.cameras.v4l2 import V4L2Camera
from airdc.common.devices.cameras.v4l2 import V4L2CameraConfig
from airdc.common.systems.basis import SystemMode
from delta_pose import FollowerTarget
from delta_pose import LeaderState
from delta_pose import TakeoverReference
from delta_pose import position_tuple
from delta_pose import quaternion_tuple
import numpy as np
from robot_config import RobotConfig

logger = logging.getLogger(__name__)


class Robot:
    """Robot class for the AIRBOT Play robot."""

    @staticmethod
    def _shutdown_instance(instance) -> None:
        try:
            instance.shutdown()
            return
        except Exception:
            logger.debug("Normal shutdown failed for partially configured instance", exc_info=True)

        capture = getattr(instance, "_capture", None)
        if capture is not None:
            try:
                capture.close()
            except Exception:
                logger.debug("Failed to close partial camera capture", exc_info=True)
        device = getattr(instance, "device", None)
        if device is not None:
            try:
                device.close()
            except Exception:
                logger.debug("Failed to close partial camera device", exc_info=True)

    def __init__(self, config: RobotConfig):
        self.config = config
        self.robots = {
            name: AIRBOTPlay(AIRBOTPlayConfig(url=url, port=port))
            for name, url, port in zip(
                self.config.robot_groups,
                self.config.robot_urls,
                self.config.robot_ports,
                strict=True,
            )
        }
        self.cameras = {
            name: V4L2Camera(V4L2CameraConfig(
                camera_index=index,
                pixel_format=pixel_format,
                width=width,
                height=height,
                fps=fps,
            ))
            for name, index, pixel_format, width, height, fps in zip(
                self.config.camera_names,
                self.config.camera_index,
                self.config.camera_pixel_format,
                self.config.camera_width,
                self.config.camera_height,
                self.config.camera_fps,
                strict=True,
            )
        }
        self.keys = list(self.robots.keys()) + list(self.cameras.keys())
        self.values = list(self.robots.values()) + list(self.cameras.values())
        self.leaders: dict[str, AIRBOTPlay] = {}
        configured_values = []
        try:
            for key, value in zip(self.keys, self.values, strict=True):
                try:
                    configured = value.configure()
                except Exception:
                    self._shutdown_instance(value)
                    raise
                if not configured:
                    self._shutdown_instance(value)
                    raise RuntimeError(f"Failed to configure {key}.")
                configured_values.append(value)
                if key in self.robots:
                    value.switch_mode(SystemMode.RESETTING)
        except Exception:
            for value in reversed(configured_values):
                self._shutdown_instance(value)
            raise

    def init_leaders(self):
        """Initialize leader (master) arm connections for DAgger mode.

        Uses leader_ports from RobotConfig. Each leader arm corresponds
        to a follower arm in the same robot_group.
        """
        if self.leaders:
            logger.info("Leader arms already initialized.")
            return

        try:
            for name, url, port in zip(
                self.config.robot_groups,
                self.config.leader_urls,
                self.config.leader_ports,
                strict=True,
            ):
                leader = AIRBOTPlay(AIRBOTPlayConfig(url=url, port=port))
                if not leader.configure():
                    self._shutdown_instance(leader)
                    raise RuntimeError(f"Failed to configure leader arm '{name}' at {url}:{port}.")
                leader.switch_mode(SystemMode.PASSIVE)
                self.leaders[name] = leader
                logger.info(f"Leader arm '{name}' initialized on port {port}.")
        except Exception:
            for leader in self.leaders.values():
                self._shutdown_instance(leader)
            self.leaders.clear()
            raise

        # Start leaders in PASSIVE mode (gravity compensation)
        self.switch_leader_mode(SystemMode.PASSIVE)
        logger.info("All leader arms initialized in PASSIVE mode.")

    def switch_mode(self, mode):
        """Switch the mode of the follower robots (backward compatible)."""
        for robot in self.robots.values():
            robot.switch_mode(mode)

    def switch_follower_mode(self, mode: SystemMode):
        """Switch the mode of follower (slave) arms."""
        for robot in self.robots.values():
            robot.switch_mode(mode)

    def switch_leader_mode(self, mode: SystemMode):
        """Switch the mode of leader (master) arms.

        PASSIVE = gravity compensation (human can freely move the arm)
        SAMPLING = position servo (arm follows commanded positions)
        """
        for leader in self.leaders.values():
            leader.switch_mode(mode)

    def reset_to_action(self, action) -> None:
        """Move followers to a joint-space reset pose without overlapping planning requests."""
        target = np.asarray(action, dtype=np.float64)
        expected_size = len(self.robots) * 7
        if target.shape != (expected_size,) or not np.all(np.isfinite(target)):
            raise ValueError(f"Reset action must contain {expected_size} finite values")

        logger.info("Resetting followers to configured start pose: %s", target.tolist())
        for index, (group, robot) in enumerate(self.robots.items()):
            group_target = target[index * 7 : (index + 1) * 7]
            if not robot.switch_mode(SystemMode.RESETTING):
                raise RuntimeError(f"Failed to enable planning mode for follower '{group}'.")
            if not robot.interface.move_to_joint_pos(group_target[:6].tolist(), blocking=True):
                raise RuntimeError(f"Failed to reset follower arm '{group}'.")

            eef_target = [float(group_target[6] * self.config.action_eef_scale)]
            for attempt in range(3):
                time.sleep(0.1)
                if robot.interface.move_eef_pos(eef_target):
                    break
                if attempt == 2:
                    raise RuntimeError(f"Failed to reset follower gripper '{group}'.")

    def capture_observation(self) -> dict:
        """Capture the current observation from the robot."""
        obs = {}
        for name, ins in zip(self.keys, self.values, strict=True):
            for key, value in ins.capture_observation().items():
                full_key = f"{name}/{key}"
                # Convert BGR to RGB for camera images
                if "image" in key and isinstance(value.get("data"), np.ndarray):
                    image_data = value["data"]
                    if len(image_data.shape) == 3 and image_data.shape[2] == 3:
                        value = value.copy()
                        value["data"] = image_data[..., ::-1]
                obs[full_key] = value
        return obs

    def send_action(self, action):
        """Send the action to the follower robot."""
        for index, (_group, robot) in enumerate(self.robots.items()):
            joint_target = [float(v) for v in action[index * 7 : (index + 1) * 7]]
            stamp = time.time_ns()
            joint_target[6] *= self.config.action_eef_scale
            robot.send_action(
                {
                    "arm/joint_state/position": {"data": joint_target[:6], "t": stamp},
                    "eef/joint_state/position": {"data": joint_target[6:7], "t": stamp},
                }
            )

    def send_leader_action(self, action):
        """Send position command to leader (master) arms.

        Used during alignment to move leader arms to follower positions.
        Leader must be in SAMPLING mode to accept position commands.
        """
        for index, (_group, leader) in enumerate(self.leaders.items()):
            joint_target = [float(v) for v in action[index * 7 : (index + 1) * 7]]
            stamp = time.time_ns()
            leader.send_action(
                {
                    "arm/joint_state/position": {"data": joint_target[:6], "t": stamp},
                    "eef/joint_state/position": {"data": joint_target[6:7], "t": stamp},
                }
            )

    def get_qpos(self, obs: dict) -> list[float]:
        """Get the joint positions of the follower robot."""
        qpos = []
        for group in self.config.robot_groups:
            qpos.extend(obs[f"{group}/arm/joint_state/position"]["data"])
            qpos.extend(obs[f"{group}/eef/joint_state/position"]["data"])
        return qpos

    def get_follower_qpos(self) -> np.ndarray:
        """Get current follower (slave) arm joint positions as numpy array."""
        qpos = []
        for group in self.config.robot_groups:
            obs = self.robots[group].capture_observation()
            qpos.extend(obs["arm/joint_state/position"]["data"])
            qpos.extend(obs["eef/joint_state/position"]["data"])
        return np.array(qpos)

    def get_leader_qpos(self) -> np.ndarray:
        """Get current leader (master) arm joint positions as numpy array."""
        qpos = []
        for group in self.config.robot_groups:
            obs = self.leaders[group].capture_observation()
            qpos.extend(obs["arm/joint_state/position"]["data"])
            qpos.extend(obs["eef/joint_state/position"]["data"])
        return np.array(qpos)

    def capture_takeover_references(self) -> dict[str, TakeoverReference]:
        references = {}
        for group in self.config.robot_groups:
            leader_position, leader_orientation = self.leaders[group].interface.get_end_pose()
            follower_position, follower_orientation = self.robots[group].interface.get_end_pose()
            references[group] = TakeoverReference(
                leader_position=position_tuple(leader_position),
                leader_orientation=quaternion_tuple(leader_orientation),
                follower_position=position_tuple(follower_position),
                follower_orientation=quaternion_tuple(follower_orientation),
            )
        return references

    def capture_leader_states(self) -> dict[str, LeaderState]:
        states = {}
        for group in self.config.robot_groups:
            leader = self.leaders[group]
            position, orientation = leader.interface.get_end_pose()
            eef_position = leader.interface.get_eef_pos()
            if not eef_position:
                raise RuntimeError(f"Failed to read leader gripper position for '{group}'.")
            states[group] = LeaderState(
                position=position_tuple(position),
                orientation=quaternion_tuple(orientation),
                eef_position=float(eef_position[0]),
            )
        return states

    def enable_follower_pose_servo(self) -> None:
        for group, robot in self.robots.items():
            if not robot.interface.switch_mode(RobotMode.SERVO_CART_POSE):
                raise RuntimeError(f"Failed to enable Cartesian servo for follower '{group}'.")

    def enable_follower_joint_servo(self) -> None:
        for group, robot in self.robots.items():
            if not robot.interface.switch_mode(RobotMode.SERVO_JOINT_POS):
                raise RuntimeError(f"Failed to restore joint servo for follower '{group}'.")

    def send_takeover_targets(self, targets: dict[str, FollowerTarget]) -> None:
        for group, robot in self.robots.items():
            target = targets[group]
            robot.interface.servo_cart_pose([list(target.position), list(target.orientation)])
            robot.interface.servo_eef_pos([target.eef_position])

    def shutdown(self) -> bool:
        """Shutdown the robot."""
        for robot in self.robots.values():
            robot.shutdown()
        for leader in self.leaders.values():
            leader.shutdown()
        for camera in self.cameras.values():
            camera.shutdown()
        return True
