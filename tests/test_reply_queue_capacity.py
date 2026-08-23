"""W-TEST-COVER-004: AIReplyFIFOBuffer.set_max_items runtime truncation."""

from __future__ import annotations

from app.config_defaults import DEFAULT_REPLY_QUEUE_MAX_ITEMS
from app.main_helpers import queue_capacity
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply


def _item(i: int) -> QueuedReply:
    return QueuedReply("p", 1, i, f"line-{i}", screenshot_round=1)


def test_set_max_items_trims_oldest_when_shrinking():
    buf = AIReplyFIFOBuffer(max_items=8)
    for i in range(8):
        buf.push(_item(i))

    buf.set_max_items(2)

    assert buf.size() == 2
    assert buf.pop().content == "line-0"
    assert buf.pop().content == "line-1"
    assert buf.pop() is None


def test_set_max_items_zero_disables_trimming():
    buf = AIReplyFIFOBuffer(max_items=2)
    buf.push(_item(0))
    buf.push(_item(1))
    buf.set_max_items(0)
    buf.push(_item(2))
    assert buf.size() == 3


class _Config:
    def __init__(self, value: int):
        self.value = value

    def get_int(self, _key: str, _default: int) -> int:
        return self.value


def test_queue_capacity_uses_safe_default_for_legacy_unlimited_value():
    assert queue_capacity(_Config(0), normal_reply_count=50) == DEFAULT_REPLY_QUEUE_MAX_ITEMS
    assert queue_capacity(_Config(-1), normal_reply_count=50) == DEFAULT_REPLY_QUEUE_MAX_ITEMS
    assert queue_capacity(_Config(250), normal_reply_count=50) == 250


def test_metrics_snapshot_tracks_capacity_backpressure_without_reply_content():
    buf = AIReplyFIFOBuffer(max_items=2)
    buf.extend([_item(0), _item(1), _item(2)])
    buf.pop()
    buf.clear()

    assert buf.metrics_snapshot().to_dict() == {
        "current_size": 0,
        "max_items": 2,
        "high_watermark": 3,
        "enqueued_total": 3,
        "dequeued_total": 1,
        "discarded_total": 2,
        "capacity_dropped_total": 1,
    }

    buf.reset_metrics()

    assert buf.metrics_snapshot().to_dict() == {
        "current_size": 0,
        "max_items": 2,
        "high_watermark": 0,
        "enqueued_total": 0,
        "dequeued_total": 0,
        "discarded_total": 0,
        "capacity_dropped_total": 0,
    }


def test_metrics_snapshot_counts_existing_items_replaced_by_prepend_batch():
    buf = AIReplyFIFOBuffer(max_items=8)
    buf.extend([_item(0), _item(1)])
    buf.prepend_batch([_item(2)], preserve_existing=0)

    assert buf.metrics_snapshot().to_dict() == {
        "current_size": 1,
        "max_items": 8,
        "high_watermark": 2,
        "enqueued_total": 3,
        "dequeued_total": 0,
        "discarded_total": 2,
        "capacity_dropped_total": 0,
    }
