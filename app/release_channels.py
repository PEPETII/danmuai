"""Centralized update metadata and mirror download channels for the update modal."""

from __future__ import annotations

from app.supabase_app_updates import clear_app_update_cache, fetch_app_update
from app.velopack_config import UPDATE_FEED_URL
from app.version_compare import is_version_newer, normalize_version

GITHUB_RELEASES_URL = "https://github.com/PEPETII/danmuai/releases"
QUARK_URL = "https://pan.quark.cn/s/33bc4f23d1df"
QUARK_SHARE_TEXT = (
    "我用夸克网盘给你分享了「danmuai」，点击链接或复制整段内容，"
    "打开「夸克APP」即可获取。 /~bb6b3Yp75s~:/"
)
BAIDU_URL = "https://pan.baidu.com/s/18GiqaUhpBw8w96-PpHU9Gw"
BAIDU_EXTRACT_CODE = "1234"
R2_LATEST_INSTALLER_URL = "https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe"


def to_dict() -> dict[str, str]:
    return {
        "github_releases_url": GITHUB_RELEASES_URL,
        "quark_url": QUARK_URL,
        "quark_share_text": QUARK_SHARE_TEXT,
        "baidu_url": BAIDU_URL,
        "baidu_extract_code": BAIDU_EXTRACT_CODE,
        "r2_latest_installer_url": R2_LATEST_INSTALLER_URL,
    }


def resolve_published_update() -> tuple[str, str, str]:
    """Return ``(latest_version, release_url, message)`` from Supabase or offline fallback."""
    from app.version import __version__

    row = fetch_app_update()
    if row is not None and row.latest_version:
        release_url = row.release_url or R2_LATEST_INSTALLER_URL
        return normalize_version(row.latest_version), release_url, row.message

    # Unconfigured / unreachable: align latest with local build to avoid false prompts.
    return normalize_version(__version__), R2_LATEST_INSTALLER_URL, ""


def build_update_metadata(*, current_version: str) -> dict[str, str | bool]:
    current = normalize_version(current_version)
    latest, release_url, message = resolve_published_update()
    update_available = is_version_newer(latest, current)

    payload: dict[str, str | bool] = {
        "current_version": current,
        "latest_version": latest,
        "update_available": update_available,
        "release_url": release_url,
        "feed_url": UPDATE_FEED_URL,
        "message": message,
    }
    payload.update(to_dict())
    return payload
