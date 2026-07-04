"""Inject data-i18n attributes into web partials from zh locale shards (fast line-based)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"
LOCALES = STATIC / "locales" / "zh"

PARTIALS = [
    "partials/sidebar.html",
    "partials/overview.html",
    "partials/settings.html",
    "partials/content-pages.html",
    "partials/modals.html",
]

ATTR_MAP = {
    "placeholder": "data-i18n-placeholder",
    "aria-label": "data-i18n-aria-label",
    "title": "data-i18n-title",
}


def flatten(obj: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = str(v)
    return out


def load_rev() -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in sorted(LOCALES.glob("*.json")):
        if path.name.startswith("_"):
            continue
        merged.update(flatten(json.loads(path.read_text(encoding="utf-8"))))
    rev: dict[str, str] = {}
    for key, text in merged.items():
        if text and text not in rev:
            rev[text] = key
    return rev


def inject_line(line: str, rev: dict[str, str]) -> str:
    if "data-i18n" in line:
        return line
    for attr, data_attr in ATTR_MAP.items():
        pat = rf'{attr}="([^"]+)"'
        m = re.search(pat, line)
        if m and re.search(r"[\u4e00-\u9fff]", m.group(1)):
            key = rev.get(m.group(1))
            if key:
                line = line.replace(f'{attr}="', f'{data_attr}="{key}" {attr}="', 1)
    # simple >text< at end of line
    m = re.search(r">([\u4e00-\u9fff][^<]{0,120})<\s*$", line)
    if m and "data-i18n=" not in line:
        text = m.group(1).strip()
        key = rev.get(text)
        if key:
            line = line.replace(f">{text}<", f' data-i18n="{key}">{text}<', 1)
    return line


def process_file(rel: str, rev: dict[str, str]) -> int:
    path = STATIC / rel
    lines = path.read_text(encoding="utf-8").splitlines()
    out = [inject_line(ln, rev) for ln in lines]
    text = "\n".join(out) + ("\n" if path.read_text(encoding="utf-8").endswith("\n") else "")
    count = text.count("data-i18n")
    path.write_text(text, encoding="utf-8")
    return count


def main() -> None:
    rev = load_rev()
    total = 0
    for rel in PARTIALS:
        n = process_file(rel, rev)
        print(f"{rel}: {n}")
        total += n
    print(f"total: {total}")


if __name__ == "__main__":
    main()
