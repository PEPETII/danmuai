"""烂梗远程采集 Runnable 单测（W-MEDLOW-005 / MB-001）；不触网。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.meme_barrage.client import MemeBarrageApiClient
from app.meme_barrage.runnable import MemeFetchRunnable


def test_meme_api_client_reuses_httpx_client():
    with patch("app.meme_barrage.client.httpx.Client") as client_cls:
        client_cls.return_value.request.return_value.json.return_value = {"code": 200, "data": {}}
        client_cls.return_value.request.return_value.raise_for_status = MagicMock()
        api = MemeBarrageApiClient()
        api.page(page_num=1, page_size=5)
        api.page(page_num=2, page_size=5)
        client_cls.assert_called_once()
    api.close()


def test_meme_api_client_close_is_idempotent():
    with patch("app.meme_barrage.client.httpx.Client") as client_cls:
        client_cls.return_value.request.return_value.json.return_value = {"code": 200, "data": {}}
        client_cls.return_value.request.return_value.raise_for_status = MagicMock()
        api = MemeBarrageApiClient()
        api.page()
        api.close()
        api.close()
        client_cls.return_value.close.assert_called_once()


def test_meme_fetch_runnable_uses_injected_client():
    on_success = MagicMock()
    on_error = MagicMock()
    payload = {"code": 200, "data": {"list": []}}
    injected = MagicMock()
    injected.page.return_value = payload

    with patch("app.meme_barrage.runnable.MemeBarrageApiClient") as client_cls:
        MemeFetchRunnable(
            category="remote",
            tag="",
            page_num=1,
            page_size=5,
            on_success=on_success,
            on_error=on_error,
            client=injected,
        ).run()

    client_cls.assert_not_called()
    injected.page.assert_called_once_with(page_num=1, page_size=5)
    on_success.assert_called_once_with(payload)


def test_meme_fetch_runnable_page_success():
    on_success = MagicMock()
    on_error = MagicMock()
    payload = {"code": 200, "data": {"list": []}}

    with patch("app.meme_barrage.runnable.MemeBarrageApiClient") as client_cls:
        client_cls.return_value.page.return_value = payload
        MemeFetchRunnable(
            category="remote",
            tag="",
            page_num=1,
            page_size=5,
            on_success=on_success,
            on_error=on_error,
        ).run()

    on_success.assert_called_once_with(payload)
    on_error.assert_not_called()
    client_cls.return_value.page.assert_called_once_with(page_num=1, page_size=5)


def test_meme_fetch_runnable_tagged_uses_sort_all():
    on_success = MagicMock()
    on_error = MagicMock()

    with patch("app.meme_barrage.runnable.MemeBarrageApiClient") as client_cls:
        client_cls.return_value.sort_all_barrage.return_value = {"code": 200}
        MemeFetchRunnable(
            category="tagged",
            tag="06,1",
            page_num=2,
            page_size=10,
            on_success=on_success,
            on_error=on_error,
        ).run()

    client_cls.return_value.sort_all_barrage.assert_called_once_with(
        page_num=2,
        page_size=10,
        tags="06,1",
    )
    on_error.assert_not_called()


def test_meme_fetch_runnable_emits_error_on_failure():
    on_success = MagicMock()
    on_error = MagicMock()

    with patch("app.meme_barrage.runnable.MemeBarrageApiClient") as client_cls:
        client_cls.return_value.page.side_effect = RuntimeError("network down")
        MemeFetchRunnable(
            category="remote",
            tag="",
            page_num=1,
            page_size=5,
            on_success=on_success,
            on_error=on_error,
        ).run()

    on_success.assert_not_called()
    on_error.assert_called_once_with("network down")
