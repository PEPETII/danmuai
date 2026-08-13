"""Web floating panel card cap: the DOM must never exceed maxCards.

W-FP-WEB-CARD-LIMIT-002: max-card eviction is synchronous so an exiting node
cannot remain in flex layout and expose maxCards + 1 during the next frame.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP_JS = _ROOT / "web" / "static" / "floating_panel" / "app.js"


def _app_js_text() -> str:
    assert _APP_JS.is_file(), f"missing {_APP_JS}"
    return _APP_JS.read_text(encoding="utf-8")


def test_remove_oldest_loops_until_card_cap():
    """The bounded loop removes one oldest node per iteration."""
    src = _app_js_text()
    body = src.split("function removeOldestIfNeeded")[1].split("function addCard")[0]
    assert "while (panel.children.length > maxCards)" in body
    assert "lastElementChild" in body
    assert "removeChild" in body


def test_remove_oldest_does_not_leave_exit_nodes_in_layout():
    src = _app_js_text()
    remove_body = src.split("function removeOldestIfNeeded")[1].split("function addCard")[0]
    assert "scheduleCardExit" not in remove_body
    assert "exiting" not in remove_body
    assert "cardIds.delete" in remove_body


def test_apply_config_triggers_remove_after_max_cards():
    src = _app_js_text()
    config_body = src.split("function applyConfig(msg)")[1].split(
        "function removeOldestIfNeeded"
    )[0]
    assert "removeOldestIfNeeded()" in config_body


def test_exit_config_fields_remain_compatible():
    """旧 exit 配置字段仍可接收；最大条数淘汰不再延迟占位。"""
    src = _app_js_text()
    assert "exitDurationMs" in src
    css = (_ROOT / "web" / "static" / "floating_panel" / "style.css").read_text(
        encoding="utf-8"
    )
    assert "slideUp" in css


def _node_available() -> bool:
    try:
        r = subprocess.run(
            ["node", "-e", "process.exit(0)"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return r.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _node_available(), reason="node not available")
def test_burst_add_keeps_active_cards_bounded_node_sim():
    """Simulate panel DOM + removeOldestIfNeeded under burst adds (no infinite loop)."""
    # Self-contained Node harness mirrors the fixed algorithm (not eval of full app.js
    # which needs WebSocket/document). Contract tests above lock the real source.
    script = r"""
const maxCards = 6;
let removeCalls = 0;

class Panel {
  constructor() { this._kids = []; }
  get children() { return this._kids; }
  get lastElementChild() { return this._kids[this._kids.length - 1] || null; }
  prepend(n) {
    n.parentNode = this;
    this._kids.unshift(n);
    return n;
  }
  removeChild(n) {
    const i = this._kids.indexOf(n);
    if (i >= 0) this._kids.splice(i, 1);
    n.parentNode = null;
    removeCalls += 1;
    return n;
  }
}

const panel = new Panel();
const cardIds = new Set();

function removeOldestIfNeeded() {
  while (panel.children.length > maxCards) {
    const oldest = panel.lastElementChild;
    if (!oldest) break;
    panel.removeChild(oldest);
    if (oldest.id) cardIds.delete(oldest.id);
  }
}

function addCard(id) {
  if (id && cardIds.has(id)) return;
  const card = { id, parentNode: null };
  if (id) {
    cardIds.add(id);
  }
  panel.prepend(card);
  removeOldestIfNeeded();
}

const N = 200;
const start = Date.now();
for (let i = 0; i < N; i++) addCard("c" + i);
const elapsed = Date.now() - start;
if (elapsed > 2000) {
  console.error("FAIL slow_or_loop elapsed=" + elapsed);
  process.exit(2);
}
if (panel.children.length !== maxCards) {
  console.error("FAIL children=" + panel.children.length);
  process.exit(3);
}
const callsBefore = removeCalls;
removeOldestIfNeeded();
if (removeCalls !== callsBefore) {
  console.error("FAIL reentry removed=" + (removeCalls - callsBefore));
  process.exit(4);
}
console.log(JSON.stringify({
  ok: true,
  children: panel.children.length,
  remove_calls: removeCalls,
  elapsed_ms: elapsed,
}));
"""
    r = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if r.returncode != 0:
        pytest.fail(
            f"node sim failed rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
        )
    assert "ok" in r.stdout
    assert '"ok":true' in r.stdout.replace(" ", "")


def test_source_matches_node_sim_key_symbols():
    """Keep the source bounded-removal symbols visible to the Node smoke test."""
    src = _app_js_text()
    for token in (
        "removeOldestIfNeeded",
        "lastElementChild",
        "maxCards",
    ):
        assert token in src, f"missing {token} in app.js"
