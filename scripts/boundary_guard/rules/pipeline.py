"""生成管线 / runtime 投影规则。

检查项：
    - check_generation_pipeline_projection
        ``app/application/generation_pipeline_state.py`` 中候选字段
        （GENERATION_PIPELINE_CANDIDATE_FIELDS）的写操作须经
        ``runtime_state`` 投影；禁止直接 ``self.xxx =`` 改写（避免运行时
        状态被绕过）。
    - check_generation_pipeline_service
        ``app/application/generation_pipeline.py``（W-GENPIPELINE-EXTRACT）服务边界：
        禁止实例化 QTimer/QThreadPool/QPixmap（所有权属 DanmuApp）；
        禁止调用主链路触发函数（_trigger_api_call/_on_ai_reply 等，仍属 DanmuApp）。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..constants import (
    GENERATION_PIPELINE_CANDIDATE_FIELDS,
    GENERATION_PIPELINE_FORBIDDEN_CALLS,
    GENERATION_PIPELINE_FORBIDDEN_TOKENS,
    GENERATION_PIPELINE_PATH,
    GENERATION_PIPELINE_SERVICE_FORBIDDEN_CALLS,
    GENERATION_PIPELINE_SERVICE_FORBIDDEN_TOKENS,
    GENERATION_PIPELINE_STATE_PATH,
    RUNTIME_STATE_PATH,
)
from ..git_diff import (
    _is_comment_or_blank,
    _read_lines,
    get_added_lines,
)
from ..models import Finding


def check_generation_pipeline_projection(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    findings: list[Finding] = []
    if GENERATION_PIPELINE_STATE_PATH in changed:
        for line_no, line in get_added_lines(repo_root, GENERATION_PIPELINE_STATE_PATH, changed[GENERATION_PIPELINE_STATE_PATH]):
            if _is_comment_or_blank(line):
                continue
            if re.search('\\bapp\\.[A-Za-z_][A-Za-z0-9_]*\\s*(?:\\+?=|-=)', line):
                findings.append(Finding(severity='error', rule='generation-pipeline-state-plan.md / phase3-c', path=str(GENERATION_PIPELINE_STATE_PATH), line=line_no, message='GenerationPipelineState is read-only and must not write back to app state'))
                continue
            for pattern, message in GENERATION_PIPELINE_FORBIDDEN_TOKENS:
                if re.search(pattern, line):
                    findings.append(Finding(severity='error', rule='generation-pipeline-state-plan.md / phase3-c', path=str(GENERATION_PIPELINE_STATE_PATH), line=line_no, message=message))
                    break
            else:
                for token in GENERATION_PIPELINE_FORBIDDEN_CALLS:
                    if token in line:
                        findings.append(Finding(severity='error', rule='generation-pipeline-state-plan.md / phase3-c', path=str(GENERATION_PIPELINE_STATE_PATH), line=line_no, message='GenerationPipelineState must not call main pipeline functions'))
                        break
    if RUNTIME_STATE_PATH in changed:
        runtime_lines = _read_lines(repo_root / RUNTIME_STATE_PATH)
        runtime_text = '\n'.join(runtime_lines)
        if 'GenerationPipelineState.from_app(app)' not in runtime_text:
            findings.append(Finding(severity='error', rule='generation-pipeline-state-plan.md / phase3-c', path=str(RUNTIME_STATE_PATH), line=0, message='RuntimeState must read Phase 3-C projection via GenerationPipelineState.from_app()'))
        for line_no, line in get_added_lines(repo_root, RUNTIME_STATE_PATH, changed[RUNTIME_STATE_PATH]):
            if _is_comment_or_blank(line):
                continue
            if 'getattr(app,' not in line:
                continue
            if any((field in line for field in GENERATION_PIPELINE_CANDIDATE_FIELDS)):
                findings.append(Finding(severity='error', rule='generation-pipeline-state-plan.md / phase3-c', path=str(RUNTIME_STATE_PATH), line=line_no, message='RuntimeState must not bypass GenerationPipelineState to read Phase 3-C projection fields directly'))
    return findings


def check_generation_pipeline_service(repo_root: Path, changed: dict[Path, str]) -> list[Finding]:
    """检查 app/application/generation_pipeline.py（W-GENPIPELINE-EXTRACT）服务边界。

    - 禁止实例化 QTimer/QThreadPool/QPixmap（所有权属 DanmuApp）
    - 禁止调用主链路触发函数（_trigger_api_call/_on_ai_reply 等，仍属 DanmuApp）
    - 允许 reply_timer.* / _display_danmu_text / _enqueue_reply_batch 等 reply 消费方法
    """
    findings: list[Finding] = []
    if GENERATION_PIPELINE_PATH not in changed:
        return findings
    for line_no, line in get_added_lines(repo_root, GENERATION_PIPELINE_PATH, changed[GENERATION_PIPELINE_PATH]):
        if _is_comment_or_blank(line):
            continue
        for pattern, message in GENERATION_PIPELINE_SERVICE_FORBIDDEN_TOKENS:
            if re.search(pattern, line):
                findings.append(Finding(severity='error', rule='w-genpipeline-extract / generation-pipeline-service', path=str(GENERATION_PIPELINE_PATH), line=line_no, message=message))
                break
        else:
            for token in GENERATION_PIPELINE_SERVICE_FORBIDDEN_CALLS:
                if token in line:
                    findings.append(Finding(severity='error', rule='w-genpipeline-extract / generation-pipeline-service', path=str(GENERATION_PIPELINE_PATH), line=line_no, message='generation_pipeline.py must not call DanmuApp main pipeline trigger functions; only reply consume / dispatch logic is allowed here'))
                    break
    return findings
