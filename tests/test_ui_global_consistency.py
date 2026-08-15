"""Static contracts for the cross-page UI consistency pass."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


class _RoleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tabs: list[dict[str, str]] = []
        self.panels: list[dict[str, str]] = []
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("id"):
            self.ids.append(values["id"])
        if values.get("role") == "tab":
            self.tabs.append(values)
        if values.get("role") == "tabpanel":
            self.panels.append(values)


def _static_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "web" / "static"


def _index_parser() -> _RoleParser:
    parser = _RoleParser()
    parser.feed((_static_dir() / "index.html").read_text(encoding="utf-8"))
    return parser


def test_all_static_tabs_have_panel_relationships() -> None:
    parser = _index_parser()
    panel_ids = {item["id"] for item in parser.panels if item.get("id")}
    tab_ids = {item["id"] for item in parser.tabs if item.get("id")}

    assert len(parser.tabs) == 19
    assert len(tab_ids) == len(parser.tabs)
    assert len(parser.panels) == 19
    assert all(tab.get("aria-controls") in panel_ids for tab in parser.tabs)
    assert all(panel.get("aria-labelledby") in tab_ids for panel in parser.panels)


def test_static_ui_ids_are_unique_and_feedback_is_announced() -> None:
    parser = _index_parser()
    assert len(parser.ids) == len(set(parser.ids))

    template = (_static_dir() / "index.template.html").read_text(encoding="utf-8")
    overview = (_static_dir() / "partials" / "overview.html").read_text(encoding="utf-8")
    assert 'id="toast"' in template and 'aria-live="polite"' in template
    assert 'id="errorBanner"' in overview and 'role="alert"' in overview


def test_shared_control_and_responsive_guards_are_declared() -> None:
    base = (_static_dir() / "warm-tokens-base.css").read_text(encoding="utf-8")
    components = (_static_dir() / "warm-tokens-components.css").read_text(encoding="utf-8")
    pages = (_static_dir() / "warm-tokens-pages.css").read_text(encoding="utf-8")
    overview = (_static_dir() / "warm-tokens-pages-overview.css").read_text(encoding="utf-8")

    assert "body.ui-shell" in base
    assert "button.ui-button" in components
    assert "input.ui-control" in components
    assert ".settings-tab,\n.danmu-pool-tab,\n.sg-tab" in pages
    assert ".toast--error" in overview
    assert "@media (max-width: 520px)" in pages
