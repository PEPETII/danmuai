"""Load PetDex-format pet packs (pet.json + 8×9 spritesheet)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtGui import QImageReader

from app.bundle_paths import resource_path
from app.translations import tr

if TYPE_CHECKING:
    from app.config_store import ConfigStore

PET_FRAME_W = 192
PET_FRAME_H = 208
PET_MAX_COLS = 9
PET_MAX_ROWS = 9

LAYOUT_PETDEX = "petdex"
LAYOUT_YUEXIN_MIAO = "yuexin-miao"
VALID_SPRITESHEET_LAYOUTS = frozenset({LAYOUT_PETDEX, LAYOUT_YUEXIN_MIAO})

# PetDex / hatch-pet standard: row 1 = running-right, row 2 = running-left.
RUNNING_ROWS_PETDEX: dict[str, int] = {
    "running-right": 1,
    "running-left": 2,
}

# Builtin yuexin-miao art has left on row 1 and right on row 2 (swapped vs PetDex names).
RUNNING_ROWS_YUEXIN_MIAO: dict[str, int] = {
    "running-right": 2,
    "running-left": 1,
}

# PetDex Desktop: spritesheet is 8 cols × 9 rows; row = state, col = frame index.
@dataclass(frozen=True)
class PetDexStateSpec:
    name: str
    row: int
    frames: int
    duration_ms: int


PETDEX_STATE_SPECS: dict[str, PetDexStateSpec] = {
    "idle": PetDexStateSpec("idle", 0, 6, 1100),
    "running-right": PetDexStateSpec("running-right", 1, 8, 1060),
    "running-left": PetDexStateSpec("running-left", 2, 8, 1060),
    "waving": PetDexStateSpec("waving", 3, 4, 700),
    "jumping": PetDexStateSpec("jumping", 4, 5, 840),
    "failed": PetDexStateSpec("failed", 5, 8, 1220),
    "waiting": PetDexStateSpec("waiting", 6, 6, 1010),
    "running": PetDexStateSpec("running", 7, 6, 820),
    "review": PetDexStateSpec("review", 8, 6, 1030),
}

# DanmuAI internal animation names → PetDex canonical state keys.
DANMUAI_TO_PETDEX_STATE = {
    "idle": "idle",
    "wave": "waving",
    "waving": "waving",
    "run": "running",
    "failed": "failed",
    "review": "review",
    "jump": "jumping",
    "jumping": "jumping",
    "running-right": "running-right",
    "running-left": "running-left",
}

# Back-compat exports for tests: DanmuAI alias → row / frame count.
PET_STATE_ROWS = {
    alias: PETDEX_STATE_SPECS[petdex].row
    for alias, petdex in DANMUAI_TO_PETDEX_STATE.items()
}

PET_STATE_FRAME_COUNTS = {
    alias: PETDEX_STATE_SPECS[petdex].frames
    for alias, petdex in DANMUAI_TO_PETDEX_STATE.items()
}

BUILTIN_PET_DIR = resource_path("data", "pet", "default")

ALLOWED_PET_PACK_ROOT = Path(os.environ.get("APPDATA", ".")) / "DanmuAI" / "pet-packs"


def resolve_petdex_state(danmu_state: str) -> PetDexStateSpec:
    """Map DanmuAI animation hint to PetDex row spec; unknown states fall back to idle."""
    key = str(danmu_state or "idle").strip().lower()
    petdex_key = DANMUAI_TO_PETDEX_STATE.get(key, key)
    return PETDEX_STATE_SPECS.get(petdex_key, PETDEX_STATE_SPECS["idle"])


def parse_spritesheet_layout(meta: dict) -> str:
    """Read optional pet.json spritesheetLayout; default PetDex standard rows."""
    raw = str(meta.get("spritesheetLayout", LAYOUT_PETDEX) or LAYOUT_PETDEX).strip().lower()
    if raw not in VALID_SPRITESHEET_LAYOUTS:
        raise ValueError(
            tr("pet.error.invalidSpritesheetLayout").format(
                raw=raw,
                allowed=", ".join(sorted(VALID_SPRITESHEET_LAYOUTS)),
            )
        )
    return raw


def running_row_for_layout(state: str, layout: str) -> int | None:
    """Resolve spritesheet row for drag locomotion states; None if not a run state."""
    key = str(state or "").strip().lower()
    if key not in ("running-left", "running-right"):
        return None
    rows = RUNNING_ROWS_YUEXIN_MIAO if layout == LAYOUT_YUEXIN_MIAO else RUNNING_ROWS_PETDEX
    return rows[key]


def state_frame_interval_sec(spec: PetDexStateSpec) -> float:
    """Per-frame display interval from PetDex loop duration and frame count."""
    frames = max(1, spec.frames)
    return spec.duration_ms / frames / 1000.0


@dataclass(frozen=True)
class PetAssetPack:
    pet_id: str
    display_name: str
    description: str
    root_dir: Path
    spritesheet_path: Path
    grid_cols: int
    grid_rows: int
    spritesheet_layout: str = LAYOUT_PETDEX

    def frame_count(self, state: str) -> int:
        return resolve_petdex_state(state).frames

    def state_frame_count(self, state: str) -> int:
        return self.frame_count(state)

    def state_duration_ms(self, state: str) -> int:
        return resolve_petdex_state(state).duration_ms

    def state_frame_interval_sec(self, state: str) -> float:
        return state_frame_interval_sec(resolve_petdex_state(state))

    def frame_rect(self, state: str, frame_index: int) -> tuple[int, int, int, int]:
        spec = resolve_petdex_state(state)
        col = frame_index % max(1, spec.frames)
        row = running_row_for_layout(spec.name, self.spritesheet_layout)
        if row is None:
            row = spec.row
        return (col * PET_FRAME_W, row * PET_FRAME_H, PET_FRAME_W, PET_FRAME_H)


def is_path_within_sandbox(path: Path, root: Path) -> bool:
    """Return True if *path* resolves to a location inside *root*."""
    try:
        resolved = path.resolve()
        resolved_root = root.resolve()
        resolved.relative_to(resolved_root)
        return True
    except (OSError, ValueError):
        return False


def resolve_and_sandbox_pack_dir(config: "ConfigStore") -> Path:
    """Resolve pack directory with path-traversal sandboxing."""
    source = str(config.get("pet_asset_source", "builtin") or "builtin").strip().lower()
    if source == "local":
        custom = str(config.get("pet_asset_path", "") or "").strip()
        if custom:
            path = Path(custom)
            if not is_path_within_sandbox(path, ALLOWED_PET_PACK_ROOT):
                raise ValueError(
                    tr("pet.error.path_out_of_range").format(path=custom, allowed=ALLOWED_PET_PACK_ROOT)
                )
            return path
    return BUILTIN_PET_DIR


def _resolve_pack_dir(config: "ConfigStore") -> Path:
    return resolve_and_sandbox_pack_dir(config)


def validate_pet_pack_dir(pack_dir: Path) -> tuple[dict, Path, int, int]:
    """Validate pet.json + spritesheet; raise ValueError with a clear message."""
    pack_dir = Path(pack_dir)
    meta_path = pack_dir / "pet.json"
    if not meta_path.is_file():
        raise ValueError(tr("pet.error.missingPetJson").format(path=meta_path))
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(tr("pet.error.petJsonParseFailed").format(error=exc)) from exc
    if not isinstance(meta, dict):
        raise ValueError(tr("pet.error.petJsonMustBeObject"))
    for key in ("id", "displayName", "spritesheetPath"):
        if not str(meta.get(key, "")).strip():
            raise ValueError(tr("pet.error.petJsonMissingField").format(field=key))

    parse_spritesheet_layout(meta)

    sheet_name = str(meta["spritesheetPath"]).strip()
    sheet_path = pack_dir / sheet_name
    if not sheet_path.is_file():
        alt = pack_dir / "spritesheet.webp"
        if alt.is_file():
            sheet_path = alt
        else:
            alt_png = pack_dir / "spritesheet.png"
            if alt_png.is_file():
                sheet_path = alt_png
            else:
                raise ValueError(tr("pet.error.spritesheetNotFound").format(path=sheet_path))

    reader = QImageReader(str(sheet_path))
    size = reader.size()
    if not size.isValid():
        raise ValueError(tr("pet.error.spritesheetLoadFailed").format(path=sheet_path))
    if size.width() % PET_FRAME_W or size.height() % PET_FRAME_H:
        raise ValueError(
            tr("pet.error.spritesheetInvalidSize").format(
                frame_w=PET_FRAME_W,
                frame_h=PET_FRAME_H,
                width=size.width(),
                height=size.height(),
            )
        )
    grid_cols = size.width() // PET_FRAME_W
    grid_rows = size.height() // PET_FRAME_H
    if not (1 <= grid_cols <= PET_MAX_COLS and 1 <= grid_rows <= PET_MAX_ROWS):
        raise ValueError(
            tr("pet.error.spritesheetInvalidGrid").format(
                max_cols=PET_MAX_COLS,
                max_rows=PET_MAX_ROWS,
                cols=grid_cols,
                rows=grid_rows,
            )
        )
    return meta, sheet_path, grid_cols, grid_rows


def load_pet_assets(config: "ConfigStore") -> PetAssetPack:
    pack_dir = _resolve_pack_dir(config)
    meta, sheet_path, grid_cols, grid_rows = validate_pet_pack_dir(pack_dir)
    return PetAssetPack(
        pet_id=str(meta.get("id", "")),
        display_name=str(meta.get("displayName", "")),
        description=str(meta.get("description", "")),
        root_dir=pack_dir,
        spritesheet_path=sheet_path,
        grid_cols=grid_cols,
        grid_rows=grid_rows,
        spritesheet_layout=parse_spritesheet_layout(meta),
    )
