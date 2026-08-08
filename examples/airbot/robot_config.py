from typing import Any

from pydantic import BaseModel

DEFAULT_EEF_ACTION_SCALE = 0.072 / 0.0471


class RobotConfig(BaseModel):
    """Configuration for the AIRBOT robot."""

    robot_type: str = "play"
    robot_groups: list[str] = ["left", "right"]
    robot_urls: list[str] = ["localhost", "localhost"]
    robot_ports: list[int] = [50051, 50053]
    leader_urls: list[str] = ["localhost", "localhost"]
    leader_ports: list[int] = [50050, 50052]
    action_eef_scale: float = DEFAULT_EEF_ACTION_SCALE
    camera_names: list[str] = ["base_0_rgb", "left_wrist_0_rgb", "right_wrist_0_rgb"]
    camera_index: list[int | str] = [6, 0, 2]
    camera_pixel_format: list[str] = ["MJPEG", "MJPEG", "MJPEG"]
    camera_width: list[int] = [640, 640, 640]
    camera_height: list[int] = [480, 480, 480]
    camera_fps: list[int] = [30, 30, 30]

    def model_post_init(self, __context: Any) -> None:
        group_count = len(self.robot_groups)
        for attr in ("robot_urls", "robot_ports", "leader_urls", "leader_ports"):
            if len(getattr(self, attr)) != group_count:
                raise ValueError(f"{attr} must contain one value per robot group")
        if self.action_eef_scale <= 0:
            raise ValueError("action_eef_scale must be positive")

        for _ in range(len(self.camera_names) - len(self.camera_index)):
            self.camera_names.pop()
        while len(self.camera_pixel_format) < len(self.camera_names):
            self.camera_pixel_format.append("YUYV")
        if len(self.camera_pixel_format) > len(self.camera_names):
            self.camera_pixel_format = self.camera_pixel_format[: len(self.camera_names)]
        for attr, default in (("camera_width", 640), ("camera_height", 480), ("camera_fps", 30)):
            values = getattr(self, attr)
            while len(values) < len(self.camera_names):
                values.append(default)
            if len(values) > len(self.camera_names):
                setattr(self, attr, values[: len(self.camera_names)])
