"""I18N tests for app_update_state validation errors."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.translations import Translator
from app.web_api.app_update_state import validate_payload


def _with_language(lang: str):
    """Context manager that switches Translator and restores zh on exit."""

    class _LanguageContext:
        def __enter__(self):
            Translator.set_language(lang)

        def __exit__(self, *_exc):
            Translator.set_language("zh")
            return False

    return _LanguageContext()


def test_validate_payload_rejects_non_string_type_in_zh():
    with _with_language("zh"):
        with pytest.raises(HTTPException) as exc_info:
            validate_payload({"dismissedLatestVersion": 123})

    assert exc_info.value.status_code == 400
    assert "dismissedLatestVersion 必须为字符串" in exc_info.value.detail
    assert "must be a string" not in exc_info.value.detail


def test_validate_payload_rejects_non_string_type_in_en():
    with _with_language("en"):
        with pytest.raises(HTTPException) as exc_info:
            validate_payload({"dismissedLatestVersion": 123})

    assert exc_info.value.status_code == 400
    assert "dismissedLatestVersion must be a string" in exc_info.value.detail


def test_validate_payload_rejects_invalid_version_in_zh():
    # The current version_compare parser is forgiving; simulate a parse failure
    # so we can exercise the translated invalid-version error path.
    with patch("app.version_compare.parse_version", side_effect=ValueError("bad")):
        with _with_language("zh"):
            with pytest.raises(HTTPException) as exc_info:
                validate_payload({"dismissedLatestVersion": "not-a-version"})

    assert exc_info.value.status_code == 400
    assert "dismissedLatestVersion 版本格式无效" in exc_info.value.detail
    assert "invalid version format" not in exc_info.value.detail


def test_validate_payload_rejects_invalid_version_in_en():
    with patch("app.version_compare.parse_version", side_effect=ValueError("bad")):
        with _with_language("en"):
            with pytest.raises(HTTPException) as exc_info:
                validate_payload({"dismissedLatestVersion": "not-a-version"})

    assert exc_info.value.status_code == 400
    assert "dismissedLatestVersion has an invalid version format" in exc_info.value.detail
