from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from app.live2d.model_loader import Live2DModelLoader
from app.live2d.model_registry import Live2DModelRegistry


class FakeConfig:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


def _write_model(tmp_path: Path, *, complete: bool = True, list_resources: bool = False) -> Path:
    model_dir = tmp_path / "user model folder"
    model_dir.mkdir(parents=True)
    motions = (
        [{"File": "idle.motion3.json"}, {"File": "tap.motion3.json"}]
        if list_resources
        else {"Idle": [{"File": "idle.motion3.json"}]}
    )
    references = {
        "Moc": "avatar.moc3",
        "Textures": ["texture.png"],
        "Motions": motions,
        "Expressions": [{"Name": "smile", "File": "smile.exp3.json"}],
    }
    model_path = model_dir / "avatar.model3.json"
    model_path.write_text(json.dumps({"FileReferences": references}), encoding="utf-8")
    if complete:
        for name in (
            "avatar.moc3",
            "texture.png",
            "idle.motion3.json",
            "tap.motion3.json",
            "smile.exp3.json",
            "standalone.motion3.json",
            "standalone.exp3.json",
        ):
            (model_dir / name).write_bytes(b"resource")
    else:
        (model_dir / "standalone.motion3.json").write_bytes(b"resource")
    return model_path


def _install_dialog(monkeypatch, selected: str):
    class FakeFileDialog:
        @staticmethod
        def getOpenFileName(*_args):
            return selected, "Live2D 模型 (*.model3.json)"

    qt = types.ModuleType("PyQt6")
    widgets = types.ModuleType("PyQt6.QtWidgets")
    widgets.QFileDialog = FakeFileDialog
    qt.__path__ = []
    monkeypatch.setitem(sys.modules, "PyQt6", qt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", widgets)


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


def test_registry_only_persists_a_ready_model_and_returns_redacted_snapshot(tmp_path, monkeypatch):
    model_path = _write_model(tmp_path)
    config = FakeConfig()
    changed = []
    registry = Live2DModelRegistry(config, on_config_changed=lambda: changed.append(True))
    _install_dialog(monkeypatch, str(model_path))

    snapshot = registry.import_model_via_dialog()

    assert snapshot["configured"] is True
    assert snapshot["status"] == "ready"
    assert snapshot["model_name"] == "avatar"
    assert snapshot["model_path"] == "<external-model>/avatar.model3.json"
    assert str(tmp_path) not in json.dumps(snapshot, ensure_ascii=False)
    assert config.get("live2d_model_path") == str(model_path.resolve())
    assert changed == [True]


def test_registry_blocks_missing_dependencies_without_overwriting_existing_config(tmp_path, monkeypatch):
    existing = _write_model(tmp_path / "existing", complete=True)
    missing = _write_model(tmp_path / "missing", complete=False)
    config = FakeConfig({"live2d_model_path": str(existing)})
    registry = Live2DModelRegistry(config)
    _install_dialog(monkeypatch, str(missing))

    snapshot = registry.import_model_via_dialog()

    assert snapshot["configured"] is False
    assert snapshot["status"] == "blocked"
    assert snapshot["reason"] == "dependency_missing"
    assert config.get("live2d_model_path") == str(existing)
    assert str(tmp_path) not in json.dumps(snapshot, ensure_ascii=False)


def test_registry_cancel_and_clear_are_stable(tmp_path, monkeypatch):
    model_path = _write_model(tmp_path)
    config = FakeConfig({"live2d_model_path": str(model_path)})
    registry = Live2DModelRegistry(config)

    class FakeFileDialog:
        @staticmethod
        def getOpenFileName(*_args):
            return "", ""

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
    assert cleared == {
        "configured": False,
        "model_name": None,
        "model_path": None,
        "status": "unconfigured",
        "reason": "cleared",
        "error": None,
        "capabilities": {
            "parameter_ids": [],
            "parameter_count": 0,
            "motion_groups": [],
            "expression_ids": [],
            "motion_files": [],
            "expression_files": [],
            "physics": False,
            "texture_count": 0,
            "dependency_count": 0,
            "missing_dependencies": [],
        },
        "cancelled": False,
    }
    assert config.get("live2d_model_path") == ""
