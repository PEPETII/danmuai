#!/usr/bin/env python3
"""Write data/danmu_pool_zh_bootstrap.txt from docs/DANMAKU_FORMULA.md."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FORMULA_DOC = REPO_ROOT / "docs" / "DANMAKU_FORMULA.md"
OUTPUT = REPO_ROOT / "data" / "danmu_pool_zh_bootstrap.txt"
ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*(?:\|.*)?$")


def main() -> int:
    if not FORMULA_DOC.is_file():
        print(f"missing {FORMULA_DOC}", file=sys.stderr)
        return 1
    items: list[str] = []
    seen: set[str] = set()
    for line in FORMULA_DOC.read_text(encoding="utf-8").splitlines():
        match = ROW_RE.match(line.strip())
        if not match:
            continue
        text = match.group(2).strip()
        if text.startswith("{") or "填空" in text:
            continue
        if text in seen:
            continue
        seen.add(text)
        items.append(text)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(items) + "\n", encoding="utf-8")
    print(f"Wrote {len(items)} lines to {OUTPUT}")
    return 0 if len(items) >= 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
