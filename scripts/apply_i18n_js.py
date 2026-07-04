"""Replace Chinese string literals in web JS with t('key') calls."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"

SKIP = frozenset({"i18n.js", "language.js"})


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
    loc = STATIC / "locales" / "zh"
    for name in ("common.json", "dynamic.json", "overview.json", "settings.json", "content.json", "modals.json", "nav.json", "hints.json"):
        p = loc / name
        if p.exists():
            merged.update(flatten(json.loads(p.read_text(encoding="utf-8"))))
    rev: dict[str, str] = {}
    for key, text in merged.items():
        if text and re.search(r"[\u4e00-\u9fff]", text) and text not in rev:
            rev[text] = key
    return rev


def ensure_import(content: str, is_app: bool) -> str:
    needle = "./modules/i18n.js" if is_app else "./i18n.js"
    if needle in content:
        return content
    imp = f"import {{ t }} from '{needle}';\n"
    idx = content.find("\n", content.find("import "))
    if idx == -1:
        return imp + content
    return content[: idx + 1] + imp + content[idx + 1 :]


def patch_content(content: str, rev: dict[str, str]) -> tuple[str, int]:
    count = 0
    # sort by length desc for greedy match
    items = sorted(rev.items(), key=lambda x: len(x[0]), reverse=True)

    def repl(m: re.Match) -> str:
        nonlocal count
        text = m.group(1)
        key = rev.get(text)
        if not key:
            return m.group(0)
        count += 1
        return f"t('{key}')"

    for text, _key in items:
        if text not in content:
            continue
        esc = re.escape(text)
        content = re.sub(rf"'({esc})'", repl, content)
        content = re.sub(rf'"({esc})"', repl, content)
        content = re.sub(rf"`({esc})`", repl, content)
    return content, count


def main() -> None:
    rev = load_rev()
    total = 0
    files = sorted((STATIC / "modules").glob("*.js")) + [STATIC / "app.js"]
    for path in files:
        if path.name in SKIP:
            continue
        content = path.read_text(encoding="utf-8")
        patched, n = patch_content(content, rev)
        if n:
            patched = ensure_import(patched, path.name == "app.js")
            path.write_text(patched, encoding="utf-8")
            print(f"{path.name}: {n}")
            total += n
    print(f"total: {total}")


if __name__ == "__main__":
    main()
