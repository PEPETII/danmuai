import time
from types import SimpleNamespace
from unittest.mock import Mock

from app.mic_buffer import MicRingBuffer, clamp_mic_window_sec
from app.mic_capture import MicCaptureService, list_input_devices, resolve_preferred_input_device_id
from app.mic_encode import pcm_to_wav_data_uri
from app.mic_prompt import build_mic_insert_user_pt, mic_insert_reply_count
from app.mic_service import mic_input_device_id_from_config
from main import MIC_POLL_MS, MIC_POLL_PHASE_MS, DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig, FakeTimer


def test_clamp_mic_window_sec():
    assert clamp_mic_window_sec(0) == 1
    assert clamp_mic_window_sec(5) == 5
    assert clamp_mic_window_sec(99) == 30


def test_ring_buffer_keeps_recent_only():
    buf = MicRingBuffer(sample_rate=1000, capacity_sec=2)
    buf.append(b"\x01" * 2000)
    buf.append(b"\x02" * 2000)
    recent = buf.take_recent(1)
    assert len(recent) == 1000 * 2
    assert recent[0] == 2


def test_pcm_to_wav_data_uri():
    pcm = b"\x00\x01" * 2000
    uri = pcm_to_wav_data_uri(pcm)
    assert uri is not None
    assert uri.startswith("data:audio/wav;base64,")


def test_pcm_to_wav_data_uri_rejects_short():
    assert pcm_to_wav_data_uri(b"\x00\x01") is None


def test_mic_poll_interval_constants():
    assert MIC_POLL_MS == 600
    assert MIC_POLL_PHASE_MS == 250


def test_try_snapshot_pcm_ms_returns_pcm_when_lock_free():
    cap = MicCaptureService()
    cap._buffer.append(b"\x01\x02" * 8000)
    pcm = cap.try_snapshot_pcm_ms(200)
    assert pcm is not None
    assert len(pcm) > 0


def test_try_snapshot_pcm_ms_returns_none_when_lock_held():
    cap = MicCaptureService()
    cap._buffer.append(b"\x01\x02" * 8000)
    buf = cap._buffer
    buf._lock.acquire()
    try:
        start = time.perf_counter()
        pcm = cap.try_snapshot_pcm_ms(200)
        elapsed = time.perf_counter() - start
        assert pcm is None
        assert elapsed < 0.05
    finally:
        buf._lock.release()


def test_resolve_preferred_input_device_id():
    assert resolve_preferred_input_device_id("") is None
    assert resolve_preferred_input_device_id("  ") is None
    assert resolve_preferred_input_device_id("3") == 3
    assert resolve_preferred_input_device_id("-1") is None


def test_mic_input_device_id_from_config():
    cfg = FakeConfig({"mic_input_device_id": "7"})
    assert mic_input_device_id_from_config(cfg) == 7
    assert mic_input_device_id_from_config(FakeConfig({})) is None


def test_list_input_devices_without_sounddevice(monkeypatch):
    monkeypatch.setattr("app.mic_capture._HAS_SOUNDDEVICE", False)
    assert list_input_devices() == []


def test_mic_capture_start_uses_preferred_device(monkeypatch):
    calls = []

    class FakeStream:
        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            return None

    class FakeSd:
        def __init__(self):
            self.default = SimpleNamespace(device=(5, 7))

        def query_devices(self, device_id=None):
            if device_id is None:
                return [
                    {"name": "Mic A", "max_input_channels": 1},
                    {"name": "Mic B", "max_input_channels": 2},
                ]
            return {"name": f"Mic {device_id}", "max_input_channels": 1}

        def InputStream(self, **kwargs):
            calls.append(kwargs)
            return FakeStream()

    monkeypatch.setattr("app.mic_capture._HAS_SOUNDDEVICE", True)
    monkeypatch.setattr("app.mic_capture.sd", FakeSd())

    cap = MicCaptureService()
    assert cap.start(preferred_device_id=1) is True
    assert calls[0]["device"] == 1
    assert cap.active_device_id == 1
    assert cap.fallback_to_default is False


def test_mic_capture_start_falls_back_to_default_device(monkeypatch):
    calls = []

    class FakeStream:
        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            return None

    class FakeSd:
        def __init__(self):
            self.default = SimpleNamespace(device=(4, 7))

        def query_devices(self, device_id=None):
            if device_id is None:
                return [
                    {"name": "Mic A", "max_input_channels": 1},
                    {"name": "Mic B", "max_input_channels": 0},
                    {"name": "Mic C", "max_input_channels": 0},
                    {"name": "Mic D", "max_input_channels": 0},
                    {"name": "Default Mic", "max_input_channels": 1},
                ]
            info = {
                4: {"name": "Default Mic", "max_input_channels": 1},
            }
            if device_id in info:
                return info[device_id]
            raise RuntimeError("missing")

        def InputStream(self, **kwargs):
            calls.append(kwargs)
            return FakeStream()

    monkeypatch.setattr("app.mic_capture._HAS_SOUNDDEVICE", True)
    monkeypatch.setattr("app.mic_capture.sd", FakeSd())

    cap = MicCaptureService()
    assert cap.start(preferred_device_id=9) is True
    assert calls[0]["device"] == 4
    assert cap.active_device_id == 4
    assert cap.fallback_to_default is True


def test_sync_mic_service_stops_capture_when_danmu_pauses(monkeypatch):
    """BUG-005: pausing/stopping danmu must release mic capture when mic mode stays enabled."""
    from app.mic_orchestrator import MicOrchestrator

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"mic_mode_enabled": "1"}),
    )
    sync_calls: list[bool] = []
    running = [True]

    def _sync(*, enabled, preferred_device_id=None):
        sync_calls.append(enabled)
        if not enabled:
            running[0] = False

    mic_service = SimpleNamespace(
        is_running=lambda: running[0],
        sync=_sync,
        stop=lambda: running.__setitem__(0, False),
        last_error=lambda: "",
    )
    app._mic_service = mic_service
    app._mic_poll_timer = FakeTimer()
    app._mic_orchestrator = MicOrchestrator(
        mic_service=mic_service,
        on_utterance_end=lambda: None,
        log_fn=lambda _msg: None,
    )
    app.engine.running = False

    monkeypatch.setattr("main.mic_audio_supported_for_mic_config", lambda _cfg: True)

    DanmuApp._sync_mic_service(app)

    assert sync_calls == [False]
    assert not mic_service.is_running()


def test_mic_service_stops_when_engine_stops(monkeypatch):
    """BUG-005: engine_running=False must disable MicService capture."""
    from app.mic_orchestrator import MicOrchestrator

    sync_calls: list[bool] = []
    running = [True]

    def _sync(*, enabled, preferred_device_id=None):
        sync_calls.append(enabled)
        if not enabled:
            running[0] = False

    mic_service = SimpleNamespace(
        is_running=lambda: running[0],
        sync=_sync,
        last_error=lambda: "",
    )
    orch = MicOrchestrator(
        mic_service=mic_service,
        on_utterance_end=lambda: None,
        log_fn=lambda _msg: None,
    )
    monkeypatch.setattr("app.mic_orchestrator.mic_mode_enabled", lambda _cfg: True)

    orch.sync(
        engine_running=False,
        config=FakeConfig({"mic_mode_enabled": "1"}),
        mic_audio_supported_fn=lambda: True,
        resolve_active_model_id_fn=lambda: "mimo",
    )

    assert sync_calls == [False]
    assert not mic_service.is_running()


def _bind_app_for_stop(app, *, mic_service, mic_orchestrator) -> None:
    app.screenshot_timer = FakeTimer()
    app._live_status_timer = FakeTimer()
    app._pool_topup_timer = FakeTimer()
    app.ai_worker = SimpleNamespace(mark_stopping=lambda: None)
    app.overlay = SimpleNamespace(stop_render_loop=lambda: None, hide=lambda: None)
    app.tray = SimpleNamespace(update_state=lambda **kw: None)
    app.state_changed = Mock()
    app._mic_service = mic_service
    app._mic_orchestrator = mic_orchestrator
    app._mic_poll_timer = FakeTimer()
    app._topmost_health_timer = FakeTimer()
    object.__setattr__(
        app,
        "_flush_session_runtime_to_lifetime",
        DanmuApp._flush_session_runtime_to_lifetime.__get__(app, DanmuApp),
    )
    object.__setattr__(app, "_ensure_stats_state", DanmuApp._ensure_stats_state.__get__(app, DanmuApp))
    object.__setattr__(app, "_sync_mic_service", DanmuApp._sync_mic_service.__get__(app, DanmuApp))
    object.__setattr__(
        app,
        "_get_request_timing_service",
        DanmuApp._get_request_timing_service.__get__(app, DanmuApp),
    )


def test_stop_releases_mic_capture_when_mode_enabled(monkeypatch):
    """BUG-005: stop() must close mic capture even when mic mode stays enabled."""
    from app.mic_orchestrator import MicOrchestrator

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"mic_mode_enabled": "1"}),
    )
    sync_calls: list[bool] = []
    running = [True]

    def _sync(*, enabled, preferred_device_id=None):
        sync_calls.append(enabled)
        if not enabled:
            running[0] = False

    mic_service = SimpleNamespace(
        is_running=lambda: running[0],
        sync=_sync,
        stop=lambda: running.__setitem__(0, False),
        last_error=lambda: "",
    )
    mic_orchestrator = MicOrchestrator(
        mic_service=mic_service,
        on_utterance_end=lambda: None,
        log_fn=lambda _msg: None,
    )
    app.engine.running = True
    _bind_app_for_stop(app, mic_service=mic_service, mic_orchestrator=mic_orchestrator)

    monkeypatch.setattr("main.mic_audio_supported_for_mic_config", lambda _cfg: True)

    DanmuApp.stop(app)

    assert sync_calls == [False]
    assert not mic_service.is_running()


def test_stop_after_mic_started_does_not_restart_poll_or_calibrate(monkeypatch):
    """W-MIC-STOP-STATE-INIT-001: stop() must not restart mic poll or noise calibration."""
    from app.mic_orchestrator import MicOrchestrator
    from app.mic_utterance import MicUtteranceConfig, MicUtteranceDetector

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"mic_mode_enabled": "1"}),
    )
    running = [True]

    def _sync(*, enabled, preferred_device_id=None):
        if not enabled:
            running[0] = False

    mic_service = SimpleNamespace(
        is_running=lambda: running[0],
        sync=_sync,
        stop=lambda: running.__setitem__(0, False),
        last_error=lambda: "",
    )
    mic_orchestrator = MicOrchestrator(
        mic_service=mic_service,
        on_utterance_end=lambda: None,
        log_fn=lambda _msg: None,
    )
    mic_orchestrator._mic_utterance_detector = MicUtteranceDetector(
        on_utterance_end=lambda: None,
        config=MicUtteranceConfig(),
    )
    app.engine.running = True
    _bind_app_for_stop(app, mic_service=mic_service, mic_orchestrator=mic_orchestrator)
    app._mic_poll_timer.start(MIC_POLL_PHASE_MS)

    calibrate_calls: list[int] = []

    def _track_single_shot(ms, fn):
        if fn.__name__ == "_calibrate_mic_noise_floor":
            calibrate_calls.append(ms)

    monkeypatch.setattr("main.mic_audio_supported_for_mic_config", lambda _cfg: True)
    monkeypatch.setattr("app.main_mic_mixin.QTimer.singleShot", _track_single_shot)

    poll_starts_before = app._mic_poll_timer.started
    DanmuApp.stop(app)

    assert app._mic_orchestrator.detector is None
    assert not app._mic_poll_timer.active
    assert app._mic_poll_timer.started == poll_starts_before
    assert calibrate_calls == []


def test_restart_after_stop_resumes_mic_poll(monkeypatch):
    """W-MIC-STOP-STATE-INIT-001: start() after stop() should resume mic polling."""
    from app.mic_orchestrator import MicOrchestrator

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"mic_mode_enabled": "1"}),
    )
    running = [False]

    def _sync(*, enabled, preferred_device_id=None):
        running[0] = enabled

    mic_service = SimpleNamespace(
        is_running=lambda: running[0],
        sync=_sync,
        stop=lambda: running.__setitem__(0, False),
        last_error=lambda: "",
    )
    mic_orchestrator = MicOrchestrator(
        mic_service=mic_service,
        on_utterance_end=lambda: None,
        log_fn=lambda _msg: None,
    )
    app._mic_service = mic_service
    app._mic_orchestrator = mic_orchestrator
    app._mic_poll_timer = FakeTimer()
    object.__setattr__(app, "_sync_mic_service", DanmuApp._sync_mic_service.__get__(app, DanmuApp))

    monkeypatch.setattr("main.mic_audio_supported_for_mic_config", lambda _cfg: True)
    monkeypatch.setattr("app.main_mic_mixin.QTimer.singleShot", lambda ms, fn: None)

    app.engine.running = True
    DanmuApp._sync_mic_service(app)

    assert app._mic_orchestrator.detector is not None
    assert app._mic_poll_timer.active

    app.engine.running = False
    DanmuApp._sync_mic_service(app)

    assert app._mic_orchestrator.detector is None
    assert not app._mic_poll_timer.active

    app.engine.running = True
    DanmuApp._sync_mic_service(app)

    assert app._mic_orchestrator.detector is not None
    assert app._mic_poll_timer.active


def test_build_mic_insert_user_pt():
    out = build_mic_insert_user_pt("请生成弹幕：")
    assert "请生成弹幕：" in out
    assert "麦克风" in out
    assert "画面" in out

    out = build_mic_insert_user_pt("base")
    assert "麦克风插入" in out
    assert out.startswith("base")
    assert "请生成 5 条 JSON 数组弹幕" in out
    assert "全部同时结合当前画面与用户刚才说话内容" in out
    assert "不要只复述语音，也不要只描述截图" in out
    assert "前3条" not in out
    assert "前几条" not in out
    assert "其余" not in out
    assert "前0" not in out
    assert "前 0" not in out


def test_build_mic_insert_user_pt_ignores_config():
    from tests.fakes import FakeConfig

    cfg = FakeConfig({"mic_insert_reply_count": "5", "mic_insert_voice_reply_count": "2"})
    out_with_cfg = build_mic_insert_user_pt("base", cfg)
    out_without_cfg = build_mic_insert_user_pt("base")
    assert out_with_cfg == out_without_cfg
    assert "请生成 5条" not in out_with_cfg
    assert "前2条" not in out_with_cfg


def test_mic_insert_reply_count_follows_normal_reply_count():
    cfg = FakeConfig({"normal_reply_count": "8"})
    assert mic_insert_reply_count(cfg) == 8
    out = build_mic_insert_user_pt("base", cfg)
    assert "请生成 8 条 JSON 数组弹幕" in out


# ── BUG-014: mic 模型不支持时把错误推到 Web 状态栏 ──────────────────────


def _bind_app_for_mic_unsupported(app, *, mic_service) -> None:
    """装配 BUG-014 测试所需的 mic 链路对象。"""
    from app.mic_orchestrator import MicOrchestrator

    app._mic_service = mic_service
    app._mic_poll_timer = FakeTimer()
    app._mic_orchestrator = MicOrchestrator(
        mic_service=mic_service,
        on_utterance_end=lambda: None,
        log_fn=lambda _msg: None,
        on_unsupported_model_fn=app._on_mic_model_unsupported,
    )
    app.engine.running = True


def test_sync_mic_service_sets_web_error_when_model_unsupported(monkeypatch):
    """BUG-014: 模型不支持 mic_audio 时，sync 应通过回调把错误推到 Web 状态栏。"""
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"mic_mode_enabled": "1"}),
    )
    mic_service = SimpleNamespace(
        is_running=lambda: True,
        sync=lambda *, enabled, preferred_device_id=None: None,
        last_error=lambda: "",
    )
    _bind_app_for_mic_unsupported(app, mic_service=mic_service)

    error_calls: list[tuple[str, bool]] = []

    def fake_set_web_error_status(message, *, is_error):
        error_calls.append((message, is_error))

    object.__setattr__(app, "set_web_error_status", fake_set_web_error_status)

    monkeypatch.setattr("main.mic_audio_supported_for_mic_config", lambda _cfg: False)

    DanmuApp._sync_mic_service(app)

    # 期望：恰好一次以 is_error=True 推送错误，文案含「未声明 mic_audio 支持」
    assert len(error_calls) == 1, f"期望 1 次错误调用，得到 {error_calls}"
    msg, is_error = error_calls[0]
    assert is_error is True
    assert "未声明 mic_audio 支持" in msg
    # 标志位已置 True
    assert app._mic_unsupported_error_active is True
    # 首次 sync 走 unsupported 分支 → stop_detector，detector 仍为 None
    assert app._mic_orchestrator.detector is None


def test_sync_mic_service_clears_error_when_model_supported(monkeypatch):
    """BUG-014: 切回支持的模型后，sync 应清掉之前的 unsupported 错误条。"""
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"mic_mode_enabled": "1"}),
    )
    mic_service = SimpleNamespace(
        is_running=lambda: True,
        sync=lambda *, enabled, preferred_device_id=None: None,
        last_error=lambda: "",
    )
    _bind_app_for_mic_unsupported(app, mic_service=mic_service)

    # 预置：上一轮已设置错误条
    object.__setattr__(app, "_mic_unsupported_error_active", True)

    error_calls: list[tuple[str, bool]] = []

    def fake_set_web_error_status(message, *, is_error):
        error_calls.append((message, is_error))

    object.__setattr__(app, "set_web_error_status", fake_set_web_error_status)

    monkeypatch.setattr("main.mic_audio_supported_for_mic_config", lambda _cfg: True)
    # 避免真起 Qt 计时器（清错路径会调 QTimer.singleShot）
    monkeypatch.setattr("app.main_mic_mixin.QTimer.singleShot", lambda ms, fn: None)

    DanmuApp._sync_mic_service(app)

    # 期望：错误条被清除，标志位复位
    assert app._mic_unsupported_error_active is False
    assert ("", False) in error_calls, f"期望清错调用 ('', False)，得到 {error_calls}"
    # start_detector 已创建 detector
    assert app._mic_orchestrator.detector is not None
