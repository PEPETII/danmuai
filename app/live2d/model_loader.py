"""External Live2D model validation and capability discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


@dataclass(frozen=True)
class ParameterSpec:
    """A parameter exposed by the injected Live2D backend."""

    parameter_id: str
    minimum: float
    maximum: float
    default: float
    current: float

    def __post_init__(self) -> None:
        if not self.parameter_id.strip():
            raise ValueError("parameter_id must not be empty")
        if self.minimum > self.maximum:
            raise ValueError("parameter minimum must not exceed maximum")


@dataclass(frozen=True)
class ModelCapabilities:
    """Static model resources plus optional backend-discovered parameters."""

    parameter_specs: tuple[ParameterSpec, ...] = ()
    motion_groups: tuple[str, ...] = ()
    expression_ids: tuple[str, ...] = ()
    physics: bool = False
    texture_count: int = 0
    dependencies: tuple[str, ...] = ()
    missing_dependencies: tuple[str, ...] = ()
    motion_files: tuple[str, ...] = ()
    expression_files: tuple[str, ...] = ()
    parameter_source: str = "none"

    @property
    def parameter_ids(self) -> tuple[str, ...]:
        return tuple(spec.parameter_id for spec in self.parameter_specs)


@dataclass(frozen=True)
class ModelLoadResult:
    ok: bool
    status: str
    reason: str | None = None
    model_path: str | None = None
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "model_path": self.model_path,
            "error": self.error,
            "capabilities": {
                "parameter_ids": list(self.capabilities.parameter_ids),
                "parameter_count": len(self.capabilities.parameter_specs),
                "parameter_source": self.capabilities.parameter_source,
                "motion_groups": list(self.capabilities.motion_groups),
                "expression_ids": list(self.capabilities.expression_ids),
                "motion_files": list(self.capabilities.motion_files),
                "expression_files": list(self.capabilities.expression_files),
                "physics": self.capabilities.physics,
                "texture_count": self.capabilities.texture_count,
                "dependency_count": len(self.capabilities.dependencies),
                "missing_dependencies": list(self.capabilities.missing_dependencies),
            },
        }


def _redacted_model_path(path: Path) -> str:
    """Expose only a stable filename; do not return user directory names."""

    return f"<external-model>/{path.name}"


def _resource_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_resource_values(item))
        return values
    if isinstance(value, Mapping):
        values: list[str] = []
        file_value = value.get("File") or value.get("file")
        if isinstance(file_value, str):
            values.append(file_value)
        for key, item in value.items():
            if key in {"File", "file", "Name", "name", "Group", "group"}:
                continue
            if isinstance(item, (list, Mapping)):
                values.extend(_resource_values(item))
        return values
    return []


def _load_json_document(path: Path) -> Any:
    """Read a small model metadata JSON using the encodings used by exports."""

    for encoding in ("utf-8-sig", "utf-8", "cp932", "gb18030"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    return None


def _motion_group_names(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        return tuple(str(key) for key in value if str(key).strip())
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                group = item.get("Group") or item.get("group")
                if isinstance(group, str) and group.strip():
                    names.append(group)
        return tuple(names)
    return ()


def _expression_names(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        value = list(value.values())
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            name = item.get("Name") or item.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name)
    return tuple(names)


def _merge_unique(*groups: Iterable[str]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            normalized = str(value).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                values.append(normalized)
    return tuple(values)


def _normalize_resource_name(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _discover_files(model_path: Path, suffix: str) -> tuple[str, ...]:
    """Find standalone Cubism resources without exposing their absolute path."""

    discovered: list[str] = []
    for resource in model_path.parent.rglob(suffix):
        if not resource.is_file():
            continue
        try:
            discovered.append(resource.relative_to(model_path.parent).as_posix())
        except ValueError:
            continue
    return tuple(sorted(set(discovered)))


def _coerce_parameter_specs(value: Iterable[Any] | None) -> tuple[ParameterSpec, ...]:
    if value is None:
        return ()
    specs: list[ParameterSpec] = []
    for item in value:
        if isinstance(item, ParameterSpec):
            specs.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        try:
            specs.append(
                ParameterSpec(
                    parameter_id=str(item["parameter_id"]),
                    minimum=float(item["minimum"]),
                    maximum=float(item["maximum"]),
                    default=float(item["default"]),
                    current=float(item.get("current", item["default"])),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(specs)


def _display_info_parameter_specs(
    model_dir: Path,
    display_info_values: Iterable[str],
) -> tuple[ParameterSpec, ...]:
    """Extract parameter IDs from the model's static DisplayInfo metadata.

    Cubism's ``.cdi3.json`` describes IDs and display names, but not the
    runtime range/current value.  The fallback range is deliberately marked
    by ``parameter_source`` on ``ModelCapabilities``; a renderer can replace
    these specs with native runtime values through ``parameter_discoverer``.
    """

    specs: list[ParameterSpec] = []
    seen: set[str] = set()
    for relative in display_info_values:
        metadata_path = model_dir / relative
        document = _load_json_document(metadata_path)
        if not isinstance(document, Mapping):
            continue
        parameters = document.get("Parameters") or document.get("parameters")
        if not isinstance(parameters, list):
            continue
        for item in parameters:
            if not isinstance(item, Mapping):
                continue
            parameter_id = item.get("Id") or item.get("id")
            if not isinstance(parameter_id, str):
                continue
            parameter_id = parameter_id.strip()
            if not parameter_id or parameter_id in seen:
                continue
            seen.add(parameter_id)
            specs.append(
                ParameterSpec(
                    parameter_id=parameter_id,
                    minimum=-1.0,
                    maximum=1.0,
                    default=0.0,
                    current=0.0,
                )
            )
    return tuple(specs)


def _merge_parameter_specs(
    static_specs: Iterable[ParameterSpec],
    runtime_specs: Iterable[ParameterSpec],
) -> tuple[ParameterSpec, ...]:
    """Merge static IDs with runtime specs, preferring native runtime ranges."""

    merged: dict[str, ParameterSpec] = {}
    for spec in static_specs:
        merged.setdefault(spec.parameter_id, spec)
    for spec in runtime_specs:
        merged[spec.parameter_id] = spec
    return tuple(merged.values())


class Live2DModelLoader:
    """Validate an external model3 file without owning a renderer or Qt object."""

    def __init__(
        self,
        *,
        parameter_discoverer: Callable[[Path], Iterable[Any]] | None = None,
    ) -> None:
        self._parameter_discoverer = parameter_discoverer

    @staticmethod
    def validate_path(model_path: str | Path) -> tuple[Path | None, str | None]:
        if isinstance(model_path, str):
            raw_path = model_path.strip()
        else:
            raw_path = model_path
        if not raw_path:
            return None, "empty_model_path"
        path = Path(raw_path).expanduser()
        if not path.is_file():
            return None, "model_not_found"
        if path.suffix.lower() != ".json" or not path.name.lower().endswith(".model3.json"):
            return None, "invalid_model_extension"
        return path.resolve(), None

    def inspect(self, model_path: str | Path) -> ModelLoadResult:
        path, reason = self.validate_path(model_path)
        redacted = _redacted_model_path(path) if path is not None else None
        if path is None:
            return ModelLoadResult(
                ok=False,
                status="invalid",
                reason=reason,
                error="model path is invalid",
            )
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ModelLoadResult(
                ok=False,
                status="invalid",
                reason="model_json_invalid",
                model_path=redacted,
                error="model3 JSON cannot be read",
            )
        if not isinstance(document, Mapping):
            return ModelLoadResult(
                ok=False,
                status="invalid",
                reason="model_json_invalid",
                model_path=redacted,
                error="model3 JSON root must be an object",
            )

        references = document.get("FileReferences")
        if not isinstance(references, Mapping):
            return ModelLoadResult(
                ok=False,
                status="invalid",
                reason="model_references_invalid",
                model_path=redacted,
                error="model3 JSON does not contain FileReferences",
            )
        if not _resource_values(references.get("Moc")):
            return ModelLoadResult(
                ok=False,
                status="invalid",
                reason="model_moc_missing",
                model_path=redacted,
                error="model3 JSON does not reference a moc3 file",
            )
        critical_keys = ("Moc", "Textures")
        optional_keys = ("Physics", "DisplayInfo", "Pose", "Expressions")
        dependencies: list[str] = []
        missing: list[str] = []
        critical_missing: list[str] = []

        def _track_dependency(relative: str, *, critical: bool) -> None:
            if relative not in dependencies:
                dependencies.append(relative)
            if (path.parent / relative).is_file() or relative in missing:
                return
            missing.append(relative)
            if critical and relative not in critical_missing:
                critical_missing.append(relative)

        for key in critical_keys:
            for relative in _resource_values(references.get(key)):
                _track_dependency(relative, critical=True)
        for key in optional_keys:
            for relative in _resource_values(references.get(key)):
                _track_dependency(relative, critical=False)
        motion_values = _resource_values(references.get("Motions"))
        for relative in motion_values:
            _track_dependency(relative, critical=False)

        motion_files = tuple(
            sorted(
                _merge_unique(
                    (_normalize_resource_name(value) for value in motion_values),
                    _discover_files(path, "*.motion3.json"),
                )
            )
        )
        expression_files = tuple(
            sorted(
                _merge_unique(
                    (
                        _normalize_resource_name(value)
                        for value in _resource_values(references.get("Expressions"))
                    ),
                    _discover_files(path, "*.exp3.json"),
                )
            )
        )

        static_specs = _display_info_parameter_specs(
            path.parent,
            _resource_values(references.get("DisplayInfo")),
        )

        discovered_specs: Iterable[Any] | None = None
        if self._parameter_discoverer is not None:
            try:
                discovered_specs = self._parameter_discoverer(path)
            except Exception:
                discovered_specs = None
        runtime_specs = _coerce_parameter_specs(discovered_specs)
        parameter_specs = _merge_parameter_specs(static_specs, runtime_specs)
        if static_specs and runtime_specs:
            parameter_source = "display_info+runtime"
        elif runtime_specs:
            parameter_source = "runtime"
        elif static_specs:
            parameter_source = "display_info"
        else:
            parameter_source = "none"
        capabilities = ModelCapabilities(
            parameter_specs=parameter_specs,
            motion_groups=_motion_group_names(references.get("Motions")),
            expression_ids=_expression_names(references.get("Expressions")),
            motion_files=motion_files,
            expression_files=expression_files,
            parameter_source=parameter_source,
            physics=bool(_resource_values(references.get("Physics"))),
            texture_count=len(_resource_values(references.get("Textures"))),
            dependencies=tuple(dependencies),
            missing_dependencies=tuple(missing),
        )
        if critical_missing:
            missing_list = "、".join(critical_missing)
            return ModelLoadResult(
                ok=False,
                status="blocked",
                reason="core_dependency_missing",
                model_path=redacted,
                capabilities=capabilities,
                error=f"核心模型资源缺失，无法加载：缺少 {missing_list}",
            )
        return ModelLoadResult(
            ok=True,
            status="ready",
            model_path=redacted,
            capabilities=capabilities,
        )

    load = inspect
