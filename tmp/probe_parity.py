"""Compare HEAD-committed zh/en locale shards for key parity.

Read-only probe: uses `git show HEAD:<path>` so neither commit state nor
working tree is modified. Prints which shards are asymmetric at HEAD.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARDS = ["common", "nav", "overview", "settings", "content", "modals", "hints", "dynamic"]


def git_show(path: str) -> str:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git show failed for {path}: {proc.stderr}")
    return proc.stdout


def flatten(obj, prefix: str = ""):
    out = {}
    for key, val in obj.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            out.update(flatten(val, full))
        else:
            out[full] = str(val)
    return out


def load_from_text(raw: str):
    return flatten(json.loads(raw))


def load_head(lang: str, shard: str):
    return load_from_text(git_show(f"web/static/locales/{lang}/{shard}.json"))


def load_worktree(lang: str, shard: str):
    path = REPO / "web" / "static" / "locales" / lang / f"{shard}.json"
    return load_from_text(path.read_text(encoding="utf-8"))


def compare(label: str, loader):
    lines = []
    for shard in SHARDS:
        zh = set(loader("zh", shard))
        en = set(loader("en", shard))
        only_zh = sorted(zh - en)
        only_en = sorted(en - zh)
        if only_zh or only_en:
            lines.append(f"[{shard}] only_zh={len(only_zh)} only_en={len(only_en)}")
            for k in only_zh[:5]:
                lines.append(f"   ZH-ONLY: {k}")
            for k in only_en[:5]:
                lines.append(f"   EN-ONLY: {k}")
    if not lines:
        lines.append("all shards zh/en key parity OK")
    return [f"===== {label} =====", *lines]


out = []
out += compare("HEAD (committed)", load_head)
out += compare("WORKING TREE", load_worktree)

(REPO / "tmp" / "probe_parity_out.txt").write_text("\n".join(out), encoding="utf-8")
print("written")
