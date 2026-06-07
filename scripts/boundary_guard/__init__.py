"""Boundary guard — DanmuAI 架构边界守护。

公共 API（再导出）：
    Finding            — 单条违规（dataclass）
    format_findings    — 把 findings 列表渲染为可读文本
    main               — CLI 入口
    run_boundary_guard — 主流程（被 CLI 与 pytest 共用）

历史：本模块原为单一文件 ``scripts/boundary_guard.py``，随规则膨胀
（约 280 行 + 数十类正则）拆分为 ``scripts/boundary_guard/``；旧
``scripts/boundary_guard.py`` 现仅作为兼容壳（见同目录同名文件）。
"""

from .cli import main
from .models import Finding
from .reporters import format_findings
from .runner import run_boundary_guard

__all__ = ["Finding", "format_findings", "main", "run_boundary_guard"]
