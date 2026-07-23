"""Contract: CSS var(--token) references must be declared or have fallback."""

from __future__ import annotations

import re
from pathlib import Path

# Console warm-token CSS only (not floating_panel / tailwindcdn).
# W-UI-CSS-SPLIT-001: pages rules live in multiple files; scan all warm-tokens*.css.
_WARM_CSS_REQUIRED = (
    "warm-tokens-base.css",
    "warm-tokens-layout.css",
    "warm-tokens-components.css",
    "warm-tokens-compat.css",
    "warm-tokens-feedback.css",
    "warm-tokens-pages-overview.css",
    "warm-tokens-settings.css",
    "warm-tokens-live-output.css",
    "warm-tokens-danmu-pool.css",
    "warm-tokens-live-output-preview.css",
    "warm-tokens-pages-stylegen.css",
    "warm-tokens-ai-butler.css",
    "warm-tokens-pages.css",
    "warm-tokens-dark.css",
)

_VAR_REF = re.compile(
    r"var\(\s*(--[a-zA-Z0-9_-]+)\s*(?:,\s*([^)]+))?\)",
    re.MULTILINE,
)
_DECL = re.compile(
    r"(--[a-zA-Z0-9_-]+)\s*:",
    re.MULTILINE,
)
# Custom properties that are intentionally set per-element / runtime.
_ALLOW_UNDECLARED = frozenset(
    {
        # Tailwind / runtime may inject; keep empty by default.
    }
)


def _static_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "web" / "static"


def _read_warm_css() -> dict[str, str]:
    root = _static_dir()
    out: dict[str, str] = {}
    for name in _WARM_CSS_REQUIRED:
        path = root / name
        assert path.is_file(), f"missing {path}"
        out[name] = path.read_text(encoding="utf-8")
    return out


def _declared_tokens(css_by_file: dict[str, str]) -> set[str]:
    declared: set[str] = set()
    for text in css_by_file.values():
        declared.update(_DECL.findall(text))
    return declared


def _undeclared_refs_without_fallback(
    css_by_file: dict[str, str],
    declared: set[str],
) -> list[tuple[str, str]]:
    """Return list of (file, token) for var(--x) with no declaration and no fallback."""
    bad: list[tuple[str, str]] = []
    for name, text in css_by_file.items():
        for match in _VAR_REF.finditer(text):
            token = match.group(1)
            fallback = match.group(2)
            if token in declared or token in _ALLOW_UNDECLARED:
                continue
            if fallback is not None and fallback.strip():
                continue
            bad.append((name, token))
    return sorted(set(bad))


def test_required_design_tokens_declared_in_root():
    base = (_static_dir() / "warm-tokens-base.css").read_text(encoding="utf-8")
    required = [
        "--space-0",
        "--space-1",
        "--space-2",
        "--space-3",
        "--space-4",
        "--space-5",
        "--space-6",
        "--space-8",
        "--space-10",
        "--space-12",
        "--radius-xs",
        "--radius-sm",
        "--radius-md",
        "--radius-lg",
        "--radius-full",
        "--control-height-sm",
        "--control-height-md",
        "--control-height-lg",
        "--color-success",
        "--color-warning",
        "--color-info",
        "--color-danger",
        "--motion-fast",
        "--motion-normal",
        "--motion-slow",
        "--ease-standard",
    ]
    for token in required:
        assert re.search(rf"{re.escape(token)}\s*:", base), f"missing declaration {token}"


def test_dark_theme_declares_status_tokens():
    base = (_static_dir() / "warm-tokens-base.css").read_text(encoding="utf-8")
    dark_block = re.search(
        r'\[data-theme=["\']dark["\']\]\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}',
        base,
        re.DOTALL,
    )
    assert dark_block is not None, "missing [data-theme=dark] block"
    body = dark_block.group(0)
    for token in (
        "--color-success",
        "--color-warning",
        "--color-info",
        "--color-danger",
    ):
        assert re.search(rf"{re.escape(token)}\s*:", body), f"dark missing {token}"


def test_css_var_refs_declared_or_have_fallback():
    css_by_file = _read_warm_css()
    declared = _declared_tokens(css_by_file)
    bad = _undeclared_refs_without_fallback(css_by_file, declared)
    assert not bad, (
        "undeclared CSS variables without fallback:\n"
        + "\n".join(f"  {f}: {t}" for f, t in bad)
    )


def test_token_contract_fails_when_var_missing_declaration():
    """Self-check: synthetic CSS with undeclared var and no fallback is detected."""
    synthetic = {
        "fake.css": ".x { border-radius: var(--radius-not-real); }",
    }
    declared = _declared_tokens(synthetic)
    bad = _undeclared_refs_without_fallback(synthetic, declared)
    assert ("fake.css", "--radius-not-real") in bad

    with_fallback = {
        "fake.css": ".x { border-radius: var(--radius-not-real, 8px); }",
    }
    bad2 = _undeclared_refs_without_fallback(with_fallback, set())
    assert bad2 == []
