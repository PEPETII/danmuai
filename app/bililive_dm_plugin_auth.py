"""bililive_dm 插件本地桥接共享密钥（与 Web Bearer 解耦）。

密钥持久化于 ``%APPDATA%/DanmuAI/bililive_dm_plugin.secret``，供：
- ``POST /api/plugin/bililive-dm/reply``（插件 → DanmuAI）
- DanmuAI → 插件 ``POST .../danmuai/push/`` 出站 header

环境变量 ``DANMU_BILILIVE_DM_PLUGIN_SECRET`` 优先于文件（测试/dev）。
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import HTTPException

from app.config_store import CONFIG_DIR, _restrict_key_file_permissions
from app.env_config import get as get_env

logger = logging.getLogger(__name__)

PLUGIN_SECRET_HEADER = "X-DanmuAI-Plugin-Secret"
PLUGIN_SECRET_FILE = CONFIG_DIR / "bililive_dm_plugin.secret"
_ENV_KEY = "DANMU_BILILIVE_DM_PLUGIN_SECRET"

_cached_secret: str | None = None

__all__ = [
    "PLUGIN_SECRET_HEADER",
    "PLUGIN_SECRET_FILE",
    "plugin_secret_headers",
    "resolve_plugin_secret",
    "validate_plugin_secret",
]


def resolve_plugin_secret(*, force_reload: bool = False) -> str:
    """返回持久化插件密钥；缺失时生成并写入文件。"""
    global _cached_secret
    if not force_reload and _cached_secret:
        return _cached_secret

    env_value = get_env(_ENV_KEY).strip()
    if env_value:
        _cached_secret = env_value
        return _cached_secret

    if PLUGIN_SECRET_FILE.is_file():
        raw = PLUGIN_SECRET_FILE.read_text(encoding="utf-8").strip()
        if raw:
            _cached_secret = raw
            return _cached_secret

    secret = secrets.token_urlsafe(32)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PLUGIN_SECRET_FILE.write_text(secret, encoding="utf-8")
    _restrict_key_file_permissions(PLUGIN_SECRET_FILE)
    logger.info("bililive_dm_plugin_auth: generated plugin secret at %s", PLUGIN_SECRET_FILE)
    _cached_secret = secret
    return secret


def validate_plugin_secret(header: str | None) -> None:
    """校验请求头中的插件密钥；失败抛 HTTPException。"""
    if not header or not str(header).strip():
        raise HTTPException(status_code=401, detail="plugin_secret_required")
    expected = resolve_plugin_secret()
    if not secrets.compare_digest(str(header).strip(), expected):
        raise HTTPException(status_code=403, detail="plugin_secret_invalid")


def plugin_secret_headers() -> dict[str, str]:
    """出站 HTTP 请求附带的插件密钥 header。"""
    return {PLUGIN_SECRET_HEADER: resolve_plugin_secret()}
