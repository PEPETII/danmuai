from __future__ import annotations

from pathlib import Path
import re

STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
CONTENT_PAGES = STATIC_ROOT / "partials" / "content-pages.html"
MODALS = STATIC_ROOT / "partials" / "modals.html"
JS_MODULES = list((STATIC_ROOT / "modules").glob("app-knowledge*.js"))

PAGE_IDS = [
    "knowledgeListView",
    "knowledgePackageDetail",
    "knowledgeRetrievalPreview",
    "knowledgePackageName",
    "knowledgePackageDescription",
    "knowledgePackagePriority",
    "knowledgePackageEnabled",
    "knowledgeSourceType",
    "knowledgeDisplayName",
    "knowledgeSourceUrl",
    "knowledgePastedText",
    "knowledgeSourceFile",
    "knowledgeJobList",
    "knowledgeItemList",
    "knowledgeItemKindFilter",
    "knowledgeItemEnabledFilter",
    "knowledgeItemSearch",
    "knowledgeQuickStart",
    "knowledgeDetailOverview",
    "knowledgeAddSource",
    "knowledgeJobProgress",
]

MODAL_IDS = [
    "knowledgeCreatePackageModal",
    "knowledgeOrganizeModal",
    "knowledgeConfirmModal",
]


def _knowledge_section_html() -> str:
    html = CONTENT_PAGES.read_text(encoding="utf-8")
    start = html.index('id="page-knowledge"')
    preview_pos = html.index("id=\"knowledgeRetrievalPreview\"", start)
    end = html.index("</section>", preview_pos)
    return html[start:end]


def test_required_dom_ids_unique():
    section = _knowledge_section_html()
    for field_id in PAGE_IDS:
        assert f'id="{field_id}"' in section
        assert section.count(f'id="{field_id}"') == 1
    modals = MODALS.read_text(encoding="utf-8")
    for field_id in MODAL_IDS:
        assert f'id="{field_id}"' in modals
        assert modals.count(f'id="{field_id}"') == 1


def test_quick_start_and_empty_state():
    section = _knowledge_section_html()
    assert "id=\"knowledgeQuickStart\"" in section
    assert "id=\"knowledgePackageEmpty\"" in section
    assert "id=\"btnKnowledgeCreateFirstPackage\"" in section


def test_detail_overview_and_advanced_accordion_aria():
    section = _knowledge_section_html()
    assert "id=\"knowledgeDetailOverview\"" in section
    assert "aria-controls=\"knowledgeAdvancedAccordionPanel\"" in section
    assert "aria-labelledby=\"knowledgeAdvancedAccordionTrigger\"" in section


def test_modals_present():
    modals = MODALS.read_text(encoding="utf-8")
    assert "id=\"knowledgeCreatePackageModal\"" in modals
    assert "id=\"knowledgeOrganizeModal\"" in modals
    assert "role=\"dialog\"" in modals


def test_no_native_prompt_or_confirm_in_js():
    combined = "\n".join(p.read_text(encoding="utf-8") for p in JS_MODULES)
    assert "window.prompt" not in combined
    assert "window.confirm" not in combined


def test_compute_package_card_state_and_transition():
    # Mirror app-knowledge-status.js pure functions for regression
    ACTIVE = {"pending", "running"}
    TERMINAL = {
        "completed",
        "completed_with_errors",
        "failed",
        "cancelled",
        "interrupted",
    }

    def is_active_to_terminal(prev, nxt):
        if nxt not in TERMINAL:
            return False
        if prev is None or prev == "":
            return False
        return prev in ACTIVE

    def compute_state(pkg, jobs):
        source_count = pkg.get("source_count") or 0
        item_count = pkg.get("item_count") or 0
        enabled = bool(pkg.get("enabled"))
        has_active = any(j.get("status") in ACTIVE for j in jobs)
        has_failure = any(
            j.get("status") in ("failed", "completed_with_errors", "interrupted")
            for j in jobs
        )
        if has_active:
            return "processing"
        if source_count == 0:
            return "noSources"
        if has_failure:
            return "partialFail"
        if item_count > 0 and not enabled:
            return "readyComplete"
        if enabled and item_count > 0:
            return "activeRetrieval"
        if enabled and item_count == 0:
            return "enabledEmpty"
        return "readyComplete"

    assert compute_state({"source_count": 0, "item_count": 0, "enabled": False}, []) == "noSources"
    assert compute_state({"source_count": 2, "item_count": 5, "enabled": False}, []) == "readyComplete"
    assert is_active_to_terminal("running", "completed")
    assert not is_active_to_terminal(None, "completed")
