"""Shared test doubles for DanmuApp and related components."""

from types import SimpleNamespace


class FakeLogger:
    def __init__(self):
        self.debug_messages = []
        self.info_messages = []
        self.error_messages = []

    def debug(self, message):
        self.debug_messages.append(message)

    def info(self, message):
        self.info_messages.append(message)

    def error(self, message):
        self.error_messages.append(message)


class FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=""):
        return self.values.get(key, default)

    def get_int(self, key, default=0):
        return int(self.values.get(key, default))

    def get_float(self, key, default=0.0):
        return float(self.values.get(key, default))

    def set_batch(self, items):
        pass


class FakeLifetimeStats:
    def add_danmu(self, count: int = 1) -> None:
        pass

    def add_tokens(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        pass

    def flush_pending(self) -> None:
        pass

    def flush_runtime(self, session_sec: float) -> None:
        pass

    def snapshot(self, *, session_runtime_sec: float = 0.0) -> dict:
        return {
            "lifetime_danmu_count": 0,
            "lifetime_runtime_sec": 0.0,
            "lifetime_input_tokens": 0,
            "lifetime_output_tokens": 0,
            "lifetime_total_tokens": 0,
        }


class FakeSessionRunLog:
    def begin(self, **_kwargs) -> None:
        pass

    def complete(self, **_kwargs) -> None:
        pass

    def list_dicts_newest_first(self, limit: int = 20) -> list[dict]:
        return []


class FakeTrack:
    def __init__(self):
        self.items = []


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.running = False
        self.screen_width = 1920.0
        self.tracks = []
        self._config_values = {}

    def add_text(self, content, persona, batch_id=0, scene_generation=0, *, skip_dedup=False, **_kwargs):
        self.calls.append((content, persona))
        return SimpleNamespace(
            content=content,
            persona=persona,
            batch_id=batch_id,
            scene_generation=scene_generation,
            x=2000.0,
            speed=2.2,
        )

    def clear_dedup_window(self):
        pass

    def drop_pending_below_generation(self, min_generation):
        return 0

    def drop_items_below_scene_generation(self, min_generation):
        return 0

    def drop_items_with_batch_id(self, batch_id):
        return 0

    def visible_display_count(self):
        return 0

    def min_on_screen(self):
        return self._config_values.get("min_on_screen", 5)

    def danmu_pool_enabled(self):
        return bool(self._config_values.get("danmu_pool_enabled", False))

    def deficit_below_min(self):
        return 0

    def current_display_count(self):
        return 0

    def get_display_count(self):
        return 0

    def right_zone_count(self):
        return 0


class FakeHistory:
    def __init__(self):
        self.calls = []

    def add(self, content, persona, round_num):
        self.calls.append((content, persona, round_num))


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

    def isActive(self):
        return self.active

    def start(self, ms=0):
        self.active = True
        self.started += 1

    def stop(self):
        self.active = False
        self.stopped += 1

    def interval(self):
        return self._interval

    def setInterval(self, ms):
        self._interval = ms
