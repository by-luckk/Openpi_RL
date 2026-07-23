import numpy as np
import pytest

from openpi.policies import airbot_policy


def test_airbot_inputs_fill_unconfigured_camera_with_mask_false():
    transform = airbot_policy.AirbotInputs(
        image_keys=("left_wrist_0_rgb", "right_wrist_0_rgb"),
    )
    image = np.ones((8, 10, 3), dtype=np.uint8)

    result = transform(
        {
            "state": np.zeros(16, dtype=np.float32),
            "left_wrist_0_rgb": image,
            "right_wrist_0_rgb": image,
        }
    )

    np.testing.assert_array_equal(result["image"]["base_0_rgb"], np.zeros_like(image))
    assert not result["image_mask"]["base_0_rgb"]
    assert result["image_mask"]["left_wrist_0_rgb"]
    assert result["image_mask"]["right_wrist_0_rgb"]


def test_airbot_inputs_require_each_configured_camera():
    transform = airbot_policy.AirbotInputs(
        image_keys=("left_wrist_0_rgb", "right_wrist_0_rgb"),
    )

    with pytest.raises(KeyError, match="right_wrist_0_rgb"):
        transform(
            {
                "state": np.zeros(16, dtype=np.float32),
                "left_wrist_0_rgb": np.zeros((8, 10, 3), dtype=np.uint8),
            }
        )
