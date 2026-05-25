#!/usr/bin/env python3
"""Remove sensitive lines from data/danmu_pool_zh.json in place."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.extract_danmu_pool import is_overlay_safe

DEFAULT_PATH = REPO_ROOT / "data" / "danmu_pool_zh.json"


def filter_items(items: list[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    removed: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = str(raw).strip()
        if not text:
            continue
        if text in seen:
            continue
        if not is_overlay_safe(text):
            removed.append(text)
            continue
        seen.add(text)
        kept.append(text)
    return kept, removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=str, default=str(DEFAULT_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.input)
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items")
    if not isinstance(items, list):
        print("No items array", file=sys.stderr)
        return 1

    kept, removed = filter_items(items)
    print(f"before={len(items)} after={len(kept)} removed={len(removed)}")
    if removed:
        for line in removed:
            print(f"  - {line}")

    if args.dry_run:
        return 0

    data["items"] = kept
    data["count"] = len(kept)
    if "corpus_count" in data:
        data["corpus_count"] = max(0, len(kept) - int(data.get("bootstrap_count") or 0))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
