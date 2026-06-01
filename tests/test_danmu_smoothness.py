"""消费节奏与缓冲模拟测试。

PipelineSimulator 仅测 reply_timer 间隔与队列排水，不复制 main 已移除的
drop_stale / freshness 轮次滞后丢弃策略（_is_reply_stale 恒为不丢弃）。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply


class FakeLogger:
    def __init__(self):
        self.messages = []

    def debug(self, m):
        self.messages.append(("debug", m))

    def info(self, m):
        self.messages.append(("info", m))

    def error(self, m):
        self.messages.append(("error", m))


class FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=""):
        return self._values.get(key, default)

    def get_int(self, key, default=0):
        v = self._values.get(key, default)
        try:
            return int(v)
        except (ValueError, TypeError):
            return default

    def get_float(self, key, default=0.0):
        v = self._values.get(key, default)
        try:
            return float(v)
        except (ValueError, TypeError):
            return default


class FakeHistoryWriter:
    def __init__(self):
        self.calls = []

    def enqueue(self, content, persona, round_num, image_bytes=None):
        self.calls.append((content, persona, round_num, image_bytes))

    def stop(self):
        pass


class FakeTimer:
    def __init__(self):
        self.active = False
        self.started = 0
        self.stopped = 0
        self._interval = 800
        self.intervals = []

    def isActive(self):
        return self.active

    def start(self, ms=0):
        self.active = True
        self.started += 1
        if ms > 0:
            self._interval = ms
        self.intervals.append(ms)

    def stop(self):
        self.active = False
        self.stopped += 1

    def interval(self):
        return self._interval

    def setInterval(self, ms):
        self._interval = ms


class FakeEngine:
    def __init__(self, config_values=None):
        self._config_values = config_values or {}
        self.running = True
        self.calls = []
        self._right_zone_count = 0
        self._display_count = 0

    def add_text(self, content, persona):
        self.calls.append((content, persona))
        return SimpleNamespace(content=content, persona=persona)

    def min_on_screen(self):
        return self._config_values.get("min_on_screen", 5)

    def deficit_below_min(self):
        return 0

    def current_display_count(self):
        return self._display_count

    def get_display_count(self):
        return self._display_count

    def right_zone_count(self):
        return self._right_zone_count

    def needs_refill(self):
        return True


class PipelineSimulator:
    def __init__(self, config_values=None):
        self.logger = FakeLogger()
        self.engine = FakeEngine(config_values)
        self.history_writer = FakeHistoryWriter()
        self.reply_buffer = AIReplyFIFOBuffer(max_items=8)
        self.reply_timer = FakeTimer()
        self.ai_in_flight = 0
        self.danmu_count = 0
        self.screenshot_round = 10
        self._latest_displayed_round = 0
        self._rtt_history = []
        self._last_request_time = 0.0
        self._queue_low_watermark = 3
        self._queue_fallback_keep = 3
        self.config = FakeConfig(config_values)

    def _estimated_reply_gap_ms(self):
        if self.reply_timer.isActive():
            current_interval = self.reply_timer.interval()
            if current_interval > 0:
                return current_interval

        right_count = self.engine.right_zone_count()
        min_n = self.engine.min_on_screen()
        right_target = max(1, (min_n // 3) if min_n > 0 else 2)
        if self.engine.current_display_count() == 0:
            return 120
        if right_count >= right_target:
            return 1000
        if right_count > 0:
            return 500
        return 200

    def _smart_cooldown_ms(self):
        if len(self._rtt_history) >= 3:
            sorted_rtt = sorted(self._rtt_history)
            idx = int(len(sorted_rtt) * 0.9)
            p90 = sorted_rtt[min(idx, len(sorted_rtt) - 1)]
            return max(1500, min(int(p90 * 0.9 * 1000), 30000))
        base = self.config.get_int("screenshot_interval", 3)
        return max(2000, base * 1000)

    def _consume_reply_queue(self):

        queued = self.reply_buffer.pop()
        if queued is None:
            return

        item = self.engine.add_text(queued.content, queued.persona_id)
        if item:
            self._latest_displayed_round = max(self._latest_displayed_round, queued.screenshot_round)
            self.history_writer.enqueue(queued.content, queued.persona_id, queued.batch_index)

        if not self.reply_buffer.is_empty():
            delay = 100 if item is None else self._estimated_reply_gap_ms()
            self.reply_timer.start(delay)

        self.danmu_count += 1

    def _on_ai_reply(self, text, persona_id, request_round):
        import json
        import time
        from json import JSONDecodeError

        self.ai_in_flight = max(0, self.ai_in_flight - 1)

        if self._last_request_time > 0:
            rtt = time.monotonic() - self._last_request_time
            self._rtt_history.append(rtt)
            if len(self._rtt_history) > 20:
                self._rtt_history.pop(0)

        try:
            items = json.loads(text) if text.strip().startswith('[') else [text]
            if not isinstance(items, list):
                items = [text]
        except JSONDecodeError:
            items = [text]

        batch_items = []
        for content_index, item_text in enumerate(items):
            item_text = str(item_text).strip()
            if not item_text:
                continue
            batch_items.append(QueuedReply(
                persona_id, request_round, content_index, item_text,
                screenshot_round=request_round,
            ))

        self.reply_buffer.prepend_batch(
            batch_items,
            preserve_existing=self._queue_fallback_keep,
            preserve_scene_generation=0,
        )

        if not self.reply_timer.isActive():
            self._consume_reply_queue()
        elif not self.reply_buffer.is_empty():
            if self.reply_buffer.size() > self._queue_low_watermark:
                self.reply_timer.stop()
                self._consume_reply_queue()
            else:
                self.reply_timer.setInterval(min(self.reply_timer.interval(), 200))


def test_consume_reply_queue_discarded_danmu_uses_short_delay():
    sim = PipelineSimulator()
    sim.engine.add_text = MagicMock(return_value=None)

    for i in range(5):
        sim.reply_buffer.push(QueuedReply("p1", 1, i, f"dup{i}", screenshot_round=10))

    sim._consume_reply_queue()

    assert sim.reply_timer.intervals[-1] == 100


def test_consume_reply_queue_successful_danmu_uses_adaptive_delay():
    sim = PipelineSimulator({"min_on_screen": 9})
    sim.engine._config_values["min_on_screen"] = 9
    sim.engine._right_zone_count = 0

    sim.reply_buffer.push(QueuedReply("p1", 1, 0, "hello", screenshot_round=10))
    sim.reply_buffer.push(QueuedReply("p1", 1, 1, "world", screenshot_round=10))
    sim._consume_reply_queue()

    assert sim.reply_timer.intervals[-1] == 120

    sim.reply_buffer.push(QueuedReply("p1", 1, 0, "busy1", screenshot_round=10))
    sim.reply_buffer.push(QueuedReply("p1", 1, 1, "busy2", screenshot_round=10))
    sim.engine._display_count = 1
    sim.engine._right_zone_count = 2
    sim._consume_reply_queue()

    assert sim.reply_timer.intervals[-1] == 120

    sim.reply_buffer.push(QueuedReply("p1", 1, 0, "full1", screenshot_round=10))
    sim.reply_buffer.push(QueuedReply("p1", 1, 1, "full2", screenshot_round=10))
    sim.engine._display_count = 1
    sim.engine._right_zone_count = 10
    sim._consume_reply_queue()

    assert sim.reply_timer.intervals[-1] == 120


def test_on_ai_reply_accelerates_consumption_when_buffer_grows():
    sim = PipelineSimulator()
    sim.reply_timer.active = True

    sim._on_ai_reply('["A1", "A2", "A3", "A4"]', "p1", 10)

    assert sim.reply_timer.stopped >= 1
    assert not sim.reply_buffer.is_empty()


def test_on_ai_reply_reduces_timer_interval_when_buffer_small():
    sim = PipelineSimulator()
    sim.reply_timer.active = True
    sim.reply_timer._interval = 1000

    sim._on_ai_reply('["B1"]', "p1", 10)

    assert sim.reply_timer._interval <= 200


def test_old_screenshot_round_still_consumes():
    sim = PipelineSimulator()
    sim.screenshot_round = 20

    sim.reply_buffer.push(QueuedReply("p1", 1, 0, "old", screenshot_round=10))
    sim.reply_buffer.push(QueuedReply("p1", 1, 1, "also-old", screenshot_round=10))
    sim._consume_reply_queue()
    sim._consume_reply_queue()

    assert [c[0] for c in sim.engine.calls] == ["old", "also-old"]


def test_engine_add_text_precomputes_width(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")

    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    item = engine.add_text("hello world")
    assert item is not None
    assert item.width > 0


def test_consume_reply_queue_drains_buffer_without_stalling():
    sim = PipelineSimulator()
    sim.engine.add_text = MagicMock(side_effect=[
        SimpleNamespace(content="a", persona="p1"),
        None,
        SimpleNamespace(content="c", persona="p1"),
    ])
    sim.engine._right_zone_count = 0

    sim.reply_buffer.push(QueuedReply("p1", 1, 0, "a", screenshot_round=10))
    sim.reply_buffer.push(QueuedReply("p1", 1, 1, "b", screenshot_round=10))
    sim.reply_buffer.push(QueuedReply("p1", 1, 2, "c", screenshot_round=10))

    sim._consume_reply_queue()
    assert sim.reply_timer.intervals[-1] == 120

    sim._consume_reply_queue()
    assert sim.reply_timer.intervals[-1] == 100

    sim._consume_reply_queue()
    assert sim.reply_buffer.is_empty()


def test_continuous_flow_multiple_replies():
    sim = PipelineSimulator()
    sim.engine._right_zone_count = 0

    for i in range(10):
        sim.reply_buffer.push(QueuedReply("p1", 1, i, f"msg{i}", screenshot_round=10))

    consumed = 0
    while not sim.reply_buffer.is_empty():
        sim._consume_reply_queue()
        consumed += 1
        if consumed > 20:
            break

    assert consumed == 8
    assert sim.reply_buffer.is_empty()


def test_mixed_success_and_dedup_drains_quickly():
    sim = PipelineSimulator()
    results = [SimpleNamespace(content="ok1", persona="p1"), None, SimpleNamespace(content="ok2", persona="p1"), None, SimpleNamespace(content="ok3", persona="p1")]
    sim.engine.add_text = MagicMock(side_effect=results)
    sim.engine._right_zone_count = 0

    for i in range(5):
        sim.reply_buffer.push(QueuedReply("p1", 1, i, f"msg{i}", screenshot_round=10))

    consumed = 0
    while not sim.reply_buffer.is_empty():
        sim._consume_reply_queue()
        consumed += 1
        if consumed > 10:
            break

    assert consumed == 5
    assert sim.reply_buffer.is_empty()

    assert 100 in sim.reply_timer.intervals
