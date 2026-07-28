"""Problem state management with deduplication and history."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from app.problems.catalog import PROBLEM_CATALOG, catalog_actions, catalog_entry
from app.problems.classifier import severity_rank
from app.problems.model import ProblemDescriptor
from app.problems.sanitizer import sanitize_context, sanitize_technical_detail

PROBLEM_DEDUP_WINDOW_SEC = 30
RECENT_PROBLEMS_LIMIT = 20

_FINGERPRINT_CONTEXT_KEYS = ("provider_id", "model_id", "status_code", "settings_target")


class ProblemService:
    def __init__(self) -> None:
        self._sequence = 0
        self._active: ProblemDescriptor | None = None
        self._recent: list[ProblemDescriptor] = []
        self._dedup_index: dict[str, ProblemDescriptor] = {}

    def report(
        self,
        code: str,
        *,
        technical_detail: str = "",
        context: dict | None = None,
        force_new_event: bool = False,
    ) -> ProblemDescriptor:
        now = time.time()
        entry = catalog_entry(code)
        safe_context = sanitize_context(context)
        fingerprint = self._build_fingerprint(code, safe_context)
        sanitized_detail = sanitize_technical_detail(technical_detail)

        existing = None if force_new_event else self._dedup_index.get(fingerprint)
        if existing is not None and (now - existing.last_occurred_at) <= PROBLEM_DEDUP_WINDOW_SEC:
            updated = replace(
                existing,
                last_occurred_at=now,
                occurrence_count=existing.occurrence_count + 1,
                technical_detail=sanitized_detail or existing.technical_detail,
                context=safe_context or existing.context,
            )
            self._dedup_index[fingerprint] = updated
            if self._active is not None and self._active.event_id == existing.event_id:
                self._active = updated
            self._replace_recent(updated)
            return updated

        self._sequence += 1
        event_id = f"problem-{int(now * 1000)}-{self._sequence}"
        descriptor = ProblemDescriptor(
            event_id=event_id,
            code=code if code in PROBLEM_CATALOG else "INTERNAL-001",
            severity=str(entry.get("severity") or "error"),
            category=str(entry.get("category") or "internal"),
            title_key=str(entry.get("title_key") or "problem.internal.title"),
            summary_key=str(entry.get("summary_key") or "problem.internal.summary"),
            cause_key=str(entry.get("cause_key") or "problem.internal.cause"),
            impact_key=str(entry.get("impact_key") or "problem.internal.impact"),
            suggestion_keys=tuple(entry.get("suggestion_keys") or ()),
            actions=catalog_actions(code if code in PROBLEM_CATALOG else "INTERNAL-001"),
            technical_detail=sanitized_detail,
            recoverable=bool(entry.get("recoverable", True)),
            feedback_allowed=bool(entry.get("feedback_allowed", True)),
            occurred_at=now,
            last_occurred_at=now,
            occurrence_count=1,
            fingerprint=fingerprint,
            context=safe_context,
        )
        self._dedup_index[fingerprint] = descriptor
        self._push_recent(descriptor)
        self._set_active(descriptor)
        return descriptor

    def clear(self, *, code: str | None = None) -> None:
        if code is None:
            self._active = None
            return
        if self._active is not None and self._active.code == code:
            self._active = None

    def active_problem(self) -> ProblemDescriptor | None:
        return self._active

    def recent_problems(self, limit: int = RECENT_PROBLEMS_LIMIT) -> list[ProblemDescriptor]:
        return list(self._recent[: max(0, int(limit))])

    def _build_fingerprint(self, code: str, context: dict[str, Any]) -> str:
        parts = [str(code)]
        for key in _FINGERPRINT_CONTEXT_KEYS:
            value = context.get(key)
            if value not in (None, ""):
                parts.append(f"{key}={value}")
        return "|".join(parts)

    def _set_active(self, descriptor: ProblemDescriptor) -> None:
        current = self._active
        if current is None:
            self._active = descriptor
            return
        if current.event_id == descriptor.event_id:
            self._active = descriptor
            return
        if severity_rank(descriptor.severity) >= severity_rank(current.severity):
            self._active = descriptor

    def _push_recent(self, descriptor: ProblemDescriptor) -> None:
        self._recent = [descriptor, *[item for item in self._recent if item.event_id != descriptor.event_id]]
        if len(self._recent) > RECENT_PROBLEMS_LIMIT:
            self._recent = self._recent[:RECENT_PROBLEMS_LIMIT]

    def _replace_recent(self, descriptor: ProblemDescriptor) -> None:
        self._recent = [
            descriptor if item.event_id == descriptor.event_id else item
            for item in self._recent
        ]
