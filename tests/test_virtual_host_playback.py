from __future__ import annotations

from app.virtual_host.playback import (
    PlaybackItem,
    PlaybackPriority,
    PlaybackQueue,
)


class FakePlayer:
    def __init__(self) -> None:
        self.current_callback = None
        self.started: list[bytes] = []
        self.stop_count = 0
        self.pause_count = 0

    def play(self, audio_bytes: bytes, on_complete):
        self.started.append(audio_bytes)
        self.current_callback = on_complete
        return object()

    def stop(self):
        self.stop_count += 1

    def pause(self):
        self.pause_count += 1

    def complete(self) -> None:
        callback = self.current_callback
        self.current_callback = None
        if callback is not None:
            callback()


def _item(turn_id: int, segment_index: int = 0, priority: int = PlaybackPriority.AUTO_SCENE):
    return PlaybackItem(
        session_id="session-1",
        turn_id=turn_id,
        segment_index=segment_index,
        audio_bytes=f"audio-{turn_id}-{segment_index}".encode(),
        priority=priority,
    )


def test_user_microphone_priority_and_playback_events():
    player = FakePlayer()
    events = []
    queue = PlaybackQueue(player, on_event=events.append)

    automatic = _item(1)
    user = _item(2, priority=PlaybackPriority.USER_MIC)
    assert queue.enqueue(automatic).status == "queued"
    assert queue.enqueue(user).status == "queued"
    assert player.started == [b"audio-1-0", b"audio-2-0"]
    assert [event.kind for event in events] == [
        "start",
        "interrupted",
        "end",
        "start",
    ]
    assert events[1].reason == "higher_priority"

    player.complete()
    assert events[-1].kind == "end"
    assert events[-1].reason == "completed"


def test_lower_priority_audio_waits_behind_user_and_pause_is_observable():
    player = FakePlayer()
    events = []
    queue = PlaybackQueue(player, on_event=events.append)
    user = _item(1, priority=PlaybackPriority.USER_MIC)
    automatic = _item(2)

    queue.enqueue(user)
    queue.enqueue(automatic)
    assert queue.active_item == user
    assert queue.queued_items == (automatic,)
    assert queue.pause() is True
    assert player.pause_count == 1
    assert events[-1].kind == "pause"

    player.complete()
    assert queue.active_item == automatic
    player.complete()
    assert events[-1].reason == "completed"


def test_replace_policy_interrupts_current_item_for_same_turn():
    player = FakePlayer()
    events = []
    queue = PlaybackQueue(player, on_event=events.append)
    original = _item(4, segment_index=0)
    replacement = _item(4, segment_index=1)

    queue.enqueue(original)
    result = queue.enqueue(replacement, policy="replace")

    assert result.status == "queued"
    assert queue.active_item == replacement
    assert player.started == [b"audio-4-0", b"audio-4-1"]
    assert [event.kind for event in events] == [
        "start",
        "interrupted",
        "end",
        "start",
    ]


def test_cancelled_turn_rejects_late_audio_and_late_player_callback():
    player = FakePlayer()
    events = []
    queue = PlaybackQueue(player, on_event=events.append)
    item = _item(7)

    queue.enqueue(item)
    queue.cancel_turn("session-1", 7, reason="turn_cancelled")
    assert queue.active_item is None
    assert player.stop_count == 1
    assert queue.enqueue(item).status == "rejected"

    # The callback captured by the old player must not end a newer item.
    old_callback = player.current_callback
    if old_callback is not None:
        old_callback()
    assert queue.active_item is None
    assert [event.kind for event in events] == ["start", "interrupted", "end"]


def test_missing_audio_device_is_structured_unavailable():
    events = []
    queue = PlaybackQueue(on_event=events.append)
    result = queue.enqueue(_item(3))

    assert result.status == "unavailable"
    assert result.reason == "audio_player_unavailable"
    assert events[-1].kind == "end"
    assert events[-1].reason == "audio_player_unavailable"
