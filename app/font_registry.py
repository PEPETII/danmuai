"""Local font file registry: import .ttf/.otf into %APPDATA%/DanmuAI/fonts/."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 与 app/config_store.py:52 风格完全一致
FONTS_DIR = Path(os.environ.get("APPDATA", ".")) / "DanmuAI" / "fonts"
ALLOWED_SUFFIXES: tuple[str, ...] = (".ttf", ".otf")
MAX_FILE_BYTES: int = 25 * 1024 * 1024  # 25 MB — 覆盖商用中文字体常见体积（待业务确认）
CONFIG_KEY_IMPORTED = "imported_fonts"

_log = logging.getLogger(__name__)


def safe_filename(sha256: str, suffix: str) -> str:
    """Return ``{sha256}{suffix}`` — never use user-supplied strings as path prefix."""
    return f"{sha256}{suffix.lower()}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class FontRegistry:
    def __init__(self, config) -> None:
        self._config = config
        self._font_ids: dict[str, int] = {}
        self._families: dict[str, str] = {}
        self._records: dict[str, dict[str, Any]] = {}
        self._disabled = False
        try:
            FONTS_DIR.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            _log.warning("font_registry.init_failed reason=%s", exc)
            self._disabled = True

    @property
    def disabled(self) -> bool:
        return self._disabled

    def _ensure_enabled(self) -> None:
        if self._disabled:
            raise ValueError("字体注册表不可用")

    def _read_imported_list(self) -> list[dict[str, Any]]:
        raw = self._config.get(CONFIG_KEY_IMPORTED, "[]") or "[]"
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = []
            self._config.set(CONFIG_KEY_IMPORTED, "[]")
        if not isinstance(parsed, list):
            parsed = []
            self._config.set(CONFIG_KEY_IMPORTED, "[]")
        return [r for r in parsed if isinstance(r, dict) and r.get("sha256")]

    def _write_imported_list(self, records: list[dict[str, Any]]) -> None:
        self._config.set(CONFIG_KEY_IMPORTED, json.dumps(records, ensure_ascii=False))

    def _register_font_file(
        self,
        path: Path,
        sha256: str,
        *,
        original_name: str | None = None,
        size: int | None = None,
        imported_at: str | None = None,
        family_override: str | None = None,
    ) -> dict[str, Any]:
        from PyQt6.QtGui import QFontDatabase

        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            raise ValueError("字体加载失败")
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            QFontDatabase.removeApplicationFont(font_id)
            raise ValueError("未检测到字体族名称")
        family = family_override or families[0]
        record = {
            "sha256": sha256,
            "family": family,
            "original_name": original_name or path.name,
            "size": size if size is not None else path.stat().st_size,
            "imported_at": imported_at or _utc_now_iso(),
        }
        self._font_ids[sha256] = font_id
        self._families[sha256] = family
        self._records[sha256] = record
        return record

    def load_all(self) -> int:
        """Scan FONTS_DIR, addApplicationFont, reconcile with DB. Returns loaded count."""
        if self._disabled:
            return 0

        records = self._read_imported_list()
        by_sha = {str(r["sha256"]): r for r in records}
        disk_files: dict[str, Path] = {}
        for pattern in ("*.ttf", "*.otf"):
            for path in FONTS_DIR.glob(pattern):
                if path.is_file():
                    disk_files[_file_sha256(path)] = path

        updated_records: list[dict[str, Any]] = []
        seen_sha: set[str] = set()

        for sha256, path in disk_files.items():
            seen_sha.add(sha256)
            existing = by_sha.get(sha256)
            try:
                if existing:
                    self._register_font_file(
                        path,
                        sha256,
                        original_name=str(existing.get("original_name", path.name)),
                        size=int(existing.get("size", path.stat().st_size)),
                        imported_at=str(existing.get("imported_at", _utc_now_iso())),
                        family_override=str(existing.get("family")) if existing.get("family") else None,
                    )
                    updated_records.append(self._records[sha256])
                else:
                    record = self._register_font_file(path, sha256, original_name=path.name)
                    updated_records.append(record)
            except ValueError as exc:
                _log.warning("font_registry.load_skip path=%s reason=%s", path, exc)

        for sha256, rec in by_sha.items():
            if sha256 not in seen_sha:
                updated_records.append(rec)

        self._write_imported_list(updated_records)
        return len(self._font_ids)

    def list_imported(self) -> list[dict[str, Any]]:
        if self._disabled:
            return []
        return [
            dict(self._records[sha])
            for sha in sorted(self._records)
            if sha in self._records
        ]

    def list_families(self) -> list[str]:
        if self._disabled:
            return []
        return sorted(set(self._families.values()))

    def import_bytes(self, data: bytes, original_name: str) -> dict[str, Any]:
        self._ensure_enabled()
        if len(data) == 0:
            raise ValueError("文件为空")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("文件过大")
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError("不支持的文件格式，仅支持 .ttf 和 .otf")

        sha256 = hashlib.sha256(data).hexdigest()
        target = FONTS_DIR / safe_filename(sha256, suffix)

        if sha256 in self._records and target.exists():
            return dict(self._records[sha256])

        if target.exists():
            records = self._read_imported_list()
            for rec in records:
                if rec.get("sha256") == sha256:
                    if sha256 not in self._font_ids:
                        self._register_font_file(
                            target,
                            sha256,
                            original_name=str(rec.get("original_name", original_name)),
                            size=int(rec.get("size", len(data))),
                            imported_at=str(rec.get("imported_at", _utc_now_iso())),
                            family_override=str(rec.get("family")) if rec.get("family") else None,
                        )
                    return dict(self._records[sha256])

        target.write_bytes(data)
        try:
            record = self._register_font_file(
                target,
                sha256,
                original_name=original_name,
                size=len(data),
            )
        except ValueError:
            target.unlink(missing_ok=True)
            raise

        records = self._read_imported_list()
        if not any(r.get("sha256") == sha256 for r in records):
            records.append(record)
            self._write_imported_list(records)
        return dict(record)

    def delete(self, sha256: str) -> bool:
        self._ensure_enabled()
        existed = sha256 in self._records or sha256 in self._font_ids
        font_id = self._font_ids.pop(sha256, None)
        if font_id is not None:
            from PyQt6.QtGui import QFontDatabase

            QFontDatabase.removeApplicationFont(font_id)
        for suffix in ALLOWED_SUFFIXES:
            path = FONTS_DIR / safe_filename(sha256, suffix)
            if path.exists():
                path.unlink(missing_ok=True)
                existed = True
        records = self._read_imported_list()
        new_records = [r for r in records if r.get("sha256") != sha256]
        if len(new_records) != len(records):
            self._write_imported_list(new_records)
            existed = True
        self._families.pop(sha256, None)
        self._records.pop(sha256, None)
        return existed
