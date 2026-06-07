#!/usr/bin/env python3
"""Rebalance T008 split files to stay under 500 lines."""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent / "tests"


def extract_named_functions(path: Path, names: set[str]) -> tuple[str, dict[str, str]]:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    chunks: dict[str, str] = {}
    skip_ranges: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            chunks[node.name] = "".join(lines[node.lineno - 1 : node.end_lineno])
            skip_ranges.append((node.lineno, node.end_lineno))
    keep = []
    for i, line in enumerate(lines, start=1):
        if not any(a <= i <= b for a, b in skip_ranges):
            keep.append(line)
    return "".join(keep), chunks


def append_chunks(path: Path, chunks: dict[str, str]) -> None:
    if not chunks:
        return
    path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n\n" + "\n\n".join(chunks.values()) + "\n")


def write_new(path: Path, header: str, chunks: dict[str, str]) -> None:
    path.write_text(header.rstrip() + "\n\n" + "\n\n".join(chunks.values()) + "\n", encoding="utf-8")


def main() -> None:
    bridge = TESTS / "test_web_bridge.py"
    auth = TESTS / "test_web_auth.py"
    server = TESTS / "test_web_server.py"
    capture = TESTS / "test_capture_flow.py"
    ai = TESTS / "test_ai_pipeline.py"

    status_names = {
        n.name
        for n in ast.parse(bridge.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef)
        and (
            n.name.startswith("test_build_status_snapshot")
            or n.name == "test_refresh_status_uses_public_status_snapshot"
        )
    }
    route_names = {
        "test_probe_route_accepts_json_body",
        "test_test_danmu_route_uses_public_app_entry",
        "test_capture_region_get_route",
        "test_capture_region_select_route_emits_signal",
        "test_capture_region_select_skips_emit_when_already_selecting",
        "test_capture_region_reset_route_emits_signal",
        "test_mic_test_route_uses_public_app_entry",
        "test_mic_test_send_route_uses_public_app_entry",
        "test_active_personae_route_uses_public_app_entry",
        "test_session_route_does_not_require_query_request",
    }
    launch_names = {
        n.name
        for n in ast.parse(capture.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef)
        and (
            n.name.startswith("test_schedule_webview")
            or n.name.startswith("test_open_web_console")
            or n.name.startswith("test_webview")
            or n.name.startswith("test_browser_mode")
        )
    }
    backoff_names = {
        "test_consecutive_failures_triggers_backoff",
        "test_fatal_error_immediate_backoff",
        "test_success_resets_failure_count",
        "test_screenshot_loop_respects_backoff",
    }
    ann_names = {
        n.name
        for n in ast.parse(auth.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef) and "announcements" in n.name
    }

    bridge_text, status_chunks = extract_named_functions(bridge, status_names)
    bridge_path = TESTS / "_bridge_tmp.py"
    bridge_path.write_text(bridge_text, encoding="utf-8")
    bridge_rest, route_chunks = extract_named_functions(bridge_path, route_names)
    bridge_path.unlink()
    bridge.write_text(bridge_rest, encoding="utf-8")

    capture_text, launch_chunks = extract_named_functions(capture, launch_names)
    capture_path = TESTS / "_capture_tmp.py"
    capture_path.write_text(capture_text, encoding="utf-8")
    capture_rest, backoff_chunks = extract_named_functions(capture_path, backoff_names)
    capture_path.unlink()
    capture.write_text(capture_rest, encoding="utf-8")

    auth_rest, ann_chunks = extract_named_functions(auth, ann_names)
    auth.write_text(auth_rest, encoding="utf-8")

    write_new(
        TESTS / "test_web_status.py",
        '''"""Web console tests: status snapshot and refresh."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.application.generation_pipeline_state import GenerationPipelineState
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.web_console import WebConsoleBridge
from main import DanmuApp
''',
        status_chunks,
    )
    write_new(
        TESTS / "test_web_routes.py",
        '''"""Web console tests: HTTP routes via bridge.invoke_on_main."""

from unittest.mock import MagicMock

import pytest
''',
        route_chunks,
    )
    write_new(
        TESTS / "test_web_launch.py",
        '''"""Main flow tests: webview / browser launch and recovery."""

import time
from unittest.mock import MagicMock, Mock, patch

import pytest
from main import DanmuApp

from tests.conftest import make_minimal_danmu_app
''',
        launch_chunks,
    )

    append_chunks(ai, backoff_chunks)
    append_chunks(server, ann_chunks)

    for p in sorted(TESTS.glob("test_web*.py")) + list(
        [TESTS / "test_capture_flow.py", TESTS / "test_ai_pipeline.py", TESTS / "test_reply_enqueue.py"]
    ):
        if p.is_file():
            print(f"{p.name}: {len(p.read_text(encoding='utf-8').splitlines())} lines")


if __name__ == "__main__":
    main()
