#!/usr/bin/env python3
"""Merge data/danmu_pool_zh_bootstrap.txt into data/danmu_pool_zh.json."""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.extract_danmu_pool import OUTPUT_PATH, merge_with_bootstrap


def main() -> int:
    if not OUTPUT_PATH.is_file():
        print(f"missing {OUTPUT_PATH}; run extract_danmu_pool.py first", file=sys.stderr)
        return 1
    payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        print("invalid pool json", file=sys.stderr)
        return 1
    corpus_items = payload.get("items") or []
    if not isinstance(corpus_items, list):
        corpus_items = []
    merged, bootstrap_count = merge_with_bootstrap([str(x).strip() for x in corpus_items if str(x).strip()])
    before = len(corpus_items)
    payload["items"] = merged
    payload["count"] = len(merged)
    payload["bootstrap_count"] = bootstrap_count
    payload["corpus_count"] = max(0, len(merged) - bootstrap_count)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Merged bootstrap into {OUTPUT_PATH}: "
        f"bootstrap={bootstrap_count}, corpus_kept={payload['corpus_count']}, "
        f"before={before}, after={len(merged)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
