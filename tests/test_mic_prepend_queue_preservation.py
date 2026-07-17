import logging

from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from tests.conftest import make_minimal_danmu_app


def _queued(
    content: str,
    *,
    source: str = "ai",
    scene_generation: int = 0,
    replaceable: bool = False,
) -> QueuedReply:
    return QueuedReply(
        persona_id="p",
        batch_index=1,
        content_index=0,
        content=content,
        scene_generation=scene_generation,
        source=source,
        is_fallback=source == "fallback",
        replaceable=replaceable,
    )


def _contents(buffer: AIReplyFIFOBuffer) -> list[str]:
    return [item.content for item in buffer._items]


def _enqueue_mic(app, items: list[str], *, scene_generation: int = 0) -> None:
    app._enqueue_reply_batch(
        "mic-persona",
        -1,
        10,
        1.0,
        scene_generation,
        items,
        from_mic_insert=True,
    )


def test_mic_prepend_preserves_all_visual_items_within_capacity():
    app = make_minimal_danmu_app()
    app.reply_buffer.set_max_items(8)
    app.reply_buffer.extend([_queued(f"v{i}") for i in range(6)])

    _enqueue_mic(app, ["m0", "m1"])

    assert _contents(app.reply_buffer) == [
        "m0",
        "m1",
        "v0",
        "v1",
        "v2",
        "v3",
        "v4",
        "v5",
    ]
    assert app.reply_buffer.pop().content == "m0"
    assert app.reply_buffer.pop().content == "m1"


def test_mic_prepend_does_not_trim_when_capacity_is_unlimited():
    app = make_minimal_danmu_app()
    app.reply_buffer.set_max_items(0)
    app.reply_buffer.extend([_queued(f"v{i}") for i in range(6)])

    _enqueue_mic(app, ["m0", "m1"])

    assert _contents(app.reply_buffer) == [
        "m0",
        "m1",
        "v0",
        "v1",
        "v2",
        "v3",
        "v4",
        "v5",
    ]


def test_mic_prepend_overflow_drops_fallbacks_then_visual_tail(caplog):
    app = make_minimal_danmu_app()
    app.reply_buffer.set_max_items(8)
    app.reply_buffer.extend(
        [
            _queued("v0"),
            _queued("fb0", source="fallback", replaceable=True),
            _queued("v1"),
            _queued("fb1", source="fallback", replaceable=True),
            _queued("v2"),
            _queued("v3"),
        ]
    )

    with caplog.at_level(logging.WARNING, logger="app.reply_queue"):
        _enqueue_mic(app, [f"m{i}" for i in range(5)])

    assert _contents(app.reply_buffer) == [
        "m0",
        "m1",
        "m2",
        "m3",
        "m4",
        "v0",
        "v1",
        "v2",
    ]
    assert any("dropped=3" in record.message for record in caplog.records)
    assert any("reason=mic_prepend_capacity" in record.message for record in caplog.records)


def test_mic_prepend_preserves_existing_mic_across_scene_generations():
    app = make_minimal_danmu_app()
    app.reply_buffer.set_max_items(0)
    app.reply_buffer.extend(
        [
            _queued("old-mic", source="mic", scene_generation=0),
            _queued("current-visual", scene_generation=1),
        ]
    )

    _enqueue_mic(app, ["new-mic"], scene_generation=1)

    assert _contents(app.reply_buffer) == ["new-mic", "old-mic", "current-visual"]


def test_local_fallback_still_preserves_only_configured_existing_count():
    app = make_minimal_danmu_app()
    app.reply_buffer.set_max_items(0)
    app.reply_buffer.extend([_queued(f"v{i}") for i in range(6)])

    app._enqueue_reply_batch(
        "fallback-persona",
        1,
        10,
        1.0,
        0,
        ["fb0", "fb1"],
        from_local_fallback=True,
    )

    assert _contents(app.reply_buffer) == ["fb0", "fb1", "v0", "v1", "v2"]


def test_prepend_default_keeps_legacy_replace_queue_behavior():
    buffer = AIReplyFIFOBuffer(max_items=0)
    buffer.extend([_queued("v0"), _queued("v1")])

    dropped = buffer.prepend_batch([_queued("priority", source="mic")])

    assert dropped == 0
    assert _contents(buffer) == ["priority"]
