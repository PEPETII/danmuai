from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class QueuedReply:
    persona_id: str
    batch_index: int
    content_index: int
    content: str
    screenshot_round: int = 0
    screenshot_id: int = 0
    captured_at: float = 0.0
    scene_generation: int = 0
    batch_id: int = 0
    request_id: str = ""
    is_fallback: bool = False
    source: str = "ai"
    replaceable: bool = False
    memory_eligible: bool = True


class AIReplyFIFOBuffer:
    def __init__(self, max_items: int = 8):
        self._items = deque()
        self._max_items = max_items

    def push(self, item: QueuedReply):
        if item.scene_generation > 0:
            self.drop_older_generations(item.scene_generation)
        self._items.append(item)
        while len(self._items) > self._max_items:
            self._items.popleft()

    def pop(self) -> QueuedReply | None:
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
        for item in items:
            self.push(item)

    def prepend_batch(
        self,
        items: list[QueuedReply],
        preserve_existing: int = 0,
        preserve_scene_generation: int | None = None,
        preserve_replaceable: bool = True,
    ):
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
        self._items = deque(
            item for item in self._items if item.screenshot_round >= min_round
        )

    def drop_older_generations(self, min_generation: int):
        self._items = deque(
            item for item in self._items if item.scene_generation >= min_generation
        )
