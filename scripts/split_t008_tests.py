#!/usr/bin/env python3
"""One-off splitter for T008: giant test files -> domain modules."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

WEB_AUTH = {
    "test_export_config",
    "test_apply_config_patch",
    "test_extract_config_payload",
    "test_web_config_keys",
    "test_export_web_config_defaults",
    "test_announcements",
}

WEB_BRIDGE = {
    "test_refresh_status",
    "test_build_status_snapshot",
    "test_bridge_save_config",
    "test_save_config_via_bridge",
    "test_web_status_timer",
    "test_resolve_request_credentials",
    "test_invoke_on_main",
    "test_save_config_times_out",
    "test_probe_route",
    "test_test_danmu_route",
    "test_capture_region",
    "test_mic_test",
    "test_active_personae_route",
    "test_session_route",
}

WEB_WS = {
    "test_ws_status",
}

WEB_SERVER = {
    "test_model_catalog",
    "test_providers_excludes",
    "test_web_settings_ui",
    "test_web_app_js",
    "test_list_recent_logs",
    "test_register_status_consumer",
    "test_enqueue_ws",
    "test_web_console_wait_ready",
    "test_notify_wait_ready",
    "test_classify_web_console",
    "test_startup_error",
    "test_startup_warning",
    "test_attach_status_timer",
    "test_web_console_server_stop",
    "test_quit_stops_web_status",
    "test_quit_logs_warning",
}

P0_CAPTURE = {
    "test_normal_mode_start",
    "test_normal_tick_skips",
    "test_compress_screenshot",
    "test_capture_failure",
    "test_invalid_pixmap",
    "test_capture_does_not",
    "test_capture_while_in_flight",
    "test_repeated_capture",
    "test_screenshot_loop",
    "test_consecutive_failures",
    "test_fatal_error",
    "test_success_resets_failure",
    "test_schedule_webview",
    "test_open_web_console",
    "test_webview",
    "test_browser_mode",
}

P0_AI = {
    "test_normal_mode_no_stale_ttl",
    "test_normal_mode_no_stale",
    "test_on_ai_reply_enqueues",
    "test_runnable_request",
    "test_ai_success_reply",
    "test_legacy_stat_fields",
    "test_legacy_web_error",
    "test_older_reply_not_dropped",
    "test_ai_error",
    "test_nonfatal_ai_error",
    "test_ai_error_does_not_crash",
    "test_empty_ai_reply",
    "test_legacy_overlay_cache",
    "test_generation_pipeline_state",
}

P0_REPLY = {
    "test_normal_mode_enqueues",
    "test_normal_mode_consumes",
    "test_history_enqueue",
    "test_inject_test_danmu",
    "test_show_startup_notice",
    "test_init_normalizes",
    "test_config_change_updates",
    "test_start_seeds",
    "test_startup_notice_skipped",
    "test_init_language",
    "test_start_without_api_key",
    "test_toggle_without_api_key",
    "test_stop_flushes",
    "test_flush_session_runtime",
    "test_pick_random",
    "test_delete_custom",
    "test_quit_stops_pool",
}


def _bucket(name: str, rules: dict[str, set[str]]) -> str | None:
    for prefix, _ in [(k, v) for k, v in rules.items()]:
        pass
    for key in rules:
        if name.startswith(key) or name == key:
            return key
    return None


def assign_web(name: str) -> str:
    for p in WEB_WS:
        if name.startswith(p):
            return "websocket"
    for p in WEB_BRIDGE:
        if name.startswith(p):
            return "bridge"
    for p in WEB_AUTH:
        if name.startswith(p):
            return "auth"
    for p in WEB_SERVER:
        if name.startswith(p):
            return "server"
    raise ValueError(f"unassigned web test: {name}")


def assign_p0(name: str) -> str:
    for p in P0_CAPTURE:
        if name.startswith(p):
            return "capture"
    for p in P0_AI:
        if name.startswith(p):
            return "ai"
    for p in P0_REPLY:
        if name.startswith(p):
            return "reply"
    raise ValueError(f"unassigned p0 test: {name}")


def extract_chunks(source: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (module_preamble, [(func_name, source_chunk), ...])."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    preamble_end = 0
    chunks: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                chunk = "".join(lines[node.lineno - 1 : node.end_lineno])
                chunks.append((node.name, chunk))
            elif isinstance(node, ast.ClassDef):
                chunk = "".join(lines[node.lineno - 1 : node.end_lineno])
                # attach classes to preamble via name
                chunks.append((f"__class__:{node.name}", chunk))
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith("test_"):
            preamble_end = max(preamble_end, node.end_lineno)
        else:
            preamble_end = max(preamble_end, getattr(node, "end_lineno", node.lineno))
    # preamble: everything before first test/class that's not a private helper after imports
    first_test_line = min(
        (n.lineno for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))),
        default=len(lines),
    )
    # include module docstring + imports only; helpers extracted separately
    preamble = "".join(lines[: first_test_line - 1])
    return preamble, chunks


WEB_IMPORTS = '''"""Web console tests: {domain}."""

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.application.generation_pipeline_state import GenerationPipelineState
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.web_console import (
    _SAVE_DONE_EVENT_KEY,
    _SAVE_RESULT_KEY,
    WEB_CONFIG_KEYS,
    WebConsoleBridge,
    _write_config_save_result,
    apply_config_patch,
    export_config,
    extract_config_payload,
    save_config_via_bridge,
)
from main import DanmuApp

from tests.fakes import FakeConfig, FakeTimer
from tests.web_console_helpers import make_status_app, pump_qt_until, build_ws_status_test_app
'''

P0_CAPTURE_IMPORTS = '''"""Main flow tests: capture, backoff, and web launch."""

import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from app.reply_queue import QueuedReply
from main import DanmuApp, compress_screenshot, show_startup_notice_if_needed
from PyQt6.QtWidgets import QApplication

from tests.conftest import make_minimal_danmu_app, start_app_timers
from tests.fakes import FakeCapturer, FakePixmap, FakeTimer
'''

P0_AI_IMPORTS = '''"""Main flow tests: AI pipeline, in-flight, and errors."""

import time
from unittest.mock import MagicMock, Mock

import pytest
from app.application.generation_pipeline_state import GenerationPipelineState
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.ai_client import AiWorker
from app.reply_queue import QueuedReply
from app.runnable import AiRunnable
from main import DanmuApp, compress_screenshot
from PyQt6.QtWidgets import QApplication

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeCapturer, FakePixmap
'''

P0_REPLY_IMPORTS = '''"""Main flow tests: reply enqueue, lifecycle, and persona."""

import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from app.application.web_runtime_state import WebRuntimeState
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine, normalize_danmu_display_text
from app.lifetime_stats import STATS_LIFETIME_RUNTIME_SEC, LifetimeStats
from app.overlay import DanmuOverlay
from app.reply_queue import AIReplyFIFOBuffer
from main import DanmuApp, show_startup_notice_if_needed
from PyQt6.QtWidgets import QApplication

from tests.conftest import bind_minimal_danmu_app, make_minimal_danmu_app, start_app_timers
from tests.fakes import DedupFakeEngine, FakeEngine, FakeTimer
'''


def split_file(
    src: Path,
    assign_fn,
    targets: dict[str, Path],
    import_headers: dict[str, str],
    helper_names: set[str],
) -> None:
    source = src.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    helpers: list[str] = []
    tests_by_bucket: dict[str, list[str]] = {k: [] for k in targets}

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            helpers.append("".join(lines[node.lineno - 1 : node.end_lineno]))
        elif isinstance(node, ast.FunctionDef):
            chunk = "".join(lines[node.lineno - 1 : node.end_lineno])
            if node.name.startswith("test_"):
                bucket = assign_fn(node.name)
                tests_by_bucket[bucket].append(chunk)
            elif node.name in helper_names or node.name.startswith("_"):
                helpers.append(chunk)

    for bucket, path in targets.items():
        header = import_headers[bucket].format(domain=bucket)
        body = "\n\n".join(tests_by_bucket[bucket])
        text = header + "\n\n" + body + "\n"
        text = text.replace("_make_minimal_app()", "make_minimal_danmu_app()")
        text = text.replace("_make_minimal_app(", "make_minimal_danmu_app(")
        text = text.replace("_start_app_timers(", "start_app_timers(")
        text = text.replace("_make_status_app()", "make_status_app()")
        text = text.replace("_make_status_app(", "make_status_app(")
        text = text.replace("_pump_qt_until(", "pump_qt_until(")
        text = text.replace("_build_ws_status_test_app(", "build_ws_status_test_app(")
        text = text.replace(
            "_make_app_for_start_without_api_key(", "make_app_for_start_without_api_key("
        )
        text = re.sub(
            r"@pytest\.fixture\(\)\ndef qapp\(\):.*?(?=\ndef test_)",
            "",
            text,
            flags=re.DOTALL,
        )
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path.name}: {len(tests_by_bucket[bucket])} tests, {path.stat().st_size} bytes")


def main() -> None:
    web_src = TESTS / "test_web_console.py"
    web_targets = {
        "auth": TESTS / "test_web_auth.py",
        "bridge": TESTS / "test_web_bridge.py",
        "server": TESTS / "test_web_server.py",
        "websocket": TESTS / "test_web_websocket.py",
    }
    web_headers = {k: WEB_IMPORTS for k in web_targets}
    split_file(
        web_src,
        assign_web,
        web_targets,
        web_headers,
        {"_make_status_app", "_build_ws_status_test_app", "_pump_qt_until"},
    )

    p0_src = TESTS / "test_p0_main_flow.py"
    p0_targets = {
        "capture": TESTS / "test_capture_flow.py",
        "ai": TESTS / "test_ai_pipeline.py",
        "reply": TESTS / "test_reply_enqueue.py",
    }
    p0_headers = {
        "capture": P0_CAPTURE_IMPORTS,
        "ai": P0_AI_IMPORTS,
        "reply": P0_REPLY_IMPORTS,
    }
    split_file(
        p0_src,
        assign_p0,
        p0_targets,
        p0_headers,
        {
            "_make_minimal_app",
            "_start_app_timers",
            "_make_app_for_start_without_api_key",
        },
    )


if __name__ == "__main__":
    main()
