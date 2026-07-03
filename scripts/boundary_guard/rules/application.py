"""application/ 收口层边界规则。

检查项：
    - check_application_layer_private_reads
        ``app/application/*.py`` 新增行禁止经 ``getattr(app, "_...")``、
        ``app.__dict__.get("_...")`` 或 ``_safe_app_attr(..., "_...")`` 直读
        DanmuApp 私有字段；须经 DanmuApp 公开 façade。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..constants import APPLICATION_DIR, APPLICATION_PRIVATE_READ_PATTERNS
from ..git_diff import _is_comment_or_blank, get_added_lines
from ..models import Finding


def check_application_layer_private_reads(
    repo_root: Path, changed: dict[Path, str]
) -> list[Finding]:
    findings: list[Finding] = []
    app_dir = repo_root / APPLICATION_DIR
    if not app_dir.is_dir():
        return findings
    targets = sorted(
        path.relative_to(repo_root)
        for path in app_dir.glob("*.py")
        if path.relative_to(repo_root) in changed
    )
    for rel_path in targets:
        for line_no, line in get_added_lines(repo_root, rel_path, changed[rel_path]):
            if _is_comment_or_blank(line):
                continue
            for pattern, message in APPLICATION_PRIVATE_READ_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        Finding(
                            severity="error",
                            rule="application-layer-facade / phase4",
                            path=str(rel_path),
                            line=line_no,
                            message=message,
                        )
                    )
                    break
    return findings
