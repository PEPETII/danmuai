"""Offline path checks for .model3.json and referenced assets."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelValidation:
    model_path: Path
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    textures: list[Path] = field(default_factory=list)
    moc: Path | None = None
    physics: Path | None = None
    display_info: Path | None = None
    motion_files: list[Path] = field(default_factory=list)
    expression_files: list[Path] = field(default_factory=list)
    raw_groups: dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"model_path={self.model_path}",
            f"ok={self.ok}",
            f"moc={self.moc}",
            f"textures={len(self.textures)}",
            f"physics={self.physics}",
            f"display_info={self.display_info}",
            f"motion_files={len(self.motion_files)}",
            f"expression_files={len(self.expression_files)}",
        ]
        for e in self.errors:
            lines.append(f"ERROR: {e}")
        for w in self.warnings:
            lines.append(f"WARN: {w}")
        return "\n".join(lines)


def validate_model3(model_path: str | Path) -> ModelValidation:
    path = Path(model_path).expanduser().resolve()
    result = ModelValidation(model_path=path, ok=False)
    if not path.exists():
        result.errors.append(f"model file does not exist: {path}")
        return result
    if not path.is_file():
        result.errors.append(f"model path is not a file: {path}")
        return result
    if path.suffix.lower() not in {".json"} or "model3" not in path.name.lower():
        result.warnings.append(
            f"path does not look like *.model3.json: {path.name}"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — diagnostic exit path
        result.errors.append(f"failed to parse JSON: {exc}")
        return result

    refs = data.get("FileReferences") or {}
    base = path.parent
    moc_name = refs.get("Moc")
    if not moc_name:
        result.errors.append("FileReferences.Moc missing")
    else:
        moc = (base / moc_name).resolve()
        result.moc = moc
        if not moc.is_file():
            result.errors.append(f"Moc missing: {moc}")

    for tex in refs.get("Textures") or []:
        tp = (base / tex).resolve()
        result.textures.append(tp)
        if not tp.is_file():
            result.errors.append(f"texture missing: {tp}")

    physics = refs.get("Physics")
    if physics:
        pp = (base / physics).resolve()
        result.physics = pp
        if not pp.is_file():
            result.errors.append(f"physics missing: {pp}")

    display = refs.get("DisplayInfo")
    if display:
        dp = (base / display).resolve()
        result.display_info = dp
        if not dp.is_file():
            result.warnings.append(f"DisplayInfo missing: {dp}")

    motions = refs.get("Motions") or {}
    result.raw_groups["Motions"] = list(motions.keys()) if isinstance(motions, dict) else []
    if isinstance(motions, dict):
        for group, items in motions.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                file_name = item.get("File")
                if not file_name:
                    continue
                mp = (base / file_name).resolve()
                result.motion_files.append(mp)
                if not mp.is_file():
                    result.errors.append(f"motion missing [{group}]: {mp}")

    expressions = refs.get("Expressions") or []
    if isinstance(expressions, list):
        for item in expressions:
            if not isinstance(item, dict):
                continue
            file_name = item.get("File")
            if not file_name:
                continue
            ep = (base / file_name).resolve()
            if not ep.is_file():
                # Incomplete packs are common; do not hard-fail load if moc/textures exist.
                result.warnings.append(f"expression missing (skipped): {ep}")
                continue
            result.expression_files.append(ep)

    if not result.motion_files:
        result.warnings.append(
            "no Motions in model3 FileReferences; runtime motion trigger may be unavailable"
        )
    if not result.expression_files:
        result.warnings.append(
            "no Expressions in model3 FileReferences; runtime expression trigger may be unavailable"
        )

    # Hard requirements: moc + all listed textures. Motions/expressions are best-effort.
    result.ok = len(result.errors) == 0
    return result
