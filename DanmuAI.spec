# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for DanmuAI（Web 控制台 + pywebview + Qt overlay）。

构建命令（项目根）：``pyinstaller DanmuAI.spec --noconfirm``。

重要约定：
    - 仅 PyQt6；``EXCLUDES`` 中显式排除 PyQt5 / PySide2 / PySide6 与开发工具
      （matplotlib / jupyter / pytest / pygments / jedi / parso），避免
      PyQt5 通过传递依赖被错误地拖入
    - ``datas`` 显式列出 ``web/static``（含控制台 UI 与 supabase 客户端）
    - ``hiddenimports`` 中：uvicorn 必须 ``collect_submodules`` + 显式列
      ``uvicorn.protocols.http.auto`` / ``uvicorn.protocols.websockets.auto``
      / ``uvicorn.lifespan.on``（PyInstaller 静态分析不到协议自动选择）
    - 我们的 app 子模块（``app.web_console`` / ``app.webview_shell`` /
      ``app.startup_trace`` / ``app.web_api.*`` / ``app.bundle_paths`` 等）
      及函数内延迟 import 路径（桌宠、卸载、live_overlay）也显式列出 —
      PyInstaller 静态分析可能漏收子进程入口与延迟 ``from app…``
    - 可选第三方懒加载（``keyboard``、``dashscope`` TTS）亦列入 hiddenimports
    - ``console=False``：发布为 GUI 应用（无控制台窗口）；debug 关闭

产物路径：``dist/DanmuAI/DanmuAI.exe``（Windows）。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)

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

datas = [
    (str(root / "web" / "static"), "web/static"),
    # 内置人格 JSON（app.persona_builtin 在 import 时读取，须在 Analysis 前可解析）
    (str(root / "data" / "personae_builtin.json"), "data"),
    # PET-009：内置桌宠素材（pet.json + spritesheet.webp），打包后通过
    # app.bundle_paths.resource_path("data", "pet", "default") 在 sys._MEIPASS
    # 下也能被 BUILTIN_PET_DIR 解析到；元组第二项必须是字符串，不能用 Path /
    (str(root / "data" / "pet" / "default"), "data/pet/default"),
]
if (root / "resources" / "icon.png").is_file():
    datas.append((str(root / "resources" / "icon.png"), "resources"))

binaries: list = []
hiddenimports: list[str] = [
    "webview",
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
    "app.startup_trace",
    "app.webview_shell",
    "app.web_console",
    "app.web_api.routes",
    "app.web_api.persona",
    "app.web_api.custom_models",
    "app.bundle_paths",
    "app.velopack_runtime",
    "app.velopack_config",
    "app.update_service",
    "app.web_api.update",
    "app.web_api.live_overlay",
    "app.uninstall_service",
    "app.font_registry",
    "app.pet.pet_window",
    "app.pet.pet_barrage",
    "app.pet.pet_command_service",
    "app.pet.pet_facade",
    "app.pet.pet_assets",
    "keyboard",
    "dashscope",
    "dashscope.audio.qwen_tts_realtime",
    "velopack",
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
