"""Background worker for microphone transcription log updates."""

from __future__ import annotations

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from app.mic_transcription import transcribe_pcm


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
        result = transcribe_pcm(self._config, self._pcm)
        self._coordinator.finished.emit(self._utterance_id, result)
