"""Load PetDex-format pet packs (pet.json + 8×9 spritesheet)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtGui import QPixmap

from app.bundle_paths import resource_path

if TYPE_CHECKING:
    from app.config_store import ConfigStore

PET_FRAME_W = 192
PET_FRAME_H = 208
PET_MAX_COLS = 9
PET_MAX_ROWS = 9
PET_STATE_ROWS = {
    "idle": 0,
    "wave": 1,
    "run": 2,
    "failed": 3,
    "review": 4,
    "jump": 5,
    "extra1": 6,
    "extra2": 7,
}
BUILTIN_PET_DIR = resource_path("data", "pet", "default")


@dataclass(frozen=True)
class PetAssetPack:
    pet_id: str
    display_name: str
    description: str
    root_dir: Path
    spritesheet_path: Path
    grid_cols: int
    grid_rows: int

    @property
    def frame_count(self) -> int:
        return self.grid_cols

    def frame_rect(self, state: str, frame_index: int) -> tuple[int, int, int, int]:
        row = PET_STATE_ROWS.get(state, PET_STATE_ROWS["idle"])
        if row >= self.grid_rows:
            row = 0
        col = frame_index % max(1, self.grid_cols)
        return (col * PET_FRAME_W, row * PET_FRAME_H, PET_FRAME_W, PET_FRAME_H)


def _resolve_pack_dir(config: "ConfigStore") -> Path:
    source = str(config.get("pet_asset_source", "builtin") or "builtin").strip().lower()
    if source == "local":
        custom = str(config.get("pet_asset_path", "") or "").strip()
        if custom:
            return Path(custom)
    return BUILTIN_PET_DIR


def validate_pet_pack_dir(pack_dir: Path) -> tuple[dict, Path, int, int]:
    """Validate pet.json + spritesheet; raise ValueError with a clear message."""
    pack_dir = Path(pack_dir)
    meta_path = pack_dir / "pet.json"
    if not meta_path.is_file():
        raise ValueError(f"缺少 pet.json：{meta_path}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"pet.json 解析失败：{exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError("pet.json 必须是 JSON 对象")
    for key in ("id", "displayName", "spritesheetPath"):
        if not str(meta.get(key, "")).strip():
            raise ValueError(f"pet.json 缺少必填字段：{key}")

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
                raise ValueError(f"找不到 spritesheet：{sheet_path}")

    pixmap = QPixmap(str(sheet_path))
    if pixmap.isNull():
        raise ValueError(f"spritesheet 无法加载：{sheet_path}")
    if pixmap.width() % PET_FRAME_W or pixmap.height() % PET_FRAME_H:
        raise ValueError(
            f"spritesheet 宽高须为 {PET_FRAME_W}×{PET_FRAME_H} 的整数倍，"
            f"实际为 {pixmap.width()}×{pixmap.height()}"
        )
    grid_cols = pixmap.width() // PET_FRAME_W
    grid_rows = pixmap.height() // PET_FRAME_H
    if not (1 <= grid_cols <= PET_MAX_COLS and 1 <= grid_rows <= PET_MAX_ROWS):
        raise ValueError(
            f"spritesheet 网格须在 1–{PET_MAX_COLS} 列、1–{PET_MAX_ROWS} 行内，"
            f"实际为 {grid_cols}×{grid_rows}"
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
    )
