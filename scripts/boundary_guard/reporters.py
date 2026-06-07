"""报告器：把 findings 列表渲染为人/机两可读的纯文本。

输出格式（CI grep 友好）：
    无 findings: ``Boundary Guard: PASS``
    有 findings: ``Boundary Guard: FAIL`` 标题 + 每条 ``- [ERROR] path:line | rule | message``

不引入 rich / colorama：CI 默认 windows-latest（无 ANSI），按本仓库 AGENTS.md
"Plain text, no color" 约定。
"""

from __future__ import annotations

from .models import Finding


def format_findings(findings: list[Finding]) -> str:
    if not findings:
        return 'Boundary Guard: PASS'
    lines = ['Boundary Guard: FAIL']
    for finding in findings:
        location = f'{finding.path}:{finding.line}' if finding.line > 0 else finding.path
        lines.append(f'- [{finding.severity.upper()}] {location} | {finding.rule} | {finding.message}')
    return '\n'.join(lines)
