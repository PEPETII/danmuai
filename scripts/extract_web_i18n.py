"""Extract Chinese UI strings from web/static into locale skeleton."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
PARTIALS = [
    "partials/sidebar.html",
    "partials/overview.html",
    "partials/settings.html",
    "partials/content-pages.html",
    "partials/modals.html",
]


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def add_key(keys: dict[str, str], domain: str, sub: str, text: str) -> None:
    text = text.strip()
    if not text or not has_cjk(text):
        return
    base = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text[:24]).strip("_") or "item"
    key = f"{domain}.{sub}.{base}"
    n = 2
    orig = key
    while key in keys and keys[key] != text:
        key = f"{orig}_{n}"
        n += 1
    keys[key] = text


def main() -> None:
    keys: dict[str, str] = {}
    hints_path = ROOT / "modules" / "settings-hints.js"
    if hints_path.exists():
        txt = hints_path.read_text(encoding="utf-8")
        for m in re.finditer(r"(\w+):\s*'([^']+)'", txt):
            add_key(keys, "hints", m.group(1), m.group(2))

    for rel in PARTIALS:
        name = Path(rel).stem
        content = (ROOT / rel).read_text(encoding="utf-8")
        for m in re.finditer(r">([^<]{1,200})<", content):
            add_key(keys, name, "text", m.group(1))
        for attr in ("placeholder", "aria-label", "title"):
            pat = rf'{attr}="([^"]+)"'
            for m in re.finditer(pat, content):
                add_key(keys, name, attr.replace("-", "_"), m.group(1))

    js_files = list((ROOT / "modules").glob("*.js")) + [ROOT / "app.js"]
    for jp in js_files:
        if not jp.exists():
            continue
        name = jp.stem
        txt = jp.read_text(encoding="utf-8")
        for m in re.finditer(r"['`]([^'`\n]{2,120})['`]", txt):
            add_key(keys, "dynamic", name, m.group(1))

    out = ROOT / "locales" / "_extracted_zh.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"extracted {len(keys)} keys -> {out}")


if __name__ == "__main__":
    main()
