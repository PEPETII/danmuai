"""运行时状态 / 线程模型 / 文档同步规则。

检查项：
    - check_legacy_runtime_state_writes
        禁在 ``main.py`` 中向 ``self._rtt_history`` / ``self._last_api_trigger_at``
        等 LEGACY_RUNTIME_ASSIGNMENT_PATTERNS 直写；这些字段已迁移至
        application/*_state.py 与 RequestTimingService。
    - check_runtime_state_doc
        增删 ``app/application/runtime_state.py`` 字段时，docs/runtime-state-map.md
        必须同步登记。
    - check_thread_trigger_docs
        新增 ``QTimer.singleShot`` / ``QThreadPool.start`` / ``threading.Thread``
        触发点时，docs/main-pipeline-sequence.md 必须有说明（避免后人不熟
        线程模型时手抖）。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..constants import (
    LEGACY_RUNTIME_ASSIGNMENT_PATTERNS,
    MAIN_PATH,
    PIPELINE_DOC,
    RUNTIME_FIELD_EXCLUDE,
    RUNTIME_STATE_DOC,
    THREAD_TRIGGER_PATTERNS,
)
from ..git_diff import (
    _is_comment_or_blank,
    _read_lines,
    get_added_lines,
)
from ..models import Finding


def _extract_init_range(lines: list[str]) -> tuple[int, int] | None:
    class_line = None
    init_start = None
    for idx, line in enumerate(lines, start=1):
        if class_line is None and re.match('^class\\s+DanmuApp\\b', line):
            class_line = idx
            continue
        if class_line is not None and init_start is None and re.match('^\\s{4}def __init__\\b', line):
            init_start = idx
            continue
        if init_start is not None and idx > init_start and re.match('^\\s{4}def\\s+\\w+\\b', line):
            return (init_start, idx - 1)
    if init_start is None:
        return None
    return (init_start, len(lines))

def _documented_runtime_fields(doc_path: Path) -> set[str]:
    text = doc_path.read_text(encoding='utf-8')
    fields = set()
    for token in re.findall('`([A-Za-z_][A-Za-z0-9_]*)`', text):
        fields.add(token)
    return fields

def _extract_added_runtime_fields(repo_root: Path, changed: dict[Path, str]) -> list[tuple[int, str]]:
    if MAIN_PATH not in changed:
        return []
    lines = _read_lines(repo_root / MAIN_PATH)
    init_range = _extract_init_range(lines)
    if init_range is None:
        return []
    start, end = init_range
    fields: list[tuple[int, str]] = []
    for line_no, line in get_added_lines(repo_root, MAIN_PATH, changed[MAIN_PATH]):
        if line_no < start or line_no > end:
            continue
        if _is_comment_or_blank(line):
            continue
        match = re.search('self\\.([A-Za-z_][A-Za-z0-9_]*)\\s*(?::[^=]+)?=', line)
        if not match:
            continue
        field = match.group(1)
        if field in RUNTIME_FIELD_EXCLUDE:
            continue
        fields.append((line_no, field))
    return fields

def check_thread_trigger_docs(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    doc_changed = PIPELINE_DOC in changed
    for rel_path, status in changed.items():
        if rel_path.suffix != '.py':
            continue
        for line_no, line in get_added_lines(repo_root, rel_path, status):
            if _is_comment_or_blank(line):
                continue
            for pattern, label in THREAD_TRIGGER_PATTERNS:
                if re.search(pattern, line):
                    if doc_changed:
                        break
                    findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 4.1', path=str(rel_path), line=line_no, message=f'发现新增或修改的调度点 `{label}`，但 `docs/main-pipeline-sequence.md` 未同步更新'))
                    break
    return findings

def check_runtime_state_doc(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    documented = _documented_runtime_fields(repo_root / RUNTIME_STATE_DOC)
    for line_no, field in _extract_added_runtime_fields(repo_root, changed):
        if field in documented:
            continue
        findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 3.1', path=str(MAIN_PATH), line=line_no, message=f'新增运行态字段 `{field}` 未登记到 `docs/runtime-state-map.md`'))
    return findings

def check_legacy_runtime_state_writes(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH not in changed:
        return findings
    for line_no, line in get_added_lines(repo_root, MAIN_PATH, changed[MAIN_PATH]):
        if _is_comment_or_blank(line):
            continue
        for pattern, message in LEGACY_RUNTIME_ASSIGNMENT_PATTERNS:
            if re.search(pattern, line):
                findings.append(Finding(severity='error', rule='runtime-ownership-plan.md / phase3-a', path=str(MAIN_PATH), line=line_no, message=message))
                break
    return findings
