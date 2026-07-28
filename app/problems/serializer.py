"""Serialize ProblemDescriptor for /api/status with translated user-facing text."""

from __future__ import annotations

from typing import Any

from app.problems.model import ProblemAction, ProblemDescriptor
from app.translations import tr


def _translate_key(key: str, *, fallback: str = "") -> str:
    text = tr(key, default=fallback or key)
    if text == key and fallback:
        return fallback
    return text


def _serialize_action(action: ProblemAction) -> dict[str, Any]:
    return {
        "type": action.type,
        "label": _translate_key(action.label_key),
        "label_key": action.label_key,
        "target": action.target,
        "payload": dict(action.payload),
    }


def serialize_problem_descriptor(problem: ProblemDescriptor, *, full: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_id": problem.event_id,
        "code": problem.code,
        "severity": problem.severity,
        "category": problem.category,
        "title": _translate_key(problem.title_key),
        "summary": _translate_key(problem.summary_key),
        "occurrence_count": problem.occurrence_count,
        "fingerprint": problem.fingerprint,
    }
    if not full:
        return payload
    payload.update(
        {
            "cause": _translate_key(problem.cause_key),
            "impact": _translate_key(problem.impact_key),
            "suggestions": [_translate_key(key) for key in problem.suggestion_keys],
            "actions": [_serialize_action(action) for action in problem.actions],
            "technical_detail": problem.technical_detail,
            "recoverable": problem.recoverable,
            "feedback_allowed": problem.feedback_allowed,
            "occurred_at": problem.occurred_at,
            "last_occurred_at": problem.last_occurred_at,
            "context": dict(problem.context),
            "title_key": problem.title_key,
            "summary_key": problem.summary_key,
            "cause_key": problem.cause_key,
            "impact_key": problem.impact_key,
            "suggestion_keys": list(problem.suggestion_keys),
        }
    )
    return payload


def serialize_problem_summary(problem: ProblemDescriptor) -> dict[str, Any]:
    return serialize_problem_descriptor(problem, full=False)
