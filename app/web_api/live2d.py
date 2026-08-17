"""Live2D model API façade helpers."""

from __future__ import annotations


def get_model_snapshot(app) -> dict[str, object]:
    return app.get_live2d_model_snapshot()


def import_model_via_dialog(app) -> dict[str, object]:
    return app.import_live2d_model_via_dialog()


def import_model_file_via_dialog(app) -> dict[str, object]:
    return app.import_live2d_model_file_via_dialog()


def clear_model(app) -> dict[str, object]:
    return app.clear_live2d_model()


def start_model(app) -> dict[str, object]:
    return app.start_live2d_model()


def stop_model(app) -> dict[str, object]:
    return app.stop_live2d_model()


def get_model_resource(app, resource_path: str) -> tuple[bytes, str]:
    return app.get_live2d_model_resource(resource_path)


def apply_settings(app, payload: dict) -> dict[str, object]:
    return app.apply_live2d_settings_patch(payload)
