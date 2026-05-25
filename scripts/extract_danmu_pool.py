#!/usr/bin/env python3
"""Extract overlay-safe danmu lines from DDmkTCCorpus sorted_danmaku.txt."""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CORPUS_URL = (
    "https://raw.githubusercontent.com/TinyTalks/DDmkTCCorpus/main/data/sorted_danmaku.txt"
)
FORMULA_DOC = REPO_ROOT / "docs" / "DANMAKU_FORMULA.md"
BOOTSTRAP_PATH = REPO_ROOT / "data" / "danmu_pool_zh_bootstrap.txt"
OUTPUT_PATH = REPO_ROOT / "data" / "danmu_pool_zh.json"

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
REPEAT_CHAR_RE = re.compile(r"(.)\1{4,}")
URL_RE = re.compile(r"https?://|www\.", re.I)
FORMULA_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*(?:\|.*)?$")

# Blocklist for overlay-safe pool (profanity, attacks, politics, celebrity flame-bait).
BLOCK_SUBSTRINGS = (
    "死妈",
    "傻逼",
    "操你",
    "nmsl",
    "cnm",
    "草泥马",
    "卧槽",
    "我操",
    "我特么",
    "我TM",
    "TMD",
    "tmd",
    "妈的",
    "牛逼",
    "牛壁",
    "装逼",
    "挂逼",
    "憨批",
    "吃口屎",
    "吔屎",
    "口也屎",
    "吃屎",
    "搓屁",
    "放屁",
    "大吊",
    "命根子",
    "嘴臭",
    "小jb",
    "摸奈子",
    "裆锯",
    "avi.",
    "尾行",
    "女少口阿",
    "沉迷女色",
    "沉迷美色",
    "妇炎洁",
    "卢本伟",
    "卢姥爷",
    "卢老爷",
    "lbw",
    "lbwnb",
    "芦苇",
    "肖战",
    "蔡徐坤",
    "吴亦凡",
    "乔碧萝",
    "药水哥",
    "脏话一堆",
    "你爹是我儿",
    "漂移~身边的小妞",
    "和天皇作对",
    "复兴华夏",
    "中华人民共和国",
    "红军加油",
    "川国同志",
    "兴兵北伐",
    "治死",
    "治一个，死一个",
    "一年治死",
    "你们杀了我",
    "鸡~你~太~美",
    "坤牛壁",
    "公开处刑",
    "澳门皇家赌场",
    "woc",
    "wdnmd",
    "我擦",
    "我透",
    "杀死",
    "李易峰",
    "普京",
    "奥巴马",
    "特朗普",
)
BLOCK_CHARS = set("▓█▅▆▇")
# Meme / sexualized spam markers common in raw corpus (not overlay tone).
BLOCK_REGEX_PATTERNS: tuple[str, ...] = (
    r"♂",  # philosophy-meme spam
    r"lbw",
    r"芦苇",
)


def _find_local_corpus(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    candidates = [
        REPO_ROOT / "开源项目" / "DDmkTCCorpus-main" / "data" / "sorted_danmaku.txt",
        REPO_ROOT / "开源项目" / "DDmkTCCorpus" / "data" / "sorted_danmaku.txt",
        REPO_ROOT / "开源项目" / "TinyTalks" / "DDmkTCCorpus-main" / "data" / "sorted_danmaku.txt",
    ]
    base = REPO_ROOT / "开源项目"
    if base.is_dir():
        for hit in base.rglob("sorted_danmaku.txt"):
            if hit.is_file():
                candidates.insert(0, hit)
    for path in candidates:
        if path.is_file():
            return path
    return None


def _iter_corpus_lines(path: Path | None, url: str | None):
    if path is not None:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                yield line.rstrip("\n\r")
        return
    if not url:
        return
    with urllib.request.urlopen(url, timeout=120) as response:
        for raw in response:
            yield raw.decode("utf-8", errors="ignore").rstrip("\n\r")


def _parse_formula_doc() -> list[str]:
    if not FORMULA_DOC.is_file():
        return []
    items: list[str] = []
    for line in FORMULA_DOC.read_text(encoding="utf-8").splitlines():
        match = FORMULA_ROW_RE.match(line.strip())
        if not match:
            continue
        text = match.group(2).strip()
        if text.startswith("{") or "填空" in text:
            continue
        items.append(text)
    return items


def load_bootstrap_lines() -> list[str]:
    if not BOOTSTRAP_PATH.is_file():
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for raw in BOOTSTRAP_PATH.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text in seen:
            continue
        if not is_overlay_safe(text, max_chars=15, min_chars=1):
            continue
        seen.add(text)
        lines.append(text)
    return lines


def merge_with_bootstrap(corpus_items: list[str]) -> tuple[list[str], int]:
    """Prepend bootstrap (formula 400); append corpus lines not already present."""
    merged: list[str] = []
    seen: set[str] = set()
    bootstrap_count = 0
    for text in load_bootstrap_lines():
        if text in seen:
            continue
        seen.add(text)
        merged.append(text)
        bootstrap_count += 1
    for text in corpus_items:
        if text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged, bootstrap_count


def is_overlay_safe(text: str, *, max_chars: int = 15, min_chars: int = 2) -> bool:
    text = text.strip()
    if not text or len(text) < min_chars or len(text) > max_chars:
        return False
    if any(ch in text for ch in ("\n", "\r", "\t")):
        return False
    if not CJK_RE.search(text):
        return False
    cjk = len(CJK_RE.findall(text))
    if cjk < min(2, len(text)):
        return False
    if REPEAT_CHAR_RE.search(text):
        return False
    if URL_RE.search(text):
        return False
    low = text.lower()
    if any(marker in text or marker.lower() in low for marker in BLOCK_SUBSTRINGS):
        return False
    for pat in BLOCK_REGEX_PATTERNS:
        if re.search(pat, text, flags=re.I):
            return False
    if any(ch in BLOCK_CHARS for ch in text):
        return False
    if text.count(" ") > 2:
        return False
    # Drop lines that are mostly duplicate punctuation spam.
    unique_chars = len(set(text))
    if unique_chars < 2 and len(text) > 4:
        return False
    return True


def extract_pool(
    *,
    target: int = 1000,
    max_chars: int = 15,
    corpus_path: str | None = None,
    download_url: str | None = DEFAULT_CORPUS_URL,
    seed: int = 42,
) -> dict:
    local = _find_local_corpus(corpus_path)
    seen: set[str] = set()
    reservoir: list[str] = []
    scanned = 0
    accepted = 0
    rng = random.Random(seed)

    formula_items = [t for t in _parse_formula_doc() if is_overlay_safe(t, max_chars=max_chars)]
    for text in formula_items:
        if text not in seen:
            seen.add(text)

    for line in _iter_corpus_lines(local, download_url if local is None else None):
        scanned += 1
        text = line.strip()
        if not is_overlay_safe(text, max_chars=max_chars):
            continue
        if text in seen:
            continue
        seen.add(text)
        accepted += 1
        if len(reservoir) < target:
            reservoir.append(text)
        else:
            j = rng.randint(0, accepted - 1)
            if j < target:
                reservoir[j] = text

    # Top up from formula doc if corpus stream was short.
    if len(reservoir) < target:
        for text in formula_items:
            if text in reservoir:
                continue
            reservoir.append(text)
            if len(reservoir) >= target:
                break

    reservoir = reservoir[:target]
    merged, bootstrap_count = merge_with_bootstrap(reservoir)
    sources = []
    if bootstrap_count:
        sources.append(
            {"type": "danmu_pool_zh_bootstrap.txt", "path": str(BOOTSTRAP_PATH), "count": bootstrap_count}
        )
    if local is not None:
        sources.append({"type": "DDmkTCCorpus", "path": str(local)})
    elif download_url:
        sources.append({"type": "DDmkTCCorpus", "url": download_url})
    if formula_items:
        sources.append({"type": "DANMAKU_FORMULA.md", "count": len(formula_items)})

    return {
        "version": 1,
        "target": target,
        "corpus_target": target,
        "bootstrap_count": bootstrap_count,
        "count": len(merged),
        "max_chars_zh": max_chars,
        "scanned_lines": scanned,
        "accepted_unique": accepted,
        "sources": sources,
        "license_note": (
            "DDmkTCCorpus (Apache-2.0, TinyTalks/DDmkTCCorpus). "
            "Curated subset for DanmuAI overlay; not a full corpus redistribution."
        ),
        "items": merged,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument("--max-chars", type=int, default=15)
    parser.add_argument("--corpus", type=str, default=None, help="Path to sorted_danmaku.txt")
    parser.add_argument("--no-download", action="store_true", help="Do not fetch from GitHub")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH))
    args = parser.parse_args()

    payload = extract_pool(
        target=args.target,
        max_chars=args.max_chars,
        corpus_path=args.corpus,
        download_url=None if args.no_download else DEFAULT_CORPUS_URL,
        seed=args.seed,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {payload['count']} items to {out} "
        f"(scanned={payload['scanned_lines']}, accepted_unique={payload['accepted_unique']})"
    )
    return 0 if payload["count"] >= args.target else 1


if __name__ == "__main__":
    raise SystemExit(main())
