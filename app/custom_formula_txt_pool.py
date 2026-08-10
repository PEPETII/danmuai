"""自定义公式化弹幕 TXT 文件夹句库。

TXT 目录为唯一数据源：扫描 ``%APPDATA%/DanmuAI/custom_formula_pool/*.txt``，
不再将内容复制到 SQLite。首次加载时若目录为空且旧版 SQLite 仍有数据，会一次性
导出到 ``migrated_from_app.txt`` 后仅读 TXT。
"""

from __future__ import annotations

import logging
import os
import random
import sys
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config_store import CONFIG_DIR
from app.danmu_pool import CUSTOM_DANMU_POOL_MAX
from app.danmu_pool_overlay import is_formula_pool_txt_line_valid

logger = logging.getLogger(__name__)

CUSTOM_FORMULA_POOL_DIRNAME = "custom_formula_pool"
MIGRATION_FLAG_KEY = "custom_formula_txt_migrated"
MIGRATION_FILENAME = "migrated_from_app.txt"
README_FILENAME = "README.txt"
README_ZH = (
    "在此文件夹中放置 .txt 文件管理自定义公式化弹幕。\n"
    "每个 TXT 文件可作为一个独立句库，一行一句弹幕。\n"
    "可直接新建、编辑或删除 TXT 文件，然后在 DanmuAI 控制台点击「刷新句库」生效。\n"
)
README_EN = (
    "Place .txt files in this folder to manage custom formula danmu.\n"
    "Each TXT file is an independent line pool; one danmu line per row.\n"
    "Create, edit, or delete TXT files directly, then click Refresh in DanmuAI.\n"
)

_pool_caches: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


@dataclass
class TxtPoolSnapshot:
    directory: Path
    texts: list[str] = field(default_factory=list)
    text_set: set[str] = field(default_factory=set)
    files: list[dict[str, Any]] = field(default_factory=list)
    file_mtimes: dict[str, float] = field(default_factory=dict)
    skipped_unsafe: int = 0
    skipped_empty: int = 0
    skipped_duplicate: int = 0

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def line_count(self) -> int:
        return len(self.texts)


def pool_dir_for_config(config: Any | None = None) -> Path:
    override = os.environ.get("DANMU_CUSTOM_FORMULA_POOL_DIR", "").strip()
    if override:
        return Path(override)
    if config is not None and getattr(config, "db_path", None):
        return Path(config.db_path).parent / CUSTOM_FORMULA_POOL_DIRNAME
    return CONFIG_DIR / CUSTOM_FORMULA_POOL_DIRNAME


def ensure_pool_directory(config: Any | None = None) -> Path:
    directory = pool_dir_for_config(config)
    directory.mkdir(parents=True, exist_ok=True)
    readme = directory / README_FILENAME
    if not readme.exists():
        readme.write_text(f"{README_ZH}\n---\n{README_EN}", encoding="utf-8")
    return directory


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _list_txt_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        (
            p
            for p in directory.iterdir()
            if p.is_file()
            and p.suffix.lower() == ".txt"
            and p.name not in (README_FILENAME,)
        ),
        key=lambda p: p.name.lower(),
    )


def _snapshot_needs_rescan(directory: Path, snapshot: TxtPoolSnapshot | None) -> bool:
    if snapshot is None or snapshot.directory != directory:
        return True
    files = _list_txt_files(directory)
    if len(files) != len(snapshot.file_mtimes):
        return True
    for path in files:
        mtime = path.stat().st_mtime
        if snapshot.file_mtimes.get(path.name) != mtime:
            return True
    return False


def _migrate_sqlite_to_txt_if_needed(config: Any, directory: Path) -> None:
    if config is None:
        return
    migrated_flag = str(getattr(config, "get", lambda _k, _d="": "")(MIGRATION_FLAG_KEY, ""))
    if migrated_flag == "1":
        return
    if _list_txt_files(directory):
        if hasattr(config, "set"):
            config.set(MIGRATION_FLAG_KEY, "1")
        return

    texts: list[str] = []
    getter = getattr(config, "get_custom_danmu_pool", None)
    if callable(getter):
        texts = [str(t).strip() for t in getter() if str(t).strip()]
    if not texts:
        if hasattr(config, "set"):
            config.set(MIGRATION_FLAG_KEY, "1")
        return

    target = directory / MIGRATION_FILENAME
    target.write_text("\n".join(texts) + "\n", encoding="utf-8")
    if hasattr(config, "set"):
        config.set(MIGRATION_FLAG_KEY, "1")
    logger.info("custom formula TXT pool migrated %d lines to %s", len(texts), target)


def _scan_directory(directory: Path) -> TxtPoolSnapshot:
    snapshot = TxtPoolSnapshot(directory=directory)
    seen: set[str] = set()
    for path in _list_txt_files(directory):
        raw_text = _read_text_file(path)
        file_lines = 0
        file_skipped_unsafe = 0
        file_skipped_empty = 0
        file_skipped_duplicate = 0
        for raw_line in raw_text.splitlines():
            text = str(raw_line).strip()
            if not text:
                file_skipped_empty += 1
                snapshot.skipped_empty += 1
                continue
            if text in seen:
                file_skipped_duplicate += 1
                snapshot.skipped_duplicate += 1
                continue
            if not is_formula_pool_txt_line_valid(text):
                file_skipped_unsafe += 1
                snapshot.skipped_unsafe += 1
                continue
            if len(seen) >= CUSTOM_DANMU_POOL_MAX:
                break
            seen.add(text)
            snapshot.texts.append(text)
            file_lines += 1
        snapshot.files.append(
            {
                "name": path.name,
                "line_count": file_lines,
                "skipped_unsafe": file_skipped_unsafe,
                "skipped_empty": file_skipped_empty,
                "skipped_duplicate": file_skipped_duplicate,
            }
        )
        snapshot.file_mtimes[path.name] = path.stat().st_mtime
    snapshot.text_set = set(snapshot.texts)
    return snapshot


def load_txt_pool_snapshot(
    config: Any | None = None,
    *,
    force: bool = False,
) -> TxtPoolSnapshot:
    directory = ensure_pool_directory(config)
    if config is not None:
        _migrate_sqlite_to_txt_if_needed(config, directory)

    cache_key = config if config is not None else object()
    cached = None if force else _pool_caches.get(cache_key)
    if not force and cached is not None and not _snapshot_needs_rescan(directory, cached):
        return cached

    snapshot = _scan_directory(directory)
    _pool_caches[cache_key] = snapshot
    return snapshot


def invalidate_txt_pool_cache(config: Any | None = None) -> None:
    if config is None:
        _pool_caches.clear()
        return
    _pool_caches.pop(config, None)


def txt_pool_line_count(config: Any | None = None) -> int:
    return load_txt_pool_snapshot(config).line_count


def txt_pool_contains_text(config: Any | None, text: str) -> bool:
    value = str(text).strip()
    if not value:
        return False
    return value in load_txt_pool_snapshot(config).text_set


def sample_txt_pool_texts(
    config: Any | None,
    count: int,
    *,
    rng: random.Random | None = None,
) -> list[str]:
    if count <= 0:
        return []
    pool = load_txt_pool_snapshot(config).texts
    if not pool:
        return []
    rng = rng or random
    n = min(count, len(pool))
    return list(rng.sample(pool, n))


def get_txt_pool_status(config: Any | None = None, *, force: bool = False) -> dict[str, Any]:
    snapshot = load_txt_pool_snapshot(config, force=force)
    return {
        "txt_dir": str(snapshot.directory),
        "txt_file_count": snapshot.file_count,
        "txt_line_count": snapshot.line_count,
        "txt_files": list(snapshot.files),
        "txt_skipped_unsafe": snapshot.skipped_unsafe,
        "txt_skipped_empty": snapshot.skipped_empty,
        "txt_skipped_duplicate": snapshot.skipped_duplicate,
    }


def refresh_txt_pool(config: Any | None = None) -> dict[str, Any]:
    invalidate_txt_pool_cache(config)
    return get_txt_pool_status(config, force=True)


def open_txt_pool_directory(config: Any | None = None) -> dict[str, Any]:
    directory = ensure_pool_directory(config)
    path = str(directory)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — Windows Explorer for local folder management
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')  # noqa: S605
    else:
        os.system(f'xdg-open "{path}"')  # noqa: S605
    return {"ok": True, "txt_dir": path}
