"""Hygiene: partials must not grow bare <style>; index build sources exist."""

from __future__ import annotations

import re
from pathlib import Path

# Known historical debt: model tag chips styles still live in modals partial.
# Do not expand this set; migrate to warm-tokens-*.css then remove.
_ALLOW_STYLE_BLOCKS: frozenset[str] = frozenset(
    {
        "modals.html",
    }
)

# Inline style="" is discouraged; soft cap avoids one-off layout escapes failing CI.
_MAX_INLINE_STYLE_ATTRS = 8

_STYLE_OPEN = re.compile(r"<\s*style\b", re.IGNORECASE)
_INLINE_STYLE = re.compile(r"""\sstyle\s*=\s*["']""", re.IGNORECASE)


def _static_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "web" / "static"


def _partials_dir() -> Path:
    return _static_dir() / "partials"


def _list_partials() -> list[Path]:
    root = _partials_dir()
    assert root.is_dir(), f"missing partials dir: {root}"
    files = sorted(root.glob("*.html"))
    assert files, "no partial HTML files"
    return files


def test_settings_partial_has_no_style_block():
    settings = _partials_dir() / "settings.html"
    text = settings.read_text(encoding="utf-8")
    assert _STYLE_OPEN.search(text) is None, (
        "settings.html must not contain <style> "
        "(legacy rules belong in warm-tokens-compat.css)"
    )


def test_partials_style_blocks_only_on_allowlist():
    offenders: list[str] = []
    for path in _list_partials():
        text = path.read_text(encoding="utf-8")
        if _STYLE_OPEN.search(text) and path.name not in _ALLOW_STYLE_BLOCKS:
            offenders.append(path.name)
    assert not offenders, (
        "bare <style> only allowed on allowlisted partials "
        f"{sorted(_ALLOW_STYLE_BLOCKS)}; found in: {offenders}"
    )


def test_allowlisted_style_partials_still_exist_when_listed():
    for name in _ALLOW_STYLE_BLOCKS:
        path = _partials_dir() / name
        assert path.is_file(), f"allowlist entry missing file: {name}"
        text = path.read_text(encoding="utf-8")
        assert _STYLE_OPEN.search(text) is not None, (
            f"{name} is allowlisted for <style> but has none — "
            "remove from _ALLOW_STYLE_BLOCKS after migration"
        )


def test_inline_style_attr_count_within_soft_cap():
    total = 0
    per_file: list[tuple[str, int]] = []
    for path in _list_partials():
        text = path.read_text(encoding="utf-8")
        n = len(_INLINE_STYLE.findall(text))
        total += n
        if n:
            per_file.append((path.name, n))
    assert total <= _MAX_INLINE_STYLE_ATTRS, (
        f"inline style= attrs in partials: {total} > cap {_MAX_INLINE_STYLE_ATTRS}; "
        f"per-file: {per_file}"
    )


def test_partials_no_data_i18n_as_text_content():
    """data-i18n must be an attribute, not text after `>` (UI F2 regression)."""
    # e.g. wrong:  <button class="..."> data-i18n="key"Label</button>
    # correct:     <button class="..." data-i18n="key">Label</button>
    bad = re.compile(r">\s*data-i18n\s*=", re.IGNORECASE)
    offenders: list[str] = []
    for path in _list_partials():
        text = path.read_text(encoding="utf-8")
        if bad.search(text):
            offenders.append(path.name)
    assert not offenders, (
        "misplaced data-i18n text content in partials: "
        f"{offenders}; move data-i18n onto the opening tag"
    )


def test_index_build_sources_exist():
    static = _static_dir()
    assert (static / "build_index_html.py").is_file()
    assert (static / "index.template.html").is_file()
    assert (static / "index.html").is_file()
    for name in (
        "sidebar.html",
        "overview.html",
        "settings.html",
        "style-generator.html",
        "content-pages.html",
        "modals.html",
    ):
        assert (_partials_dir() / name).is_file(), f"missing partial {name}"


def test_index_html_matches_build_output():
    """Shipped index.html must match build_index_html (no hand-edits)."""
    import importlib.util

    build_path = _static_dir() / "build_index_html.py"
    spec = importlib.util.spec_from_file_location("danmu_build_index_html", build_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    expected = mod.build_index_html()
    actual = (_static_dir() / "index.html").read_text(encoding="utf-8")
    assert actual == expected, (
        "web/static/index.html is out of date; run: "
        "python web/static/build_index_html.py"
    )
