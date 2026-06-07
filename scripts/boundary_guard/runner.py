"""runner — 扫描流程编排。

``run_boundary_guard(repo_root)`` 主流程：
    1) git_diff.get_changed_files(repo_root)   收集变更文件 (Path → status)
    2) 逐个调 rules/*.check_*(repo_root, changed)  返回 list[Finding]
    3) 聚合所有 findings 返回

设计：所有规则**独立**接收 ``(repo_root, changed)``，不互相依赖；新增规则
只需在 ``rules/`` 下加一个 check_* 函数并在这里 import + 调用。
"""

from __future__ import annotations

from pathlib import Path

from .git_diff import get_changed_files
from .models import Finding
from .rules.baseline import check_final_architecture_baseline
from .rules.config import (
    check_config_conn_spread,
    check_config_service_delegation,
    check_default_model_selection_guard,
)
from .rules.diagnostics import check_diagnostic_snapshot_boundary
from .rules.pipeline import check_generation_pipeline_projection
from .rules.request import (
    check_request_metadata_boundary,
    check_request_scheduler_ownership,
    check_request_service_boundaries,
    check_request_timing_history_ownership,
    check_request_timing_ownership,
)
from .rules.runtime import (
    check_legacy_runtime_state_writes,
    check_runtime_state_doc,
    check_thread_trigger_docs,
)
from .rules.status import check_status_snapshot_builder_delegation
from .rules.web import (
    check_status_route_boundary,
    check_web_diagnostics_route_boundary,
    check_web_diagnostics_ui_boundary,
    check_web_private_access,
    check_web_status_composition,
)


def run_boundary_guard(repo_root: Path) -> list[Finding]:
    changed = get_changed_files(repo_root)
    findings: list[Finding] = []
    findings.extend(check_web_private_access(repo_root, changed))
    findings.extend(check_config_conn_spread(repo_root, changed))
    findings.extend(check_thread_trigger_docs(repo_root, changed))
    findings.extend(check_runtime_state_doc(repo_root, changed))
    findings.extend(check_legacy_runtime_state_writes(repo_root, changed))
    findings.extend(check_request_scheduler_ownership(repo_root, changed))
    findings.extend(check_request_timing_ownership(repo_root, changed))
    findings.extend(check_request_timing_history_ownership(repo_root, changed))
    findings.extend(check_web_status_composition(repo_root, changed))
    findings.extend(check_status_snapshot_builder_delegation(repo_root, changed))
    findings.extend(check_config_service_delegation(repo_root, changed))
    findings.extend(check_default_model_selection_guard(repo_root, changed))
    findings.extend(check_generation_pipeline_projection(repo_root, changed))
    findings.extend(check_request_metadata_boundary(repo_root, changed))
    findings.extend(check_request_service_boundaries(repo_root, changed))
    findings.extend(check_diagnostic_snapshot_boundary(repo_root, changed))
    findings.extend(check_web_diagnostics_route_boundary(repo_root, changed))
    findings.extend(check_status_route_boundary(repo_root, changed))
    findings.extend(check_web_diagnostics_ui_boundary(repo_root, changed))
    findings.extend(check_final_architecture_baseline(repo_root))
    findings.sort(key=lambda item: (item.path, item.line, item.rule, item.message))
    return findings
