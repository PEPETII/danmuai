"""Build the compact static index.html from template fragments.

This keeps the runtime contract unchanged: the shipped ``index.html`` still
contains the full static DOM tree, while the editable source is split into
maintainable partials under ``web/static/partials/``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "index.template.html"
OUTPUT_PATH = ROOT / "index.html"
PARTIALS = {
    "{{sidebar}}": ROOT / "partials" / "sidebar.html",
    "{{overview}}": ROOT / "partials" / "overview.html",
    "{{settings}}": ROOT / "partials" / "settings.html",
    "{{style_generator}}": ROOT / "partials" / "style-generator.html",
    "{{content_pages}}": ROOT / "partials" / "content-pages.html",
    "{{modals}}": ROOT / "partials" / "modals.html",
}


def _compact_html_fragment(text: str) -> str:
    """Collapse an HTML fragment to one logical line without changing DOM."""

    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def build_index_html() -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    for marker, partial_path in PARTIALS.items():
        fragment = _compact_html_fragment(partial_path.read_text(encoding="utf-8"))
        template = template.replace(marker, fragment)
    return template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check the output without rewriting it.')
    args = parser.parse_args()
    output = build_index_html()
    if args.check:
        if not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_text(encoding='utf-8') != output:
            print('index.html is stale; run python web/static/build_index_html.py.')
            return 1
        print('index.html matches its template and partials.')
        return 0
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
