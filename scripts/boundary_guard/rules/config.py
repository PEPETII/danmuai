"""配置 / 模型选择连通性边界规则。

检查项：
    - check_config_service_delegation
        路由（``app/web_console.py``）写配置必须经 ``ConfigService``，禁止
        直接调 ``ConfigStore``。
    - check_config_conn_spread
        ``app/`` 内不允许散落 ``requests.post`` / ``httpx.post`` 等原始 HTTP
        调用（仅 ``app/ai_client.py``、``app/api_probe.py``、``app/live_freshness.py``
        白名单）。
    - check_default_model_selection_guard
        ``WEB_CONSOLE_PATH`` 的 GET /api/config/defaults 返回必须来自
        ``CONFIG_DEFAULTS``，禁止就地硬编码；保证「恢复默认」行为可追溯。
"""

from __future__ import annotations

from pathlib import Path

from ..constants import (
    CONFIG_CONN_PATTERNS,
    CONFIG_CONN_WHITELIST,
    CUSTOM_MODELS_PATH,
    MAIN_PATH,
    WEB_CONSOLE_PATH,
)
from ..git_diff import (
    _is_comment_or_blank,
    _read_lines,
    get_added_lines,
)
from ..models import Finding
from ..source_parse import _extract_function_body, _meaningful_body_lines


def check_config_conn_spread(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    for rel_path, status in changed.items():
        if rel_path.suffix != '.py' or (not rel_path.parts or rel_path.parts[0] != 'app'):
            continue
        if rel_path in CONFIG_CONN_WHITELIST:
            continue
        for line_no, line in get_added_lines(repo_root, rel_path, status):
            if _is_comment_or_blank(line):
                continue
            if any((pattern in line for pattern in CONFIG_CONN_PATTERNS)):
                findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 6.2', path=str(rel_path), line=line_no, message='禁止在新的模块中继续扩散 config.conn / self.config.conn'))
    return findings

def check_config_service_delegation(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH in changed:
        lines = _read_lines(repo_root / MAIN_PATH)
        body = _extract_function_body(lines, 'apply_web_config_payload')
        meaningful = _meaningful_body_lines(body)
        body_text = '\n'.join(meaningful)
        if not body:
            findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 2.2 / phase2.5', path=str(MAIN_PATH), line=0, message='`DanmuApp.apply_web_config_payload()` 必须保留并继续委托 `ConfigService`'))
        else:
            if 'apply_web_config_patch(' not in body_text and 'ConfigService(' not in body_text:
                findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 2.2 / phase2.5', path=str(MAIN_PATH), line=0, message='`DanmuApp.apply_web_config_payload()` 必须继续委托 `ConfigService` / `apply_web_config_patch()`'))
            forbidden = ('set_batch(', '.set(', 'set_default_model_id(', 'set_custom_models(', 'config_changed.emit(')
            if any((token in body_text for token in forbidden)):
                findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 2.2 / phase2.5', path=str(MAIN_PATH), line=0, message='`DanmuApp.apply_web_config_payload()` 不允许绕过 `ConfigService` 直接改配置或发信号'))
    if WEB_CONSOLE_PATH in changed:
        lines = _read_lines(repo_root / WEB_CONSOLE_PATH)
        body = _extract_function_body(lines, 'apply_config_patch')
        if body:
            meaningful = _meaningful_body_lines(body)
            body_text = '\n'.join(meaningful)
            if 'apply_web_config_patch(' not in body_text and '.apply_web_config_payload(' not in body_text:
                findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 2.2 / phase2.5', path=str(WEB_CONSOLE_PATH), line=0, message='`app/web_console.py::apply_config_patch()` 若保留，只能作为兼容包装委托 `ConfigService` 或 `DanmuApp.apply_web_config_payload()`'))
            forbidden = ('set_batch(', 'set_default_model_id(', 'set_custom_models(', 'config_changed.emit(')
            if any((token in body_text for token in forbidden)):
                findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 2.2 / phase2.5', path=str(WEB_CONSOLE_PATH), line=0, message='`app/web_console.py::apply_config_patch()` 不允许重新回退到直接拼接配置 patch 逻辑'))
    return findings

def check_default_model_selection_guard(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if CUSTOM_MODELS_PATH not in changed:
        return findings
    lines = _read_lines(repo_root / CUSTOM_MODELS_PATH)
    for func_name in ('delete_custom_model', 'set_default_custom_model'):
        body = _extract_function_body(lines, func_name)
        if not body:
            continue
        body_text = '\n'.join(_meaningful_body_lines(body))
        if 'set_default_model_selection(' not in body_text:
            findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 2.2 / phase2.5', path=str(CUSTOM_MODELS_PATH), line=0, message=f'`{func_name}()` 必须继续复用 `set_default_model_selection()` 维护 `model/default_model_id` 兼容写规则'))
        forbidden = ('set_default_model_id(', '.set("model"', ".set('model'")
        if any((token in body_text for token in forbidden)):
            findings.append(Finding(severity='error', rule='phase1-boundary-rules.md 2.2 / phase2.5', path=str(CUSTOM_MODELS_PATH), line=0, message='`app/web_api/custom_models.py` 不允许重新手写不一致的 `model/default_model_id` 默认模型回退逻辑'))
    return findings
