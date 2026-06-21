# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for DanmuAI（Web 控制台 + pywebview + Qt overlay）。

构建命令（项目根）：``pyinstaller DanmuAI.spec --noconfirm``。

重要约定：
    - 仅 PyQt6；``EXCLUDES`` 中显式排除 PyQt5 / PySide2 / PySide6 与开发工具
      （matplotlib / jupyter / pytest / pygments / jedi / parso），避免
      PyQt5 通过传递依赖被错误地拖入
    - ``datas`` 显式列出 ``web/static``（含控制台 UI 与 supabase 客户端），
      排除 ``supabase-config.js``（含凭据，不应打入发布包）
    - ``hiddenimports`` 中：uvicorn 必须 ``collect_submodules`` + 显式列
      ``uvicorn.protocols.http.auto`` / ``uvicorn.protocols.websockets.auto``
      / ``uvicorn.lifespan.on``（PyInstaller 静态分析不到协议自动选择）
    - ``hiddenimports`` 按分区组织：第三方包 → app 顶层 → app.application / memory /
      meme_barrage / pet / providers / web_api 子包；新增模块须同步此列表
    - 可选第三方懒加载（``keyboard``、``dashscope`` TTS）亦列入 hiddenimports
    - ``console=False``：发布为 GUI 应用（无控制台窗口）；debug 关闭

产物路径：``dist/DanmuAI/DanmuAI.exe``（Windows）。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)


def _collect_dir_datas(src_dir: Path, dest_prefix: str, *, exclude_names: frozenset[str] = frozenset()) -> list:
    """Collect (src, dest_dir) pairs for PyInstaller datas (replaces Tree)."""
    entries: list = []
    for path in sorted(src_dir.rglob("*")):
        if not path.is_file() or path.name in exclude_names:
            continue
        rel_parent = path.parent.relative_to(src_dir)
        dest_dir = dest_prefix if rel_parent == Path(".") else f"{dest_prefix}/{rel_parent.as_posix()}"
        entries.append((str(path), dest_dir))
    return entries

# Only PyQt6 is used; exclude other Qt bindings and dev tools that pull PyQt5 in.
EXCLUDES = [
    "matplotlib",
    "tkinter",
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.sip",
    "PySide2",
    "PySide6",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "_pytest",
    "jedi",
    "parso",
    "pygments",
    "zmq",
]

datas = []
# web/static — 排除 supabase-config.js（含凭据，不应打入发布包）
datas += _collect_dir_datas(
    root / "web" / "static",
    "web/static",
    exclude_names=frozenset({"supabase-config.js"}),
)
# 内置人格 JSON（app.persona_builtin 在 import 时读取，须在 Analysis 前可解析）
datas.append((str(root / "data" / "personae_builtin.json"), "data"))
# PET-009：内置桌宠素材（pet.json + spritesheet.webp），打包后通过
# app.bundle_paths.resource_path("data", "pet", "default") 在 sys._MEIPASS
# 下也能被 BUILTIN_PET_DIR 解析到；元组第二项必须是字符串，不能用 Path /
datas.append((str(root / "data" / "pet" / "default"), "data/pet/default"))
if (root / "resources" / "icon.png").is_file():
    datas.append((str(root / "resources" / "icon.png"), "resources"))

binaries: list = []
hiddenimports: list[str] = [
    # ── 第三方包 ──────────────────────────────────────────────────
    "webview",
    "pywebview",
    "clr",
    *collect_submodules("uvicorn"),
    *collect_submodules("uvicorn.protocols"),
    *collect_submodules("uvicorn.lifespan"),
    *collect_submodules("uvicorn.loops"),
    "uvicorn.logging",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.lifespan.on",
    "h11",
    "httptools",
    "click",
    "sniffio",
    "annotated_types",
    "pydantic",
    "pydantic_core",
    "starlette.routing",
    "starlette.middleware",
    "multipart",
    "python_multipart",
    "Levenshtein",
    "rapidfuzz",
    "rapidfuzz.distance",
    "rapidfuzz.distance.Levenshtein",
    "httpx",
    "h2",
    "certifi",
    "PIL",
    "PIL._imaging",
    "sounddevice",
    "numpy",
    "cryptography",
    "fastapi",
    "starlette",
    "websockets",
    "watchfiles",
    "anyio",
    "keyboard",
    "dashscope",
    "dashscope.audio.qwen_tts_realtime",
    "velopack",
    # ── app 顶层模块 ─────────────────────────────────────────────
    "app.ai_client",
    "app.ai_client_requests",
    "app.ai_client_support",
    "app.api_probe",
    "app.api_schedule",
    "app.bundle_paths",
    "app.config_defaults",
    "app.config_store",
    "app.danmu_engine",
    "app.danmu_engine_dedup",
    "app.danmu_engine_models",
    "app.danmu_pool",
    "app.danmu_pool_overlay",
    "app.danmu_read_service",
    "app.danmu_tts",
    "app.danmu_tts_playback",
    "app.doubao_responses_stream",
    "app.floating_panel_engine",
    "app.floating_panel_overlay",
    "app.font_registry",
    "app.history_writer",
    "app.hotkey",
    "app.image_compress",
    "app.image_metrics",
    "app.jpeg_resize",
    "app.lifetime_stats",
    "app.live_freshness",
    "app.live_overlay_hub",
    "app.logger",
    "app.main_display_mixin",
    "app.main_helpers",
    "app.main_launch",
    "app.main_launch_mixin",
    "app.main_lifecycle_mixin",
    "app.main_meme_mixin",
    "app.main_mic_mixin",
    "app.main_mic_probe",
    "app.main_request_context_mixin",
    "app.main_state_mixin",
    "app.main_web_facade_mixin",
    "app.mic_buffer",
    "app.mic_capture",
    "app.mic_encode",
    "app.mic_orchestrator",
    "app.mic_prompt",
    "app.mic_service",
    "app.mic_test",
    "app.mic_test_send",
    "app.mic_utterance",
    "app.model_catalog",
    "app.model_providers",
    "app.model_selection",
    "app.overlay",
    "app.persona_builtin",
    "app.persona_contract",
    "app.persona_manager",
    "app.persona_version_history",
    "app.personae",
    "app.region_selector",
    "app.release_channels",
    "app.reply_parser",
    "app.reply_queue",
    "app.runnable",
    "app.screenshot_compress",
    "app.session_run_log",
    "app.single_instance",
    "app.snipper",
    "app.startup_trace",
    "app.supabase_app_updates",
    "app.supabase_config",
    "app.templates",
    "app.translations",
    "app.translations_danmu",
    "app.translations_settings",
    "app.translations_ui",
    "app.tray",
    "app.tts_audio_utils",
    "app.tts_catalog",
    "app.tts_providers",
    "app.uninstall_service",
    "app.update_service",
    "app.velopack_config",
    "app.velopack_runtime",
    "app.version",
    "app.version_compare",
    "app.web_console",
    "app.web_console_runtime",
    "app.web_console_session_auth",
    "app.web_console_support",
    "app.web_console_ws",
    "app.web_static_mime",
    "app.webview_shell",
    "app.win32_overlay_zorder",
    "app.worker_pools",
    # ── app.application.* ────────────────────────────────────────
    "app.application",
    "app.application.config_service",
    "app.application.danmu_diagnostics",
    "app.application.diagnostics_hub",
    "app.application.diagnostic_snapshot",
    "app.application.generation_pipeline_state",
    "app.application.live_status_projection",
    "app.application.request_scheduler",
    "app.application.request_timing_service",
    "app.application.runtime_state",
    "app.application.stats_state",
    "app.application.status_snapshot",
    "app.application.web_runtime_state",
    # ── app.meme_barrage.* ───────────────────────────────────────
    "app.meme_barrage",
    "app.meme_barrage.ai_select",
    "app.meme_barrage.client",
    "app.meme_barrage.config",
    "app.meme_barrage.runnable",
    "app.meme_barrage.service",
    "app.meme_barrage.store",
    # ── app.pet.* ────────────────────────────────────────────────
    "app.pet",
    "app.pet.pet_animation_mapper",
    "app.pet.pet_assets",
    "app.pet.pet_barrage",
    "app.pet.pet_command_service",
    "app.pet.pet_facade",
    "app.pet.pet_prompt",
    "app.pet.pet_state",
    "app.pet.pet_window",
    # ── app.providers.* ──────────────────────────────────────────
    "app.providers",
    "app.providers.adapters",
    "app.providers.adapters.base",
    "app.providers.adapters.default_openai",
    "app.providers.adapters.mimo",
    "app.providers.capabilities",
    "app.providers.constants",
    "app.providers.registry",
    # ── app.web_api.* ────────────────────────────────────────────
    "app.web_api",
    "app.web_api.announcements_state",
    "app.web_api.app_update_state",
    "app.web_api.capture_region",
    "app.web_api.console_theme",
    "app.web_api.custom_models",
    "app.web_api.danmu_pool",
    "app.web_api.danmu_read",
    "app.web_api.font_registry",
    "app.web_api.live_overlay",
    "app.web_api.meme_barrage",
    "app.web_api.mic_test",
    "app.web_api.persona",
    "app.web_api.pet",
    "app.web_api.preview_compress",
    "app.web_api.providers",
    "app.web_api.routes",
    "app.web_api.update",
]

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DanmuAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "resources" / "icon.ico")
    if (root / "resources" / "icon.ico").is_file()
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DanmuAI",
)
