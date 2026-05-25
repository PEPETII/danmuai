# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DanmuAI (Web console + pywebview + Qt overlay)."""

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
    (str(root / "data" / "danmu_pool_zh.json"), "data"),
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
    "app.webview_shell",
    "app.web_console",
    "app.web_api.routes",
    "app.web_api.persona",
    "app.web_api.custom_models",
    "app.bundle_paths",
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
