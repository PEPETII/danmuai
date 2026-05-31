from unittest.mock import MagicMock

from app.history_writer import HistoryWriter


def test_history_writer_logs_flush_failures(monkeypatch):
    logger = MagicMock()
    monkeypatch.setattr("app.history_writer._logger", logger)

    config = MagicMock()
    config.conn.executemany.side_effect = RuntimeError("db locked")

    writer = HistoryWriter(config, flush_interval=60.0)
    writer.enqueue("hello", "persona", 1)
    writer.flush()
    writer.stop()

    logger.exception.assert_called_once()
