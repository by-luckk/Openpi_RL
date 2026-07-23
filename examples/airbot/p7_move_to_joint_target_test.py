import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

MODULE_PATH = Path(__file__).with_name("p7_move_to_joint_target.py")
SPEC = importlib.util.spec_from_file_location("p7_move_to_joint_target", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
move_to_target = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(move_to_target)


class FakeClient:
    def __init__(self) -> None:
        self.angles = np.zeros(7, dtype=np.float64)
        self.controllers = []
        self.move_joint_calls = []
        self.released = False

    def get_service_state(self):
        return SimpleNamespace(service_state=True, fsm_state="IDLE", controller_state="idle", valid=True)

    def get_arm_joint_state(self):
        return SimpleNamespace(angles=self.angles.tolist())

    def get_end_pose(self):
        return "fake-pose"

    def get_eef_mode(self):
        return {"has_eef": True, "current_mode_name": "idle"}

    def get_eef_joint_state(self):
        return SimpleNamespace(eef_pos=[0.0])

    def switch_eef_control_mode(self, mode, timeout_ms):
        return True

    def set_eef_speed(self, speed):
        return True

    def move_eef(self, pos, options, timeout_ms):
        return True

    def acquire_control(self, lease_ms, renew_period_s):
        return True

    def switch_controller(self, controller, timeout_ms):
        self.controllers.append(controller)
        return True

    def set_arm_speed(self, speed):
        self.speed = speed
        return True

    def move_joint(self, pos, options, timeout_ms):
        self.move_joint_calls.append((pos, options, timeout_ms))
        self.angles = np.asarray(pos, dtype=np.float64)
        return True

    def release_control(self):
        self.released = True

    def close(self):
        pass


def test_execute_uses_one_blocking_servo_command_per_arm(monkeypatch, tmp_path):
    clients = {50071: FakeClient(), 50072: FakeClient()}
    monkeypatch.setattr(move_to_target, "AirbotClient", lambda host, port, backend: clients[port])
    monkeypatch.setattr(move_to_target.time, "sleep", lambda duration: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(MODULE_PATH),
            "--side",
            "both",
            "--target",
            "0,0.647,0,-0.933,0,0,-1.15",
            "--speed-rad-s",
            "0.55",
            "--effort",
            "8",
            "--max-joint-delta-rad",
            "3.0",
            "--settle-s",
            "0",
            "--trajectory-dir",
            str(tmp_path),
            "--execute",
            "--allow-robot-motion",
        ],
    )

    assert move_to_target.main() == 0

    target = [0.0, 0.647, 0.0, -0.933, 0.0, 0.0, -1.15]
    for client in clients.values():
        assert client.controllers == [
            move_to_target.Controller.servo_control,
            move_to_target.Controller.idle,
        ]
        assert client.speed == [0.55] * 7
        assert len(client.move_joint_calls) == 1
        pos, options, timeout_ms = client.move_joint_calls[0]
        assert pos == target
        assert options.blocking is True
        assert options.eff == [8.0] * 7
        assert timeout_ms == 60000
        assert client.released is True
