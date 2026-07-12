"""Shared test doubles for DanmuApp and related components."""

import json
from types import SimpleNamespace


class FakeLogger:
    """替代 ``SanitizedLogger`` 的内存版记录器。

    收集 4 类调用（debug/info/warning/error）到 list；不写文件，不接 Qt 信号。
    单测断言常用::

        assert "expected" in app.logger.error_messages
    """

    def __init__(self):
        self.debug_messages = []
        self.info_messages = []
        self.error_messages = []
        self.warning_messages = []

    @staticmethod
    def _format(message, args):
        if not args:
            return message
        try:
            return message % args
        except Exception:
            return f"{message} {args!r}"

    def debug(self, message, *args):
        self.debug_messages.append(self._format(message, args))

    def info(self, message, *args):
        self.info_messages.append(self._format(message, args))

    def error(self, message, *args):
        self.error_messages.append(self._format(message, args))

    def warning(self, message, *args):
        self.warning_messages.append(self._format(message, args))


class FakeConfig:
    """替代 ``ConfigStore`` 的纯内存版配置。

    用法：``FakeConfig({"api_key": "sk-...", "model": "doubao-seed-1-6-vision"})``
    提供 ``.get()`` / ``.set()`` / ``.get_int()`` 等与 ``ConfigStore`` 一致的
    公开方法；``api_key`` 仍走 ``_api_key`` 私有字段（与生产一致），但不做
    Fernet 加密。
    """

    def __init__(self, values=None):
        self.values = dict(values or {})
        if values and "_api_key" in values:
            self._api_key = values["_api_key"]
        else:
            self._api_key = self.values.get("api_key", self.values.get("_api_key", ""))

    def get(self, key, default=""):
        return self.values.get(key, default)

    def get_int(self, key, default=0):
        val = self.get(key)
        if val == "" or val is None:
            return int(default)
        return int(val)

    def get_float(self, key, default=0.0):
        val = self.get(key)
        if val == "" or val is None:
            return float(default)
        return float(val)

    def set(self, key, value):
        self.values[key] = value

    def set_batch(self, items):
        self.values.update(items)

    def apply_web_save(
        self,
        *,
        items: dict[str, str] | None = None,
        api_key: str | None = None,
        mic_api_key: str | None = None,
        custom_models: list[dict] | None = None,
        flags: dict[str, str] | None = None,
    ) -> None:
        if items:
            self.values.update(items)
        if api_key is not None:
            self.set_api_key(api_key)
        if mic_api_key:
            self.set_mic_api_key(mic_api_key)
        if custom_models is not None:
            self.set_custom_models(custom_models)
        if flags:
            if not hasattr(self, "_flags"):
                self._flags = {}
            self._flags.update(flags)

    def set_api_key(self, key):
        self._api_key = key
        self.values["api_key_encrypted"] = "enc"

    def set_default_model_id(self, model_id):
        self.values["default_model_id"] = model_id

    def set_custom_models(self, models):
        self.values["custom_models"] = models

    def get_custom_danmu_pool(self):
        raw = self.values.get("custom_danmu_pool", [])
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def get_recent_history(self, limit: int = 30) -> list[str]:
        return []

    def set_custom_danmu_pool(self, items):
        self.values["custom_danmu_pool"] = list(items)

    def get_region(self):
        region = self.values.get("region")
        if region is not None:
            return region
        return (
            self.get_int("region_x", 0),
            self.get_int("region_y", 0),
            self.get_int("region_w", 0),
            self.get_int("region_h", 0),
        )

    def set_region(self, x, y, w, h):
        self.values["region_x"] = str(x)
        self.values["region_y"] = str(y)
        self.values["region_w"] = str(w)
        self.values["region_h"] = str(h)

    def get_default_model_id(self):
        return str(self.values.get("default_model_id", self.values.get("model", "")))

    def get_api_key(self):
        if self._api_key:
            return str(self._api_key)
        return str(self.values.get("api_key", ""))

    def get_mic_api_key(self):
        return str(self.values.get("_mic_api_key", self.values.get("mic_api_key", "")))

    def set_mic_api_key(self, key):
        self.values["_mic_api_key"] = key
        self.values["mic_api_key_encrypted"] = "enc"

    def get_custom_models(self):
        from app.config_store.crypto import canonicalize_custom_model_profile

        raw = self.values.get("custom_models", [])
        return [
            canonicalize_custom_model_profile(dict(m))
            for m in raw
            if isinstance(m, dict)
        ]

    def get_mic_devices(self):
        return list(self.values.get("mic_devices", []))

    def get_json(self, key: str, default=None):
        val = self.get(key)
        if not val:
            return default if default is not None else {}
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default if default is not None else {}

    def set_json(self, key: str, value):
        self.values[key] = json.dumps(value, ensure_ascii=False)


AI_CLIENT_FAKE_DEFAULTS = {
    "api_endpoint": "https://global.example.com/v1",
    "api_mode": "doubao",
    "model": "doubao-seed-1-6-flash-250828",
    "_api_key": "sk-global-key",
}


def ai_client_fake_config(*, data=None, api_key=None, default_model_id=None, custom_models=None):
    """Build ``FakeConfig`` with AI client test defaults (see ``test_ai_client.py``)."""
    values = dict(AI_CLIENT_FAKE_DEFAULTS)
    if data:
        values.update(data)
    if default_model_id is not None:
        values["default_model_id"] = default_model_id
    if api_key is not None:
        values["_api_key"] = api_key
    if custom_models is not None:
        values["custom_models"] = custom_models
    else:
        # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: resolve_request_credentials 仅走 custom_models；
        # 未显式传 custom_models 时自动从 data 构建完整档案以兼容旧测试
        model_id = values.get("default_model_id") or values.get("model", "")
        endpoint = values.get("api_endpoint", "")
        mode = values.get("api_mode", "doubao")
        key = values.get("_api_key") or values.get("api_key") or ""
        if model_id and endpoint:
            values["custom_models"] = [
                {
                    "name": "Fake",
                    "default_model_id": model_id,
                    "modelId": model_id,
                    "endpoint": endpoint,
                    "apiKey": key,
                    "mode": mode,
                }
            ]
            if "default_model_id" not in values:
                values["default_model_id"] = model_id
    cfg = FakeConfig(values)
    if api_key is not None:
        cfg.set_api_key(api_key)
    return cfg


class FakeLifetimeStats:
    """空操作版 ``LifetimeStats``，不持久化、不递增。

    主链路单测里只要确保接口被调用即可；累计统计由 ``test_lifetime_stats.py``
    单独覆盖真实现。
    """

    def add_danmu(self, count: int = 1) -> None:
        pass

    def add_tokens(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        pass

    def flush_pending(self) -> None:
        pass

    def flush_runtime(self, session_sec: float) -> bool:
        return True

    def snapshot(self, *, session_runtime_sec: float = 0.0) -> dict:
        return {
            "lifetime_danmu_count": 0,
            "lifetime_runtime_sec": 0.0,
            "lifetime_input_tokens": 0,
            "lifetime_output_tokens": 0,
            "lifetime_total_tokens": 0,
        }


class FakeSessionRunLog:
    """空操作版 ``SessionRunLog``，不写 config.db，``list_dicts_newest_first`` 返回空。

    完整 SQLite 持久化由 ``test_session_run_log.py`` 覆盖。
    """

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
    """替代 ``danmu_engine.DanmuEngine`` 的可断言版。

    关键点：
        - ``add_text`` 总是"成功"，返回 SimpleNamespace（content/persona/...）
          但不真正创建 QGraphicsItem（避免起 QApplication）
        - ``calls`` 列表记录每次 ``add_text`` 的 ``(content, persona)``
        - ``running`` / ``dropped_pending`` 让 stop/clear 路径可断言
        - ``min_on_screen`` / ``danmu_pool_use_custom`` 来自 ``_config_values``
    """

    def __init__(self, config_values=None):
        self.calls = []
        self.running = False
        self.dropped_pending = 0
        self.screen_width = 1920.0
        self.screen_height = 1080.0
        self._accel_remaining = 0
        self._accel_peak = 1.0
        self.tracks = []
        self._config_values = dict(config_values or {})
        self._right_zone_count = 0
        self._display_count = 0

    def add_text(self, content, persona, batch_id=0, scene_generation=0, *, skip_dedup=False, **_kwargs):
        self.calls.append((content, persona))
        return SimpleNamespace(
            content=content,
            persona=persona,
            batch_id=batch_id,
            scene_generation=scene_generation,
            x=2000.0,
            y=90.0,
            speed=2.2,
        )

    def clear_dedup_window(self):
        pass

    def drop_pending_below_generation(self, min_generation):
        return 0

    def visible_display_count(self):
        return 0

    def min_on_screen(self):
        return self._config_values.get("min_on_screen", 5)

    def danmu_pool_enabled(self):
        return bool(self._config_values.get("danmu_pool_use_custom", False))

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

    def drop_pending_items(self):
        self.dropped_pending += 1
        return 1

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class DedupFakeEngine(FakeEngine):
    def __init__(self, duplicate_text: str):
        super().__init__()
        self.duplicate_text = duplicate_text
        self.running = True

    def add_text(self, content, persona, batch_id=0, scene_generation=0, *, skip_dedup=False, **_kwargs):
        if not skip_dedup and content == self.duplicate_text:
            return None
        return super().add_text(
            content,
            persona,
            batch_id=batch_id,
            scene_generation=scene_generation,
            skip_dedup=skip_dedup,
        )

    def is_duplicate(self, content: str) -> bool:
        return content == self.duplicate_text


class FakeCapturer:
    """替代 ``app.snipper.ScreenCapturer``：``grab()`` 永远返回构造时传入的 pixmap。

    单测里用 ``FakePixmap`` 作为 pixmap，模拟"截到一帧"或"截到 None"。
    """

    def __init__(self, pixmap=None):
        self._pixmap = pixmap

    def grab(self):
        return self._pixmap

    def build_plan(self):
        if self._pixmap is None:
            return None
        from app.snipper import CapturePlan

        return CapturePlan(
            mode="screen",
            screen_index=0,
            grab_x=0,
            grab_y=0,
            grab_w=200,
            grab_h=200,
            hwnd=0,
        )


class FakePixmap:
    def __init__(self, scene_byte, *, is_null: bool = False, width: int = 200, height: int = 200):
        self.scene_byte = scene_byte
        self._is_null = is_null
        self._width = width
        self._height = height

    def isNull(self):
        return self._is_null

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeHistoryWriter:
    """替代 ``HistoryWriter`` 的可断言版。

    ``enqueue`` 收集 ``(content, persona, round_num, image_bytes)`` 到
    ``self.calls``；不写 SQLite。``stop`` 空操作（生产里是 flush + 关线程）。
    """

    def __init__(self):
        self.calls = []

    def enqueue(self, content, persona, round_num, image_bytes=None):
        self.calls.append((content, persona, round_num, image_bytes))

    def stop(self):
        pass


class FakeTimer:
    """替代 ``QTimer`` 的可断言版：记录 start/stop 次数，不真触发。

    默认 ``_interval=800``（与主链路截图节拍一致）；单测里可改 ``_interval``
    模拟不同节奏。``active`` 是状态查询的真相源（不靠 ``isActive`` 调用）。
    """

    def __init__(self):
        self.active = False
        self.started = 0
        self.stopped = 0
        self._interval = 800
        self._single_shot = False
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

    def setSingleShot(self, val):
        self._single_shot = val
