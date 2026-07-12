"""DanmuApp 烂梗公式化 mixin：独立采集/展示定时器与上屏。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.meme_barrage.client import MemeBarrageApiClient, format_tags_for_remote_api
from app.meme_barrage.config import meme_barrage_enabled, read_meme_barrage_settings
from app.meme_barrage.runnable import MemeAiSelectRunnable, MemeFetchRunnable, meme_fetch_pool
from app.meme_barrage.service import MemeBarrageService
from app.screenshot_compress import IMAGE_JPEG_QUALITY, IMAGE_MAX_WIDTH, compress_screenshot
from app.worker_pools import meme_ai_pool

_MEME_DISPLAY_MAX_PER_TICK = 2
_MEME_DISPLAY_MAX_RECURSION = 10  # BUG-G06: limit recursive singleShot rounds


class _MemeBarrageBridge(QObject):
    """QThreadPool 回调经 Qt 信号回主线程；勿在工作线程使用 QTimer.singleShot。

    parent=DanmuApp（进程级单例）；随应用 quit() 停止 meme 定时器后不再接收新回调。
    """

    fetch_done = pyqtSignal(object)
    fetch_failed = pyqtSignal()
    ai_select_done = pyqtSignal(object, object, int, int, int, int)
    ai_select_failed = pyqtSignal(object, int, int, int, int)


class DanmuAppMemeMixin:
    def _ensure_meme_barrage_service(self) -> MemeBarrageService:
        service = self.__dict__.get("_meme_barrage_service")
        if service is None:
            service = MemeBarrageService(self.config)
            self._meme_barrage_service = service
        return service

    def _ensure_meme_barrage_client(self) -> MemeBarrageApiClient:
        client = self.__dict__.get("_meme_barrage_api_client")
        if client is None:
            client = MemeBarrageApiClient()
            self._meme_barrage_api_client = client
        return client

    def close_meme_barrage_client(self) -> None:
        """关闭烂梗 API httpx 客户端；quit() 时调用以释放连接池（W-TEARDOWN-RES-001）。"""
        client = self.__dict__.get("_meme_barrage_api_client")
        if client is not None:
            client.close()
            self._meme_barrage_api_client = None

    def _init_meme_barrage_timers(self) -> None:
        self._meme_barrage_service = MemeBarrageService(self.config)
        parent = self if isinstance(self, QObject) else None
        self._meme_barrage_bridge = _MemeBarrageBridge(parent)
        self._meme_barrage_bridge.fetch_done.connect(self._on_meme_fetch_success)
        self._meme_barrage_bridge.fetch_failed.connect(self._on_meme_fetch_error)
        self._meme_barrage_bridge.ai_select_done.connect(self._on_meme_ai_select_done_signal)
        self._meme_barrage_bridge.ai_select_failed.connect(self._on_meme_ai_select_failed_signal)

        self._meme_collect_timer = QTimer()
        self._meme_collect_timer.timeout.connect(self._meme_collect_tick)

        self._meme_display_timer = QTimer()
        self._meme_display_timer.timeout.connect(self._meme_display_tick)
        self._meme_display_ticking = False

    def get_meme_barrage_status(self) -> dict[str, object]:
        enabled = meme_barrage_enabled(self.config)
        service = self.__dict__.get("_meme_barrage_service")
        if service is not None:
            return {
                "enabled": enabled,
                "library_count": service.library_count(),
                "display_queue_size": service.display_queue_size(),
            }
        if getattr(self.config, "conn", None) is None:
            return {
                "enabled": enabled,
                "library_count": 0,
                "display_queue_size": 0,
            }
        store = MemeBarrageService(self.config).store
        return {
            "enabled": enabled,
            "library_count": store.count(),
            "display_queue_size": 0,
        }

    def _sync_meme_barrage_timer_intervals(self, settings: dict[str, object]) -> None:
        """Apply collect/display intervals; restart active timers so new cadence takes effect."""
        collect_ms = max(1000, int(settings["collect_interval_sec"]) * 1000)
        display_ms = max(1000, int(settings["display_interval_sec"]) * 1000)
        collect_timer = self.__dict__.get("_meme_collect_timer")
        display_timer = self.__dict__.get("_meme_display_timer")
        if collect_timer is not None:
            collect_timer.setInterval(collect_ms)
            if collect_timer.isActive():
                collect_timer.start(collect_ms)
        if display_timer is not None:
            display_timer.setInterval(display_ms)
            if display_timer.isActive():
                display_timer.start(display_ms)

    def apply_meme_barrage_settings(self, *, reset_cursors: bool = False) -> None:
        service = self._ensure_meme_barrage_service()
        service.invalidate_settings_cache()
        settings = read_meme_barrage_settings(self.config)
        if reset_cursors:
            self._ensure_meme_barrage_service().reset_cursors()
        self._sync_meme_barrage_timer_intervals(settings)
        if bool(getattr(self.engine, "running", False)) and settings["enabled"]:
            # Hot reload: reschedule only; do not singleShot(0) or every save triggers fetch.
            collect_timer = self.__dict__.get("_meme_collect_timer")
            display_timer = self.__dict__.get("_meme_display_timer")
            if collect_timer is not None and not collect_timer.isActive():
                collect_timer.start()
            if display_timer is not None and not display_timer.isActive():
                display_timer.start()
        else:
            self._stop_meme_barrage_timers()

    def _start_meme_barrage_timers(self) -> None:
        if not meme_barrage_enabled(self.config):
            self._stop_meme_barrage_timers()
            return
        settings = read_meme_barrage_settings(self.config)
        self._sync_meme_barrage_timer_intervals(settings)
        if not self._meme_collect_timer.isActive():
            self._meme_collect_timer.start()
        if not self._meme_display_timer.isActive():
            self._meme_display_timer.start()
        # Engine start only: immediate first collect/display tick.
        QTimer.singleShot(0, self._meme_collect_tick)
        QTimer.singleShot(0, self._meme_display_tick)

    def _stop_meme_barrage_timers(self) -> None:
        collect_timer = self.__dict__.get("_meme_collect_timer")
        display_timer = self.__dict__.get("_meme_display_timer")
        if collect_timer is not None:
            collect_timer.stop()
        if display_timer is not None:
            display_timer.stop()
        service = self.__dict__.get("_meme_barrage_service")
        self.__dict__["_meme_ai_select_active_request_id"] = 0
        if service is not None:
            service.set_fetch_in_flight(False)
            service.set_ai_select_in_flight(False)

    def clear_meme_barrage_library(self) -> dict[str, object]:
        service = self._ensure_meme_barrage_service()
        service.clear_all()
        return {"ok": True, "library_count": 0, "display_queue_size": 0}

    def _meme_collect_tick(self) -> None:
        if not bool(getattr(self.engine, "running", False)):
            return
        if not meme_barrage_enabled(self.config):
            return
        service = self._ensure_meme_barrage_service()
        if service.is_fetch_in_flight() or service.is_ai_select_in_flight():
            return

        settings = read_meme_barrage_settings(self.config)
        category = str(settings["category"])

        if category == "local":
            # 本地库已含校验过的句，无需 ingest_collected_texts 二次 INSERT / is_overlay_safe。
            texts = service.collect_local_batch()
            self._meme_enqueue_for_display(service, texts, settings)
            return

        service.set_fetch_in_flight(True)
        batch_size = int(settings["collect_batch_size"])
        tags_list = settings.get("tag") or ["06"]
        if not isinstance(tags_list, list):
            tags_list = [str(tags_list)]
        page_num = service.next_page_num()
        tag = format_tags_for_remote_api(
            [str(t).strip() for t in tags_list if str(t).strip()],
            page_num,
        )

        bridge = self._meme_barrage_bridge

        def on_success(data: dict[str, Any]) -> None:
            bridge.fetch_done.emit(data)

        def on_error(_message: str) -> None:
            bridge.fetch_failed.emit()

        runnable = MemeFetchRunnable(
            category=category,
            tag=tag,
            page_num=page_num,
            page_size=batch_size,
            on_success=on_success,
            on_error=on_error,
            client=self._ensure_meme_barrage_client(),
        )
        meme_fetch_pool().start(runnable)

    def _on_meme_fetch_error(self) -> None:
        service = self._ensure_meme_barrage_service()
        service.set_fetch_in_flight(False)
        self.logger.warning("meme_barrage_fetch_failed reason=remote_error")

    def _on_meme_fetch_success(self, data: dict[str, Any]) -> None:
        service = self._ensure_meme_barrage_service()
        service.set_fetch_in_flight(False)
        try:
            filtered = service.apply_remote_page(data)
            texts = [row[0] for row in filtered]
            if not texts:
                self.logger.warning("meme_barrage_fetch_empty reason=no_items_after_filter")
            if texts:
                service.store.insert_many(filtered)
            settings = read_meme_barrage_settings(self.config)
            self._meme_enqueue_for_display(service, texts, settings)
        except (ValueError, TypeError, KeyError) as exc:
            self.logger.warning(f"meme_barrage_fetch_failed reason=parse_error detail={exc!r}")

    def _meme_enqueue_for_display(
        self,
        service: MemeBarrageService,
        candidates: list[str],
        settings: dict[str, object],
    ) -> None:
        if not candidates:
            return
        display_mode = str(settings.get("display_mode", "full"))
        if display_mode == "ai":
            self._meme_start_ai_select(service, candidates, settings)
            return
        service.enqueue_display(candidates)

    def _meme_start_ai_select(
        self,
        service: MemeBarrageService,
        candidates: list[str],
        settings: dict[str, object],
    ) -> None:
        if service.is_ai_select_in_flight():
            service.enqueue_display(candidates[: int(settings["display_batch_size"])])
            return
        pixmap = getattr(self, "_latest_screenshot", None)
        if pixmap is None or pixmap.isNull():
            self.logger.warning("meme_ai_select_failed reason=no_screenshot")
            service.enqueue_display(candidates[: int(settings["display_batch_size"])])
            return

        max_width = self.config.get_int("image_max_width", IMAGE_MAX_WIDTH)
        quality = self.config.get_int("image_quality", IMAGE_JPEG_QUALITY)
        service.set_ai_select_in_flight(True)
        pick_count = int(settings["display_batch_size"])
        fallback_n = pick_count
        request_id = int(self.__dict__.get("_meme_ai_select_request_id", 0)) + 1
        self.__dict__["_meme_ai_select_request_id"] = request_id
        self.__dict__["_meme_ai_select_active_request_id"] = request_id

        bridge = self._meme_barrage_bridge

        def on_success(selected: list[str], input_tokens: int, output_tokens: int) -> None:
            bridge.ai_select_done.emit(
                selected,
                candidates,
                fallback_n,
                request_id,
                input_tokens,
                output_tokens,
            )

        def on_error(_message: str, input_tokens: int, output_tokens: int) -> None:
            bridge.ai_select_failed.emit(
                candidates,
                fallback_n,
                request_id,
                input_tokens,
                output_tokens,
            )

        runnable = MemeAiSelectRunnable(
            worker=self.ai_worker,
            config=self.config,
            pixmap=pixmap,
            compress_fn=lambda p: compress_screenshot(p, max_width=max_width, quality=quality),
            candidates=candidates,
            pick_count=pick_count,
            on_success=on_success,
            on_error=on_error,
        )
        meme_ai_pool().start(runnable)

    def _on_meme_ai_select_done_signal(
        self,
        selected: list[str],
        fallback_candidates: list[str],
        fallback_n: int,
        request_id: int,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self._on_meme_ai_select_done(
            selected,
            fallback_candidates=fallback_candidates,
            fallback_n=fallback_n,
            request_id=request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _on_meme_ai_select_failed_signal(
        self,
        candidates: list[str],
        fallback_n: int,
        request_id: int,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self._on_meme_ai_select_failed(
            candidates,
            fallback_n,
            request_id=request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _finish_meme_ai_select(
        self,
        service: MemeBarrageService,
        *,
        request_id: int,
        input_tokens: int,
        output_tokens: int,
    ) -> bool:
        if request_id <= 0:
            service.set_ai_select_in_flight(False)
            if input_tokens > 0 or output_tokens > 0:
                self._account_reply_token_usage(input_tokens, output_tokens)
            return True

        accounted_ids = self.__dict__.setdefault(
            "_meme_ai_select_accounted_request_ids",
            set(),
        )
        is_duplicate = request_id in accounted_ids
        if not is_duplicate:
            accounted_ids.add(request_id)
            if input_tokens > 0 or output_tokens > 0:
                self._account_reply_token_usage(input_tokens, output_tokens)

        active_request_id = int(
            self.__dict__.get("_meme_ai_select_active_request_id", 0)
        )
        if request_id != active_request_id:
            reason = "duplicate_callback" if is_duplicate else "stale_request"
            self.logger.warning(
                "meme_ai_select_callback_ignored reason=%s request_id=%s active_request_id=%s",
                reason,
                request_id,
                active_request_id,
            )
            return False

        self.__dict__["_meme_ai_select_active_request_id"] = 0
        service.set_ai_select_in_flight(False)
        return not is_duplicate

    def _on_meme_ai_select_done(
        self,
        selected: list[str],
        *,
        fallback_candidates: list[str],
        fallback_n: int,
        request_id: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        service = self._ensure_meme_barrage_service()
        if not self._finish_meme_ai_select(
            service,
            request_id=request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ):
            return
        if selected:
            service.enqueue_display(selected)
        else:
            self.logger.warning("meme_ai_select_failed reason=empty_result")
            service.enqueue_display(fallback_candidates[:fallback_n])

    def _on_meme_ai_select_failed(
        self,
        candidates: list[str],
        fallback_n: int,
        *,
        request_id: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        service = self._ensure_meme_barrage_service()
        if not self._finish_meme_ai_select(
            service,
            request_id=request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ):
            return
        self.logger.warning("meme_ai_select_failed reason=request_failed")
        service.enqueue_display(candidates[:fallback_n])

    def _meme_display_tick(self, _depth: int = 0) -> None:
        if self.__dict__.get("_meme_display_ticking", False):
            return
        self.__dict__["_meme_display_ticking"] = True
        try:
            if not bool(getattr(self.engine, "running", False)):
                return
            if not meme_barrage_enabled(self.config):
                return
            service = self._ensure_meme_barrage_service()
            backlog: list[str] = list(self.__dict__.get("_meme_display_backlog") or [])
            if not backlog:
                settings = read_meme_barrage_settings(self.config)
                batch_size = int(settings["display_batch_size"])
                backlog = list(service.pop_display_batch(batch_size))
            if not backlog:
                self._meme_display_backlog = []
                return
            chunk = backlog[:_MEME_DISPLAY_MAX_PER_TICK]
            self._meme_display_backlog = backlog[_MEME_DISPLAY_MAX_PER_TICK:]
            scene_generation = int(getattr(self, "_scene_generation", 0))
            for text in chunk:
                item = self.engine.add_text(
                    text,
                    persona="",
                    batch_id=0,
                    scene_generation=scene_generation,
                    skip_dedup=True,
                )
                if item:
                    self._update_stats(success=True)
                    self._broadcast_live_overlay_item(
                        item,
                        item.content,
                        source="meme_barrage",
                    )
            if self._meme_display_backlog and _depth + 1 < _MEME_DISPLAY_MAX_RECURSION:
                QTimer.singleShot(0, lambda: self._meme_display_tick(_depth + 1))
        finally:
            self.__dict__["_meme_display_ticking"] = False
