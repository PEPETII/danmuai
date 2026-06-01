"""AI 回复弹幕的有序 FIFO 缓冲（由 main.DanmuApp 持有并消费）。

队列存在的根本原因：AI 请求延迟不可预测（数百毫秒到数秒），而弹幕上屏需要有序、
可控节奏。队列在「AI 异步返回」与「主线程定时消费」之间做缓冲与过滤。

主流程位置：
- 写入：DanmuApp._enqueue_reply_batch() → push / prepend_batch
- 消费：DanmuApp._consume_reply_queue() → pop，由 reply_timer 或主循环主动触发
- AI 回复到达：_on_ai_reply() → 先 drop_replaceable_fallbacks 清理兜底，再 prepend_batch

三种核心队列语义：
1. **入队 push**：按到达顺序追加；超出 max_items 时从队首丢弃最旧条目（容量裁剪）。
2. **代际淘汰（历史兼容）**：push 时若 item.scene_generation>0，先 drop_older_generations。
   当前普通模式运行期 _scene_generation 恒为 0，该路径通常不触发；字段仍随请求携带供记忆/日志。
3. **fallback 替换**：本地轻量兜底弹幕（replaceable=True）可被同批次的 AI 回复顶掉。

过期回复硬丢弃由 main._is_reply_stale 负责（当前恒为不丢弃）；本队列不做 TTL 判定。
"""
from collections import deque
from dataclasses import dataclass


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
    scene_generation: int = 0  # 记忆/日志兼容字段；drop_older_generations 仅在 >0 入队时生效
    batch_id: int = 0  # drop_replaceable_fallbacks / 批次锚点加速
    request_id: str = ""  # 视觉 vs 麦克风来源；drop_replaceable_fallbacks 匹配
    is_fallback: bool = False  # True=本地轻量兜底批次，非模型输出
    source: str = "ai"  # ai | fallback | mic；mic 跳过去重、fallback 不写 scene_memory
    replaceable: bool = False  # True 且 source=fallback 时，可被同 request_id/batch_id 的 AI 批次替换
    memory_eligible: bool = True  # False 时不上报 scene_memory（兜底通常 False）


class AIReplyFIFOBuffer:
    """有序 FIFO 缓冲：先入先出消费，容量有界（默认 max_items=8）。

    缓冲 AI/兜底/麦克风插入批次；replaceable fallback 清理与容量裁剪配合，
    避免低质量条目长期占位。当前主链路不对回复做 scene_generation/TTL 硬丢弃。
    """

    def __init__(self, max_items: int = 8):
        self._items = deque()
        self._max_items = max_items  # 容量上界：过大则消费延迟，过小则易空窗；默认 8

    def push(self, item: QueuedReply):
        """追加一条到队尾；若 item.scene_generation>0，先 drop_older_generations（兼容路径）。"""
        if item.scene_generation > 0:
            self.drop_older_generations(item.scene_generation)
        self._items.append(item)
        while len(self._items) > self._max_items:
            self._items.popleft()

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
        self._max_items = max(1, max_items)
        while len(self._items) > self._max_items:
            self._items.pop()

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
        while len(self._items) > self._max_items:
            self._items.pop()

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

    def drop_older_generations(self, min_generation: int):
        """丢弃 scene_generation < min_generation 的条目（历史兼容；运行期 generation 常为 0）。"""
        self._items = deque(
            item for item in self._items if item.scene_generation >= min_generation
        )
