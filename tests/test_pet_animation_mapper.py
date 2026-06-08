"""Contract tests for app.pet.pet_animation_mapper (PET-011)."""

from app.pet.pet_animation_mapper import resolve_base_animation, resolve_pet_animation_hint
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app


def _minimal_app(**overrides):
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, **overrides)
    return app


def test_resolve_base_animation_idle():
    app = _minimal_app()
    assert resolve_base_animation(app) == "idle"


def test_resolve_base_animation_review_when_ai_in_flight():
    app = _minimal_app(ai_in_flight=1)
    assert resolve_base_animation(app) == "review"


def test_resolve_base_animation_review_when_generating():
    app = _minimal_app(_is_generating=True)
    assert resolve_base_animation(app) == "review"


def test_resolve_base_animation_run_when_visible_danmu():
    app = _minimal_app()
    object.__setattr__(app, "visible_display_count", lambda: 1)
    assert resolve_base_animation(app) == "run"


def test_resolve_pet_animation_hint_one_shot_jump():
    app = _minimal_app()
    hint = resolve_pet_animation_hint(
        app,
        one_shot="jump",
        one_shot_until=100.0,
        now=50.0,
    )
    assert hint == "jump"
