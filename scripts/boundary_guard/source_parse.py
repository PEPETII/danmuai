"""源码轻量解析：按缩进抽取函数体、过滤空行与注释。

仅做正则 + 缩进判断，不引入 ast 依赖（启动开销小，CI 友好）。规则模块若需要
"函数体匹配某模式"，用 ``_extract_function_body`` + ``_meaningful_body_lines``
拿到可比较的代码行。
"""

from __future__ import annotations

import re


def _extract_function_body(lines: list[str], func_name: str) -> list[str]:
    start = None
    indent = None
    for idx, line in enumerate(lines):
        match = re.match('^(\\s*)def\\s+' + re.escape(func_name) + '\\b', line)
        if match:
            start = idx + 1
            indent = len(match.group(1))
            break
    if start is None or indent is None:
        return []
    body: list[str] = []
    for line in lines[start:]:
        if line.strip() and len(line) - len(line.lstrip(' ')) <= indent and re.match('^\\s*def\\s+\\w+\\b', line):
            break
        body.append(line)
    return body

def _meaningful_body_lines(body: list[str]) -> list[str]:
    lines: list[str] = []
    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped in ('"""', "'''"):
            continue
        lines.append(stripped)
    return lines
