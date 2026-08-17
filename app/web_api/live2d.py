"""Live2D model API façade helpers."""

from __future__ import annotations


def get_model_snapshot(app) -> dict[str, object]:
    return app.get_live2d_model_snapshot()


def import_model_via_dialog(app) -> dict[str, object]:
    return app.import_live2d_model_via_dialog()


def clear_model(app) -> dict[str, object]:
    return app.clear_live2d_model()
