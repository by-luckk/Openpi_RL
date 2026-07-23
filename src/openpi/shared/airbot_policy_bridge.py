"""Offline-testable helpers for validating and selecting OpenPI action rows."""

from __future__ import annotations

from typing import Any

import numpy as np

from openpi.shared import airbot_relpose as relpose


def normalize_action_chunk(actions: np.ndarray | list[Any]) -> np.ndarray:
    """Return a 2D action chunk and validate that each row has dual-arm action dims."""

    chunk = np.asarray(actions, dtype=np.float64)
    if chunk.ndim == 1:
        chunk = chunk[np.newaxis, :]
    if chunk.ndim != 2 or chunk.shape[1] < relpose.DUAL_ARM_ACTION_DIM:
        raise ValueError(
            f"actions must be shape (H, >= {relpose.DUAL_ARM_ACTION_DIM}) or (>= {relpose.DUAL_ARM_ACTION_DIM},), "
            f"got {chunk.shape}"
        )
    if not np.all(np.isfinite(chunk[:, : relpose.DUAL_ARM_ACTION_DIM])):
        raise ValueError("actions contain non-finite values in the first 14 dimensions")
    return chunk


def select_action_step(actions: np.ndarray | list[Any], action_index: int = 0) -> tuple[np.ndarray, tuple[int, int]]:
    """Select one action row from a policy chunk."""

    chunk = normalize_action_chunk(actions)
    if action_index < 0 or action_index >= chunk.shape[0]:
        raise IndexError(f"action_index {action_index} out of range for chunk length {chunk.shape[0]}")
    return chunk[action_index].copy(), tuple(int(v) for v in chunk.shape)
