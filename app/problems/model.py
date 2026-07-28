"""Unified problem descriptor model (immutable)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProblemAction:
    type: str
    label_key: str
    target: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProblemDescriptor:
    event_id: str
    code: str
    severity: str
    category: str

    title_key: str
    summary_key: str
    cause_key: str
    impact_key: str
    suggestion_keys: tuple[str, ...]

    actions: tuple[ProblemAction, ...] = ()
    technical_detail: str = ""

    recoverable: bool = True
    feedback_allowed: bool = True
    occurred_at: float = 0.0
    last_occurred_at: float = 0.0
    occurrence_count: int = 1
    fingerprint: str = ""

    context: dict[str, Any] = field(default_factory=dict)
