from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from app.api_probe import probe_connection


class ProbeBridge(QObject):
    finished = pyqtSignal(object)


class ProbeRunnable(QRunnable):
    def __init__(
        self,
        bridge: ProbeBridge,
        endpoint: str,
        api_key: str,
        model_id: str,
        mode: str,
        generation: int = 0,
    ):
        super().__init__()
        self.bridge = bridge
        self.endpoint = endpoint
        self.api_key = api_key
        self.model_id = model_id
        self.mode = mode
        self.generation = generation
        self.setAutoDelete(True)

    def run(self):
        result = probe_connection(
            self.endpoint,
            self.api_key,
            self.model_id,
            self.mode,
        )
        self.bridge.finished.emit((self.generation, result))
