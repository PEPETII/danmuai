from unittest.mock import MagicMock, patch

import httpx
from app.api_probe import probe_connection


def test_probe_connection_missing_key():
    result = probe_connection("https://api.deepseek.com/v1", "", "deepseek-chat", "openai-compatible")
    assert result.ok is False
    assert result.status_code is None


@patch("app.api_probe.httpx.Client")
def test_probe_openai_success(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    result = probe_connection(
        "https://api.deepseek.com/v1",
        "sk-test",
        "deepseek-chat",
        "openai-compatible",
    )
    assert result.ok is True
    assert result.status_code == 200


@patch("app.api_probe.httpx.Client")
def test_probe_openai_auth_failure(mock_client_cls):
    request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    response = httpx.Response(401, request=request)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = httpx.HTTPStatusError("auth", request=request, response=response)
    mock_client_cls.return_value = mock_client

    result = probe_connection(
        "https://api.deepseek.com/v1",
        "bad-key",
        "deepseek-chat",
        "openai",
    )
    assert result.ok is False
    assert result.status_code == 401
