import logging
import threading
from collections import deque
from datetime import datetime

_logger = logging.getLogger(__name__)


class HistoryWriter:
    def __init__(self, config, flush_interval: float = 2.0):
        self.config = config
        self.flush_interval = flush_interval
        self._buffer: deque[tuple] = deque()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="HistoryWriter")
        self._thread.start()

    def enqueue(self, content: str, persona: str, round_num: int, image_bytes: bytes | None = None):
        now = datetime.now().isoformat()
        with self._lock:
            self._buffer.append((now, persona, content, image_bytes, round_num))

    def flush(self):
        with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
        if not items:
            return
        try:
            self.config.conn.executemany(
                "INSERT INTO history (time, persona, content, image, round) VALUES (?,?,?,?,?)",
                items,
            )
            self.config.conn.commit()
        except Exception:
            _logger.exception("history flush failed items=%d", len(items))

    def _run(self):
        while not self._stop_event.wait(self.flush_interval):
            self.flush()

    def stop(self):
        self._stop_event.set()
        self.flush()
        self._thread.join(timeout=3.0)
