"""Centralized update metadata and mirror download channels for the update modal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.velopack_config import UPDATE_FEED_URL
from app.version_compare import compare_versions, is_version_newer, normalize_version

if TYPE_CHECKING:
    from app.update_service import UpdateStatus

GITHUB_RELEASES_URL = "https://github.com/PEPETII/danmuai/releases"
QUARK_URL = "https://pan.quark.cn/s/33bc4f23d1df"
QUARK_SHARE_TEXT = (
    "我用夸克网盘给你分享了「danmuai」，点击链接或复制整段内容，"
    "打开「夸克APP」即可获取。 /~bb6b3Yp75s~:/"
)
BAIDU_URL = "https://pan.baidu.com/s/18GiqaUhpBw8w96-PpHU9Gw"
BAIDU_EXTRACT_CODE = "1234"
R2_LATEST_INSTALLER_URL = "https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe"

# Align with app.version.__version__ and Supabase app_updates on each release.
LATEST_PUBLISHED_VERSION = "0.3.1"
UPDATE_ANNOUNCEMENT_MESSAGE = ""


def to_dict() -> dict[str, str]:
    return {
        "github_releases_url": GITHUB_RELEASES_URL,
        "quark_url": QUARK_URL,
        "quark_share_text": QUARK_SHARE_TEXT,
        "baidu_url": BAIDU_URL,
        "baidu_extract_code": BAIDU_EXTRACT_CODE,
        "r2_latest_installer_url": R2_LATEST_INSTALLER_URL,
    }


def build_update_metadata(
    *,
    current_version: str,
    velopack_status: UpdateStatus | None = None,
) -> dict[str, str | bool]:
    """Assemble channel metadata. velopack_status is for unit tests only; HTTP channels must not pass it."""
    current = normalize_version(current_version)
    latest = normalize_version(LATEST_PUBLISHED_VERSION)
    message = UPDATE_ANNOUNCEMENT_MESSAGE
    update_available = is_version_newer(latest, current)

    if velopack_status is not None and velopack_status.frozen and velopack_status.ok:
        vp_latest = normalize_version(velopack_status.latest_version or "")
        if vp_latest and compare_versions(vp_latest, latest) > 0:
            latest = vp_latest
        if velopack_status.update_available:
            update_available = True
        elif vp_latest:
            update_available = is_version_newer(vp_latest, current)

    payload: dict[str, str | bool] = {
        "current_version": current,
        "latest_version": latest,
        "update_available": update_available,
        "release_url": R2_LATEST_INSTALLER_URL,
        "feed_url": UPDATE_FEED_URL,
        "message": message,
    }
    payload.update(to_dict())
    return payload
