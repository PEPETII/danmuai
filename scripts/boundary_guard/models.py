"""Finding 数据类 — 单条违规。

字段：
    severity  'error' | 'warning'（目前规则全部为 error；预留 warning 通道）
    rule      规则 ID（短横线命名，如 'web-private-pattern'）
    path      相对仓库根的路径
    line      命中行号（0 = 文件级违规）
    message   提示文案（包含修复建议）

设计：使用 @dataclass 便于 pytest 断言（``Finding(...) == Finding(...)`` 走
字段相等比较）；不要在此加业务方法，保持纯数据。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Finding:
    severity: str
    rule: str
    path: str
    line: int
    message: str
