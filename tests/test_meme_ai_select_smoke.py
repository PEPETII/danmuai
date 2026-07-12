"""Smoke test: meme AI select with a real project image."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.ai_client_support import AiProbeResult
from app.application.stats_state import StatsState
from app.config_store import ConfigStore
from app.lifetime_stats import LifetimeStats
from app.main_meme_mixin import _MemeBarrageBridge
from app.meme_barrage.ai_select import parse_meme_ai_selection
from app.meme_barrage.runnable import MemeAiSelectRunnable
from app.meme_barrage.service import MemeBarrageService
from app.screenshot_compress import compress_screenshot
from main import DanmuApp
from PyQt6.QtGui import QPixmap

ROOT = Path(__file__).resolve().parent.parent


def _pick_project_image() -> Path:
    for rel in (
        "web/static/image/qrcode_1779738450536.jpg",
        "image/qrcode_1779738450536.jpg",
        "data/pet/default/spritesheet.webp",
    ):
        path = ROOT / rel
        if path.is_file():
            return path
    pytest.skip("no project test image found")


@pytest.fixture
def project_pixmap(qapp):
    path = _pick_project_image()
    pixmap = QPixmap(str(path))
    if pixmap.isNull() or pixmap.width() <= 0:
        pytest.skip(f"invalid pixmap from {path}")
    return pixmap


def test_meme_ai_select_with_project_image(project_pixmap, tmp_path):
    uri = compress_screenshot(project_pixmap)
    assert uri.startswith("data:image/jpeg;base64,")

    candidates = [
        "扫码加群领福利",
        "这画面有个二维码",
        "完全无关的烂梗",
        "瓦批的一天启动",
    ]
    pick_count = 2

    worker = MagicMock()
    worker._stopping = MagicMock()
    worker._stopping.is_set.return_value = False
    worker.resolve_request_credentials.return_value = (
        "https://example.com/v1",
        "sk-test",
        "test-model",
        "openai",
    )

    cfg = ConfigStore(db_path=tmp_path / "meme_smoke.db")
    selected_holder: list[tuple[list[str], int, int]] = []
    error_holder: list[tuple[str, int, int]] = []

    with patch(
        "app.ai_client_requests.request_openai",
        return_value=AiProbeResult(
            signal="finished",
            message=json.dumps(["这画面有个二维码"], ensure_ascii=False),
            input_tokens=123,
            output_tokens=45,
        ),
    ):
        MemeAiSelectRunnable(
            worker=worker,
            config=cfg,
            image_data_uri=uri,
            candidates=candidates,
            pick_count=pick_count,
            on_success=lambda selected, input_tokens, output_tokens: selected_holder.append(
                (selected, input_tokens, output_tokens)
            ),
            on_error=lambda message, input_tokens, output_tokens: error_holder.append(
                (message, input_tokens, output_tokens)
            ),
        ).run()

    assert not error_holder, error_holder
    assert selected_holder == [(["这画面有个二维码"], 123, 45)]

    parsed = parse_meme_ai_selection(
        json.dumps(["这画面有个二维码", "编造的"], ensure_ascii=False),
        candidates,
    )
    assert parsed == ["这画面有个二维码"]


def test_meme_ai_select_uses_functional_doubao_request(tmp_path):
    worker = MagicMock()
    worker._stopping.is_set.return_value = False
    resolved = (
        "https://ark.cn-beijing.volces.com/api/v3",
        "sk-test",
        "test-model",
        "doubao",
    )
    worker.resolve_request_credentials.return_value = resolved
    cfg = ConfigStore(db_path=tmp_path / "meme_doubao_request.db")
    selected_holder: list[tuple[list[str], int, int]] = []

    with (
        patch(
            "app.ai_client_requests.request_doubao",
            return_value=AiProbeResult(
                signal="finished",
                message=json.dumps(["候选弹幕"], ensure_ascii=False),
                input_tokens=12,
                output_tokens=3,
            ),
        ) as request_doubao,
        patch("app.ai_client_requests.request_openai") as request_openai,
    ):
        MemeAiSelectRunnable(
            worker=worker,
            config=cfg,
            image_data_uri="data:image/jpeg;base64,dGVzdA==",
            candidates=["候选弹幕"],
            pick_count=1,
            on_success=lambda selected, input_tokens, output_tokens: selected_holder.append(
                (selected, input_tokens, output_tokens)
            ),
            on_error=lambda *_args: pytest.fail("unexpected error callback"),
        ).run()

    request_openai.assert_not_called()
    request_doubao.assert_called_once()
    assert request_doubao.call_args.args[0] is worker
    assert request_doubao.call_args.kwargs["resolved"] == resolved
    assert request_doubao.call_args.kwargs["emit"] is False
    assert selected_holder == [(["候选弹幕"], 12, 3)]


@pytest.mark.parametrize(
    ("result", "expected_reason"),
    [
        (
            AiProbeResult(
                signal="error",
                message="provider_failed",
                input_tokens=123,
                output_tokens=45,
            ),
            "provider_failed",
        ),
        (
            AiProbeResult(
                signal="finished",
                message="[]",
                input_tokens=123,
                output_tokens=45,
            ),
            "empty_parse",
        ),
    ],
)
def test_meme_ai_select_error_paths_forward_usage(tmp_path, result, expected_reason):
    worker = MagicMock()
    worker._stopping.is_set.return_value = False
    worker.resolve_request_credentials.return_value = (
        "https://example.com/v1",
        "sk-test",
        "test-model",
        "openai",
    )
    cfg = ConfigStore(db_path=tmp_path / "meme_error_usage.db")
    error_holder: list[tuple[str, int, int]] = []

    with patch("app.ai_client_requests.request_openai", return_value=result):
        MemeAiSelectRunnable(
            worker=worker,
            config=cfg,
            image_data_uri="data:image/jpeg;base64,dGVzdA==",
            candidates=["候选弹幕"],
            pick_count=1,
            on_success=lambda *_args: pytest.fail("unexpected success callback"),
            on_error=lambda message, input_tokens, output_tokens: error_holder.append(
                (message, input_tokens, output_tokens)
            ),
        ).run()

    assert error_holder == [(expected_reason, 123, 45)]


def test_meme_ai_select_local_failure_has_zero_usage(tmp_path):
    worker = MagicMock()
    worker._stopping.is_set.return_value = False
    worker.resolve_request_credentials.return_value = None
    cfg = ConfigStore(db_path=tmp_path / "meme_local_failure.db")
    error_holder: list[tuple[str, int, int]] = []

    with patch("app.ai_client_requests.request_openai") as request_openai:
        MemeAiSelectRunnable(
            worker=worker,
            config=cfg,
            image_data_uri="data:image/jpeg;base64,dGVzdA==",
            candidates=["候选弹幕"],
            pick_count=1,
            on_success=lambda *_args: pytest.fail("unexpected success callback"),
            on_error=lambda message, input_tokens, output_tokens: error_holder.append(
                (message, input_tokens, output_tokens)
            ),
        ).run()

    request_openai.assert_not_called()
    assert error_holder == [("incomplete_credentials", 0, 0)]


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("stopping", "stopping"),
        ("no_image", "no_image"),
        ("compress_error", "compress_error:"),
    ],
    ids=("stopping", "no_image", "compress_error"),
)
def test_meme_ai_select_unrequested_paths_have_zero_usage(tmp_path, case, expected_reason):
    worker = MagicMock()
    worker._stopping.is_set.return_value = case == "stopping"
    cfg = ConfigStore(db_path=tmp_path / f"meme_unrequested_{case}.db")
    error_holder: list[tuple[str, int, int]] = []
    kwargs = {
        "image_data_uri": "data:image/jpeg;base64,dGVzdA==",
        "pixmap": None,
        "compress_fn": None,
    }
    if case == "no_image":
        kwargs["image_data_uri"] = None
    elif case == "compress_error":
        kwargs["image_data_uri"] = None
        kwargs["pixmap"] = object()

        def fail_compress(_pixmap):
            raise ValueError("boom")

        kwargs["compress_fn"] = fail_compress

    with (
        patch("app.ai_client_requests.request_openai") as request_openai,
        patch("app.ai_client_requests.request_doubao") as request_doubao,
    ):
        MemeAiSelectRunnable(
            worker=worker,
            config=cfg,
            candidates=["候选弹幕"],
            pick_count=1,
            on_success=lambda *_args: pytest.fail("unexpected success callback"),
            on_error=lambda message, input_tokens, output_tokens: error_holder.append(
                (message, input_tokens, output_tokens)
            ),
            **kwargs,
        ).run()

    request_openai.assert_not_called()
    request_doubao.assert_not_called()
    assert len(error_holder) == 1
    assert error_holder[0][0].startswith(expected_reason)
    assert error_holder[0][1:] == (0, 0)


def test_meme_ai_select_bridge_preserves_request_and_usage(qapp):
    bridge = _MemeBarrageBridge()
    done_holder: list[tuple[object, ...]] = []
    failed_holder: list[tuple[object, ...]] = []
    bridge.ai_select_done.connect(lambda *args: done_holder.append(args))
    bridge.ai_select_failed.connect(lambda *args: failed_holder.append(args))

    bridge.ai_select_done.emit(["已选"], ["候选"], 1, 7, 123, 45)
    bridge.ai_select_failed.emit(["候选"], 1, 8, 67, 9)
    qapp.processEvents()

    assert done_holder == [(["已选"], ["候选"], 1, 7, 123, 45)]
    assert failed_holder == [(["候选"], 1, 8, 67, 9)]


def _make_meme_app_with_stats(tmp_path):
    cfg = ConfigStore(db_path=tmp_path / "meme_accounting.db")
    danmu = DanmuApp.__new__(DanmuApp)
    danmu.config = cfg
    danmu.logger = MagicMock()
    danmu.stats_state = StatsState()
    danmu.lifetime_stats = LifetimeStats(cfg)
    service = MemeBarrageService(cfg)
    service.set_ai_select_in_flight(True)
    danmu._meme_barrage_service = service
    danmu._meme_ai_select_active_request_id = 1
    return danmu, service


@pytest.mark.parametrize("outcome", ["success", "error", "empty_parse"])
def test_meme_ai_select_accounts_usage_exactly_once(tmp_path, outcome):
    danmu, service = _make_meme_app_with_stats(tmp_path)
    candidates = ["候选弹幕", "回退弹幕"]

    if outcome == "success":
        invoke = lambda: danmu._on_meme_ai_select_done(
            ["候选弹幕"],
            fallback_candidates=candidates,
            fallback_n=1,
            request_id=1,
            input_tokens=123,
            output_tokens=45,
        )
    else:
        invoke = lambda: danmu._on_meme_ai_select_failed(
            candidates,
            1,
            request_id=1,
            input_tokens=123,
            output_tokens=45,
        )

    invoke()
    first_lifetime = danmu.lifetime_stats.snapshot()
    assert danmu.stats_state.total_input_tokens == 123
    assert danmu.stats_state.total_output_tokens == 45
    assert first_lifetime["lifetime_input_tokens"] == 123
    assert first_lifetime["lifetime_output_tokens"] == 45
    assert not service.is_ai_select_in_flight()

    invoke()
    second_lifetime = danmu.lifetime_stats.snapshot()
    assert danmu.stats_state.total_input_tokens == 123
    assert danmu.stats_state.total_output_tokens == 45
    assert second_lifetime["lifetime_input_tokens"] == 123
    assert second_lifetime["lifetime_output_tokens"] == 45


def test_meme_ai_select_duplicate_callback_does_not_repeat_display(tmp_path):
    danmu, service = _make_meme_app_with_stats(tmp_path)

    for _ in range(2):
        danmu._on_meme_ai_select_done(
            ["已选弹幕"],
            fallback_candidates=["回退弹幕"],
            fallback_n=1,
            request_id=1,
            input_tokens=123,
            output_tokens=45,
        )

    assert service.pop_display_batch(10) == ["已选弹幕"]
    assert danmu.stats_state.total_input_tokens == 123
    assert danmu.stats_state.total_output_tokens == 45


def test_meme_ai_select_stale_callback_preserves_new_inflight(tmp_path):
    danmu, service = _make_meme_app_with_stats(tmp_path)
    danmu._meme_ai_select_active_request_id = 2

    danmu._on_meme_ai_select_done(
        ["旧请求弹幕"],
        fallback_candidates=["旧回退"],
        fallback_n=1,
        request_id=1,
        input_tokens=123,
        output_tokens=45,
    )

    assert service.is_ai_select_in_flight()
    assert service.pop_display_batch(10) == []
    assert danmu.stats_state.total_input_tokens == 123
    assert danmu.stats_state.total_output_tokens == 45

    danmu._on_meme_ai_select_done(
        ["新请求弹幕"],
        fallback_candidates=["新回退"],
        fallback_n=1,
        request_id=2,
        input_tokens=20,
        output_tokens=5,
    )

    assert not service.is_ai_select_in_flight()
    assert service.pop_display_batch(10) == ["新请求弹幕"]
    assert danmu.stats_state.total_input_tokens == 143
    assert danmu.stats_state.total_output_tokens == 50


def test_meme_ai_select_stop_ignores_late_display_but_accounts_usage(tmp_path):
    danmu, service = _make_meme_app_with_stats(tmp_path)

    danmu._stop_meme_barrage_timers()
    danmu._on_meme_ai_select_failed(
        ["迟到回退"],
        1,
        request_id=1,
        input_tokens=123,
        output_tokens=45,
    )

    assert not service.is_ai_select_in_flight()
    assert service.pop_display_batch(10) == []
    assert danmu.stats_state.total_input_tokens == 123
    assert danmu.stats_state.total_output_tokens == 45


def test_meme_ai_select_local_failure_does_not_account_tokens(tmp_path):
    danmu, _service = _make_meme_app_with_stats(tmp_path)

    danmu._on_meme_ai_select_failed(
        ["候选弹幕"],
        1,
        request_id=1,
        input_tokens=0,
        output_tokens=0,
    )

    assert danmu.stats_state.total_input_tokens == 0
    assert danmu.stats_state.total_output_tokens == 0
    lifetime = danmu.lifetime_stats.snapshot()
    assert lifetime["lifetime_input_tokens"] == 0
    assert lifetime["lifetime_output_tokens"] == 0


def test_meme_ai_select_done_enqueues_filtered_only(project_pixmap, tmp_path):
    """入队路径：AI 成功时只写入筛选结果，不是全量 candidates。"""
    candidates = [
        "扫码加群领福利",
        "这画面有个二维码",
        "完全无关的烂梗",
        "瓦批的一天启动",
    ]
    cfg = ConfigStore(db_path=tmp_path / "meme_enqueue.db")
    danmu = DanmuApp.__new__(DanmuApp)
    danmu.config = cfg
    danmu.logger = MagicMock()
    service = MemeBarrageService(cfg)
    service.set_ai_select_in_flight(True)
    danmu._meme_barrage_service = service

    danmu._on_meme_ai_select_done(
        ["这画面有个二维码"],
        fallback_candidates=candidates,
        fallback_n=2,
    )

    batch = service.pop_display_batch(10)
    assert batch == ["这画面有个二维码"]
    assert len(batch) < len(candidates)


def test_meme_ai_select_live_api_if_configured(project_pixmap):
    import os

    from app.ai_client import AiWorker
    from app.ai_client_requests import request_doubao, request_openai
    from app.meme_barrage.ai_select import (
        build_meme_select_system_prompt,
        build_meme_select_user_prompt,
    )
    from app.model_providers import resolve_api_transport

    appdata = os.environ.get("APPDATA", "")
    real_db = Path(appdata) / "DanmuAI" / "config.db"
    if not real_db.is_file():
        pytest.skip("no user DanmuAI config.db")

    uri = compress_screenshot(project_pixmap)
    candidates = [
        "扫码加群领福利",
        "这画面有个二维码",
        "完全无关的烂梗",
    ]

    real_cfg = ConfigStore(db_path=real_db)
    real_worker = AiWorker(real_cfg)
    creds = real_worker.resolve_request_credentials()
    if creds is None:
        pytest.skip("incomplete API credentials")

    sys_pt = build_meme_select_system_prompt(real_cfg)
    user_pt = build_meme_select_user_prompt(candidates, 2)
    endpoint, _, _, api_mode = creds
    transport = resolve_api_transport(endpoint, api_mode)

    if transport == "doubao":
        res = request_doubao(
            real_worker, uri, sys_pt, user_pt, "meme_select", 0, 0, 0.0, 0, resolved=creds, emit=False
        )
    else:
        res = request_openai(
            real_worker, uri, sys_pt, user_pt, "meme_select", 0, 0, 0.0, 0, resolved=creds, emit=False
        )

    assert res is not None and res.signal == "finished", res
    selected = parse_meme_ai_selection(res.message, candidates)
    assert selected, f"empty parse from: {res.message[:400]!r}"
    print(f"\n[live meme AI] image={_pick_project_image().name}")
    print(f"[live meme AI] raw={res.message[:400]!r}")
    print(f"[live meme AI] selected={selected}")
    print(f"[live meme AI] tokens in/out={res.input_tokens}/{res.output_tokens}")
