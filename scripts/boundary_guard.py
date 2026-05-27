from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

RUNTIME_STATE_DOC = Path("docs/runtime-state-map.md")
PIPELINE_DOC = Path("docs/main-pipeline-sequence.md")
FINAL_ARCH_BASELINE_DOC = Path("docs/final-architecture-baseline.md")
WEB_CONSOLE_PATH = Path("app/web_console.py")
WEB_API_DIR = Path("app/web_api")
WEB_STATIC_DIR = Path("web/static")
CUSTOM_MODELS_PATH = Path("app/web_api/custom_models.py")
MAIN_PATH = Path("main.py")
RUNTIME_STATE_PATH = Path("app/application/runtime_state.py")
GENERATION_PIPELINE_STATE_PATH = Path("app/application/generation_pipeline_state.py")
REQUEST_METADATA_STATE_PATH = Path("app/application/request_metadata_state.py")
STATS_STATE_PATH = Path("app/application/stats_state.py")
WEB_RUNTIME_STATE_PATH = Path("app/application/web_runtime_state.py")
REQUEST_SCHEDULER_PATH = Path("app/application/request_scheduler.py")
REQUEST_TIMING_SERVICE_PATH = Path("app/application/request_timing_service.py")
DIAGNOSTIC_SNAPSHOT_PATH = Path("app/application/diagnostic_snapshot.py")

WEB_PRIVATE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\b_rtt_history\b",
        "Phase 4-F forbids Web/API direct reads of `_rtt_history`; add a diagnostic snapshot first if exposure is ever needed",
    ),
    (
        r"\b_last_api_trigger_at\b",
        "Phase 4-A 禁止 Web/API 直接读取 `_last_api_trigger_at`；若未来需要暴露，必须先设计 diagnostic snapshot",
    ),
    (
        r"\b_request_started_at_by_id\b",
        "Phase 4-A 禁止 Web/API 直接读取 `_request_started_at_by_id`；若未来需要暴露，必须先设计 diagnostic snapshot",
    ),
    (r"\bdanmu_app\._", "禁止 Web/API 直接访问 danmu_app 私有字段"),
    (r"\bapp\._", "禁止 Web/API 直接访问 app 私有字段"),
    (r"\bdanmu_app\.web_runtime_state\b", "禁止 Web/API 直接访问 danmu_app.web_runtime_state"),
    (r"\bapp\.web_runtime_state\b", "禁止 Web/API 直接访问 app.web_runtime_state"),
    (r"\bcached_danmu_lines\b", "禁止 Web/API 绕过 build_status_snapshot() 直接读取展示缓存"),
    (r"\bcached_layout_mode\b", "禁止 Web/API 绕过 build_status_snapshot() 直接读取展示缓存"),
    (r"\bai_worker\._", "禁止 Web/API 直接访问 ai_worker 私有实现"),
    (r"\b_mic_service\b", "禁止 Web/API 直接访问 _mic_service"),
    (r"\b_set_error_status_safe\b", "禁止 Web/API 直接调用 _set_error_status_safe"),
    (r"\b_build_live_status_snapshot\b", "禁止 Web/API 直接调用 _build_live_status_snapshot"),
    (r"\b_visible_display_count\b", "禁止 Web/API 直接调用 _visible_display_count"),
    (r"\b_resolve_request_credentials\b", "禁止 Web/API 直接调用 _resolve_request_credentials"),
)

CONFIG_CONN_PATTERNS: tuple[str, ...] = (
    "config.conn",
    "self.config.conn",
)

CONFIG_CONN_WHITELIST = {
    Path("app/config_store.py"),
    Path("app/history.py"),
    Path("app/history_writer.py"),
    Path("app/session_run_log.py"),
    Path("app/templates.py"),
    Path("app/danmu_engine.py"),
}

THREAD_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bQTimer\(", "QTimer"),
    (r"\bQThreadPool\b", "QThreadPool"),
    (r"\bglobalInstance\(\)\.start\b", "QThreadPool.globalInstance().start"),
    (r"\bthreading\.Thread\b", "threading.Thread"),
    (r"\basyncio\.create_task\b", "asyncio.create_task"),
)

RUNTIME_FIELD_EXCLUDE = {
    "web_launch_mode",
    "config",
    "logger",
    "personae",
    "templates",
    "history",
    "history_writer",
    "capturer",
    "engine",
    "overlay",
    "tray",
    "hotkey",
    "ai_worker",
}

LEGACY_RUNTIME_ASSIGNMENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\bself\._web_error_message\s*(?:\+?=|-=)",
        "Web 错误状态已迁入 WebRuntimeState，禁止在 DanmuApp 中重新直接写 `_web_error_message`",
    ),
    (
        r"\bself\._web_error_is_error\s*(?:\+?=|-=)",
        "Web 错误状态已迁入 WebRuntimeState，禁止在 DanmuApp 中重新直接写 `_web_error_is_error`",
    ),
    (
        r"\bself\.danmu_count\s*(?:\+?=|-=)",
        "统计字段已迁入 StatsState，禁止在 DanmuApp 中重新直接写 `danmu_count`",
    ),
    (
        r"\bself\._total_input_tokens\s*(?:\+?=|-=)",
        "统计字段已迁入 StatsState，禁止在 DanmuApp 中重新直接写 `_total_input_tokens`",
    ),
    (
        r"\bself\._total_output_tokens\s*(?:\+?=|-=)",
        "统计字段已迁入 StatsState，禁止在 DanmuApp 中重新直接写 `_total_output_tokens`",
    ),
    (
        r"\bself\._start_time\s*(?:\+?=|-=)",
        "统计字段已迁入 StatsState，禁止在 DanmuApp 中重新直接写 `_start_time`",
    ),
    (
        r"\bself\._cached_danmu_lines\s*(?:\+?=|-=)",
        "展示缓存已迁入 WebRuntimeState，禁止在 DanmuApp 中重新直接写 `_cached_danmu_lines`",
    ),
    (
        r"\bself\._cached_layout_mode\s*(?:\+?=|-=)",
        "展示缓存已迁入 WebRuntimeState，禁止在 DanmuApp 中重新直接写 `_cached_layout_mode`",
    ),
)

GENERATION_PIPELINE_CANDIDATE_FIELDS: tuple[str, ...] = (
    "_active_scene_probe_size",
    "_scene_generation_bumped_at",
    "_last_activity_collect_at",
    "_latest_displayed_round",
    "_latest_requested_screenshot_id",
    "_latest_queued_screenshot_id",
    "_latest_displayed_screenshot_id",
    "_last_api_trigger_at",
    "_request_started_at_by_id",
)

GENERATION_PIPELINE_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bQTimer\b", "GenerationPipelineState must not reference QTimer"),
    (r"\bQThreadPool\b", "GenerationPipelineState must not reference QThreadPool"),
    (r"\bQPixmap\b", "GenerationPipelineState must not reference QPixmap"),
    (r"\bai_in_flight\b", "Phase 3-C forbids moving ai_in_flight into GenerationPipelineState"),
    (r"\breply_buffer\b", "Phase 3-C forbids moving reply_buffer into GenerationPipelineState"),
    (r"\bdanmu_queue\b", "Phase 3-C forbids moving danmu_queue into GenerationPipelineState"),
    (r"\b_scene_generation\b", "Phase 3-C forbids moving _scene_generation into GenerationPipelineState"),
    (r"\b_pending_request_meta\b", "Phase 3-C forbids moving _pending_request_meta into GenerationPipelineState"),
    (r"\b_inflight_screenshot_id\b", "Phase 3-C forbids moving _inflight_screenshot_id into GenerationPipelineState"),
    (r"\b_latest_screenshot\b", "Phase 3-C forbids moving _latest_screenshot into GenerationPipelineState"),
)

GENERATION_PIPELINE_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_on_screenshot_timer(",
    "_check_rhythm_trigger(",
    "_trigger_api_call(",
    "_consume_reply_queue(",
    "_enqueue_reply_batch(",
    "_on_ai_reply(",
    "_on_ai_error(",
)

REQUEST_METADATA_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (
        r"\b_last_api_trigger_at\b",
        "Phase 4-A forbids moving _last_api_trigger_at ownership into RequestMetadataState",
    ),
    (
        r"\b_request_started_at_by_id\b",
        "Phase 4-A forbids moving _request_started_at_by_id ownership into RequestMetadataState",
    ),
    (r"\bQTimer\b", "RequestMetadataState must not reference QTimer"),
    (r"\bQThreadPool\b", "RequestMetadataState must not reference QThreadPool"),
    (r"\bQPixmap\b", "RequestMetadataState must not reference QPixmap"),
    (r"\bai_in_flight\b", "RequestMetadataState must not hold ai_in_flight"),
    (r"\breply_buffer\b", "RequestMetadataState must not hold reply_buffer"),
    (r"\bdanmu_queue\b", "RequestMetadataState must not hold danmu_queue"),
    (r"\b_scene_generation\b", "RequestMetadataState must not hold _scene_generation"),
    (r"\b_pending_request_meta\b", "RequestMetadataState must not hold _pending_request_meta"),
)

REQUEST_METADATA_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_api_schedule_block_reason(",
    "_consume_request_timing(",
    "_trigger_api_call(",
    "_on_ai_reply(",
    "_on_ai_error(",
)

STATE_OBJECT_FORBIDDEN_FIELDS: tuple[str, ...] = (
    "_last_api_trigger_at",
    "_request_started_at_by_id",
    "_rtt_history",
)

REQUEST_SCHEDULER_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bPyQt6\b", "RequestScheduler must not import Qt modules"),
    (r"\bQTimer\b", "RequestScheduler must not reference QTimer"),
    (r"\bQThreadPool\b", "RequestScheduler must not reference QThreadPool"),
    (r"\bQPixmap\b", "RequestScheduler must not reference QPixmap"),
    (r"\breply_buffer\b", "RequestScheduler must not hold reply_buffer"),
    (r"\bdanmu_queue\b", "RequestScheduler must not hold danmu_queue"),
    (r"\b_scene_generation\b", "RequestScheduler must not hold _scene_generation"),
    (r"\b_pending_request_meta\b", "RequestScheduler must not hold _pending_request_meta"),
    (r"\bself\.app\s*=", "RequestScheduler must not become a God Object by storing app"),
    (r"\bself\._app\s*=", "RequestScheduler must not become a God Object by storing app"),
    (r"\bself\.danmu_app\s*=", "RequestScheduler must not become a God Object by storing app"),
    (r"\bapp\.web_console\b|\bfrom app\.web_console\b", "RequestScheduler must not import web_console"),
    (r"\bapp\.web_api\b|\bfrom app\.web_api\b", "RequestScheduler must not import web_api"),
    (r"\bapp\.overlay\b|\bfrom app\.overlay\b", "RequestScheduler must not import overlay"),
    (r"\bapp\.danmu_engine\b|\bfrom app\.danmu_engine\b", "RequestScheduler must not import danmu_engine"),
)

REQUEST_SCHEDULER_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_trigger_api_call(",
    "_on_ai_reply(",
    "_on_ai_error(",
    "_consume_reply_queue(",
)

REQUEST_TIMING_SERVICE_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bPyQt6\b", "RequestTimingService must not import Qt modules"),
    (r"\bQTimer\b", "RequestTimingService must not reference QTimer"),
    (r"\bQThreadPool\b", "RequestTimingService must not reference QThreadPool"),
    (r"\bQPixmap\b", "RequestTimingService must not reference QPixmap"),
    (r"\breply_buffer\b", "RequestTimingService must not hold reply_buffer"),
    (r"\bdanmu_queue\b", "RequestTimingService must not hold danmu_queue"),
    (r"\boverlay\b", "RequestTimingService must not handle Overlay"),
    (r"\bDanmuEngine\b", "RequestTimingService must not handle DanmuEngine"),
    (r"\bself\.app\s*=", "RequestTimingService must not become a God Object by storing app"),
    (r"\bself\._app\s*=", "RequestTimingService must not become a God Object by storing app"),
    (r"\bself\.danmu_app\s*=", "RequestTimingService must not become a God Object by storing app"),
    (r"\bapp\.web_console\b|\bfrom app\.web_console\b", "RequestTimingService must not import web_console"),
    (r"\bapp\.web_api\b|\bfrom app\.web_api\b", "RequestTimingService must not import web_api"),
    (r"\bapp\.overlay\b|\bfrom app\.overlay\b", "RequestTimingService must not import overlay"),
    (r"\bapp\.danmu_engine\b|\bfrom app\.danmu_engine\b", "RequestTimingService must not import danmu_engine"),
)

REQUEST_TIMING_SERVICE_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_trigger_api_call(",
    "_consume_reply_queue(",
)

DIAGNOSTIC_SNAPSHOT_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bPyQt6\b", "DiagnosticSnapshot must not import Qt modules"),
    (r"\bQTimer\b", "DiagnosticSnapshot must not reference QTimer"),
    (r"\bQThreadPool\b", "DiagnosticSnapshot must not reference QThreadPool"),
    (r"\bQPixmap\b", "DiagnosticSnapshot must not reference QPixmap"),
    (r"\bapp\.overlay\b|\bfrom app\.overlay\b", "DiagnosticSnapshot must not import overlay"),
    (
        r"\bapp\.danmu_engine\b|\bfrom app\.danmu_engine\b",
        "DiagnosticSnapshot must not import danmu_engine",
    ),
)

DIAGNOSTIC_SNAPSHOT_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_trigger_api_call(",
    "_on_ai_reply(",
    "_on_ai_error(",
    "_consume_reply_queue(",
)

DIAGNOSTICS_ROUTE_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bPyQt6\b", "Diagnostics route must not import Qt modules"),
    (r"\bapp\.overlay\b|\bfrom app\.overlay\b", "Diagnostics route must not import overlay"),
    (
        r"\bapp\.danmu_engine\b|\bfrom app\.danmu_engine\b",
        "Diagnostics route must not import danmu_engine",
    ),
)

DIAGNOSTICS_ROUTE_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_trigger_api_call(",
    "_on_ai_reply(",
    "_on_ai_error(",
    "_consume_reply_queue(",
)

WEB_DIAGNOSTICS_UI_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b_last_api_trigger_at\b", "Diagnostics UI must not reference `_last_api_trigger_at` directly"),
    (
        r"\b_request_started_at_by_id\b",
        "Diagnostics UI must not reference `_request_started_at_by_id` directly",
    ),
    (r"\b_rtt_history\b", "Diagnostics UI must not reference `_rtt_history` directly"),
    (r"\b_scene_generation\b", "Diagnostics UI must not reference `_scene_generation` directly"),
    (r"\breply_buffer\b", "Diagnostics UI must not reference `reply_buffer` directly"),
    (r"\bdanmu_queue\b", "Diagnostics UI must not reference `danmu_queue` directly"),
)

LAST_API_TRIGGER_AT_WRITE_PATTERN = re.compile(
    r"\bself\._last_api_trigger_at\s*(?::[^=]+)?(?:\+?=|-=)"
)
LAST_API_TRIGGER_AT_WRITE_MESSAGE = (
    "Phase 4-D has moved `_last_api_trigger_at` into RequestScheduler; "
    "DanmuApp may only keep a compatibility facade that delegates to RequestScheduler"
)
REQUEST_STARTED_AT_BY_ID_WRITE_PATTERN = re.compile(
    r"\bself\._request_started_at_by_id\s*(?::[^=]+)?(?:\+?=|-=)|\bself\._request_started_at_by_id\.clear\("
)
REQUEST_STARTED_AT_BY_ID_WRITE_MESSAGE = (
    "Phase 4-E has moved `_request_started_at_by_id` into RequestTimingService; "
    "DanmuApp may only keep a compatibility facade that delegates to RequestTimingService"
)
RTT_HISTORY_WRITE_PATTERN = re.compile(
    r"\bself\._rtt_history\s*(?::[^=]+)?(?:\+?=|-=)|\bself\._rtt_history\.(?:append|clear|extend|insert|pop|remove)\("
)
RTT_HISTORY_WRITE_MESSAGE = (
    "Phase 4-F has moved `_rtt_history` into RequestTimingService; "
    "DanmuApp may only keep a compatibility facade that delegates to RequestTimingService"
)


@dataclass
class Finding:
    severity: str
    rule: str
    path: str
    line: int
    message: str


def _run_git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _repo_has_head(repo_root: Path) -> bool:
    try:
        _run_git(repo_root, "rev-parse", "--verify", "HEAD")
        return True
    except subprocess.CalledProcessError:
        return False


def _normalize_rel(path_str: str) -> Path:
    return Path(path_str.replace("\\", "/"))


def get_changed_files(repo_root: Path) -> dict[Path, str]:
    result = _run_git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    changed: dict[Path, str] = {}
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        status = raw[:2]
        path_part = raw[3:]
        if "->" in path_part:
            path_part = path_part.split("->", 1)[1].strip()
        changed[_normalize_rel(path_part)] = status
    return changed


def _parse_added_lines_from_diff(diff_text: str) -> list[tuple[int, str]]:
    added: list[tuple[int, str]] = []
    current_line: int | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            if not match:
                current_line = None
                continue
            current_line = int(match.group(1))
            continue
        if current_line is None:
            continue
        if raw.startswith("+++"):
            continue
        if raw.startswith("+"):
            added.append((current_line, raw[1:]))
            current_line += 1
        elif raw.startswith("-"):
            continue
        else:
            current_line += 1
    return added


def get_added_lines(repo_root: Path, rel_path: Path, status: str) -> list[tuple[int, str]]:
    abs_path = repo_root / rel_path
    if status == "??" or not _repo_has_head(repo_root):
        lines = abs_path.read_text(encoding="utf-8").splitlines()
        return [(idx + 1, line) for idx, line in enumerate(lines)]
    diff = _run_git(repo_root, "diff", "--no-color", "--unified=0", "HEAD", "--", str(rel_path), check=False)
    if diff.returncode not in (0, 1):
        raise RuntimeError(diff.stderr.strip() or f"git diff failed for {rel_path}")
    return _parse_added_lines_from_diff(diff.stdout)


def _iter_python_files(root: Path) -> Iterable[Path]:
    yield from root.rglob("*.py")


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _has_phase2_todo(lines: list[str], line_no: int) -> bool:
    start = max(0, line_no - 3)
    end = min(len(lines), line_no)
    for idx in range(start, end):
        if "TODO(phase2-boundary)" in lines[idx]:
            return True
    return False


def _is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def check_web_private_access(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    targets = [WEB_CONSOLE_PATH]
    targets.extend(
        sorted(path.relative_to(repo_root) for path in (repo_root / WEB_API_DIR).glob("*.py"))
    )
    for rel_path in targets:
        if rel_path not in changed:
            continue
        lines = _read_lines(repo_root / rel_path)
        for line_no, line in get_added_lines(repo_root, rel_path, changed[rel_path]):
            if _is_comment_or_blank(line):
                continue
            for pattern, message in WEB_PRIVATE_PATTERNS:
                if re.search(pattern, line):
                    if _has_phase2_todo(lines, line_no):
                        break
                    findings.append(
                        Finding(
                            severity="error",
                            rule="phase1-boundary-rules.md 2.1 / 2.3",
                            path=str(rel_path),
                            line=line_no,
                            message=message,
                        )
                    )
                    break
    return findings


def check_config_conn_spread(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    for rel_path, status in changed.items():
        if rel_path.suffix != ".py" or (not rel_path.parts or rel_path.parts[0] != "app"):
            continue
        if rel_path in CONFIG_CONN_WHITELIST:
            continue
        for line_no, line in get_added_lines(repo_root, rel_path, status):
            if _is_comment_or_blank(line):
                continue
            if any(pattern in line for pattern in CONFIG_CONN_PATTERNS):
                findings.append(
                    Finding(
                        severity="error",
                        rule="phase1-boundary-rules.md 6.2",
                        path=str(rel_path),
                        line=line_no,
                        message="禁止在新的模块中继续扩散 config.conn / self.config.conn",
                    )
                )
    return findings


def check_thread_trigger_docs(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    doc_changed = PIPELINE_DOC in changed
    for rel_path, status in changed.items():
        if rel_path.suffix != ".py":
            continue
        for line_no, line in get_added_lines(repo_root, rel_path, status):
            if _is_comment_or_blank(line):
                continue
            for pattern, label in THREAD_TRIGGER_PATTERNS:
                if re.search(pattern, line):
                    if doc_changed:
                        break
                    findings.append(
                        Finding(
                            severity="error",
                            rule="phase1-boundary-rules.md 4.1",
                            path=str(rel_path),
                            line=line_no,
                            message=f"发现新增或修改的调度点 `{label}`，但 `docs/main-pipeline-sequence.md` 未同步更新",
                        )
                    )
                    break
    return findings


def _extract_init_range(lines: list[str]) -> tuple[int, int] | None:
    class_line = None
    init_start = None
    for idx, line in enumerate(lines, start=1):
        if class_line is None and re.match(r"^class\s+DanmuApp\b", line):
            class_line = idx
            continue
        if class_line is not None and init_start is None and re.match(r"^\s{4}def __init__\b", line):
            init_start = idx
            continue
        if init_start is not None and idx > init_start and re.match(r"^\s{4}def\s+\w+\b", line):
            return init_start, idx - 1
    if init_start is None:
        return None
    return init_start, len(lines)


def _documented_runtime_fields(doc_path: Path) -> set[str]:
    text = doc_path.read_text(encoding="utf-8")
    fields = set()
    for token in re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", text):
        fields.add(token)
    return fields


def _extract_added_runtime_fields(
    repo_root: Path,
    changed: dict[Path, str],
) -> list[tuple[int, str]]:
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
        match = re.search(r"self\.([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=", line)
        if not match:
            continue
        field = match.group(1)
        if field in RUNTIME_FIELD_EXCLUDE:
            continue
        fields.append((line_no, field))
    return fields


def check_runtime_state_doc(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    documented = _documented_runtime_fields(repo_root / RUNTIME_STATE_DOC)
    for line_no, field in _extract_added_runtime_fields(repo_root, changed):
        if field in documented:
            continue
        findings.append(
            Finding(
                severity="error",
                rule="phase1-boundary-rules.md 3.1",
                path=str(MAIN_PATH),
                line=line_no,
                message=f"新增运行态字段 `{field}` 未登记到 `docs/runtime-state-map.md`",
            )
        )
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
                findings.append(
                    Finding(
                        severity="error",
                        rule="runtime-ownership-plan.md / phase3-a",
                        path=str(MAIN_PATH),
                        line=line_no,
                        message=message,
                    )
                )
                break
    return findings


def check_request_scheduler_ownership(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH not in changed:
        return findings
    for line_no, line in get_added_lines(repo_root, MAIN_PATH, changed[MAIN_PATH]):
        if _is_comment_or_blank(line):
            continue
        if LAST_API_TRIGGER_AT_WRITE_PATTERN.search(line):
            findings.append(
                Finding(
                    severity="error",
                    rule="request-scheduler-plan.md / phase4-d",
                    path=str(MAIN_PATH),
                    line=line_no,
                    message=LAST_API_TRIGGER_AT_WRITE_MESSAGE,
                )
            )
    return findings


def check_request_timing_ownership(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH not in changed:
        return findings
    for line_no, line in get_added_lines(repo_root, MAIN_PATH, changed[MAIN_PATH]):
        if _is_comment_or_blank(line):
            continue
        if REQUEST_STARTED_AT_BY_ID_WRITE_PATTERN.search(line):
            findings.append(
                Finding(
                    severity="error",
                    rule="request-timing-service-plan.md / phase4-e",
                    path=str(MAIN_PATH),
                    line=line_no,
                    message=REQUEST_STARTED_AT_BY_ID_WRITE_MESSAGE,
                )
            )
    return findings


def check_request_timing_history_ownership(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH not in changed:
        return findings
    for line_no, line in get_added_lines(repo_root, MAIN_PATH, changed[MAIN_PATH]):
        if _is_comment_or_blank(line):
            continue
        if RTT_HISTORY_WRITE_PATTERN.search(line):
            findings.append(
                Finding(
                    severity="error",
                    rule="request-timing-service-plan.md / phase4-f",
                    path=str(MAIN_PATH),
                    line=line_no,
                    message=RTT_HISTORY_WRITE_MESSAGE,
                )
            )
    return findings


def _extract_function_body(lines: list[str], func_name: str) -> list[str]:
    start = None
    indent = None
    for idx, line in enumerate(lines):
        match = re.match(r"^(\s*)def\s+" + re.escape(func_name) + r"\b", line)
        if match:
            start = idx + 1
            indent = len(match.group(1))
            break
    if start is None or indent is None:
        return []
    body: list[str] = []
    for line in lines[start:]:
        if line.strip() and len(line) - len(line.lstrip(" ")) <= indent and re.match(r"^\s*def\s+\w+\b", line):
            break
        body.append(line)
    return body


def _meaningful_body_lines(body: list[str]) -> list[str]:
    lines: list[str] = []
    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ('"""', "'''"):
            continue
        lines.append(stripped)
    return lines


def check_web_status_composition(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if WEB_CONSOLE_PATH not in changed:
        return findings
    lines = _read_lines(repo_root / WEB_CONSOLE_PATH)
    body = _extract_function_body(lines, "refresh_status")
    if not body:
        return findings
    body_text = "\n".join(body)
    if "build_status_snapshot(" not in body_text:
        findings.append(
            Finding(
                severity="error",
                rule="phase1-boundary-rules.md 3.2 / 3.3",
                path=str(WEB_CONSOLE_PATH),
                line=0,
                message="`WebConsoleBridge.refresh_status()` 必须委托 `build_status_snapshot()`，禁止 Web 层自行拼接运行态状态",
            )
        )
    return findings


def check_status_snapshot_builder_delegation(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH not in changed:
        return findings
    lines = _read_lines(repo_root / MAIN_PATH)
    body = _extract_function_body(lines, "build_status_snapshot")
    if not body:
        findings.append(
            Finding(
                severity="error",
                rule="phase1-boundary-rules.md 3.2 / phase2.5",
                path=str(MAIN_PATH),
                line=0,
                message="`DanmuApp.build_status_snapshot()` 必须保留并继续委托 `StatusSnapshotBuilder`",
            )
        )
        return findings
    meaningful = _meaningful_body_lines(body)
    body_text = "\n".join(meaningful)
    if "StatusSnapshotBuilder" not in body_text or ".build(" not in body_text:
        findings.append(
            Finding(
                severity="error",
                rule="phase1-boundary-rules.md 3.2 / phase2.5",
                path=str(MAIN_PATH),
                line=0,
                message="`DanmuApp.build_status_snapshot()` 必须继续委托 `StatusSnapshotBuilder`",
            )
        )
    if "return {" in body_text or "WebStatusSnapshot(" in body_text:
        findings.append(
            Finding(
                severity="error",
                rule="phase1-boundary-rules.md 3.2 / phase2.5",
                path=str(MAIN_PATH),
                line=0,
                message="`DanmuApp.build_status_snapshot()` 不允许回退为直接拼装 status dict / WebStatusSnapshot",
            )
        )
    allowed_single_line = {
        "return StatusSnapshotBuilder(self).build()",
    }
    allowed_two_line = {
        "builder = StatusSnapshotBuilder(self)",
        "return builder.build()",
    }
    if meaningful:
        if len(meaningful) == 1 and meaningful[0] in allowed_single_line:
            return findings
        if len(meaningful) == 2 and set(meaningful) == allowed_two_line:
            return findings
        findings.append(
            Finding(
                severity="error",
                rule="phase1-boundary-rules.md 3.2 / phase2.5",
                path=str(MAIN_PATH),
                line=0,
                message="`DanmuApp.build_status_snapshot()` 只能保留薄 façade，不能重新夹带额外状态拼装逻辑",
            )
        )
    return findings


def check_config_service_delegation(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if MAIN_PATH in changed:
        lines = _read_lines(repo_root / MAIN_PATH)
        body = _extract_function_body(lines, "apply_web_config_payload")
        meaningful = _meaningful_body_lines(body)
        body_text = "\n".join(meaningful)
        if not body:
            findings.append(
                Finding(
                    severity="error",
                    rule="phase1-boundary-rules.md 2.2 / phase2.5",
                    path=str(MAIN_PATH),
                    line=0,
                    message="`DanmuApp.apply_web_config_payload()` 必须保留并继续委托 `ConfigService`",
                )
            )
        else:
            if "apply_web_config_patch(" not in body_text and "ConfigService(" not in body_text:
                findings.append(
                    Finding(
                        severity="error",
                        rule="phase1-boundary-rules.md 2.2 / phase2.5",
                        path=str(MAIN_PATH),
                        line=0,
                        message="`DanmuApp.apply_web_config_payload()` 必须继续委托 `ConfigService` / `apply_web_config_patch()`",
                    )
                )
            forbidden = (
                "set_batch(",
                ".set(",
                "set_default_model_id(",
                "set_custom_models(",
                "config_changed.emit(",
            )
            if any(token in body_text for token in forbidden):
                findings.append(
                    Finding(
                        severity="error",
                        rule="phase1-boundary-rules.md 2.2 / phase2.5",
                        path=str(MAIN_PATH),
                        line=0,
                        message="`DanmuApp.apply_web_config_payload()` 不允许绕过 `ConfigService` 直接改配置或发信号",
                    )
                )
    if WEB_CONSOLE_PATH in changed:
        lines = _read_lines(repo_root / WEB_CONSOLE_PATH)
        body = _extract_function_body(lines, "apply_config_patch")
        if body:
            meaningful = _meaningful_body_lines(body)
            body_text = "\n".join(meaningful)
            if "apply_web_config_patch(" not in body_text and ".apply_web_config_payload(" not in body_text:
                findings.append(
                    Finding(
                        severity="error",
                        rule="phase1-boundary-rules.md 2.2 / phase2.5",
                        path=str(WEB_CONSOLE_PATH),
                        line=0,
                        message="`app/web_console.py::apply_config_patch()` 若保留，只能作为兼容包装委托 `ConfigService` 或 `DanmuApp.apply_web_config_payload()`",
                    )
                )
            forbidden = (
                "set_batch(",
                "set_default_model_id(",
                "set_custom_models(",
                "config_changed.emit(",
            )
            if any(token in body_text for token in forbidden):
                findings.append(
                    Finding(
                        severity="error",
                        rule="phase1-boundary-rules.md 2.2 / phase2.5",
                        path=str(WEB_CONSOLE_PATH),
                        line=0,
                        message="`app/web_console.py::apply_config_patch()` 不允许重新回退到直接拼接配置 patch 逻辑",
                    )
                )
    return findings


def check_default_model_selection_guard(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if CUSTOM_MODELS_PATH not in changed:
        return findings
    lines = _read_lines(repo_root / CUSTOM_MODELS_PATH)
    for func_name in ("delete_custom_model", "set_default_custom_model"):
        body = _extract_function_body(lines, func_name)
        if not body:
            continue
        body_text = "\n".join(_meaningful_body_lines(body))
        if "set_default_model_selection(" not in body_text:
            findings.append(
                Finding(
                    severity="error",
                    rule="phase1-boundary-rules.md 2.2 / phase2.5",
                    path=str(CUSTOM_MODELS_PATH),
                    line=0,
                    message=f"`{func_name}()` 必须继续复用 `set_default_model_selection()` 维护 `model/default_model_id` 兼容写规则",
                )
            )
        forbidden = (
            "set_default_model_id(",
            '.set("model"',
            ".set('model'",
        )
        if any(token in body_text for token in forbidden):
            findings.append(
                Finding(
                    severity="error",
                    rule="phase1-boundary-rules.md 2.2 / phase2.5",
                    path=str(CUSTOM_MODELS_PATH),
                    line=0,
                    message="`app/web_api/custom_models.py` 不允许重新手写不一致的 `model/default_model_id` 默认模型回退逻辑",
                )
            )
    return findings


def check_generation_pipeline_projection(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []

    if GENERATION_PIPELINE_STATE_PATH in changed:
        for line_no, line in get_added_lines(
            repo_root, GENERATION_PIPELINE_STATE_PATH, changed[GENERATION_PIPELINE_STATE_PATH]
        ):
            if _is_comment_or_blank(line):
                continue
            if re.search(r"\bapp\.[A-Za-z_][A-Za-z0-9_]*\s*(?:\+?=|-=)", line):
                findings.append(
                    Finding(
                        severity="error",
                        rule="generation-pipeline-state-plan.md / phase3-c",
                        path=str(GENERATION_PIPELINE_STATE_PATH),
                        line=line_no,
                        message="GenerationPipelineState is read-only and must not write back to app state",
                    )
                )
                continue
            for pattern, message in GENERATION_PIPELINE_FORBIDDEN_TOKENS:
                if re.search(pattern, line):
                    findings.append(
                        Finding(
                            severity="error",
                            rule="generation-pipeline-state-plan.md / phase3-c",
                            path=str(GENERATION_PIPELINE_STATE_PATH),
                            line=line_no,
                            message=message,
                        )
                    )
                    break
            else:
                for token in GENERATION_PIPELINE_FORBIDDEN_CALLS:
                    if token in line:
                        findings.append(
                            Finding(
                                severity="error",
                                rule="generation-pipeline-state-plan.md / phase3-c",
                                path=str(GENERATION_PIPELINE_STATE_PATH),
                                line=line_no,
                                message="GenerationPipelineState must not call main pipeline functions",
                            )
                        )
                        break

    if RUNTIME_STATE_PATH in changed:
        runtime_lines = _read_lines(repo_root / RUNTIME_STATE_PATH)
        runtime_text = "\n".join(runtime_lines)
        if "GenerationPipelineState.from_app(app)" not in runtime_text:
            findings.append(
                Finding(
                    severity="error",
                    rule="generation-pipeline-state-plan.md / phase3-c",
                    path=str(RUNTIME_STATE_PATH),
                    line=0,
                    message="RuntimeState must read Phase 3-C projection via GenerationPipelineState.from_app()",
                )
            )
        for line_no, line in get_added_lines(repo_root, RUNTIME_STATE_PATH, changed[RUNTIME_STATE_PATH]):
            if _is_comment_or_blank(line):
                continue
            if "getattr(app," not in line:
                continue
            if any(field in line for field in GENERATION_PIPELINE_CANDIDATE_FIELDS):
                findings.append(
                    Finding(
                        severity="error",
                        rule="generation-pipeline-state-plan.md / phase3-c",
                        path=str(RUNTIME_STATE_PATH),
                        line=line_no,
                        message="RuntimeState must not bypass GenerationPipelineState to read Phase 3-C projection fields directly",
                    )
                )
    return findings


def check_request_metadata_boundary(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []

    if REQUEST_METADATA_STATE_PATH in changed:
        for line_no, line in get_added_lines(
            repo_root, REQUEST_METADATA_STATE_PATH, changed[REQUEST_METADATA_STATE_PATH]
        ):
            if _is_comment_or_blank(line):
                continue
            for pattern, message in REQUEST_METADATA_FORBIDDEN_TOKENS:
                if re.search(pattern, line):
                    findings.append(
                        Finding(
                            severity="error",
                            rule="generation-pipeline-state-plan.md / phase4-a",
                            path=str(REQUEST_METADATA_STATE_PATH),
                            line=line_no,
                            message=message,
                        )
                    )
                    break
            else:
                for token in REQUEST_METADATA_FORBIDDEN_CALLS:
                    if token in line:
                        findings.append(
                            Finding(
                                severity="error",
                                rule="generation-pipeline-state-plan.md / phase4-a",
                                path=str(REQUEST_METADATA_STATE_PATH),
                                line=line_no,
                                message="RequestMetadataState must not call main pipeline scheduling or timing functions",
                            )
                        )
                        break

    for path, state_name in (
        (STATS_STATE_PATH, "StatsState"),
        (WEB_RUNTIME_STATE_PATH, "WebRuntimeState"),
    ):
        if path not in changed:
            continue
        for line_no, line in get_added_lines(repo_root, path, changed[path]):
            if _is_comment_or_blank(line):
                continue
            for field in STATE_OBJECT_FORBIDDEN_FIELDS:
                if field in line:
                    findings.append(
                        Finding(
                            severity="error",
                            rule="runtime-ownership-plan.md / phase4-a",
                            path=str(path),
                            line=line_no,
                            message=f"Phase 4-A forbids moving `{field}` into {state_name}",
                        )
                    )
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
                    findings.append(
                        Finding(
                            severity="error",
                            rule="request-scheduler-plan.md / phase4-b",
                            path=str(REQUEST_SCHEDULER_PATH),
                            line=line_no,
                            message=message,
                        )
                    )
                    break
            else:
                for token in REQUEST_SCHEDULER_FORBIDDEN_CALLS:
                    if token in line:
                        findings.append(
                            Finding(
                                severity="error",
                                rule="request-scheduler-plan.md / phase4-b",
                                path=str(REQUEST_SCHEDULER_PATH),
                                line=line_no,
                                message="RequestScheduler must not call trigger, reply handling, or queue consumption functions",
                            )
                        )
                        break

    if REQUEST_TIMING_SERVICE_PATH in changed:
        for line_no, line in get_added_lines(
            repo_root, REQUEST_TIMING_SERVICE_PATH, changed[REQUEST_TIMING_SERVICE_PATH]
        ):
            if _is_comment_or_blank(line):
                continue
            for pattern, message in REQUEST_TIMING_SERVICE_FORBIDDEN_TOKENS:
                if re.search(pattern, line):
                    findings.append(
                        Finding(
                            severity="error",
                            rule="request-timing-service-plan.md / phase4-b",
                            path=str(REQUEST_TIMING_SERVICE_PATH),
                            line=line_no,
                            message=message,
                        )
                    )
                    break
            else:
                for token in REQUEST_TIMING_SERVICE_FORBIDDEN_CALLS:
                    if token in line:
                        findings.append(
                            Finding(
                                severity="error",
                                rule="request-timing-service-plan.md / phase4-b",
                                path=str(REQUEST_TIMING_SERVICE_PATH),
                                line=line_no,
                                message="RequestTimingService must not call trigger or queue consumption functions",
                            )
                        )
                        break

    return findings


def check_diagnostic_snapshot_boundary(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if DIAGNOSTIC_SNAPSHOT_PATH not in changed:
        return findings

    for line_no, line in get_added_lines(
        repo_root, DIAGNOSTIC_SNAPSHOT_PATH, changed[DIAGNOSTIC_SNAPSHOT_PATH]
    ):
        if _is_comment_or_blank(line):
            continue
        if re.search(r"\b(?:app|self\._app)\.[A-Za-z_][A-Za-z0-9_]*\s*(?::[^=]+)?(?:\+?=|-=)", line) or re.search(
            r"\b(?:app|self\._app)\.[A-Za-z_][A-Za-z0-9_]*\.(?:append|clear|extend|insert|pop|remove|update|setdefault)\(",
            line,
        ):
            findings.append(
                Finding(
                    severity="error",
                    rule="diagnostics-plan.md / phase5-a",
                    path=str(DIAGNOSTIC_SNAPSHOT_PATH),
                    line=line_no,
                    message="DiagnosticSnapshot must be read-only and must not write app state",
                )
            )
            continue
        for pattern, message in DIAGNOSTIC_SNAPSHOT_FORBIDDEN_TOKENS:
            if re.search(pattern, line):
                findings.append(
                    Finding(
                        severity="error",
                        rule="diagnostics-plan.md / phase5-a",
                        path=str(DIAGNOSTIC_SNAPSHOT_PATH),
                        line=line_no,
                        message=message,
                    )
                )
                break
        else:
            for token in DIAGNOSTIC_SNAPSHOT_FORBIDDEN_CALLS:
                if token in line:
                    findings.append(
                        Finding(
                            severity="error",
                            rule="diagnostics-plan.md / phase5-a",
                            path=str(DIAGNOSTIC_SNAPSHOT_PATH),
                            line=line_no,
                            message="DiagnosticSnapshot must not call trigger, reply, or queue pipeline functions",
                        )
                    )
                    break

    return findings


def check_web_diagnostics_route_boundary(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    routes_path = WEB_API_DIR / "routes.py"
    if routes_path not in changed:
        return findings

    lines = _read_lines(repo_root / routes_path)
    routes_text = "\n".join(lines)
    if '"/api/diagnostics"' not in routes_text and "'/api/diagnostics'" not in routes_text:
        return findings

    body = _extract_function_body(lines, "get_diagnostics")
    meaningful = _meaningful_body_lines(body)
    body_text = "\n".join(meaningful)

    if not body or "build_diagnostic_snapshot(" not in body_text:
        findings.append(
            Finding(
                severity="error",
                rule="diagnostics-plan.md / phase5-b",
                path=str(routes_path),
                line=0,
                message="`/api/diagnostics` must delegate to `DanmuApp.build_diagnostic_snapshot()`",
            )
        )

    if "build_status_snapshot(" in body_text:
        findings.append(
            Finding(
                severity="error",
                rule="diagnostics-plan.md / phase5-b",
                path=str(routes_path),
                line=0,
                message="`/api/diagnostics` must stay independent from `/api/status` and must not reuse `build_status_snapshot()`",
            )
        )

    if '"ok": True' not in body_text and "'ok': True" not in body_text:
        findings.append(
            Finding(
                severity="error",
                rule="diagnostics-plan.md / phase5-b",
                path=str(routes_path),
                line=0,
                message="`/api/diagnostics` must return an independent payload with `ok` and `diagnostics` keys",
            )
        )

    for line_no, line in get_added_lines(repo_root, routes_path, changed[routes_path]):
        if _is_comment_or_blank(line):
            continue
        for pattern, message in DIAGNOSTICS_ROUTE_FORBIDDEN_TOKENS:
            if re.search(pattern, line):
                findings.append(
                    Finding(
                        severity="error",
                        rule="diagnostics-plan.md / phase5-b",
                        path=str(routes_path),
                        line=line_no,
                        message=message,
                    )
                )
                break
        else:
            for token in DIAGNOSTICS_ROUTE_FORBIDDEN_CALLS:
                if token in line:
                    findings.append(
                        Finding(
                            severity="error",
                            rule="diagnostics-plan.md / phase5-b",
                            path=str(routes_path),
                            line=line_no,
                            message="Diagnostics route must not call trigger, reply, or queue pipeline functions",
                        )
                    )
                    break

    return findings


def check_status_route_boundary(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if WEB_CONSOLE_PATH not in changed:
        return findings

    lines = _read_lines(repo_root / WEB_CONSOLE_PATH)
    body = _extract_function_body(lines, "status")
    body_text = "\n".join(_meaningful_body_lines(body))
    if not body_text:
        return findings
    if "build_diagnostic_snapshot(" in body_text or '"diagnostics"' in body_text or "'diagnostics'" in body_text:
        findings.append(
            Finding(
                severity="error",
                rule="diagnostics-plan.md / phase5-c",
                path=str(WEB_CONSOLE_PATH),
                line=0,
                message="`/api/status` must not be polluted by diagnostics data or `build_diagnostic_snapshot()`",
            )
        )
    return findings


def check_web_diagnostics_ui_boundary(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    targets = (
        WEB_STATIC_DIR / "app.js",
        WEB_STATIC_DIR / "index.html",
    )
    for rel_path in targets:
        if rel_path not in changed:
            continue
        for line_no, line in get_added_lines(repo_root, rel_path, changed[rel_path]):
            if _is_comment_or_blank(line):
                continue
            for pattern, message in WEB_DIAGNOSTICS_UI_FORBIDDEN_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        Finding(
                            severity="error",
                            rule="diagnostics-plan.md / phase5-c",
                            path=str(rel_path),
                            line=line_no,
                            message=message,
                        )
                    )
                    break
    return findings


def check_final_architecture_baseline(repo_root: Path) -> list[Finding]:
    if (repo_root / FINAL_ARCH_BASELINE_DOC).exists():
        return []
    return [
        Finding(
            severity="error",
            rule="final-architecture-baseline.md / phase5-c",
            path=str(FINAL_ARCH_BASELINE_DOC),
            line=0,
            message="`docs/final-architecture-baseline.md` must exist as the final architecture baseline",
        )
    ]


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


def format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "Boundary Guard: PASS"
    lines = ["Boundary Guard: FAIL"]
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line > 0 else finding.path
        lines.append(
            f"- [{finding.severity.upper()}] {location} | {finding.rule} | {finding.message}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Boundary guard for Phase 1 architecture rules.")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to scan. Defaults to current working directory.",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    findings = run_boundary_guard(repo_root)
    print(format_findings(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
