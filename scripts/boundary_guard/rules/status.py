"""``DanmuApp.build_status_snapshot()`` 必须继续委托 ``StatusSnapshotBuilder``。

规则（与 [docs/CONTRIBUTING_ARCHITECTURE.md] 3.2 / phase2.5 对应）：
    - ``main.py`` 改动时，``build_status_snapshot`` 函数体**必须**存在
    - 函数体**必须**包含 ``StatusSnapshotBuilder`` 与 ``.build(`` 调用
    - 禁止把 snapshot 内联回 ``DanmuApp``（防止状态字段散落主类）
"""

from __future__ import annotations

from pathlib import Path

from ..constants import MAIN_PATH
from ..git_diff import (
    _read_lines,
)
from ..models import Finding
from ..source_parse import _extract_function_body, _meaningful_body_lines


def check_status_snapshot_builder_delegation(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH not in changed:
        return findings
    lines = _read_lines(repo_root / MAIN_PATH)
    body = _extract_function_body(lines, 'build_status_snapshot')
    if not body:
        findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 3.2 / phase2.5', path=str(MAIN_PATH), line=0, message='`DanmuApp.build_status_snapshot()` 必须保留并继续委托 `StatusSnapshotBuilder`'))
        return findings
    meaningful = _meaningful_body_lines(body)
    body_text = '\n'.join(meaningful)
    if 'StatusSnapshotBuilder' not in body_text or '.build(' not in body_text:
        findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 3.2 / phase2.5', path=str(MAIN_PATH), line=0, message='`DanmuApp.build_status_snapshot()` 必须继续委托 `StatusSnapshotBuilder`'))
    if 'return {' in body_text or 'WebStatusSnapshot(' in body_text:
        findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 3.2 / phase2.5', path=str(MAIN_PATH), line=0, message='`DanmuApp.build_status_snapshot()` 不允许回退为直接拼装 status dict / WebStatusSnapshot'))
    allowed_single_line = {'return StatusSnapshotBuilder(self).build()'}
    allowed_two_line = {'builder = StatusSnapshotBuilder(self)', 'return builder.build()'}
    if meaningful:
        if len(meaningful) == 1 and meaningful[0] in allowed_single_line:
            return findings
        if len(meaningful) == 2 and set(meaningful) == allowed_two_line:
            return findings
        findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 3.2 / phase2.5', path=str(MAIN_PATH), line=0, message='`DanmuApp.build_status_snapshot()` 只能保留薄 façade，不能重新夹带额外状态拼装逻辑'))
    return findings
