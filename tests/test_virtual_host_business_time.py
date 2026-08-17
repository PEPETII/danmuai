"""回归：虚拟主播业务时间统一 wall clock，性能计时使用 monotonic。"""

from __future__ import annotations

import time

from app.virtual_host.chat import HostChatHttpResult
from app.virtual_host.contracts import DanmuBatchCreated, HostTurnResult, SceneContext
from app.virtual_host.model_config import VISION_MODEL_KEY, apply_virtual_host_model_config
from app.virtual_host.response_scheduler import ResponseCandidateEvent, VirtualHostResponseScheduler
from app.virtual_host.runtime_service import VirtualHostRuntimeService, _monotonic_elapsed_since
from app.virtual_host.vision import SceneSummaryResult

from tests.fakes import FakePixmap
from tests.test_virtual_host_runtime import _fake_app, _FakeConfig, _vision_profile


def _vision_config(vision_model: str = "qwen3-vl-flash") -> _FakeConfig:
    config = _FakeConfig({VISION_MODEL_KEY: vision_model}, custom_models=[_vision_profile(vision_model)])
    apply_virtual_host_model_config(config, {"vision_model_id": vision_model})
    return config


def _running_service(monkeypatch, *, sync_workers: bool = False) -> VirtualHostRuntimeService:
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.compress_screenshot",
        lambda _pixmap: "data:image/jpeg;base64,ZmFrZQ==",
    )
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_scene_summary",
        lambda *_args, **_kwargs: SceneSummaryResult(
            ok=True,
            text="桌面游戏画面",
            model_id="qwen3-vl-flash",
        ),
    )
    if sync_workers:
        class _SyncPool:
            def start(self, runnable):
                runnable.run()

        monkeypatch.setattr("app.virtual_host.runtime_service.ai_worker_pool", lambda: _SyncPool())
    service = VirtualHostRuntimeService(_fake_app(_vision_config()))
    service.start()
    return service


def test_monotonic_captured_at_scene_context_is_fresh_with_wall_clock_now():
    """主链路 monotonic captured_at 不得写入 SceneContext.updated_at。"""

    captured_at = time.monotonic() - 0.05
    service = VirtualHostRuntimeService(_fake_app(_vision_config()))
    service.start()
    service._apply_scene_summary(
        SceneSummaryResult(ok=True, text="Boss 战", model_id="qwen3-vl-flash"),
        screenshot_id=1,
        scene_generation=0,
        captured_at=captured_at,
    )

    context = service.session.current_scene_context()
    assert context is not None
    assert context.summary == "Boss 战"
    assert context.updated_at >= 1_000_000_000
    assert context.is_fresh(scene_generation=0, now=time.time())


def test_scene_context_survives_danmu_batch_with_wall_clock_created_at(monkeypatch):
    """SceneContext(wall) 与 DanmuBatch(wall) 同域时调度器仍能看到画面上下文。"""

    service = _running_service(monkeypatch)
    captured_at = time.monotonic() - 0.02
    service._apply_scene_summary(
        SceneSummaryResult(ok=True, text="联机大厅", model_id="qwen3-vl-flash"),
        screenshot_id=2,
        scene_generation=0,
        captured_at=captured_at,
    )

    batch = DanmuBatchCreated.from_lines(
        batch_id="wall-batch",
        lines=["来了来了"],
        created_at=time.time(),
        scene_generation=0,
    )
    service.on_danmu_batch_created(batch)

    scheduler = VirtualHostResponseScheduler(rng=lambda: 0.0)
    decision = scheduler.evaluate(
        ResponseCandidateEvent(kind="danmu_batch", at=time.time(), batch_id="wall-batch", scene_generation=0),
        running=True,
        model_enabled=True,
        chat_in_flight=False,
        last_spoke_at=None,
        session=service.session,
        now=time.time(),
    )
    assert service.session.current_scene_context(now=time.time()) is not None
    assert decision.reason != "no_context"


def test_second_scene_change_not_permanently_blocked_by_clock_mix(monkeypatch):
    """scene_change → chat 完成 → 冷却结束后第二次 scene_change 不得永久 cooldown。"""

    service = _running_service(monkeypatch, sync_workers=True)
    service._response_scheduler = VirtualHostResponseScheduler(
        rng=lambda: 0.0,
        min_cooldown_seconds=0.05,
    )
    chat_calls = 0

    def _fake_chat(prompt, resolved, *, session_id, turn_id, http_client=None):
        del prompt, resolved, http_client
        nonlocal chat_calls
        chat_calls += 1
        return HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="接话", speak=False),
            model_id="qwen3-vl-flash",
        )

    monkeypatch.setattr("app.virtual_host.runtime_service.request_host_chat", _fake_chat)

    captured_at = time.monotonic() - 0.01
    service._apply_scene_summary(
        SceneSummaryResult(ok=True, text="第一幕", model_id="qwen3-vl-flash"),
        screenshot_id=3,
        scene_generation=0,
        captured_at=captured_at,
    )
    assert chat_calls == 1
    assert service._last_spoke_at is not None
    assert service._last_spoke_at >= 1_000_000_000

    time.sleep(0.06)
    service._apply_scene_summary(
        SceneSummaryResult(ok=True, text="第二幕", model_id="qwen3-vl-flash"),
        screenshot_id=4,
        scene_generation=0,
        captured_at=time.monotonic() - 0.01,
    )
    assert chat_calls == 2


def test_scene_context_ttl_still_expires_with_wall_clock():
    from app.virtual_host.session import VirtualHostSession

    session = VirtualHostSession()
    session.update_scene_context(
        SceneContext(scene_generation=0, summary="旧画面", updated_at=1_000.0, ttl_seconds=10.0)
    )
    assert session.current_scene_context(now=1_000.0) is not None
    assert session.current_scene_context(now=1_011.0) is None


def test_danmu_batch_ttl_does_not_regress():
    now = time.time()
    batch = DanmuBatchCreated.from_lines(
        batch_id="ttl-batch",
        lines=["未过期"],
        created_at=now - 5.0,
        scene_generation=0,
        ttl_seconds=10.0,
    )
    assert not batch.is_expired(now=now)
    assert batch.is_expired(now=now + 6.0)


def test_scene_latency_diagnostic_uses_monotonic_capture_stamp(monkeypatch, qapp):
    """scene_latency_ms 仍基于 monotonic captured_at，数值应接近真实耗时。"""

    config = _vision_config()
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.compress_screenshot",
        lambda _pixmap: "data:image/jpeg;base64,ZmFrZQ==",
    )

    def _slow_request(_image_data_uri, resolved, *, http_client=None):
        del http_client
        time.sleep(0.08)
        return SceneSummaryResult(ok=True, text="延迟画面", model_id=resolved[2])

    monkeypatch.setattr("app.virtual_host.runtime_service.request_scene_summary", _slow_request)

    from PyQt6.QtCore import QThreadPool

    pool = QThreadPool()
    monkeypatch.setattr("app.virtual_host.runtime_service.ai_worker_pool", lambda: pool)

    captured: list[dict] = []

    def _capture_diag(event, **fields):
        if event == "scene_end" and fields.get("applied"):
            captured.append(dict(fields))

    monkeypatch.setattr("app.virtual_host.runtime_service.log_diagnostic", _capture_diag)

    service = VirtualHostRuntimeService(_fake_app(config))
    service.start()
    capture_stamp = time.monotonic()
    service.on_capture_completed(
        FakePixmap(1),
        screenshot_id=8,
        scene_generation=1,
        captured_at=capture_stamp,
    )

    deadline = time.monotonic() + 2.0
    while service.vision_in_flight and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    pool.waitForDone(2000)

    assert captured, "expected scene_end diagnostic"
    latency_ms = captured[-1]["scene_latency_ms"]
    assert latency_ms >= 50.0
    assert latency_ms < 5_000.0
    assert _monotonic_elapsed_since(capture_stamp) >= 0.05


def test_monotonic_elapsed_since_rejects_negative_drift():
    future_stamp = time.monotonic() + 1.0
    assert _monotonic_elapsed_since(future_stamp) == 0.0
