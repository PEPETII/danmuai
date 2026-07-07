"""Web 控制台支撑模块：状态快照、配置导出/导入、保存流程辅助。

与 web_console.py 关系：从 web_console 提取的辅助函数，保持路由/启动代码精简。
所有函数均在 HTTP 线程执行（除 apply_config_patch 经 bridge 到主线程）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.application.config_service import MASKED_API_KEY, WEB_CONFIG_KEYS, apply_web_config_patch
from app.errors import AppError
from app.translations import tr
from app.logger import (
    API_KEY_PATTERN,
    AUTH_HEADER_PATTERN,
    BASE64_AUDIO_PATTERN,
    BASE64_IMAGE_PATTERN,
    ENCRYPTED_KEY_PATTERN,
    GENERIC_API_KEY_PATTERN,
)

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge

_STATUS_DIFF_SKIP_KEYS = frozenset({
    "runtime_sec",
    "live_delay_sec",
    "lifetime_runtime_sec",
})


def status_payloads_semantically_equal(
    a: dict[str, Any] | None,
    b: dict[str, Any] | None,
) -> bool:
    """比较 status payload，忽略单调递增时间字段（前端 RUNTIME_CLOCK 本地推进）。"""
    if a is None or b is None:
        return a is b
    a_cmp = {k: v for k, v in a.items() if k not in _STATUS_DIFF_SKIP_KEYS}
    b_cmp = {k: v for k, v in b.items() if k not in _STATUS_DIFF_SKIP_KEYS}
    return a_cmp == b_cmp


SAVE_CONFIG_TIMEOUT_SEC = 10.0
SAVE_CONFIG_ERROR_DETAIL_MAX = 200
SAVE_DONE_EVENT_KEY = "__save_done_event"
SAVE_RESULT_KEY = "__save_result"


@dataclass
class WebStatusSnapshot:
    running: bool = False
    danmu_count: int = 0
    queue_count: int = 0
    display_count: int = 0
    dropped_by_cap: int = 0
    danmu_render_mode: str = "scrolling"
    overlay_display_count: int = 0
    floating_panel_active_count: int = 0
    floating_panel_render_active: bool = False
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    runtime_sec: float = 0.0
    error_message: str = ""
    is_error: bool = False
    overlay_compat_warning: str = ""
    screen_index_fallback_warning: str = ""
    live_analyzing: bool = False
    live_local_fallback: bool = False
    live_delay_sec: float = 0.0
    live_message: str = ""
    persona_names: list[str] = field(default_factory=list)
    screen_index: int = 0
    has_api_key: bool = False
    dedup_profile: dict[str, Any] | None = None
    lifetime_danmu_count: int = 0
    lifetime_runtime_sec: float = 0.0
    lifetime_total_tokens: int = 0
    lifetime_input_tokens: int = 0
    lifetime_output_tokens: int = 0
    session_runs: list[dict] = field(default_factory=list)
    active_model_id: str = ""
    inferred_provider_id: str = ""
    model_display_name: str = ""
    uses_custom_credentials: bool = False
    model_source: str = "unknown"
    provider_model_mismatch: bool = False
    capture_mode: str = "screen"
    capture_window_hwnd: int = 0
    capture_region_mode: str = "full"
    region_x: int = 0
    region_y: int = 0
    region_w: int = 0
    region_h: int = 0
    region_selection_state: str = "idle"
    meme_barrage: dict[str, Any] = field(default_factory=dict)
    danmu_track_layout: dict[str, Any] = field(default_factory=dict)


def summarize_config_save_error(detail: object, *, max_len: int = SAVE_CONFIG_ERROR_DETAIL_MAX) -> str:
    text = str(detail or "").strip()
    if not text:
        return tr("config.saveFailedGeneric")
    text = API_KEY_PATTERN.sub("sk-****", text)
    text = BASE64_IMAGE_PATTERN.sub("data:image/***;base64,(hidden)", text)
    text = BASE64_AUDIO_PATTERN.sub("data:audio/***;base64,(hidden)", text)
    text = AUTH_HEADER_PATTERN.sub("Authorization: Bearer (hidden)", text)
    text = ENCRYPTED_KEY_PATTERN.sub("gAAAA****(hidden)", text)
    text = GENERIC_API_KEY_PATTERN.sub("(api_key: ****)", text)
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}…"


def _screen_label(index: int, width: int, height: int) -> str:
    n = index + 1
    w = int(width or 0)
    h = int(height or 0)
    if w > 0 and h > 0:
        return tr("display.labelWithSize").format(n=n, w=w, h=h)
    return tr("display.label").format(n=n)


def _screen_item(index: int, width: int, height: int) -> dict[str, Any]:
    return {
        "index": index,
        "label": _screen_label(index, width, height),
        "width": int(width),
        "height": int(height),
    }


def localize_screen_labels(screens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-label cached screens for the active Translator language."""
    if not screens:
        return [_screen_item(0, 0, 0)]
    return [
        _screen_item(
            int(item.get("index", 0)),
            int(item.get("width", 0)),
            int(item.get("height", 0)),
        )
        for item in screens
    ]


def enumerate_screens() -> list[dict[str, Any]]:
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return [_screen_item(0, 0, 0)]
    screens = app.screens() or []
    items = []
    for index, screen in enumerate(screens):
        geo = screen.geometry()
        dpr = screen.devicePixelRatio()
        phys_w = int(geo.width() * dpr)
        phys_h = int(geo.height() * dpr)
        items.append(_screen_item(index, phys_w, phys_h))
    return items or [_screen_item(0, 0, 0)]


def is_empty_screens_fallback(screens: list[dict[str, Any]]) -> bool:
    """True when enumerate_screens had no Qt screens() yet (single 0×0 placeholder)."""
    if len(screens) != 1:
        return False
    item = screens[0]
    return (
        item.get("index") == 0
        and int(item.get("width", -1)) == 0
        and int(item.get("height", -1)) == 0
    )


def resolve_screens_for_api(
    cached: list[dict[str, Any]] | None,
    live: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer live enumeration when cache is empty, stale fallback, or has fewer displays."""
    cached_list = list(cached or [])
    if not cached_list:
        return live
    if len(live) > len(cached_list):
        return live
    if is_empty_screens_fallback(cached_list) and not is_empty_screens_fallback(live):
        return live
    return cached_list


def screens_for_api(bridge: object) -> list[dict[str, Any]]:
    """Return cached screens when valid; otherwise enumerate and merge."""
    cached = getattr(bridge, "cached_screens", None)
    if cached and not is_empty_screens_fallback(cached):
        raw = list(cached)
    else:
        live = enumerate_screens()
        raw = resolve_screens_for_api(cached, live)
    return localize_screen_labels(raw)


def try_cache_screens(bridge: object) -> bool:
    """Write bridge.cached_screens when Qt reports real displays; return True if cached."""
    screens = enumerate_screens()
    if not is_empty_screens_fallback(screens):
        bridge.cached_screens = screens
        return True
    return False


_SCREEN_CACHE_RETRY_DELAYS_MS = (500, 100, 500)


def schedule_screen_cache(bridge: object) -> None:
    """Delay first cache until displays exist; retry up to 3 times (BUG-030)."""
    from PyQt6.QtCore import QTimer

    def _attempt(attempt_index: int) -> None:
        if try_cache_screens(bridge):
            return
        if attempt_index >= len(_SCREEN_CACHE_RETRY_DELAYS_MS) - 1:
            screens = enumerate_screens()
            if screens:
                bridge.cached_screens = screens
            return
        delay_ms = _SCREEN_CACHE_RETRY_DELAYS_MS[attempt_index + 1]
        QTimer.singleShot(delay_ms, lambda: _attempt(attempt_index + 1))

    QTimer.singleShot(_SCREEN_CACHE_RETRY_DELAYS_MS[0], lambda: _attempt(0))


def _mask_mic_api_key(config) -> str:
    getter = getattr(config, "get_mic_api_key", None)
    if callable(getter) and getter():
        return MASKED_API_KEY
    return ""


def export_config(config) -> dict[str, Any]:
    from app.config_defaults import config_value_with_default
    from app.model_providers import (
        mic_audio_supported_for_mic_config,
        resolve_active_model_id,
    )
    from app.model_selection import resolve_model_status
    from app.personae import normal_reply_count_from_config
    from app.web_api.capture_region import capture_region_mode
    from app.web_api.custom_models import _mask_model

    data = {key: config_value_with_default(config, key) for key in WEB_CONFIG_KEYS}
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: GET /api/config 不再返回 api_key / has_api_key
    # （has_api_key 仍由 /api/status 经 runtime_state.py 提供）
    active_model_id = resolve_active_model_id(config)
    model_status = resolve_model_status(config)
    data["default_model_id"] = config.get_default_model_id()
    data["active_model_id"] = active_model_id
    data.update(model_status)
    data["mic_api_key"] = _mask_mic_api_key(config)
    data["has_mic_api_key"] = bool(getattr(config, "get_mic_api_key", lambda: "")())
    data["mic_audio_likely_supported"] = mic_audio_supported_for_mic_config(config)
    data["mic_input_device_id"] = str(config.get("mic_input_device_id", "") or "")
    data["custom_models"] = [
        _mask_model(model)
        for model in config.get_custom_models()
        if isinstance(model, dict)
    ]
    data["reply_batch_total"] = normal_reply_count_from_config(config)
    data["pet_barrage_mode_enabled"] = str(config.get("pet_barrage_mode_enabled", "0") or "0")
    data["pet_barrage_count"] = str(config.get("pet_barrage_count", "5") or "5")
    rx, ry, rw, rh = config.get_region()
    data["region_x"] = rx
    data["region_y"] = ry
    data["region_w"] = rw
    data["region_h"] = rh
    data["capture_region_mode"] = capture_region_mode(config)
    data["thinking_supported"] = _thinking_supported(config, active_model_id)
    return data


def _thinking_supported(config, active_model_id: str) -> bool:
    from app.model_catalog import catalog_model_supports_thinking_toggle
    from app.model_providers import get_capabilities_for_model

    mid = (active_model_id or "").strip()
    if not mid or not catalog_model_supports_thinking_toggle(mid):
        return False

    # 优先检查自定义模型档案（W-CUSTOMMODEL-SCHEMA-002：default_model_id 优先于 modelId）
    custom_models = config.get_custom_models()
    for model in custom_models:
        if isinstance(model, dict):
            entry_id = (
                model.get("default_model_id") or model.get("modelId") or ""
            ).strip()
            if entry_id == active_model_id:
                endpoint = model.get("endpoint") or ""
                api_mode = model.get("mode") or ""
                caps = get_capabilities_for_model(active_model_id, endpoint, api_mode)
                return caps.thinking_param_style != "none"

    # 全局 api_endpoint + api_mode
    endpoint = config.get("api_endpoint") or ""
    api_mode = config.get("api_mode") or "doubao"
    caps = get_capabilities_for_model(active_model_id, endpoint, api_mode)
    return caps.thinking_param_style != "none"


def extract_config_payload(body: Any) -> dict[str, Any]:
    """Accept `{data: {...}}` wrapper or a flat config patch dict."""
    if not isinstance(body, dict):
        raise ValueError(tr("config.invalidData"))
    nested = body.get("data")
    if isinstance(nested, dict):
        return nested
    if body:
        return body
    raise ValueError(tr("config.emptyData"))


def apply_config_patch(danmu_app, payload: dict[str, Any]) -> None:
    """主线程执行：委托 ConfigService 统一处理 Web 配置 patch。"""
    apply_web_config_patch(danmu_app, payload)


def write_config_save_result(
    result_holder: object,
    *,
    ok: bool,
    error: str | None = None,
    detail: str | None = None,
) -> None:
    if not isinstance(result_holder, dict):
        return
    result_holder.clear()
    result_holder["ok"] = ok
    if error:
        result_holder["error"] = error
    if detail:
        result_holder["detail"] = detail


def save_config_via_bridge(
    bridge: "WebConsoleBridge",
    payload: dict[str, Any],
    *,
    timeout_sec: float = SAVE_CONFIG_TIMEOUT_SEC,
) -> dict[str, Any]:
    done = threading.Event()
    result: dict[str, Any] = {
        "ok": False,
        "error": "save_timeout",
        "detail": tr("config.saveTimeout"),
    }
    queued_payload = dict(payload)
    queued_payload[SAVE_DONE_EVENT_KEY] = done
    queued_payload[SAVE_RESULT_KEY] = result
    bridge.save_config_requested.emit(queued_payload)
    if done.wait(timeout=timeout_sec):
        return result
    bridge.danmu_app.logger.error(
        "配置保存超时: keys=%s timeout_sec=%.1f",
        sorted(payload.keys()),
        timeout_sec,
    )
    return result


def handle_save_config_request(bridge: "WebConsoleBridge", payload: object) -> None:
    if not isinstance(payload, dict):
        return
    done_event = payload.pop(SAVE_DONE_EVENT_KEY, None)
    result_holder = payload.pop(SAVE_RESULT_KEY, None)
    keys = sorted(payload.keys())
    cap_mode = payload.get("capture_mode", "<missing>")
    cap_hwnd = payload.get("capture_window_hwnd", "<missing>")
    try:
        bridge.danmu_app.apply_web_config_payload(payload)
    except (AppError, ValueError, TypeError, PermissionError) as exc:
        detail = summarize_config_save_error(tr("config.saveFailed", error=exc))
        write_config_save_result(
            result_holder,
            ok=False,
            error="save_failed",
            detail=detail,
        )
        bridge.danmu_app.logger.error(
            "配置保存失败: keys=%s, error=%s",
            keys,
            exc,
            exc_info=True,
        )
        bridge.danmu_app.set_web_error_status(detail, is_error=True)
        bridge.publish_status()
        if done_event is not None:
            done_event.set()
        return
    except Exception as exc:  # boundary: unexpected config save failure
        detail = summarize_config_save_error(tr("config.saveFailed", error=exc))
        write_config_save_result(
            result_holder,
            ok=False,
            error="save_failed",
            detail=detail,
        )
        bridge.danmu_app.logger.error(
            "配置保存失败: keys=%s, error=%s",
            keys,
            exc,
            exc_info=True,
        )
        bridge.danmu_app.set_web_error_status(detail, is_error=True)
        bridge.publish_status()
        if done_event is not None:
            done_event.set()
        return
    write_config_save_result(result_holder, ok=True)
    if done_event is not None:
        done_event.set()
    stored_mode = bridge.danmu_app.config.get("capture_mode", "screen")
    stored_hwnd = bridge.danmu_app.config.get("capture_window_hwnd", "0")
    bridge.danmu_app.logger.info(
        "配置保存成功: keys=%s capture_mode=%s→%s capture_window_hwnd=%s→%s",
        keys,
        cap_mode,
        stored_mode,
        cap_hwnd,
        stored_hwnd,
    )
    bridge.danmu_app.set_web_error_status("", is_error=False)
    bridge.publish_status()
