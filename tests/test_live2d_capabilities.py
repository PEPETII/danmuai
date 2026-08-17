from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.live2d.model_loader import Live2DModelLoader

PUPPY_MODEL = Path(r"E:\news-test\live 2d\puppy by恩慈_ENCY\puppy.model3.json")


def test_capabilities_merge_references_discovery_and_runtime_parameter_specs(
    tmp_path: Path,
):
    model_dir = tmp_path / "avatar"
    (model_dir / "nested").mkdir(parents=True)
    (model_dir / "expressions").mkdir()
    (model_dir / "avatar.moc3").write_bytes(b"moc3")
    (model_dir / "display.cdi3.json").write_text(
        json.dumps(
            {
                "Parameters": [
                    {"Id": "ParamA", "Name": "A"},
                    {"Id": "ParamA", "Name": "A duplicate"},
                    {"Id": "ParamB", "Name": "B"},
                ]
            }
        ),
        encoding="utf-8",
    )
    for relative in (
        "idle.motion3.json",
        "nested/idle.motion3.json",
        "nested/standalone.motion3.json",
        "expressions/smile.exp3.json",
        "expressions/other.exp3.json",
    ):
        resource = model_dir / relative
        resource.write_bytes(b"resource")
    model_path = model_dir / "avatar.model3.json"
    model_path.write_text(
        json.dumps(
            {
                "FileReferences": {
                    "Moc": "avatar.moc3",
                    "DisplayInfo": "display.cdi3.json",
                    "Motions": {"Idle": [{"File": "idle.motion3.json"}]},
                    "Expressions": [
                        {"Name": "smile", "File": "expressions/smile.exp3.json"}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = Live2DModelLoader(
        parameter_discoverer=lambda _path: [
            {
                "parameter_id": "ParamA",
                "minimum": -30,
                "maximum": 30,
                "default": 0,
                "current": 2,
            },
            {
                "parameter_id": "ParamC",
                "minimum": 0,
                "maximum": 1,
                "default": 0,
                "current": 0,
            },
        ]
    ).inspect(model_path)

    assert result.ok
    assert result.capabilities.motion_files == (
        "idle.motion3.json",
        "nested/idle.motion3.json",
        "nested/standalone.motion3.json",
    )
    assert result.capabilities.expression_files == (
        "expressions/other.exp3.json",
        "expressions/smile.exp3.json",
    )
    assert result.capabilities.parameter_ids == ("ParamA", "ParamB", "ParamC")
    assert result.capabilities.parameter_source == "display_info+runtime"
    assert result.capabilities.parameter_specs[0].minimum == -30
    assert result.capabilities.parameter_specs[0].current == 2


@pytest.mark.skipif(not PUPPY_MODEL.is_file(), reason="reference puppy model is unavailable")
def test_puppy_uses_display_info_and_recursive_expression_discovery():
    result = Live2DModelLoader().inspect(PUPPY_MODEL)

    assert result.ok
    assert result.capabilities.parameter_source == "display_info"
    assert len(result.capabilities.parameter_specs) == 196
    assert "ParamAngleX" in result.capabilities.parameter_ids
    assert result.capabilities.motion_files == ()
    assert len(result.capabilities.expression_files) == 9
    assert result.capabilities.expression_files[0] == "expressions/1_ParamCheek.exp3.json"
    assert result.capabilities.expression_ids == ()
