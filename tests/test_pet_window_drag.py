"""PET-013: PetDex Desktop–aligned drag / momentum animation contracts."""

import pytest
from app.pet.pet_assets import PET_FRAME_H, load_pet_assets
from app.pet.pet_window import (
    PointerSample,
    compute_pointer_velocity,
    drag_run_state_for_dx,
    momentum_run_state_for_vx,
    resolve_interaction_animation,
)
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def test_frame_rect_running_right_on_row_2(qapp):
    """Builtin sheet row 2 faces right (PET-013 debug: rows 1/2 swapped vs PetDex names)."""
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    _, sy, _, _ = pack.frame_rect("running-right", 0)
    assert sy == 2 * PET_FRAME_H


def test_frame_rect_running_left_on_row_1(qapp):
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    _, sy, _, _ = pack.frame_rect("running-left", 0)
    assert sy == 1 * PET_FRAME_H


def test_drag_run_state_for_dx_threshold():
    assert drag_run_state_for_dx(3) is None
    assert drag_run_state_for_dx(4) == "running-right"
    assert drag_run_state_for_dx(-4) == "running-left"


def test_compute_pointer_velocity_from_samples():
    samples = [
        PointerSample(x=0.0, y=0.0, t=0.0),
        PointerSample(x=100.0, y=0.0, t=0.1),
    ]
    vel = compute_pointer_velocity(samples)
    assert vel is not None
    vx, vy = vel
    assert vx == pytest.approx(1000.0)
    assert vy == pytest.approx(0.0)


def test_momentum_run_state_for_vx():
    assert momentum_run_state_for_vx(80) == "running-right"
    assert momentum_run_state_for_vx(-80) == "running-left"
    assert momentum_run_state_for_vx(10) is None


def test_resolve_interaction_drag_overrides_mapper_review():
    now = 100.0
    assert (
        resolve_interaction_animation(
            dragging=True,
            momentum_active=False,
            drag_anim_state="jumping",
            post_drag_waving_until=0.0,
            now=now,
            mapper_state="review",
        )
        == "jumping"
    )


def test_resolve_interaction_momentum_overrides_mapper_review():
    now = 100.0
    assert (
        resolve_interaction_animation(
            dragging=False,
            momentum_active=True,
            drag_anim_state="running-right",
            post_drag_waving_until=0.0,
            now=now,
            mapper_state="review",
        )
        == "running-right"
    )


def test_resolve_interaction_post_drag_waving_then_idle_mapper(qapp):
    now = 100.0
    assert (
        resolve_interaction_animation(
            dragging=False,
            momentum_active=False,
            drag_anim_state="waving",
            post_drag_waving_until=now + 1.0,
            now=now,
            mapper_state="review",
        )
        == "waving"
    )
    assert (
        resolve_interaction_animation(
            dragging=False,
            momentum_active=False,
            drag_anim_state="waving",
            post_drag_waving_until=now - 0.1,
            now=now,
            mapper_state="idle",
        )
        == "idle"
    )


def test_pet_window_current_animation_priority_over_review(qapp):
    from app.pet.pet_window import PetWindow

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, ai_in_flight=1)
    window = PetWindow(app)
    window._dragging = True
    window._drag_anim_state = "running-left"
    assert window._current_animation() == "running-left"
    window._dragging = False
    window._momentum_active = True
    window._drag_anim_state = "running-right"
    assert window._current_animation() == "running-right"


def test_anim_tick_skips_redundant_repaint_when_frame_unchanged(qapp, monkeypatch):
    from app.pet.pet_window import PetWindow

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, ai_in_flight=1)
    window = PetWindow(app)
    window._ensure_assets_loaded()
    update_calls = {"n": 0}
    original_update = window.update

    def counting_update(*_args, **_kwargs):
        update_calls["n"] += 1
        return original_update(*_args, **_kwargs)

    monkeypatch.setattr(window, "update", counting_update)
    window._on_anim_tick()
    assert update_calls["n"] == 1
    window._on_anim_tick()
    assert update_calls["n"] == 1


def test_pet_window_does_not_set_ws_ex_transparent(qapp, monkeypatch):
    """BUG-017: PetWindow must receive mouse events (no overlay click-through default)."""
    import app.win32_overlay_zorder as mod
    from app.pet.pet_window import PetWindow

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=FakeConfig({"pet_asset_source": "builtin", "pet_click_through": "0"}))
    window = PetWindow(app)

    stored: dict[int, int] = {mod._GWL_EXSTYLE: 0}
    monkeypatch.setattr(mod, "_GetWindowLong", lambda hwnd, idx: stored.get(idx, 0))
    monkeypatch.setattr(
        mod,
        "_SetWindowLong",
        lambda hwnd, idx, value: stored.__setitem__(idx, value),
    )
    apply_calls: list[bool] = []
    original_apply = mod.apply_overlay_exstyles

    def recording_apply(hwnd, *, click_through=True):
        apply_calls.append(click_through)
        return original_apply(hwnd, click_through=click_through)

    monkeypatch.setattr("app.pet.pet_window.apply_overlay_exstyles", recording_apply)
    monkeypatch.setattr(window, "winId", lambda: 12345)
    monkeypatch.setattr(window, "isVisible", lambda: True)
    window._apply_win32_surface()

    assert apply_calls == [False]
    assert stored[mod._GWL_EXSTYLE] & mod._WS_EX_LAYERED
    assert not (stored[mod._GWL_EXSTYLE] & mod._WS_EX_TRANSPARENT)
    window.close()
