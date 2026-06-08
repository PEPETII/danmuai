"""Scene memory store: context + bullet dedup.

SceneMemoryStore 是记忆子系统的门面，组合 SceneContextMemory（场景卡片）与
BulletDedupMemory（近期弹幕去重）。纯内存、随 DanmuApp 会话生命周期，不写 SQLite。

注意：activity（活跃度等）由 DanmuApp 直接持有，不在 store 内组合；
store 只负责 context + dedup 两块。

四档 memory_mode（在 format_prompt_for_generation → build_memory_prompt_block 生效）：
- off：不注入记忆提示词
- dedup_only：仅弹幕去重段，字符预算最小
- scene_card：语气 + 场景状态卡片（默认）
- strong：更高字符预算

调用链：
  format_prompt_for_generation → build_memory_prompt_block → append_memory_to_user_pt → AiWorker._request
"""

from __future__ import annotations

import logging

from app.memory.bullet_dedup import BulletDedupMemory
from app.memory.scene_context import SceneContextMemory
from app.memory.types import VisualMemoryUpdate

logger = logging.getLogger(__name__)


class SceneMemoryStore:
    """场景记忆门面：context（视觉卡片）+ dedup（已播弹幕窗口）。

    职责：组合 ``SceneContextMemory``（场景卡片）与 ``BulletDedupMemory``（去重窗口），
    是 ``DanmuApp.scene_memory`` 的访问入口。**不**直接持有 activity 状态；
    activity 由 ``DanmuApp._recent_activity`` 单独管理。

    线程安全：本类实例由 ``DanmuApp`` 在主线程创建/访问；单线程，无需锁。

    代际（``scene_generation``）说明：
    - 与 ``DanmuApp._scene_generation`` 对齐；视觉结果入场时 store.update_from_visual_result
      会校验 ``update.scene_generation``，代际不匹配则静默 return。
    - 这避免了 AI 异步返回的旧代际 scene_memory 覆盖当前代际的卡片。
    """

    def __init__(self) -> None:
        self._context = SceneContextMemory(scene_generation=0)
        self._dedup = BulletDedupMemory()

    @property
    def context(self) -> SceneContextMemory:
        return self._context

    @property
    def dedup(self) -> BulletDedupMemory:
        return self._dedup

    @property
    def generation(self) -> int:
        return self._context.scene_generation

    def reset(self) -> None:
        self._context = SceneContextMemory(scene_generation=0)
        self._dedup.clear()

    def update_from_visual_result(self, update: VisualMemoryUpdate) -> None:
        """将 AI 回复信封中的 scene_memory 合并进当前代际 context。

        代际不匹配时记录警告日志：迟到的视觉更新不写入当前代际卡片。
        """
        if update.scene_generation != self._context.scene_generation:
            logger.warning(
                f"Generation mismatch in visual update: expected {self._context.scene_generation}, got {update.scene_generation}"
            )
            return
        self._context.merge_visual_update(update)

    def record_displayed_bullet(
        self,
        content: str,
        scene_generation: int,
        *,
        window: int = 10,
        angle: str = "",
    ) -> None:
        """记录一条已上屏弹幕，供 dedup 提示与引擎去重协同。"""
        if scene_generation != self._context.scene_generation:
            return
        self._dedup.record(content, angle=angle, window=window)

    def format_prompt_for_generation(
        self,
        scene_generation: int,
        memory_mode: str,
    ) -> str:
        """为当前 AI 请求组装记忆提示词块；代际不匹配返回空串。"""
        if scene_generation != self._context.scene_generation:
            return ""
        from app.memory_prompt_builder import build_memory_prompt_block

        return build_memory_prompt_block(self._context, self._dedup, memory_mode)
