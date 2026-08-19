from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.live2d.model_storage import (
    allocate_model_id,
    copy_model_directory,
    discover_models_in_folder,
    model_selection_label,
    resolve_managed_model_path,
)


def _write_model(model_dir: Path, name: str = "avatar") -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{name}.model3.json"
    model_path.write_text(
        json.dumps(
            {
                "FileReferences": {
                    "Moc": f"{name}.moc3",
                    "Textures": ["texture.png"],
                }
            }
        ),
        encoding="utf-8",
    )
    (model_dir / f"{name}.moc3").write_bytes(b"moc3")
    (model_dir / "texture.png").write_bytes(b"png")
    return model_path


def test_discover_models_in_nested_and_empty_directories(tmp_path: Path):
    root = tmp_path / "下载包"
    root.mkdir()
    nested = root / "角色A"
    _write_model(nested, "角色A")
    nested_deep = root / "pack" / "角色B"
    _write_model(nested_deep, "角色B")
    (root / "notes.txt").write_text("readme", encoding="utf-8")

    discovered = discover_models_in_folder(root)

    assert len(discovered) == 2
    assert {item.name for item in discovered} == {"角色A", "角色B"}


def test_discover_models_returns_empty_for_missing_directory(tmp_path: Path):
    assert discover_models_in_folder(tmp_path / "missing") == []


def test_model_selection_label_disambiguates_duplicate_names(tmp_path: Path):
    first = _write_model(tmp_path / "char-a", "avatar")
    second = _write_model(tmp_path / "char-b", "avatar")
    models = discover_models_in_folder(tmp_path)

    labels = [model_selection_label(model, models) for model in models]

    assert labels == ["avatar（char-a）", "avatar（char-b）"]
    assert first.name.endswith(".model3.json")
    assert second.name.endswith(".model3.json")


def test_allocate_model_id_handles_duplicates(tmp_path: Path):
    (tmp_path / "avatar").mkdir()
    (tmp_path / "avatar-2").mkdir()

    assert allocate_model_id("avatar", tmp_path) == "avatar-3"


def test_copy_model_directory_preserves_unicode_paths(tmp_path: Path):
    source = tmp_path / "用户模型"
    model_path = _write_model(source, "测试角色")
    managed_root = tmp_path / "managed"

    copied_root = copy_model_directory(source, model_id="测试角色", root=managed_root)

    assert copied_root == managed_root / "测试角色"
    assert (copied_root / model_path.name).is_file()
    assert (copied_root / "texture.png").is_file()


def test_resolve_managed_model_path_rejects_traversal(tmp_path: Path):
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    (managed_root / "avatar").mkdir()

    with pytest.raises(ValueError):
        resolve_managed_model_path("avatar", "../outside.model3.json", root=managed_root)

    with pytest.raises(ValueError):
        resolve_managed_model_path("../outside", "avatar.model3.json", root=managed_root)
