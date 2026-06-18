"""AI 回复弹幕的有序 FIFO 缓冲（由 main.DanmuApp 持有并消费）。

队列存在的根本原因：AI 请求延迟不可预测（数百毫秒到数秒），而弹幕上屏需要有序、
可控节奏。队列在「AI 异步返回」与「主线程定时消费」之间做缓冲与过滤。

自适应延迟设计：reply_timer 单次触发间隔 100-1000ms，按屏上弹幕密度动态调节，
使弹幕上屏节奏平滑（密度高时间隔长，避免堆积）。

主流程位置：
- 写入：DanmuApp._enqueue_reply_batch() → push / prepend_batch
- 消费：DanmuApp._consume_reply_queue() → pop，由 reply_timer 或主循环主动触发
- AI 回复到达：_on_ai_reply() → 先 drop_replaceable_fallbacks 清理兜底，再 prepend_batch

三种核心队列语义：
1. **入队 push**：按到达顺序追加；超出 max_items 时从队首丢弃最旧条目（容量裁剪）。
2. **fallback 替换**：本地轻量兜底弹幕（replaceable=True）可被同批次的 AI 回复顶掉。

scene_generation 随请求携带，场景配置变更时由 DanmuApp 递增；purge_stale_by_generation
在 bump 后清理队列内落后的 ai/fallback（mic 保留）。本队列不做 TTL 判定。
"""
import logging
from collections import deque
from dataclasses import dataclass

_logger = logging.getLogger(__name__)

_STALE_VISUAL_SOURCES = frozenset({"ai", "fallback"})


@dataclass(frozen=True)
class QueuedReply:
    """单条待上屏弹幕及其批次/场景元数据（不可变，便于在队列间传递）。"""

    persona_id: str  # 人格 id，决定弹幕样式与记忆 tone
    batch_index: int  # 请求轮次内的批次序号（历史/日志用）
    content_index: int  # 批次内第几条，用于记忆角度 bullet_angle_from_index
    content: str  # 弹幕正文（展示前可能再经 normalize_danmu_display_text）
    screenshot_round: int = 0  # 调度轮次（粗粒度）；purge_before_round 按此淘汰
    screenshot_id: int = 0  # 逐帧 id，随请求/RTT 元数据携带；当前不参与 stale 硬丢弃
    captured_at: float = 0.0  # 截图 monotonic 时间戳（元数据）；当前不参与 TTL 硬丢弃
    scene_generation: int = 0  # 场景版本；live_topic 等变更时递增，供 stale 判定与 purge
    batch_id: int = 0  # drop_replaceable_fallbacks / 批次锚点加速
    request_id: str = ""  # 视觉 vs 麦克风来源；drop_replaceable_fallbacks 匹配
    is_fallback: bool = False  # True=本地轻量兜底批次，非模型输出
    source: str = "ai"  # ai | fallback | mic；mic 跳过去重、fallback 不写 scene_memory
    replaceable: bool = False  # True 且 source=fallback 时，可被同 request_id/batch_id 的 AI 批次替换
    memory_eligible: bool = True  # False 时不上报 scene_memory（兜底通常 False）


class AIReplyFIFOBuffer:
    """有序 FIFO 缓冲：先入先出消费。max_items=0 表示无容量裁剪（默认由配置 reply_queue_max_items 控制）。"""

    def __init__(self, max_items: int = 8):
        self._items = deque()
        self._max_items = max(0, max_items)

    def _drop_one_tail_replaceable_fallback(self) -> bool:
        # Single-element delete: deque supports indexed del (Py 3.5+), avoiding
        # list copy + deque rebuild. Bulk filters (prepend_batch, drop_*,
        # purge_*) keep deque(...) rebuild — small max_items, O(n) scan anyway.
        for index in range(len(self._items) - 1, -1, -1):
            item = self._items[index]
            if item.is_fallback and item.replaceable and item.source == "fallback":
                del self._items[index]
                return True
        return False

    def _trim_overflow(
        self,
        *,
        drop_from_left: bool,
        prefer_replaceable_fallback: bool = False,
    ) -> None:
        if self._max_items <= 0:
            return
        size_before = len(self._items)
        dropped = 0
        while len(self._items) > self._max_items:
            if (
                not drop_from_left
                and prefer_replaceable_fallback
                and self._drop_one_tail_replaceable_fallback()
            ):
                dropped += 1
                continue
            if drop_from_left:
                self._items.popleft()
            else:
                self._items.pop()
            dropped += 1
        if dropped:
            from app.main_request_context_mixin import reply_pipeline_log_enabled

            extra = ""
            if reply_pipeline_log_enabled():
                extra = (
                    f" queue_size_before={size_before}"
                    f" queue_size_after={len(self._items)}"
                )
            _logger.warning(
                "reply_queue trim: dropped=%s max_items=%s drop_from_left=%s "
                "reason=reply_queue_trim%s",
                dropped,
                self._max_items,
                drop_from_left,
                extra,
            )

    def push(self, item: QueuedReply):
        """追加一条到队尾。"""
        self._items.append(item)
        self._trim_overflow(drop_from_left=True)

    def pop(self) -> QueuedReply | None:
        """FIFO 队首取出一条，供 _consume_reply_queue 上屏。"""
        if not self._items:
            return None
        return self._items.popleft()

    def peek(self) -> QueuedReply | None:
        if not self._items:
            return None
        return self._items[0]

    def clear(self):
        self._items.clear()

    def is_empty(self) -> bool:
        return not self._items

    def size(self) -> int:
        return len(self._items)

    def set_max_items(self, max_items: int):
        self._max_items = max(0, max_items)
        self._trim_overflow(drop_from_left=False)

    def extend(self, items: list[QueuedReply]):
        """批量 push，每条仍走代际淘汰（若 generation>0）与容量裁剪。"""
        for item in items:
            self.push(item)

    def prepend_batch(
        self,
        items: list[QueuedReply],
        preserve_existing: int = 0,
        preserve_scene_generation: int | None = None,
        preserve_replaceable: bool = True,
    ):
        """麦克风或本地兜底插入时，新批次插在队首而非 append。

        push 追加队尾（正常 AI 回复）；prepend 插队首（优先消费新批次）。
        超长时 push 从队首丢、prepend 从队尾丢。
        preserve_scene_generation: 非 None 时只保留该代际（历史兼容，运行期常为 0）。
        """
        preserved: list[QueuedReply] = []
        if preserve_existing > 0:
            for item in self._items:
                if preserve_scene_generation is not None and item.scene_generation != preserve_scene_generation:
                    continue
                if not preserve_replaceable and item.replaceable:
                    continue
                preserved.append(item)
                if len(preserved) >= preserve_existing:
                    break

        self._items = deque([*items, *preserved])
        # S-017: prepend overflow drops replaceable fallback tail before AI batches.
        self._trim_overflow(drop_from_left=False, prefer_replaceable_fallback=True)

    def drop_replaceable_fallbacks(
        self,
        *,
        request_id: str = "",
        batch_id: int | None = None,
        scene_generation: int | None = None,
    ) -> int:
        """移除可被 AI 顶掉的本地 fallback，返回删除条数。"""
        before = len(self._items)
        self._items = deque(
            item
            for item in self._items
            if not (
                item.is_fallback
                and item.replaceable
                and item.source == "fallback"
                and (scene_generation is None or item.scene_generation == scene_generation)
                and (
                    (request_id and item.request_id == request_id)
                    or (batch_id is not None and item.batch_id == batch_id)
                )
            )
        )
        return before - len(self._items)

    def purge_before_round(self, min_round: int):
        """丢弃 screenshot_round 早于 min_round 的条目（调度轮次回退或重置时用）。"""
        self._items = deque(
            item for item in self._items if item.screenshot_round >= min_round
        )

    def purge_stale_by_generation(
        self,
        min_generation: int,
        *,
        sources: frozenset[str] | None = _STALE_VISUAL_SOURCES,
    ) -> int:
        """丢弃 scene_generation < min_generation 的条目，返回删除条数。

        默认仅清理 source 为 ai/fallback 的项，mic 保留。
        sources=None 时与 drop_older_generations 一致（全部来源）。
        """
        before = len(self._items)

        def _keep(item: QueuedReply) -> bool:
            if item.scene_generation >= min_generation:
                return True
            if sources is None:
                return False
            return item.source not in sources

        self._items = deque(item for item in self._items if _keep(item))
        return before - len(self._items)

    def drop_older_generations(self, min_generation: int) -> int:
        """丢弃 scene_generation < min_generation 的条目（全部来源，含 mic）。"""
        return self.purge_stale_by_generation(min_generation, sources=None)
