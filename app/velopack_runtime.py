"""Velopack startup hook — must run before QApplication (Velopack installs only)."""

from __future__ import annotations

import sys
from pathlib import Path


def _read_windows_version_string_blob(path: Path) -> str:
    """Return concatenated StringFileInfo values from a PE file (Windows only)."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        ver_dll = ctypes.windll.version
        path_w = str(path)
        size = ver_dll.GetFileVersionInfoSizeW(path_w, None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ver_dll.GetFileVersionInfoW(path_w, 0, size, buf):
            return ""
        u_ptr = ctypes.c_void_p()
        u_len = wintypes.UINT()
        if not ver_dll.VerQueryValueW(
            buf,
            "\\VarFileInfo\\Translation",
            ctypes.byref(u_ptr),
            ctypes.byref(u_len),
        ):
            return ""
        lang, codepage = ctypes.cast(u_ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
        parts: list[str] = []
        for key in (
            "ProductName",
            "CompanyName",
            "FileDescription",
            "OriginalFilename",
            "InternalName",
        ):
            subblock = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{key}"
            s_ptr = ctypes.c_void_p()
            s_len = wintypes.UINT()
            if ver_dll.VerQueryValueW(buf, subblock, ctypes.byref(s_ptr), ctypes.byref(s_len)):
                text = ctypes.wstring_at(s_ptr.value)
                if text:
                    parts.append(text)
        return " ".join(parts)
    except OSError:
        return ""


def is_velopack_update_exe(path: Path) -> bool:
    """True when Update.exe carries Velopack branding (not an unrelated homonym)."""
    if not path.is_file():
        return False
    metadata = _read_windows_version_string_blob(path)
    if metadata:
        return "velopack" in metadata.lower()
    try:
        sample = path.read_bytes()[:65536]
    except OSError:
        return False
    return b"Velopack" in sample


def is_velopack_install() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    exe_path = getattr(sys, "executable", "") or ""
    if not exe_path:
        return False
    resolved = Path(exe_path).resolve()
    if resolved.parent.name.lower() != "current":
        return False
    return is_velopack_update_exe(resolved.parent.parent / "Update.exe")


def _is_velopack_install() -> bool:
    return is_velopack_install()


def run_startup_apply_if_needed() -> None:
    """Apply pending Velopack updates before Qt initializes.

    Source runs skip entirely. Import or runtime errors are logged, not swallowed.
    """
    if not is_velopack_install():
        return

    from app.startup_trace import log_startup

    log_startup("velopack.begin")
    try:
        import velopack
    except ImportError as exc:
        log_startup("velopack.skip", reason="import_error", detail=str(exc))
        return

    try:
        from app.uninstall_service import delete_user_data_if_requested

        app = velopack.App()
        app.on_before_uninstall_fast_callback(delete_user_data_if_requested)
        app.run()
        log_startup("velopack.done")
    except Exception as exc:  # boundary: velopack runtime must not block startup
        log_startup("velopack.error", detail=str(exc))
        return
