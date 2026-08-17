from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from app.live2d.model_loader import Live2DModelLoader
from app.live2d.model_storage import DiscoveredModel
from app.live2d.model_registry import (
    LIVE2D_MODEL_ENTRY_KEY,
    LIVE2D_MODEL_ID_KEY,
    LIVE2D_MODEL_NAME_KEY,
    LIVE2D_MODEL_PATH_KEY,
    Live2DModelRegistry,
)


class FakeConfig:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


def _write_model(tmp_path: Path, *, complete: bool = True, list_resources: bool = False, name: str = "avatar") -> Path:
    model_dir = tmp_path / "user model folder"
    model_dir.mkdir(parents=True)
    motions = (
        [{"File": "idle.motion3.json"}, {"File": "tap.motion3.json"}]
        if list_resources
        else {"Idle": [{"File": "idle.motion3.json"}]}
    )
    references = {
        "Moc": f"{name}.moc3",
        "Textures": ["texture.png"],
        "Motions": motions,
        "Expressions": [{"Name": "smile", "File": "smile.exp3.json"}],
    }
    model_path = model_dir / f"{name}.model3.json"
    model_path.write_text(json.dumps({"FileReferences": references}), encoding="utf-8")
    if complete:
        for file_name in (
            f"{name}.moc3",
            "texture.png",
            "idle.motion3.json",
            "tap.motion3.json",
            "smile.exp3.json",
            "standalone.motion3.json",
            "standalone.exp3.json",
        ):
            (model_dir / file_name).write_bytes(b"resource")
    else:
        (model_dir / "standalone.motion3.json").write_bytes(b"resource")
    return model_path


def _install_folder_dialog(monkeypatch, selected: str):
    class FakeFileDialog:
        class Option:
            ShowDirsOnly = 1

        @staticmethod
        def getExistingDirectory(*_args, **_kwargs):
            return selected

    qt = types.ModuleType("PyQt6")
    widgets = types.ModuleType("PyQt6.QtWidgets")
    widgets.QFileDialog = FakeFileDialog
    qt.__path__ = []
    monkeypatch.setitem(sys.modules, "PyQt6", qt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", widgets)


def _install_file_dialog(monkeypatch, selected: str):
    class FakeFileDialog:
        @staticmethod
        def getOpenFileName(*_args, **_kwargs):
            return selected, "Live2D 模型 (*.model3.json)"

    qt = types.ModuleType("PyQt6")
    widgets = types.ModuleType("PyQt6.QtWidgets")
    widgets.QFileDialog = FakeFileDialog
    qt.__path__ = []
    monkeypatch.setitem(sys.modules, "PyQt6", qt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", widgets)


def _install_model_selection(monkeypatch, selected_index: int):
    class FakeInputDialog:
        @staticmethod
        def getItem(_parent, _title, _label, items, _current, _editable):
            return items[selected_index], True

    qt_widgets = sys.modules.get("PyQt6.QtWidgets")
    if qt_widgets is None:
        qt_widgets = types.ModuleType("PyQt6.QtWidgets")
        monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qt_widgets)
    qt_widgets.QInputDialog = FakeInputDialog


def test_snapshot_scans_references_and_standalone_resources_without_leaking_path(tmp_path):
    model_path = _write_model(tmp_path, list_resources=True)
    result = Live2DModelLoader().inspect(model_path)

    assert result.ok
    assert result.capabilities.motion_files == (
        "idle.motion3.json",
        "standalone.motion3.json",
        "tap.motion3.json",
    )
    assert result.capabilities.expression_files == (
        "smile.exp3.json",
        "standalone.exp3.json",
    )
    assert str(tmp_path) not in json.dumps(result.as_dict(), ensure_ascii=False)


def test_registry_imports_folder_into_managed_storage(tmp_path, monkeypatch):
    model_path = _write_model(tmp_path)
    managed_root = tmp_path / "managed"
    config = FakeConfig()
    changed = []
    registry = Live2DModelRegistry(
        config,
        on_config_changed=lambda: changed.append(True),
        models_root=managed_root,
    )
    _install_folder_dialog(monkeypatch, str(model_path.parent))

    snapshot = registry.import_model_via_dialog()

    assert snapshot["configured"] is True
    assert snapshot["status"] == "ready"
    assert snapshot["model_name"] == "avatar"
    assert snapshot["model_id"] == "avatar"
    assert snapshot["model_entry"] == "avatar.model3.json"
    assert snapshot["model_path"] == "<external-model>/avatar.model3.json"
    assert str(tmp_path) not in json.dumps(snapshot, ensure_ascii=False)
    stored_path = Path(config.get(LIVE2D_MODEL_PATH_KEY))
    assert stored_path.is_file()
    assert stored_path.parent.parent == managed_root
    assert config.get(LIVE2D_MODEL_ID_KEY) == "avatar"
    assert config.get(LIVE2D_MODEL_NAME_KEY) == "avatar"
    assert config.get(LIVE2D_MODEL_ENTRY_KEY) == "avatar.model3.json"
    assert changed == [True]


def test_registry_blocks_missing_core_dependencies_without_overwriting_existing_config(tmp_path, monkeypatch):
    existing = _write_model(tmp_path / "existing", complete=True)
    missing = _write_model(tmp_path / "missing", complete=False)
    config = FakeConfig({LIVE2D_MODEL_PATH_KEY: str(existing)})
    registry = Live2DModelRegistry(config, models_root=tmp_path / "managed")
    _install_folder_dialog(monkeypatch, str(missing.parent))

    snapshot = registry.import_model_via_dialog()

    assert snapshot["configured"] is False
    assert snapshot["status"] == "blocked"
    assert snapshot["reason"] == "core_dependency_missing"
    assert config.get(LIVE2D_MODEL_PATH_KEY) == str(existing)
    assert str(tmp_path) not in json.dumps(snapshot, ensure_ascii=False)


def test_registry_allows_missing_optional_motion_files(tmp_path):
    model_dir = tmp_path / "avatar"
    model_dir.mkdir()
    model_path = model_dir / "avatar.model3.json"
    model_path.write_text(
        json.dumps(
            {
                "FileReferences": {
                    "Moc": "avatar.moc3",
                    "Textures": ["texture.png"],
                    "Motions": {"Idle": [{"File": "missing.motion3.json"}]},
                    "Expressions": [{"Name": "smile", "File": "missing.exp3.json"}],
                }
            }
        ),
        encoding="utf-8",
    )
    (model_dir / "avatar.moc3").write_bytes(b"moc3")
    (model_dir / "texture.png").write_bytes(b"png")

    result = Live2DModelLoader().inspect(model_path)

    assert result.ok
    assert "missing.motion3.json" in result.capabilities.missing_dependencies


def test_registry_reports_empty_folder_without_models(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    registry = Live2DModelRegistry(FakeConfig(), models_root=tmp_path / "managed")
    _install_folder_dialog(monkeypatch, str(empty))

    snapshot = registry.import_model_via_dialog()

    assert snapshot["configured"] is False
    assert snapshot["status"] == "invalid"
    assert snapshot["reason"] == "model_not_found_in_folder"
    assert "未在该文件夹中识别到可用的 Live2D 模型" in snapshot["error"]


def test_registry_selects_one_model_from_multi_model_folder(tmp_path, monkeypatch):
    root = tmp_path / "pack"
    _write_model(root / "char-b", name="beta")
    _write_model(root / "char-a", name="alpha")
    config = FakeConfig()
    registry = Live2DModelRegistry(config, models_root=tmp_path / "managed")
    _install_folder_dialog(monkeypatch, str(root))
    _install_model_selection(monkeypatch, 1)

    snapshot = registry.import_model_via_dialog()

    assert snapshot["configured"] is True
    assert snapshot["model_name"] == "beta"
    assert Path(config.get(LIVE2D_MODEL_PATH_KEY)).name == "beta.model3.json"
    assert config.get(LIVE2D_MODEL_ID_KEY) == "beta"


def test_registry_advanced_file_import_copies_managed_model(tmp_path, monkeypatch):
    model_path = _write_model(tmp_path)
    config = FakeConfig()
    registry = Live2DModelRegistry(config, models_root=tmp_path / "managed")
    _install_file_dialog(monkeypatch, str(model_path))

    snapshot = registry.import_model_file_via_dialog()

    assert snapshot["configured"] is True
    assert snapshot["status"] == "ready"
    assert Path(config.get(LIVE2D_MODEL_PATH_KEY)).is_file()


def test_registry_cancel_and_clear_are_stable(tmp_path, monkeypatch):
    model_path = _write_model(tmp_path)
    config = FakeConfig({LIVE2D_MODEL_PATH_KEY: str(model_path), LIVE2D_MODEL_ID_KEY: "avatar"})
    registry = Live2DModelRegistry(config, models_root=tmp_path / "managed")

    class FakeFileDialog:
        class Option:
            ShowDirsOnly = 1

        @staticmethod
        def getExistingDirectory(*_args, **_kwargs):
            return ""

    qt = types.ModuleType("PyQt6")
    widgets = types.ModuleType("PyQt6.QtWidgets")
    widgets.QFileDialog = FakeFileDialog
    qt.__path__ = []
    monkeypatch.setitem(sys.modules, "PyQt6", qt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", widgets)

    cancelled = registry.import_model_via_dialog()
    assert cancelled["cancelled"] is True
    assert cancelled["configured"] is True
    assert cancelled["reason"] == "cancelled"

    cleared = registry.clear_model()
    assert cleared["configured"] is False
    assert cleared["reason"] == "cleared"
    assert config.get(LIVE2D_MODEL_PATH_KEY) == ""
    assert config.get(LIVE2D_MODEL_ID_KEY) == ""
    assert config.get(LIVE2D_MODEL_NAME_KEY) == ""
    assert config.get(LIVE2D_MODEL_ENTRY_KEY) == ""


def test_browser_resource_merges_standalone_motion_and_expression_files(tmp_path):
    model_path = _write_model(tmp_path)
    config = FakeConfig({LIVE2D_MODEL_PATH_KEY: str(model_path)})
    registry = Live2DModelRegistry(config, models_root=tmp_path / "managed")

    content, media_type = registry.read_resource("model.json")
    document = json.loads(content)
    references = document["FileReferences"]
    motion_files = {
        item["File"]
        for group in references["Motions"].values()
        for item in group
    }
    expression_files = {item["File"] for item in references["Expressions"]}

    assert media_type == "application/json"
    assert "standalone.motion3.json" in motion_files
    assert "standalone.exp3.json" in expression_files
    assert str(tmp_path) not in content.decode("utf-8")


def test_resource_path_is_confined_to_model_directory(tmp_path):
    model_path = _write_model(tmp_path)
    registry = Live2DModelRegistry(FakeConfig({LIVE2D_MODEL_PATH_KEY: str(model_path)}))

    try:
        registry.read_resource("../outside.txt")
    except PermissionError as exc:
        assert str(exc) == "invalid_model_resource_path"
    else:
        raise AssertionError("path traversal must be rejected")


def test_registry_duplicate_import_allocates_unique_model_id(tmp_path, monkeypatch):
    model_path = _write_model(tmp_path)
    managed_root = tmp_path / "managed"
    config = FakeConfig()
    registry = Live2DModelRegistry(config, models_root=managed_root)
    _install_folder_dialog(monkeypatch, str(model_path.parent))

    first = registry.import_model_via_dialog()
    second = registry.import_model_via_dialog()

    assert first["configured"] is True
    assert second["configured"] is True
    assert config.get(LIVE2D_MODEL_ID_KEY) == "avatar-2"
    assert (managed_root / "avatar").exists()
    assert (managed_root / "avatar-2").exists()


def test_registry_snapshot_survives_reload_from_config(tmp_path):
    model_path = _write_model(tmp_path)
    managed_root = tmp_path / "managed"
    config = FakeConfig()
    registry = Live2DModelRegistry(config, models_root=managed_root)
    discovered = DiscoveredModel(
        name="avatar",
        model_path=model_path.resolve(),
        model_dir=model_path.parent.resolve(),
    )
    managed = registry._copy_to_managed_storage(discovered)
    registry._persist_managed_model(
        model_id=managed["model_id"],
        model_name="avatar",
        model_entry=managed["model_entry"],
        model_path=managed["model_path"],
    )

    reloaded = Live2DModelRegistry(config, models_root=managed_root)
    snapshot = reloaded.snapshot()

    assert snapshot["configured"] is True
    assert snapshot["status"] == "ready"
    assert snapshot["model_name"] == "avatar"
    assert snapshot["model_id"] == "avatar"


def test_start_and_stop_are_model_lifecycle_facade_operations(tmp_path):
    model_path = _write_model(tmp_path)
    registry = Live2DModelRegistry(FakeConfig({LIVE2D_MODEL_PATH_KEY: str(model_path)}))

    started = registry.start_model()
    stopped = registry.stop_model()

    assert started["runtime_status"] == "running"
    assert started["model_url"] == "/api/live2d/resource/model.json"
    assert stopped["runtime_status"] == "stopped"
