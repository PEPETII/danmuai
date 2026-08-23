"""QThreadPool 与 AiWorker / 截图 worker 之间的执行桥。

DanmuApp._trigger_api_call 在主线程构造 AiRunnable 并 start；
run() 在工作线程内压缩截图、调用 AiWorker._request()，经 Qt 信号把结果队列回主线程
_on_ai_reply / _on_ai_error。

W-PERF-HIGH-001：CaptureRunnable 在 capture_worker_pool 执行 grabWindow，
经 CaptureCoordinator.completed 队列回主线程。禁止在此修改 DanmuApp 运行态或触碰 QWidget。
"""
import threading
import time

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from app.ai_client import AiWorker
from app.image_metrics import log_compress_metrics
from app.logger import SanitizedLogger
from app.main_helpers import REQUEST_WALL_CLOCK_SEC
from app.mic_encode import pcm_to_wav_data_uri
from app.translations import tr


class CaptureCoordinator(QObject):
    """Main-thread QObject; capture worker emits completed/failed signals."""

    completed = pyqtSignal(object, int)
    failed = pyqtSignal(str, int)


class CaptureRunnable(QRunnable):
    """Carry a main-thread-created QImage snapshot to the coordinator.

    The legacy name is retained for the capture-slot contract. This worker
    must not touch QApplication, QScreen, or QPixmap.
    """

    def __init__(
        self,
        image,
        coordinator: CaptureCoordinator,
        stopping: threading.Event,
        session_epoch: int = 0,
    ) -> None:
        super().__init__()
        self._image = image
        self._coordinator = coordinator
        self._stopping = stopping
        self._session_epoch = session_epoch
        self.setAutoDelete(True)

    def run(self) -> None:
        # stopping 早退必须 failed 结算槽位；主线程 _on_capture_failed 清 _capture_in_flight
        #（worker 禁止直接写 DanmuApp；W-AUDIT-0714-CAPTURE-STOP-001 / BUG-005）
        if self._stopping.is_set():
            self._coordinator.failed.emit(
                "capture_aborted_stopping",
                self._session_epoch,
            )
            return
        if self._stopping.is_set():
            self._coordinator.failed.emit(
                "capture_aborted_stopping",
                self._session_epoch,
            )
            return
        self._coordinator.completed.emit(self._image, self._session_epoch)


class AiRunnable(QRunnable):
    """QThreadPool 执行单元：压缩截图 → 调 AiWorker._request() → 信号回传主线程。

    W-015 异常兜底：_request() 最终异常时经 error 信号释放 ai_in_flight/mic_in_flight，
    防止主链路卡死。禁止在此修改 DanmuApp 运行态或触碰 QWidget。

    W-PERF-HIGH-002：pixmap 为借用的只读快照引用；实例持有至 run() 结束，worker 侧
    仅经 compress_fn 读取，不得修改 QPixmap。
    """

    def __init__(
        self,
        worker: AiWorker,
        pixmap,
        system_pt: str,
        user_pt: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        compress_fn,
        image_quality: int | None = None,
        mic_pcm: bytes | None = None,
        mic_attach_audio: bool = False,
        session_token: int | None = None,
        session_is_current=None,
    ):
        super().__init__()
        self.worker = worker
        self.pixmap = pixmap
        self.system_pt = system_pt
        self.user_pt = user_pt
        self.persona_id = persona_id
        self.request_round = request_round
        self.screenshot_id = screenshot_id
        self.captured_at = captured_at
        self.scene_generation = scene_generation
        self.compress_fn = compress_fn
        self.image_quality = image_quality
        self.mic_pcm = mic_pcm
        self.mic_attach_audio = mic_attach_audio
        self.session_token = session_token
        self.session_is_current = session_is_current
        self.setAutoDelete(True)

    def run(self):
        """QThreadPool 工作线程入口：压缩截图 → _request() → finished/error 信号回主线程。"""
        if not self._session_is_current():
            return

        logger = SanitizedLogger()
        started = time.monotonic()
        try:
            image_data_uri = self.compress_fn(self.pixmap)
        except (OSError, ValueError, RuntimeError) as exc:
            self.worker._emit_safe(
                "error",
                tr("runnable.compress_failed"),
                self.persona_id,
                self.request_round,
                self.screenshot_id,
                self.captured_at,
                self.scene_generation,
                0,
                0,
            )
            logger.debug(f"compress failed: {exc}")
            return

        if not image_data_uri:
            self.worker._emit_safe(
                "error",
                tr("runnable.compress_failed"),
                self.persona_id,
                self.request_round,
                self.screenshot_id,
                self.captured_at,
                self.scene_generation,
                0,
                0,
            )
            return

        # stop() clears the old Event and start() resets it. The immutable
        # session token remains the queue-time cancellation boundary.
        if not self._session_is_current():
            return

        compress_ms = (time.monotonic() - started) * 1000.0
        try:
            try:
                orig_w = int(self.pixmap.width())
                orig_h = int(self.pixmap.height())
            except (AttributeError, TypeError, ValueError):
                orig_w, orig_h = 0, 0
            quality = 85 if self.image_quality is None else int(self.image_quality)
            log_compress_metrics(
                logger,
                orig_w=orig_w,
                orig_h=orig_h,
                quality=quality,
                compress_ms=compress_ms,
                data_uri=image_data_uri,
            )

            audio_data_uri = None
            if self.mic_pcm and self.mic_attach_audio:
                audio_data_uri = pcm_to_wav_data_uri(self.mic_pcm)
        except Exception as exc:  # boundary: pre-request preprocessing
            if self._session_is_current():
                self.worker._emit_safe(
                    "error",
                    tr("runnable.compress_failed"),
                    self.persona_id,
                    self.request_round,
                    self.screenshot_id,
                    self.captured_at,
                    self.scene_generation,
                    0,
                    0,
                )
                logger.debug(
                    f"preprocess failed: {type(exc).__name__}: {exc}"
                )
            return

        if not self._session_is_current():
            return
        deadline_at = started + REQUEST_WALL_CLOCK_SEC
        try:
            self.worker._request(
                image_data_uri,
                self.system_pt,
                self.user_pt,
                self.persona_id,
                self.request_round,
                self.screenshot_id,
                self.captured_at,
                self.scene_generation,
                audio_data_uri=audio_data_uri,
                request_started_at=started,
                request_deadline_at=deadline_at,
            )
        except Exception as exc:  # boundary: AI request worker top-level
            if self._session_is_current():
                self.worker._emit_safe(
                    "error",
                    tr("ai.error_request_failed").format(error=exc),
                    self.persona_id,
                    self.request_round,
                    self.screenshot_id,
                    self.captured_at,
                    self.scene_generation,
                    0,
                    0,
                )
                logger.debug(
                    f"ai request failed in runnable: {type(exc).__name__}: {exc}"
                )

    def _session_is_current(self) -> bool:
        if self.worker._stopping.is_set():
            return False
        if self.session_token is None or self.session_is_current is None:
            return True
        try:
            return bool(self.session_is_current(self.session_token))
        except Exception:
            # Cancellation guards fail closed: do not send a stale request.
            return False
