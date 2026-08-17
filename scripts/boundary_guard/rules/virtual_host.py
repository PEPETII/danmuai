"""virtual_host/ 模块边界规则。"""

from __future__ import annotations

import re
from pathlib import Path

from ..constants import VIRTUAL_HOST_DIR, VIRTUAL_HOST_RUNTIME_PATH
from ..git_diff import _is_comment_or_blank, get_added_lines
from ..models import Finding


def check_virtual_host_module_boundaries(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    vh_dir = repo_root / VIRTUAL_HOST_DIR
    if not vh_dir.is_dir():
        return findings

    qt_pattern = re.compile(r"\bfrom PyQt6\b|\bimport PyQt6\b")
    for path in sorted(vh_dir.glob("*.py")):
        rel_path = path.relative_to(repo_root)
        if rel_path == VIRTUAL_HOST_RUNTIME_PATH:
            continue
        if rel_path not in changed:
            continue
        for line_no, line in get_added_lines(repo_root, rel_path, changed[rel_path]):
            if _is_comment_or_blank(line):
                continue
            if qt_pattern.search(line):
                findings.append(
                    Finding(
                        severity="error",
                        rule="virtual-host-module-boundary",
                        path=str(rel_path),
                        line=line_no,
                        message="virtual_host modules except runtime_service.py must not import PyQt6",
                    )
                )

    if VIRTUAL_HOST_RUNTIME_PATH in changed:
        added_lines = [
            line
            for _, line in get_added_lines(
                repo_root,
                VIRTUAL_HOST_RUNTIME_PATH,
                changed[VIRTUAL_HOST_RUNTIME_PATH],
            )
            if not _is_comment_or_blank(line)
        ]
        added_text = "\n".join(added_lines)
        if "on_danmu_batch_created" in added_text and "start_turn" in added_text:
            for line_no, line in get_added_lines(
                repo_root,
                VIRTUAL_HOST_RUNTIME_PATH,
                changed[VIRTUAL_HOST_RUNTIME_PATH],
            ):
                if _is_comment_or_blank(line):
                    continue
                if "start_turn" in line and "_start_chat_request" not in line:
                    findings.append(
                        Finding(
                            severity="error",
                            rule="virtual-host-response-scheduler",
                            path=str(VIRTUAL_HOST_RUNTIME_PATH),
                            line=line_no,
                            message="on_danmu_batch_created must not call session.start_turn directly; use VirtualHostResponseScheduler",
                        )
                    )
                    break
    return findings
