"""Background worker for microphone transcription log updates."""

from __future__ import annotations

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from app.mic_transcription import MicTranscriptionResult, transcribe_pcm


class MicTranscriptCoordinator(QObject):
    finished = pyqtSignal(str, object)  # utterance_id, MicTranscriptionResult


class MicTranscriptRunnable(QRunnable):
    def __init__(
        self,
        *,
        config,
        pcm: bytes,
        utterance_id: str,
        coordinator: MicTranscriptCoordinator,
    ) -> None:
        super().__init__()
        self._config = config
        self._pcm = pcm
        self._utterance_id = utterance_id
        self._coordinator = coordinator
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = transcribe_pcm(self._config, self._pcm)
        except Exception as exc:  # noqa: BLE001 — worker must always emit a terminal result
            result = MicTranscriptionResult(ok=False, error=type(exc).__name__)
        self._coordinator.finished.emit(self._utterance_id, result)
