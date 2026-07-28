"""Helpers to parse catalog action definitions into ProblemAction tuples."""

from __future__ import annotations

from typing import Any

from app.problems.model import ProblemAction


def parse_actions(raw_actions: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None) -> tuple[ProblemAction, ...]:
    if not raw_actions:
        return ()
    parsed: list[ProblemAction] = []
    for item in raw_actions:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or "").strip()
        label_key = str(item.get("label_key") or "").strip()
        if not action_type or not label_key:
            continue
        target = str(item.get("target") or "")
        payload = item.get("payload")
        parsed.append(
            ProblemAction(
                type=action_type,
                label_key=label_key,
                target=target,
                payload=dict(payload) if isinstance(payload, dict) else {},
            )
        )
    return tuple(parsed)
