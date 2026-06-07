"""诊断快照边界规则。

检查项：
    - check_diagnostic_snapshot_boundary
        ``app/application/diagnostic_snapshot.py`` 内不允许直写
        ``app.<attr> = ...`` 或 ``app.<list>.append(...)``；只能从 ``runtime_state``
        投影到快照字段。这是 Phase 4-F 的具体落地：HTTP 出口统一经 snapshot。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..constants import (
    DIAGNOSTIC_SNAPSHOT_FORBIDDEN_CALLS,
    DIAGNOSTIC_SNAPSHOT_FORBIDDEN_TOKENS,
    DIAGNOSTIC_SNAPSHOT_PATH,
)
from ..git_diff import (
    _is_comment_or_blank,
    get_added_lines,
)
from ..models import Finding


def check_diagnostic_snapshot_boundary(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if DIAGNOSTIC_SNAPSHOT_PATH not in changed:
        return findings
    for line_no, line in get_added_lines(repo_root, DIAGNOSTIC_SNAPSHOT_PATH, changed[DIAGNOSTIC_SNAPSHOT_PATH]):
        if _is_comment_or_blank(line):
            continue
        if re.search('\\b(?:app|self\\._app)\\.[A-Za-z_][A-Za-z0-9_]*\\s*(?::[^=]+)?(?:\\+?=|-=)', line) or re.search('\\b(?:app|self\\._app)\\.[A-Za-z_][A-Za-z0-9_]*\\.(?:append|clear|extend|insert|pop|remove|update|setdefault)\\(', line):
            findings.append(Finding(severity='error', rule='diagnostics-plan.md / phase5-a', path=str(DIAGNOSTIC_SNAPSHOT_PATH), line=line_no, message='DiagnosticSnapshot must be read-only and must not write app state'))
            continue
        for pattern, message in DIAGNOSTIC_SNAPSHOT_FORBIDDEN_TOKENS:
            if re.search(pattern, line):
                findings.append(Finding(severity='error', rule='diagnostics-plan.md / phase5-a', path=str(DIAGNOSTIC_SNAPSHOT_PATH), line=line_no, message=message))
                break
        else:
            for token in DIAGNOSTIC_SNAPSHOT_FORBIDDEN_CALLS:
                if token in line:
                    findings.append(Finding(severity='error', rule='diagnostics-plan.md / phase5-a', path=str(DIAGNOSTIC_SNAPSHOT_PATH), line=line_no, message='DiagnosticSnapshot must not call trigger, reply, or queue pipeline functions'))
                    break
    return findings
