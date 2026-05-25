"""Tests for DANMU_IMAGE_METRICS optional logging."""


from app.image_metrics import image_metrics_enabled, jpeg_output_size, log_compress_metrics


class FakeLogger:
    def __init__(self):
        self.debug_messages = []

    def debug(self, message: str):
        self.debug_messages.append(message)


def test_image_metrics_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DANMU_IMAGE_METRICS", raising=False)
    assert image_metrics_enabled() is False


def test_image_metrics_enabled(monkeypatch):
    monkeypatch.setenv("DANMU_IMAGE_METRICS", "1")
    assert image_metrics_enabled() is True


def test_log_compress_metrics_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("DANMU_IMAGE_METRICS", raising=False)
    logger = FakeLogger()
    log_compress_metrics(
        logger,
        orig_w=1920,
        orig_h=1080,
        quality=85,
        compress_ms=12.5,
        data_uri="data:image/jpeg;base64,",
    )
    assert logger.debug_messages == []


def test_log_compress_metrics_emits_sizes(monkeypatch):
    monkeypatch.setenv("DANMU_IMAGE_METRICS", "1")
    logger = FakeLogger()
    # Minimal valid JPEG (1x1) as base64
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color=(1, 2, 3)).save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    data_uri = f"data:image/jpeg;base64,{b64}"

    out_w, out_h, jpeg_bytes = jpeg_output_size(data_uri)
    assert out_w == 1 and out_h == 1
    assert jpeg_bytes > 0

    log_compress_metrics(
        logger,
        orig_w=100,
        orig_h=50,
        quality=85,
        compress_ms=3.0,
        data_uri=data_uri,
    )
    assert len(logger.debug_messages) == 1
    msg = logger.debug_messages[0]
    assert "image_metrics" in msg
    assert "orig=100x50" in msg
    assert "out=1x1" in msg
    assert "quality=85" in msg
    assert "data_uri_len=" in msg
    assert b64 not in msg
