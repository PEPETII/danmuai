"""CLI 入口：解析参数 → 调 ``run_boundary_guard`` → ``format_findings`` 打印。

参数：
    --repo-root PATH   仓库根目录；默认当前工作目录

退出码：``0`` 表示无违规（PASS），``1`` 表示至少一条 finding（FAIL）。

脚本壳 ``scripts/boundary_guard.py``（同目录单文件）也最终走本 main。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .reporters import format_findings
from .runner import run_boundary_guard


def main(argv: list[str] | None=None) -> int:
    """CLI 主入口；返回值即进程退出码。"""
    parser = argparse.ArgumentParser(description='Boundary guard for Phase 1 architecture rules.')
    parser.add_argument('--repo-root', default='.', help='Repository root to scan. Defaults to current working directory.')
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    findings = run_boundary_guard(repo_root)
    print(format_findings(findings))
    return 1 if findings else 0
