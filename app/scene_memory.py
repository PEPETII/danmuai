"""Compatibility facade for scene memory (see app.memory package)."""

from app.memory import (
    SceneMemoryStore,
    VisualMemoryUpdate,
    bullet_angle_from_index,
    clamp_memory_window,
    memory_window_from_config,
)
from app.memory.types import MAX_BULLET_SNIPPET_LEN
from app.memory_prompt_builder import append_memory_to_user_pt, build_memory_prompt_block

# Legacy alias
MAX_SNIPPET_LEN = MAX_BULLET_SNIPPET_LEN

__all__ = [
    "SceneMemoryStore",
    "VisualMemoryUpdate",
    "append_memory_to_user_pt",
    "build_memory_prompt_block",
    "bullet_angle_from_index",
    "clamp_memory_window",
    "memory_window_from_config",
    "MAX_SNIPPET_LEN",
]
