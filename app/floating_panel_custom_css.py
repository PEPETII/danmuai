"""Managed custom CSS files for the Web floating panel.

Custom CSS is deliberately kept outside the configuration database.  The
configuration stores only the selected managed filename; this module owns the
directory, filename validation, content validation, and the small built-in
template library used by the style generator.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CUSTOM_CSS_DIRECTORY_NAME = "custom_css"
CUSTOM_CSS_SUFFIX = ".css"
MAX_CUSTOM_CSS_BYTES = 512 * 1024

_INVALID_FILENAME_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_DISALLOWED_CSS_RE = re.compile(
    r"@\s*import\b|javascript\s*:|url\s*\(\s*['\"]?\s*https?://",
    re.IGNORECASE,
)

# These templates intentionally use the same selectors as
# ``web/static/floating_panel/style.css``.  They are starter files, not a
# second renderer or a new visual design system.
CUSTOM_CSS_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "id": "no_bubble",
        "name": "无气泡模板",
        "description": "保留用户名和文字，只移除卡片/气泡表面。",
        "css": """/* DanmuAI Custom CSS Contract v1: no bubble */
#panel {
  --panel-padding: 16px;
}

.card,
.card.layout-stacked {
  background: transparent;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  padding: 2px 4px;
}

.card .username {
  color: #ffffff;
  text-shadow: 0 1px 2px #000000;
}

.card .content,
.card.layout-stacked .bubble .content {
  color: #ffffff;
  text-shadow: 0 1px 2px #000000;
}

.card.layout-stacked .bubble {
  background: transparent;
  border: 0;
  box-shadow: none;
  padding: 0;
}
""",
    },
    {
        "id": "bubble",
        "name": "气泡模板",
        "description": "保留真实浮动面板的圆角气泡、尾巴和两种布局选择器。",
        "css": """/* DanmuAI Custom CSS Contract v1: bubble */
#panel {
  --panel-padding: 16px;
}

.card {
  background: rgba(255, 236, 210, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.45);
  border-radius: 16px;
  box-shadow: 0 6px 18px rgba(72, 36, 16, 0.18);
}

.card .username {
  color: #8b4a2f;
}

.card .content,
.card.layout-stacked .bubble .content {
  color: #281c12;
}

.card.layout-stacked {
  background: transparent;
  border: 0;
  box-shadow: none;
  padding: 0;
}

.card.layout-stacked .bubble {
  background: rgba(255, 236, 210, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.45);
  border-radius: 16px;
  box-shadow: 0 6px 18px rgba(72, 36, 16, 0.18);
}
""",
    },
)


def _default_custom_css_root() -> Path:
    # Import lazily so this pure file-management module does not participate
    # in ConfigStore's startup import cycle.
    from app.config_store.storage import CONFIG_DIR

    return CONFIG_DIR / CUSTOM_CSS_DIRECTORY_NAME


def custom_css_dir_for_config(config: Any | None = None) -> Path:
    """Return the managed directory for a config store or test database."""

    override = str(os.environ.get("DANMU_CUSTOM_CSS_DIR", "") or "").strip()
    if override:
        return Path(override)
    db_path = getattr(config, "db_path", None)
    if db_path:
        return Path(db_path).resolve().parent / CUSTOM_CSS_DIRECTORY_NAME
    return _default_custom_css_root()


def ensure_custom_css_directory(config: Any | None = None) -> Path:
    directory = custom_css_dir_for_config(config)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def normalize_custom_css_file_name(value: Any) -> str:
    """Return a safe managed basename, or ``""`` for an invalid value."""

    name = str(value or "").strip()
    if not name or name in {".", ".."}:
        return ""
    if Path(name).name != name or "/" in name or "\\" in name:
        return ""
    if _INVALID_FILENAME_RE.search(name) or name.endswith((".", " ")):
        return ""
    if not name.lower().endswith(CUSTOM_CSS_SUFFIX):
        return ""
    return name


def validate_custom_css_text(data: bytes | str) -> str:
    """Decode and validate CSS that may be injected into the panel document."""

    if isinstance(data, bytes):
        if len(data) > MAX_CUSTOM_CSS_BYTES:
            raise ValueError(f"CSS 文件不能超过 {MAX_CUSTOM_CSS_BYTES // 1024} KB")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSS 文件必须使用 UTF-8 编码") from exc
    else:
        text = str(data)
        if len(text.encode("utf-8")) > MAX_CUSTOM_CSS_BYTES:
            raise ValueError(f"CSS 文件不能超过 {MAX_CUSTOM_CSS_BYTES // 1024} KB")

    if _DISALLOWED_CSS_RE.search(text):
        raise ValueError("CSS 不允许 @import、javascript: 或远程 http(s) 资源")
    if not text.strip():
        raise ValueError("CSS 文件不能为空")
    return text


def _safe_path(directory: Path, file_name: str, *, must_exist: bool = False) -> Path:
    name = normalize_custom_css_file_name(file_name)
    if not name:
        raise ValueError("CSS 文件名必须是单层 .css 文件名")
    directory = directory.resolve()
    path = directory / name
    resolved = path.resolve(strict=False)
    if resolved.parent != directory:
        raise ValueError("CSS 文件路径无效")
    if must_exist and (not path.exists() or not path.is_file()):
        raise FileNotFoundError(name)
    if path.is_symlink():
        raise ValueError("不允许读取符号链接 CSS 文件")
    return path


def _record(path: Path) -> dict[str, str]:
    return {"file_name": path.name, "name": path.name}


def list_custom_css_files(config: Any | None = None) -> list[dict[str, str]]:
    directory = ensure_custom_css_directory(config)
    records: list[dict[str, str]] = []
    for path in sorted(directory.iterdir(), key=lambda p: p.name.casefold()):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() == CUSTOM_CSS_SUFFIX:
            records.append(_record(path))
    return records


def read_custom_css(config: Any | None, file_name: str) -> str:
    path = _safe_path(ensure_custom_css_directory(config), file_name, must_exist=True)
    try:
        return validate_custom_css_text(path.read_bytes())
    except UnicodeDecodeError as exc:
        raise ValueError("CSS 文件必须使用 UTF-8 编码") from exc


def import_custom_css_bytes(
    config: Any | None,
    data: bytes,
    original_name: str,
) -> dict[str, str]:
    """Copy one validated upload into managed storage without overwriting."""

    requested = normalize_custom_css_file_name(original_name)
    if not requested:
        raise ValueError("只能导入 .css 文件，且文件名不能包含路径")
    text = validate_custom_css_text(data)
    directory = ensure_custom_css_directory(config)
    stem = Path(requested).stem
    suffix = Path(requested).suffix
    candidate = requested
    index = 1
    while True:
        path = _safe_path(directory, candidate)
        if not path.exists():
            break
        if path.is_symlink():
            raise ValueError("目标 CSS 文件是符号链接，拒绝覆盖")
        candidate = f"{stem} ({index}){suffix}"
        index += 1
    # The existence check chooses the public name; exclusive creation closes
    # the race with another concurrent import using the same basename.
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(text)
    except FileExistsError:
        return import_custom_css_bytes(config, data, candidate)
    return _record(path)


def selected_custom_css_text(config: Any | None) -> str:
    """Return the selected CSS, or empty text when the mode is not custom CSS."""

    if str(config.get("floating_panel_style_preset", "") or "").strip().lower() != "custom_css":
        return ""
    file_name = normalize_custom_css_file_name(config.get("floating_panel_custom_css_file", ""))
    if not file_name:
        return ""
    try:
        return read_custom_css(config, file_name)
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.warning("selected custom CSS unavailable file=%s reason=%s", file_name, exc)
        return ""


def custom_css_templates() -> list[dict[str, str]]:
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "description": item["description"],
            "css": item["css"],
        }
        for item in CUSTOM_CSS_TEMPLATES
    ]


def open_custom_css_directory(config: Any | None = None) -> dict[str, str]:
    directory = ensure_custom_css_directory(config)
    if sys.platform == "win32":
        os.startfile(str(directory))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(directory)])
    else:
        subprocess.Popen(["xdg-open", str(directory)])
    return {"ok": "true"}


__all__ = [
    "CUSTOM_CSS_DIRECTORY_NAME",
    "CUSTOM_CSS_SUFFIX",
    "MAX_CUSTOM_CSS_BYTES",
    "CUSTOM_CSS_TEMPLATES",
    "custom_css_dir_for_config",
    "ensure_custom_css_directory",
    "normalize_custom_css_file_name",
    "validate_custom_css_text",
    "list_custom_css_files",
    "read_custom_css",
    "import_custom_css_bytes",
    "selected_custom_css_text",
    "custom_css_templates",
    "open_custom_css_directory",
]
