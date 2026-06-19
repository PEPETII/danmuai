"""P3-03: Long-run danmu memory stability (accelerated soak + optional extended run)."""

from __future__ import annotations

import os
import tracemalloc

import pytest
from app.config_store import ConfigStore
from app.danmu_engine import FADE_IN_PX, DanmuEngine
from app.overlay import _PRERENDER_AHEAD_PX, DanmuOverlay
from PyQt6.QtWidgets import QApplication

_STEADY_PLATEAU_RATIO_MAX = 0.25
_FAR_OFFSCREEN_PIXMAP_NONE_RATIO_MIN = 0.5
_WARMUP_ROUNDS = 800


@pytest.fixture()
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def memory_stack(qapp, workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "mem.db")
    store.set("danmu_speed", "4.0")
    store.set("danmu_lines", "8")
    store.set("danmu_pending_entry_cap", "300")
    store.set("danmu_track_retention_cap", "600")
    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    engine.recent.clear()
    engine.recent_exact_set.clear()
    overlay = DanmuOverlay(store, engine)
    engine.overlay = overlay
    overlay.setGeometry(0, 0, 1920, 1080)
    overlay._screen_width = 1920.0
    return store, engine, overlay


def _snapshot_total_bytes() -> int:
    snapshot = tracemalloc.take_snapshot()
    return sum(stat.size for stat in snapshot.statistics("lineno"))


def _far_offscreen_pixmap_none_ratio(engine: DanmuEngine, screen_width: float) -> float:
    threshold = screen_width + FADE_IN_PX + _PRERENDER_AHEAD_PX
    far = 0
    none_pixmap = 0
    for track in engine.tracks:
        for item in track.items:
            if item.x >= threshold:
                far += 1
                if item._pixmap is None:
                    none_pixmap += 1
    if far == 0:
        return 1.0
    return none_pixmap / far


def _soak_round(engine: DanmuEngine, overlay: DanmuOverlay, *, index: int) -> None:
    engine.add_text(f"soak-{index}", skip_dedup=True)
    for _ in range(3):
        engine.update(speed_factor=1.0, dt_sec=1.0 / 30.0)
    overlay._prepare_pixmaps_near_visible()


def _run_measured_soak(engine: DanmuEngine, overlay: DanmuOverlay, *, rounds: int) -> list[int]:
    for i in range(_WARMUP_ROUNDS):
        _soak_round(engine, overlay, index=i)

    tracemalloc.start()
    samples: list[int] = []
    retention_cap = engine._track_retention_cap()
    for i in range(rounds):
        _soak_round(engine, overlay, index=_WARMUP_ROUNDS + i)
        if i % 100 == 0:
            samples.append(_snapshot_total_bytes())
        assert engine.current_display_count() <= retention_cap

    tracemalloc.stop()
    return samples


def test_danmu_memory_stable_under_accelerated_soak(memory_stack):
    """CI-friendly accelerated soak: tracemalloc plateau after cap, lazy pixmap on far pending."""
    _, engine, overlay = memory_stack
    measured_rounds = 1200 if os.environ.get("DANMU_MEMORY_SOAK") != "1" else 6000

    samples = _run_measured_soak(engine, overlay, rounds=measured_rounds)
    assert engine.current_display_count() <= engine._track_retention_cap()
    assert len(samples) >= 3

    steady = samples[-3:]
    min_steady = min(steady)
    max_steady = max(steady)
    if min_steady > 0:
        plateau_drift = (max_steady - min_steady) / min_steady
        assert plateau_drift < _STEADY_PLATEAU_RATIO_MAX, (
            f"steady tracemalloc drift {plateau_drift:.1%} ({min_steady}..{max_steady})"
        )

    assert _far_offscreen_pixmap_none_ratio(engine, engine.screen_width) >= (
        _FAR_OFFSCREEN_PIXMAP_NONE_RATIO_MIN
    )


@pytest.mark.skipif(
    os.environ.get("DANMU_MEMORY_SOAK") != "1",
    reason="Extended soak requires DANMU_MEMORY_SOAK=1",
)
def test_danmu_memory_extended_soak_optional_psutil(memory_stack):
    """Maintainer-only: longer run with optional RSS check via psutil."""
    psutil = pytest.importorskip("psutil")
    _, engine, overlay = memory_stack
    process = psutil.Process()

    rss_samples: list[int] = []
    for block in range(6):
        _run_measured_soak(engine, overlay, rounds=2000)
        rss_samples.append(process.memory_info().rss)

    if rss_samples[0] > 0:
        growth = (max(rss_samples[-2:]) - rss_samples[0]) / rss_samples[0]
        assert growth < 0.25, f"RSS grew {growth:.1%} over extended soak"
