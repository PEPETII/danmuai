"""Semantic-style version comparison (numeric segments; not lexicographic strings).

Supports semver vx.x.x (0.2.2, v0.3.0), legacy CalVer, and optional -prerelease.
"""

from __future__ import annotations

import re

_SEGMENT_RE = re.compile(r"^(\d*)")

# semver prerelease priority: lower number = lower precedence (earlier pre-release)
# Unknown identifiers have the lowest precedence (0), sorted among themselves by string order
_PRERELEASE_PRIORITY = {
    "dev": 1,
    "a": 2,
    "alpha": 2,
    "b": 3,
    "beta": 3,
    "c": 4,
    "rc": 4,
}


def normalize_version(raw: str) -> str:
    """Strip whitespace and optional leading v/V."""
    s = str(raw or "").strip()
    if s.lower().startswith("v") and len(s) > 1 and s[1].isdigit():
        s = s[1:]
    return s


def _parse_numeric_segments(core: str) -> tuple[int, ...]:
    """Split core (before prerelease) by '.'; each segment uses leading digits only."""
    if not core:
        return (0,)
    parts: list[int] = []
    for piece in core.split("."):
        piece = piece.strip()
        if not piece:
            parts.append(0)
            continue
        m = _SEGMENT_RE.match(piece)
        if not m or m.group(1) == "":
            raise ValueError(f"invalid version segment: {piece!r}")
        parts.append(int(m.group(1)))
    return tuple(parts)


def _split_core_prerelease(normalized: str) -> tuple[str, str | None]:
    # Strip build metadata (+build) per semver — it must be ignored for comparison.
    if "+" in normalized:
        normalized = normalized.split("+", 1)[0]
    if "-" not in normalized:
        return normalized, None
    core, prerelease = normalized.split("-", 1)
    prerelease = prerelease.strip() or None
    return core, prerelease


def parse_version(raw: str) -> tuple[tuple[int, ...], str | None]:
    """Return (numeric_segments, prerelease_or_none)."""
    normalized = normalize_version(raw)
    if not normalized:
        raise ValueError("empty version")
    core, prerelease = _split_core_prerelease(normalized)
    return _parse_numeric_segments(core), prerelease


def _compare_prerelease(a: str, b: str) -> int:
    """Compare two prerelease identifiers by semver priority.

    Extracts the identifier prefix (before first '.') and maps it to a priority.
    Unknown identifiers fall back to string comparison with lowest priority.
    """
    def _priority(s: str) -> tuple[int, str]:
        prefix = s.split(".")[0].lower()
        return _PRERELEASE_PRIORITY.get(prefix, 0), s

    pa, sa = _priority(a)
    pb, sb = _priority(b)
    if pa != pb:
        return -1 if pa < pb else 1
    return -1 if sa < sb else 1 if sa > sb else 0


def compare_versions(a: str, b: str) -> int:
    """Compare two versions: -1 if a<b, 0 if equal, 1 if a>b."""
    seg_a, pre_a = parse_version(a)
    seg_b, pre_b = parse_version(b)

    if seg_a != seg_b:
        return -1 if seg_a < seg_b else 1

    # Same numeric core: release beats prerelease; both prerelease → semantic order
    if pre_a is None and pre_b is None:
        return 0
    if pre_a is None and pre_b is not None:
        return 1
    if pre_a is not None and pre_b is None:
        return -1
    return _compare_prerelease(pre_a, pre_b)


def is_version_newer(latest: str, current: str) -> bool:
    """True when latest is strictly greater than current (for update prompts)."""
    return compare_versions(latest, current) > 0
