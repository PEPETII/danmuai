"""请求调度 / timing / metadata 边界规则。

检查项：
    - check_request_scheduler_ownership
        ``app.application.request_scheduler`` 是 API 调度门控，所有触发点必须
        经此模块；其他文件出现 ``min_api_interval`` / ``ai_in_flight`` 等 token
        视为绕过（Phase 4-A）。
    - check_request_timing_ownership / check_request_timing_history_ownership
        RTT 历史与 ``_started_at_by_id`` 仅 ``RequestTimingService`` 可写；
        Web/API 通过 diagnostic snapshot 读取。
    - check_request_metadata_boundary
        ``RequestMetadataState`` 是 HTTP 侧请求元数据入口；非 metadata 状态
        文件禁止出现 ``request_metadata_*`` 字段（避免越界）。
    - check_request_service_boundaries
        ``app.application`` 子模块之间的 import 边带关系；某些模块不得
        直接依赖 ``web_console`` / ``main``（防止循环 import）。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..constants import (
    LAST_API_TRIGGER_AT_WRITE_MESSAGE,
    LAST_API_TRIGGER_AT_WRITE_PATTERN,
    MAIN_PATH,
    REQUEST_METADATA_FORBIDDEN_CALLS,
    REQUEST_METADATA_FORBIDDEN_TOKENS,
    REQUEST_METADATA_STATE_PATH,
    REQUEST_SCHEDULER_FORBIDDEN_CALLS,
    REQUEST_SCHEDULER_FORBIDDEN_TOKENS,
    REQUEST_SCHEDULER_PATH,
    REQUEST_STARTED_AT_BY_ID_WRITE_MESSAGE,
    REQUEST_STARTED_AT_BY_ID_WRITE_PATTERN,
    REQUEST_TIMING_SERVICE_FORBIDDEN_CALLS,
    REQUEST_TIMING_SERVICE_FORBIDDEN_TOKENS,
    REQUEST_TIMING_SERVICE_PATH,
    RTT_HISTORY_WRITE_MESSAGE,
    RTT_HISTORY_WRITE_PATTERN,
    STATE_OBJECT_FORBIDDEN_FIELDS,
    STATS_STATE_PATH,
    WEB_RUNTIME_STATE_PATH,
)
from ..git_diff import (
    _is_comment_or_blank,
    get_added_lines,
)
from ..models import Finding


def check_request_scheduler_ownership(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH not in changed:
        return findings
    for line_no, line in get_added_lines(repo_root, MAIN_PATH, changed[MAIN_PATH]):
        if _is_comment_or_blank(line):
            continue
        if LAST_API_TRIGGER_AT_WRITE_PATTERN.search(line):
            findings.append(Finding(severity='error', rule='request-scheduler-plan.md / phase4-d', path=str(MAIN_PATH), line=line_no, message=LAST_API_TRIGGER_AT_WRITE_MESSAGE))
    return findings

def check_request_timing_ownership(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH not in changed:
        return findings
    for line_no, line in get_added_lines(repo_root, MAIN_PATH, changed[MAIN_PATH]):
        if _is_comment_or_blank(line):
            continue
        if REQUEST_STARTED_AT_BY_ID_WRITE_PATTERN.search(line):
            findings.append(Finding(severity='error', rule='request-timing-service-plan.md / phase4-e', path=str(MAIN_PATH), line=line_no, message=REQUEST_STARTED_AT_BY_ID_WRITE_MESSAGE))
    return findings

def check_request_timing_history_ownership(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH not in changed:
        return findings
    for line_no, line in get_added_lines(repo_root, MAIN_PATH, changed[MAIN_PATH]):
        if _is_comment_or_blank(line):
            continue
        if RTT_HISTORY_WRITE_PATTERN.search(line):
            findings.append(Finding(severity='error', rule='request-timing-service-plan.md / phase4-f', path=str(MAIN_PATH), line=line_no, message=RTT_HISTORY_WRITE_MESSAGE))
    return findings

def check_request_metadata_boundary(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if REQUEST_METADATA_STATE_PATH in changed:
        for line_no, line in get_added_lines(repo_root, REQUEST_METADATA_STATE_PATH, changed[REQUEST_METADATA_STATE_PATH]):
            if _is_comment_or_blank(line):
                continue
            for pattern, message in REQUEST_METADATA_FORBIDDEN_TOKENS:
                if re.search(pattern, line):
                    findings.append(Finding(severity='error', rule='generation-pipeline-state-plan.md / phase4-a', path=str(REQUEST_METADATA_STATE_PATH), line=line_no, message=message))
                    break
            else:
                for token in REQUEST_METADATA_FORBIDDEN_CALLS:
                    if token in line:
                        findings.append(Finding(severity='error', rule='generation-pipeline-state-plan.md / phase4-a', path=str(REQUEST_METADATA_STATE_PATH), line=line_no, message='RequestMetadataState must not call main pipeline scheduling or timing functions'))
                        break
    for path, state_name in ((STATS_STATE_PATH, 'StatsState'), (WEB_RUNTIME_STATE_PATH, 'WebRuntimeState')):
        if path not in changed:
            continue
        for line_no, line in get_added_lines(repo_root, path, changed[path]):
            if _is_comment_or_blank(line):
                continue
            for field in STATE_OBJECT_FORBIDDEN_FIELDS:
                if field in line:
                    findings.append(Finding(severity='error', rule='runtime-ownership-plan.md / phase4-a', path=str(path), line=line_no, message=f'Phase 4-A forbids moving `{field}` into {state_name}'))
                    break
    return findings

def check_request_service_boundaries(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if REQUEST_SCHEDULER_PATH in changed:
        for line_no, line in get_added_lines(repo_root, REQUEST_SCHEDULER_PATH, changed[REQUEST_SCHEDULER_PATH]):
            if _is_comment_or_blank(line):
                continue
            for pattern, message in REQUEST_SCHEDULER_FORBIDDEN_TOKENS:
                if re.search(pattern, line):
                    findings.append(Finding(severity='error', rule='request-scheduler-plan.md / phase4-b', path=str(REQUEST_SCHEDULER_PATH), line=line_no, message=message))
                    break
            else:
                for token in REQUEST_SCHEDULER_FORBIDDEN_CALLS:
                    if token in line:
                        findings.append(Finding(severity='error', rule='request-scheduler-plan.md / phase4-b', path=str(REQUEST_SCHEDULER_PATH), line=line_no, message='RequestScheduler must not call trigger, reply handling, or queue consumption functions'))
                        break
    if REQUEST_TIMING_SERVICE_PATH in changed:
        for line_no, line in get_added_lines(repo_root, REQUEST_TIMING_SERVICE_PATH, changed[REQUEST_TIMING_SERVICE_PATH]):
            if _is_comment_or_blank(line):
                continue
            for pattern, message in REQUEST_TIMING_SERVICE_FORBIDDEN_TOKENS:
                if re.search(pattern, line):
                    findings.append(Finding(severity='error', rule='request-timing-service-plan.md / phase4-b', path=str(REQUEST_TIMING_SERVICE_PATH), line=line_no, message=message))
                    break
            else:
                for token in REQUEST_TIMING_SERVICE_FORBIDDEN_CALLS:
                    if token in line:
                        findings.append(Finding(severity='error', rule='request-timing-service-plan.md / phase4-b', path=str(REQUEST_TIMING_SERVICE_PATH), line=line_no, message='RequestTimingService must not call trigger or queue consumption functions'))
                        break
    return findings
