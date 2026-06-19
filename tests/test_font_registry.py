"""FontRegistry: local .ttf/.otf import, persistence, and QFontDatabase registration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app import font_registry as fr_mod
from app.config_store import ConfigStore
from app.font_registry import CONFIG_KEY_IMPORTED, FontRegistry, safe_filename
from PyQt6.QtWidgets import QApplication

_FIXTURE_TTF = Path(__file__).parent / "fixtures" / "minimal.ttf"


@pytest.fixture()
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def fonts_dir(monkeypatch, workspace_tmp):
    path = workspace_tmp / "fonts"
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(fr_mod, "FONTS_DIR", path)
    return path


@pytest.fixture()
def registry(fonts_dir, workspace_tmp, qapp):
    store = ConfigStore(db_path=workspace_tmp / "config.db")
    return FontRegistry(store)


def _ttf_bytes() -> bytes:
    if not _FIXTURE_TTF.is_file():
        pytest.skip("tests/fixtures/minimal.ttf missing")
    return _FIXTURE_TTF.read_bytes()


def test_safe_filename_uses_sha256_only():
    assert safe_filename("a" * 64, ".TTF") == ("a" * 64) + ".ttf"


def test_import_bytes_writes_to_fonts_dir(registry, fonts_dir, qapp):
    data = _ttf_bytes()
    record = registry.import_bytes(data, "my.ttf")
    sha = hashlib.sha256(data).hexdigest()
    assert (fonts_dir / f"{sha}.ttf").is_file()
    assert record["sha256"] == sha
    assert record["family"]


def test_import_bytes_rejects_empty_file(registry, qapp):
    with pytest.raises(ValueError, match="文件为空"):
        registry.import_bytes(b"", "empty.ttf")


def test_import_bytes_rejects_unsupported_extension(registry, qapp):
    with pytest.raises(ValueError, match="不支持的文件格式"):
        registry.import_bytes(b"abc", "foo.zip")


def test_import_bytes_rejects_oversized_file(registry, qapp):
    from app.font_registry import MAX_FILE_BYTES
    data = b"\x00" * (MAX_FILE_BYTES + 1)
    with pytest.raises(ValueError, match="文件过大"):
        registry.import_bytes(data, "big.ttf")


def test_import_bytes_returns_real_family(registry, qapp):
    record = registry.import_bytes(_ttf_bytes(), "sample.ttf")
    assert record.get("family")
    assert isinstance(record["family"], str)
    assert record["family"].strip()


def test_import_bytes_dedup_by_sha256(registry, fonts_dir, qapp):
    data = _ttf_bytes()
    first = registry.import_bytes(data, "a.ttf")
    second = registry.import_bytes(data, "b.ttf")
    assert first["sha256"] == second["sha256"]
    assert len(list(fonts_dir.glob("*.ttf"))) == 1
    imported = json.loads(registry._config.get(CONFIG_KEY_IMPORTED, "[]"))
    assert len(imported) == 1


def test_load_all_scans_fonts_dir_and_reconciles_db(registry, fonts_dir, workspace_tmp, qapp):
    data = _ttf_bytes()
    sha = hashlib.sha256(data).hexdigest()
    (fonts_dir / f"{sha}.ttf").write_bytes(data)

    store = ConfigStore(db_path=workspace_tmp / "config.db")
    store.set(
        CONFIG_KEY_IMPORTED,
        json.dumps(
            [
                {
                    "sha256": sha,
                    "family": "GhostFamily",
                    "original_name": "ghost.ttf",
                    "size": len(data),
                    "imported_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "sha256": "deadbeef" * 8,
                    "family": "Missing",
                    "original_name": "gone.ttf",
                    "size": 1,
                    "imported_at": "2026-01-01T00:00:00+00:00",
                },
            ]
        ),
    )
    reg2 = FontRegistry(store)
    count = reg2.load_all()
    assert count >= 1
    imported = json.loads(store.get(CONFIG_KEY_IMPORTED, "[]"))
    shas = {r["sha256"] for r in imported}
    assert sha in shas
    assert "deadbeef" * 8 in shas


def test_delete_removes_file_and_unregisters(registry, fonts_dir, qapp):
    record = registry.import_bytes(_ttf_bytes(), "del.ttf")
    sha = record["sha256"]
    assert registry.delete(sha) is True
    assert not (fonts_dir / f"{sha}.ttf").exists()
    assert registry.list_imported() == []
    assert sha not in registry._font_ids


def test_delete_nonexistent_returns_false(registry, qapp):
    assert registry.delete("0" * 64) is False


def test_list_families_dedup(registry, qapp):
    data = _ttf_bytes()
    registry.import_bytes(data, "one.ttf")
    registry.import_bytes(data, "two.ttf")
    families = registry.list_families()
    assert len(families) == len(set(families))
