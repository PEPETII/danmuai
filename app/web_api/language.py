"""Web 控制台语言偏好：config.db 字符串键 + Qt 侧实时生效。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/language``：返回当前语言、系统检测语言与支持语言列表
  ``{language, system_language, supported_languages}``。
- ``PUT /api/language``：写入用户偏好（仅 zh/en，其他值归一化到 zh），
  并在主线程同步调用 ``Translator.set_language`` 触发 ``language_changed``
  信号，使托盘菜单 / Overlay / 桌宠等 Qt 侧文本实时更新。

本模块**仅**处理语言偏好落库与 Qt 侧实时切换；Web 控制台自身字符串
目前为硬编码中文，需重载页面由后续 i18n 工单覆盖。
"""

from __future__ import annotations

from fastapi import HTTPException

from app.supported_languages import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    normalize_language,
    supported_languages_payload,
)
from app.translations import Translator, tr

LANGUAGE_KEY = "language"

__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGE_KEY",
    "SUPPORTED_LANGUAGES",
    "get_from_config",
    "normalize_language",
    "save_to_config",
    "validate_payload",
]


def get_from_config(config) -> dict[str, object]:
    raw = config.get(LANGUAGE_KEY, default=DEFAULT_LANGUAGE)
    language = normalize_language(raw)
    return {
        "language": language,
        "system_language": Translator.detect_system_language(),
        "supported_languages": supported_languages_payload(language),
    }


def save_to_config(config, language: str) -> None:
    normalized = normalize_language(language)
    config.set(LANGUAGE_KEY, normalized)
    # 触发 language_changed 信号，Qt 侧（托盘/Overlay/桌宠）实时更新；
    # 必须在主线程执行（经 bridge.invoke_on_main 调入）。
    Translator.set_language(normalized)


def validate_payload(body: dict) -> str:
    language = body.get("language", DEFAULT_LANGUAGE)
    if language is None:
        language = DEFAULT_LANGUAGE
    if not isinstance(language, str):
        raise HTTPException(
            status_code=400,
            detail=tr("validation.languageMustBeString"),
        )
    normalized = language.strip().lower()
    if normalized not in SUPPORTED_LANGUAGES:
        allowed = ", ".join(SUPPORTED_LANGUAGES)
        raise HTTPException(
            status_code=400,
            detail=tr("validation.languageMustBeOneOf", allowed=allowed),
        )
    return normalized
