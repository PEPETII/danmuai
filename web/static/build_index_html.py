"""Build the compact static index.html from template fragments.

This keeps the runtime contract unchanged: the shipped ``index.html`` still
contains the full static DOM tree, while the editable source is split into
maintainable partials under ``web/static/partials/``.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "index.template.html"
OUTPUT_PATH = ROOT / "index.html"
PARTIALS = {
    "{{sidebar}}": ROOT / "partials" / "sidebar.html",
    "{{overview}}": ROOT / "partials" / "overview.html",
    "{{settings}}": ROOT / "partials" / "settings.html",
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


def main() -> None:
    output = build_index_html()
    OUTPUT_PATH.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
