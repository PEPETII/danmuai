"""DanmuApp 烂梗公式化 mixin：独立采集/展示定时器与上屏。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QThreadPool, QTimer, pyqtSignal

from app.meme_barrage.config import meme_barrage_enabled, read_meme_barrage_settings
from app.meme_barrage.runnable import MemeAiSelectRunnable, MemeFetchRunnable
from app.meme_barrage.service import MemeBarrageService
from app.screenshot_compress import IMAGE_JPEG_QUALITY, IMAGE_MAX_WIDTH, compress_screenshot

if TYPE_CHECKING:
    pass


class _MemeBarrageBridge(QObject):
    """QThreadPool 回调经 Qt 信号回主线程；勿在工作线程使用 QTimer.singleShot。"""

    fetch_done = pyqtSignal(object)
    fetch_failed = pyqtSignal()
    ai_select_done = pyqtSignal(object, object, int)
    ai_select_failed = pyqtSignal(object, int)


class DanmuAppMemeMixin:
    def _ensure_meme_barrage_service(self) -> MemeBarrageService:
        service = self.__dict__.get("_meme_barrage_service")
        if service is None:
            service = MemeBarrageService(self.config)
            self._meme_barrage_service = service
        return service

    def _init_meme_barrage_timers(self) -> None:
        self._meme_barrage_service = MemeBarrageService(self.config)
        self._meme_ai_in_flight = False
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

    def apply_meme_barrage_settings(self, *, reset_cursors: bool = False) -> None:
        settings = read_meme_barrage_settings(self.config)
        if reset_cursors:
            self._ensure_meme_barrage_service().reset_cursors()
        collect_ms = int(settings["collect_interval_sec"]) * 1000
        display_ms = int(settings["display_interval_sec"]) * 1000
        collect_timer = self.__dict__.get("_meme_collect_timer")
        display_timer = self.__dict__.get("_meme_display_timer")
        if collect_timer is not None:
            collect_timer.setInterval(max(1000, collect_ms))
        if display_timer is not None:
            display_timer.setInterval(max(1000, display_ms))
        if bool(getattr(self.engine, "running", False)) and settings["enabled"]:
            self._start_meme_barrage_timers()
        else:
            self._stop_meme_barrage_timers()

    def _start_meme_barrage_timers(self) -> None:
        if not meme_barrage_enabled(self.config):
            self._stop_meme_barrage_timers()
            return
        settings = read_meme_barrage_settings(self.config)
        self._meme_collect_timer.setInterval(max(1000, int(settings["collect_interval_sec"]) * 1000))
        self._meme_display_timer.setInterval(max(1000, int(settings["display_interval_sec"]) * 1000))
        if not self._meme_collect_timer.isActive():
            self._meme_collect_timer.start()
        if not self._meme_display_timer.isActive():
            self._meme_display_timer.start()
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
        if service is not None:
            service.set_fetch_in_flight(False)
            service.set_ai_select_in_flight(False)
        self._meme_ai_in_flight = False

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
            texts = service.collect_local_batch()
            cleaned = service.ingest_collected_texts(texts)
            self._meme_enqueue_for_display(service, cleaned, settings)
            return

        service.set_fetch_in_flight(True)
        batch_size = int(settings["collect_batch_size"])
        tag = str(settings["tag"])
        page_num = service.next_page_num()

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
        )
        QThreadPool.globalInstance().start(runnable)

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
            if texts:
                service.store.insert_many(filtered)
            settings = read_meme_barrage_settings(self.config)
            self._meme_enqueue_for_display(service, texts, settings)
        except Exception as exc:
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
        try:
            max_width = self.config.get_int("image_max_width", IMAGE_MAX_WIDTH)
            quality = self.config.get_int("image_quality", IMAGE_JPEG_QUALITY)
            image_data_uri = compress_screenshot(pixmap, max_width=max_width, quality=quality)
        except Exception as exc:
            self.logger.warning(f"meme_ai_select_failed reason=compress_error detail={exc!r}")
            service.enqueue_display(candidates[: int(settings["display_batch_size"])])
            return
        if not image_data_uri:
            service.enqueue_display(candidates[: int(settings["display_batch_size"])])
            return

        service.set_ai_select_in_flight(True)
        self._meme_ai_in_flight = True
        pick_count = int(settings["display_batch_size"])
        fallback_n = pick_count

        bridge = self._meme_barrage_bridge

        def on_success(selected: list[str]) -> None:
            bridge.ai_select_done.emit(selected, candidates, fallback_n)

        def on_error(_message: str) -> None:
            bridge.ai_select_failed.emit(candidates, fallback_n)

        runnable = MemeAiSelectRunnable(
            worker=self.ai_worker,
            config=self.config,
            image_data_uri=image_data_uri,
            candidates=candidates,
            pick_count=pick_count,
            on_success=on_success,
            on_error=on_error,
        )
        QThreadPool.globalInstance().start(runnable)

    def _on_meme_ai_select_done_signal(
        self,
        selected: list[str],
        fallback_candidates: list[str],
        fallback_n: int,
    ) -> None:
        self._on_meme_ai_select_done(
            selected,
            fallback_candidates=fallback_candidates,
            fallback_n=fallback_n,
        )

    def _on_meme_ai_select_failed_signal(self, candidates: list[str], fallback_n: int) -> None:
        self._on_meme_ai_select_failed(candidates, fallback_n)

    def _on_meme_ai_select_done(
        self,
        selected: list[str],
        *,
        fallback_candidates: list[str],
        fallback_n: int,
    ) -> None:
        service = self._ensure_meme_barrage_service()
        service.set_ai_select_in_flight(False)
        self._meme_ai_in_flight = False
        if selected:
            service.enqueue_display(selected)
        else:
            self.logger.warning("meme_ai_select_failed reason=empty_result")
            service.enqueue_display(fallback_candidates[:fallback_n])

    def _on_meme_ai_select_failed(self, candidates: list[str], fallback_n: int) -> None:
        service = self._ensure_meme_barrage_service()
        service.set_ai_select_in_flight(False)
        self._meme_ai_in_flight = False
        self.logger.warning("meme_ai_select_failed reason=request_failed")
        service.enqueue_display(candidates[:fallback_n])

    def _meme_display_tick(self) -> None:
        if not bool(getattr(self.engine, "running", False)):
            return
        if not meme_barrage_enabled(self.config):
            return
        service = self._ensure_meme_barrage_service()
        settings = read_meme_barrage_settings(self.config)
        batch_size = int(settings["display_batch_size"])
        texts = service.pop_display_batch(batch_size)
        if not texts:
            return
        scene_generation = int(getattr(self, "_scene_generation", 0))
        for text in texts:
            item = self.engine.add_text(
                text,
                persona="",
                batch_id=0,
                scene_generation=scene_generation,
                skip_dedup=True,
            )
            if item:
                self._update_stats(success=True)
