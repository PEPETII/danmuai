"""Scan Web/Python sources for i18n gaps; write a text report under scripts/output/."""
from __future__ import annotations

import json
import os
import re
from html.parser import HTMLParser

# scripts/ → repo root
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPORT_DIR = os.path.join(BASE, "scripts", "output")
REPORT_PATH = os.path.join(REPORT_DIR, "i18n_scan_report.txt")


def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, full))
        else:
            out[full] = str(v)
    return out


def load_locales():
    zh_dir = os.path.join(BASE, "web", "static", "locales", "zh")
    en_dir = os.path.join(BASE, "web", "static", "locales", "en")
    zh, en = {}, {}
    for name in os.listdir(zh_dir):
        if name.endswith(".json"):
            with open(os.path.join(zh_dir, name), "r", encoding="utf-8") as f:
                zh.update(flatten(json.load(f)))
            with open(os.path.join(en_dir, name), "r", encoding="utf-8") as f:
                en.update(flatten(json.load(f)))
    return zh, en


def has_chinese(text):
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def has_meaningful_text(text):
    return bool(re.search(r"[a-zA-Z]{3,}|[\u4e00-\u9fff]", text))


class I18nHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self._current_tag = None
        self._current_attrs = None
        self._skip_depth = 0

    def _line(self):
        return super().getpos()[0]

    def handle_starttag(self, tag, attrs):
        self._current_tag = tag
        self._current_attrs = dict(attrs)
        if tag in ("script", "style", "template"):
            self._skip_depth += 1
            return
        line = self._line()
        for attr in ["placeholder", "aria-label", "title"]:
            if attr in self._current_attrs:
                val = self._current_attrs[attr]
                if val and has_meaningful_text(val):
                    i18n_attr = f"data-i18n-{attr}" in self._current_attrs
                    self.items.append((line, attr, val, i18n_attr, tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template"):
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        line = self._line()
        text = data.strip()
        if text and has_meaningful_text(text):
            self.items.append((line, "text", text, False, self._current_tag, self._current_attrs))


def find_unwrapped_chinese_literals(content):
    cleaned = re.sub(r"//[^\n]*", "\n", content)
    cleaned = re.sub(r"/\*[\s\S]*?\*/", "", cleaned)
    pattern = r'(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|`((?:[^`\\]|\\.)*)`)'
    results = []
    for m in re.finditer(pattern, cleaned):
        val = m.group(1) if m.group(1) is not None else (m.group(2) if m.group(2) is not None else m.group(3))
        if not val or not has_chinese(val):
            continue
        before = cleaned[max(0, m.start() - 30) : m.start()]
        if re.search(r"(?:t|i18n\.t)\s*\(\s*$", before):
            continue
        line_num = cleaned[: m.start()].count("\n") + 1
        results.append((line_num, val))
    return results


def scan_html_file(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    parser = I18nHtmlParser()
    parser.feed(content)
    results = []
    for line, cat, snippet, has_i18n, tag, attrs in parser.items:
        results.append((path, line, cat, snippet, has_i18n, tag))
    return results


def scan_js_file(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    results = []
    for line, val in find_unwrapped_chinese_literals(content):
        results.append((path, line, val))
    return results


def scan_python_file(path):
    """Scan Python file for lines containing Chinese."""
    results = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f, 1):
            if has_chinese(line):
                # Skip comments and docstrings with simple heuristic
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                results.append((path, i, line.strip()))
    return results


def main():
    zh, en = load_locales()
    all_zh_values = set(zh.values())
    all_en_values = set(en.values())

    lines = []
    lines.append("=== Locale key differences ===")
    only_in_zh = set(zh) - set(en)
    only_in_en = set(en) - set(zh)
    lines.append(f"Keys in zh missing in en: {len(only_in_zh)}")
    for k in sorted(only_in_zh):
        lines.append(f"  {k}: {zh[k][:80]!r}")
    lines.append(f"\nKeys in en missing in zh: {len(only_in_en)}")
    for k in sorted(only_in_en):
        lines.append(f"  {k}: {en[k][:80]!r}")

    lines.append("\n=== HTML: unwrapped visible text / attributes (template + partials + live-overlay) ===")
    partials_dir = os.path.join(BASE, "web", "static", "partials")
    html_files = [
        os.path.join(BASE, "web", "static", "index.template.html"),
        os.path.join(BASE, "web", "static", "live-overlay.html"),
    ] + [
        os.path.join(partials_dir, f)
        for f in os.listdir(partials_dir)
        if f.endswith(".html")
    ]
    for path in html_files:
        if not os.path.exists(path):
            continue
        for item in scan_html_file(path):
            path_out, line, cat, snippet, has_i18n, tag = item
            in_dict = snippet in all_zh_values or snippet in all_en_values
            lines.append(
                f"{path_out}:{line} | [{cat}] {snippet[:120]!r} | "
                f"wrapped_attr={has_i18n} in_locale={in_dict} tag={tag}"
            )

    lines.append("\n=== JS: unwrapped Chinese string literals ===")
    modules_dir = os.path.join(BASE, "web", "static", "modules")
    app_js = os.path.join(BASE, "web", "static", "app.js")
    for path in [app_js] + [
        os.path.join(modules_dir, f) for f in os.listdir(modules_dir) if f.endswith(".js")
    ]:
        for p, line, val in scan_js_file(path):
            lines.append(f"{p}:{line} | {val[:120]!r}")

    lines.append("\n=== Python: lines containing Chinese strings ===")
    for root, dirs, files in os.walk(os.path.join(BASE, "app")):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            for p, line, text in scan_python_file(path):
                lines.append(f"{p}:{line} | {text[:120]}")

    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
