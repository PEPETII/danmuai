"""Live2D model API façade helpers."""

from __future__ import annotations


def get_model_snapshot(app) -> dict[str, object]:
    return app.get_live2d_model_snapshot()


def import_model_via_dialog(app) -> dict[str, object]:
    return app.import_live2d_model_via_dialog()


def clear_model(app) -> dict[str, object]:
    return app.clear_live2d_model()


def start_model(app) -> dict[str, object]:
    return app.start_live2d_model()


def stop_model(app) -> dict[str, object]:
    return app.stop_live2d_model()


def control_parameter(app, payload: dict[str, object]) -> dict[str, object]:
    return app.set_live2d_parameter(
        str(payload.get("parameter_id") or ""),
        float(payload.get("value")),
    )


def control_action(app, payload: dict[str, object]) -> dict[str, object]:
    return app.trigger_live2d_action(str(payload.get("action") or ""))


def control_motion(app, payload: dict[str, object]) -> dict[str, object]:
    return app.start_live2d_motion(str(payload.get("file") or ""))


def control_expression(app, payload: dict[str, object]) -> dict[str, object]:
    return app.set_live2d_expression(str(payload.get("file") or ""))


def get_model_resource(app, resource_path: str) -> tuple[bytes, str]:
    return app.get_live2d_model_resource(resource_path)
