"""架构基线文档存在性规则（Phase 5-c）。

检查项：
    - check_final_architecture_baseline
        ``docs/final-architecture-baseline.md`` 必须存在；缺失即报
        ``final-architecture-baseline.md / phase5-c``。
"""

from __future__ import annotations

from pathlib import Path

from ..constants import FINAL_ARCH_BASELINE_DOC
from ..models import Finding


def check_final_architecture_baseline(repo_root: Path) -> list[Finding]:
    if (repo_root / FINAL_ARCH_BASELINE_DOC).exists():
        return []
    return [Finding(severity='error', rule='final-architecture-baseline.md / phase5-c', path=str(FINAL_ARCH_BASELINE_DOC), line=0, message='`docs/final-architecture-baseline.md` must exist as the final architecture baseline')]
