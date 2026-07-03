"""Web console API services."""

from __future__ import annotations

__all__ = ["register_web_routes"]


def __getattr__(name: str):
    if name == "register_web_routes":
        from app.web_api.routes import register_web_routes

        return register_web_routes
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
