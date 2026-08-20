from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PET_PAGE_JS = ROOT / "web" / "static" / "modules" / "app-pet-page.js"
PET_PAGE_MJS_TEST = Path(__file__).with_name("test_pet_page_barrage_slots.mjs")


def _extract_function_body(source: str, function_name: str) -> str:
    marker = f"function {function_name}"
    export_marker = f"export function {function_name}"
    start = source.find(export_marker)
    if start < 0:
        start = source.find(marker)
    assert start >= 0, f"{function_name} not found"
    brace_start = source.index("{", start)
    depth = 0
    for index in range(brace_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start : index + 1]
    raise AssertionError(f"unterminated body for {function_name}")


def test_pet_page_barrage_slot_renderer_avoids_unsafe_inner_html():
    source = PET_PAGE_JS.read_text(encoding="utf-8")

    assert "card.innerHTML" not in source
    assert re.search(r"innerHTML\s*=\s*`", source) is None

    create_body = _extract_function_body(source, "createBarrageSlotCard")
    assert "innerHTML" not in create_body
    assert "textContent" in create_body
    assert "display_name" in create_body
    assert "resource_label" in create_body
    assert "asset.error" in create_body

    render_body = _extract_function_body(source, "renderBarrageSlots")
    assert "innerHTML" not in render_body
    assert "createBarrageSlotCard" in render_body


def test_pet_page_asset_error_and_labels_use_text_content():
    source = PET_PAGE_JS.read_text(encoding="utf-8")

    assert "errorEl.textContent = message" in source
    assert "setText(" in source
    assert re.search(r"petAssetErrorText.*innerHTML", source) is None


def test_pet_page_js_passes_node_syntax_check():
    result = subprocess.run(
        ["node", "--check", str(PET_PAGE_JS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_pet_page_barrage_slot_dom_safety_node():
    result = subprocess.run(
        ["node", str(PET_PAGE_MJS_TEST)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr or result.stdout
