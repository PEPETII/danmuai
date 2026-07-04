"""Pet render-loop idle-stop scheduling (overlay-style adaptive timer)."""

import time

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from app.pet.pet_render_loop import (
    BUBBLE_ALPHA_EPSILON,
    needs_animation_tick,
    needs_high_frequency_tick,
    ms_until_next_frame_tick,
)
from app.pet.pet_window import PetWindow
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def test_needs_high_frequency_tick_drag_and_bubble():
    assert needs_high_frequency_tick(
        dragging=True,
        momentum_active=False,
        bubble_alpha=0.0,
        bubble_target_alpha=0.0,
    )
    assert needs_high_frequency_tick(
        dragging=False,
        momentum_active=False,
        bubble_alpha=0.0,
        bubble_target_alpha=BUBBLE_ALPHA_EPSILON + 0.01,
    )
    assert not needs_high_frequency_tick(
        dragging=False,
        momentum_active=False,
        bubble_alpha=0.5,
        bubble_target_alpha=0.5,
    )


def test_needs_animation_tick_idle_assets():
    now = 100.0
    assert needs_animation_tick(
        visible=True,
        assets_ready=True,
        dragging=False,
        momentum_active=False,
        bubble_alpha=0.0,
        bubble_target_alpha=0.0,
        one_shot=None,
        one_shot_until=0.0,
        post_drag_waving_until=0.0,
        now=now,
    )
    assert not needs_animation_tick(
        visible=False,
        assets_ready=True,
        dragging=False,
        momentum_active=False,
        bubble_alpha=0.0,
        bubble_target_alpha=0.0,
        one_shot=None,
        one_shot_until=0.0,
        post_drag_waving_until=0.0,
        now=now,
    )


def test_ms_until_next_frame_tick_minimum():
    assert ms_until_next_frame_tick(frame_clock=0.0, frame_interval_sec=0.183) >= 1
    assert ms_until_next_frame_tick(frame_clock=0.2, frame_interval_sec=0.183) == 1


def _make_visible_pet(qapp):
    from app.translations import Translator

    Translator._instance = None
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"pet_asset_source": "builtin"}),
    )
    window = PetWindow(app)
    window.show()
    qapp.processEvents()
    window._ensure_assets_loaded()
    return window


def test_idle_stops_16ms_timer_between_frames(qapp):
    window = _make_visible_pet(qapp)
    window._bubble_alpha = 0.0
    window._bubble_target_alpha = 0.0
    window._frame_clock = 0.05
    window._on_anim_tick()
    assert not window._anim_timer.isActive()
    assert window._wake_timer.isActive()


def test_bubble_text_restarts_timer_from_idle(qapp):
    window = _make_visible_pet(qapp)
    window.stop_render_loop()
    assert not window._anim_timer.isActive()
    assert not window._wake_timer.isActive()

    window.set_bubble_text("hello")

    assert window._anim_timer.isActive()


def test_one_shot_restarts_timer(qapp):
    window = _make_visible_pet(qapp)
    window.stop_render_loop()
    window._trigger_one_shot("wave")
    assert window._anim_timer.isActive() or window._wake_timer.isActive()


def test_drag_press_restarts_high_freq_timer(qapp):
    from app.pet.pet_state import PetSettings

    window = _make_visible_pet(qapp)
    window._settings = PetSettings.from_config(
        FakeConfig({"pet_asset_source": "builtin", "pet_click_through": "0"})
    )
    window.stop_render_loop()
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mousePressEvent(press)
    assert window._anim_timer.isActive()


def test_hide_pet_stops_both_timers(qapp):
    window = _make_visible_pet(qapp)
    window.start_render_loop()
    assert window._anim_timer.isActive() or window._wake_timer.isActive()
    window.hide_pet()
    assert not window._anim_timer.isActive()
    assert not window._wake_timer.isActive()
