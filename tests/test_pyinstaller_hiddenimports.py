"""Static regression: DanmuAI.spec must list critical deferred/lazy hiddenimports."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "DanmuAI.spec"
AUDIT_SCRIPT = ROOT / "scripts" / "audit_hiddenimports.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_hiddenimports", AUDIT_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def audit_mod():
    if not AUDIT_SCRIPT.is_file():
        pytest.skip(f"missing {AUDIT_SCRIPT}")
    return _load_audit_module()


@pytest.fixture(scope="module")
def spec_text() -> str:
    assert SPEC_PATH.is_file(), f"missing {SPEC_PATH}"
    return SPEC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def spec_entries(audit_mod, spec_text: str) -> set[str]:
    return audit_mod.parse_spec_hiddenimports(spec_text)


def test_critical_deferred_imports_in_spec(audit_mod, spec_entries: set[str]) -> None:
    missing_app, missing_3p = audit_mod.missing_critical(spec_entries)
    assert not missing_app, f"missing app hiddenimports: {sorted(missing_app)}"
    assert not missing_3p, f"missing third-party hiddenimports: {sorted(missing_3p)}"


def test_spec_lists_pet_stack_literals(spec_text: str) -> None:
    for name in (
        "app.pet.pet_window",
        "app.pet.pet_barrage",
        "app.pet.pet_command_service",
        "app.pet.pet_facade",
        "app.pet.pet_assets",
    ):
        assert f'"{name}"' in spec_text, f"DanmuAI.spec must include {name}"


def test_spec_lists_live_overlay_and_uninstall(spec_text: str) -> None:
    assert '"app.web_api.live_overlay"' in spec_text
    assert '"app.uninstall_service"' in spec_text
    assert '"app.font_registry"' in spec_text


def test_spec_lists_bililive_dm_and_ai_butler_lazy_modules(spec_text: str) -> None:
    for name in (
        "app.application.bililive_dm_push_service",
        "app.application.bililive_dm_bridge_service",
        "app.application.ai_butler_service",
        "app.web_api.ai_butler",
    ):
        assert f'"{name}"' in spec_text, f"DanmuAI.spec must include {name}"


def test_spec_lists_lazy_third_party(spec_text: str) -> None:
    assert '"keyboard"' in spec_text
    assert '"dashscope"' in spec_text
    assert '"dashscope.audio.qwen_tts_realtime"' in spec_text


def test_spec_lists_webview2_runtime(spec_text: str) -> None:
    # BUG-001: webview_shell.py conditionally imports app.webview2_runtime on
    # win32 inside begin_start(); PyInstaller static analysis cannot see it,
    # so it must be listed explicitly.
    assert '"app.webview2_runtime"' in spec_text, (
        "DanmuAI.spec must include app.webview2_runtime (deferred win32 import)"
    )


def test_audit_script_exits_zero() -> None:
    audit_mod = _load_audit_module()
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    missing_app, missing_3p = audit_mod.missing_critical(
        audit_mod.parse_spec_hiddenimports(spec_text)
    )
    assert not missing_app and not missing_3p
