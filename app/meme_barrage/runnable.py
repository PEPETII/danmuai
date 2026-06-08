"""烂梗采集与 AI 筛选 QRunnable（QThreadPool 工作线程）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from PyQt6.QtCore import QRunnable

from app.meme_barrage.ai_select import (
    build_meme_select_system_prompt,
    build_meme_select_user_prompt,
    parse_meme_ai_selection,
)
from app.meme_barrage.client import MemeBarrageApiClient

if TYPE_CHECKING:
    from app.ai_client import AiWorker
    from app.config_store import ConfigStore


def _safe_emit(callback: Callable[..., None] | None, *args: Any) -> None:
    if callback is None:
        return
    try:
        callback(*args)
    except RuntimeError:
        pass


class MemeFetchRunnable(QRunnable):
    def __init__(
        self,
        *,
        category: str,
        tag: str,
        page_num: int,
        page_size: int,
        on_success: Callable[[dict[str, Any]], None],
        on_error: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._category = category
        self._tag = tag
        self._page_num = page_num
        self._page_size = page_size
        self._on_success = on_success
        self._on_error = on_error
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            client = MemeBarrageApiClient()
            if self._category == "tagged":
                data = client.sort_all_barrage(
                    page_num=self._page_num,
                    page_size=self._page_size,
                    tags=self._tag,
                )
            else:
                data = client.page(page_num=self._page_num, page_size=self._page_size)
            _safe_emit(self._on_success, data)
        except Exception as exc:
            _safe_emit(self._on_error, str(exc))


class MemeAiSelectRunnable(QRunnable):
    def __init__(
        self,
        *,
        worker: "AiWorker",
        config: "ConfigStore",
        image_data_uri: str,
        candidates: list[str],
        pick_count: int,
        on_success: Callable[[list[str]], None],
        on_error: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._worker = worker
        self._config = config
        self._image_data_uri = image_data_uri
        self._candidates = list(candidates)
        self._pick_count = pick_count
        self._on_success = on_success
        self._on_error = on_error
        self.setAutoDelete(True)

    def run(self) -> None:
        if self._worker._stopping:
            _safe_emit(self._on_error, "stopping")
            return
        if not self._candidates:
            _safe_emit(self._on_error, "empty_candidates")
            return
        try:
            from app.model_providers import resolve_api_transport

            system_pt = build_meme_select_system_prompt(self._config)
            user_pt = build_meme_select_user_prompt(self._candidates, self._pick_count)
            resolved = self._worker.resolve_request_credentials()
            if resolved is None:
                _safe_emit(self._on_error, "incomplete_credentials")
                return
            endpoint, _, _, api_mode = resolved
            persona_id = "meme_select"
            if resolve_api_transport(endpoint, api_mode) == "doubao":
                result = self._worker._request_doubao(
                    self._image_data_uri,
                    system_pt,
                    user_pt,
                    persona_id,
                    0,
                    0,
                    0.0,
                    0,
                    resolved=resolved,
                    emit=False,
                )
            else:
                result = self._worker._request_openai(
                    self._image_data_uri,
                    system_pt,
                    user_pt,
                    persona_id,
                    0,
                    0,
                    0.0,
                    0,
                    resolved=resolved,
                    emit=False,
                )
            if result is None or result.signal != "finished":
                msg = result.message if result else "no_result"
                _safe_emit(self._on_error, msg or "request_failed")
                return
            selected = parse_meme_ai_selection(result.message, self._candidates)
            if not selected:
                _safe_emit(self._on_error, "empty_parse")
                return
            _safe_emit(self._on_success, selected[: self._pick_count])
        except Exception as exc:
            _safe_emit(self._on_error, str(exc))
