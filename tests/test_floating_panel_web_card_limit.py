"""Web floating panel card cap: no OOM loop when maxCards is exceeded.

W-FP-WEB-CARD-LIMIT-OOM-001: removeOldestIfNeeded must count non-exiting cards,
schedule exit once per node, and never while(children.length > maxCards).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP_JS = _ROOT / "web" / "static" / "floating_panel" / "app.js"


def _app_js_text() -> str:
    assert _APP_JS.is_file(), f"missing {_APP_JS}"
    return _APP_JS.read_text(encoding="utf-8")


def test_remove_oldest_not_while_on_children_length():
    """The OOM bug: while(panel.children.length > maxCards) never shrinks DOM."""
    src = _app_js_text()
    body = src.split("function removeOldestIfNeeded")[1].split("function addCard")[0]
    assert "while (panel.children.length > maxCards)" not in body
    assert "while(panel.children.length > maxCards)" not in body
    # Must not reintroduce length-based infinite while for the soft cap
    assert re.search(r"while\s*\(\s*panel\.children\.length\s*>\s*maxCards\s*\)", body) is None


def test_remove_oldest_uses_exiting_guard_and_active_count():
    src = _app_js_text()
    assert "function scheduleCardExit(node)" in src
    assert "classList.contains(\"exiting\")" in src
    remove_body = src.split("function removeOldestIfNeeded")[1].split("function addCard")[0]
    assert "scheduleCardExit" in remove_body
    assert "exiting" in remove_body
    # Soft cap must consider non-exiting / active, not raw children only
    assert "active" in remove_body or "needExit" in remove_body


def test_schedule_card_exit_is_idempotent_source():
    src = _app_js_text()
    sched = src.split("function scheduleCardExit(node)")[1].split(
        "function removeOldestIfNeeded"
    )[0]
    assert "contains(\"exiting\")" in sched
    assert "classList.add(\"exiting\")" in sched
    assert "setTimeout" in sched


def test_apply_config_triggers_remove_after_max_cards():
    src = _app_js_text()
    config_body = src.split("function applyConfig(msg)")[1].split(
        "function detachCard"
    )[0]
    assert "removeOldestIfNeeded()" in config_body


def test_exit_animation_path_preserved():
    """Bottom-up stack still uses .exiting + delayed removeChild (fadeOut CSS)."""
    src = _app_js_text()
    assert "classList.add(\"exiting\")" in src
    assert "exitDurationMs" in src
    css = (_ROOT / "web" / "static" / "floating_panel" / "style.css").read_text(
        encoding="utf-8"
    )
    assert ".card.exiting" in css
    assert "fadeOut" in css
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
const exitDurationMs = 10;
let setTimeoutCalls = 0;
const timers = [];

function setTimeout(fn, ms) {
  setTimeoutCalls += 1;
  timers.push({ fn, ms, fired: false });
  return setTimeoutCalls;
}

class ClassList {
  constructor(el) { this.el = el; this._set = new Set(); }
  add(c) { this._set.add(c); }
  contains(c) { return this._set.has(c); }
}

class Node {
  constructor() {
    this.classList = new ClassList(this);
    this.dataset = {};
    this.parentNode = null;
  }
}

class Panel {
  constructor() { this._kids = []; }
  get children() { return this._kids; }
  get firstElementChild() { return this._kids[0] || null; }
  appendChild(n) {
    n.parentNode = this;
    this._kids.push(n);
    return n;
  }
  removeChild(n) {
    const i = this._kids.indexOf(n);
    if (i >= 0) this._kids.splice(i, 1);
    n.parentNode = null;
    return n;
  }
}

const panel = new Panel();
const cardIds = new Set();

function detachCard(node) {
  if (!node) return;
  const id = node.dataset && node.dataset.cardId;
  if (node.parentNode) node.parentNode.removeChild(node);
  if (id) cardIds.delete(id);
}

function scheduleCardExit(node) {
  if (!node || !node.classList || node.classList.contains("exiting")) return;
  node.classList.add("exiting");
  const id = node.dataset && node.dataset.cardId;
  setTimeout(function () {
    if (node && node.parentNode) node.parentNode.removeChild(node);
    if (id) cardIds.delete(id);
  }, exitDurationMs);
}

function removeOldestIfNeeded() {
  if (!panel) return;
  const children = panel.children;
  let i;
  let active = 0;
  for (i = 0; i < children.length; i++) {
    if (!children[i].classList.contains("exiting")) active += 1;
  }
  let needExit = active - maxCards;
  for (i = 0; i < children.length && needExit > 0; i++) {
    if (children[i].classList.contains("exiting")) continue;
    scheduleCardExit(children[i]);
    needExit -= 1;
  }
  const hardLimit = Math.max(maxCards * 2, maxCards + 1);
  while (panel.children.length > hardLimit) {
    let drop = null;
    for (i = 0; i < panel.children.length; i++) {
      if (panel.children[i].classList.contains("exiting")) {
        drop = panel.children[i];
        break;
      }
    }
    if (!drop) drop = panel.firstElementChild;
    if (!drop) break;
    detachCard(drop);
  }
}

function addCard(id) {
  if (id && cardIds.has(id)) return;
  const card = new Node();
  if (id) {
    card.dataset.cardId = id;
    cardIds.add(id);
  }
  panel.appendChild(card);
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

function activeCount() {
  let n = 0;
  for (const c of panel.children) {
    if (!c.classList.contains("exiting")) n += 1;
  }
  return n;
}

if (activeCount() > maxCards) {
  console.error("FAIL active=" + activeCount());
  process.exit(3);
}
if (panel.children.length > maxCards * 2) {
  console.error("FAIL children=" + panel.children.length);
  process.exit(4);
}
// One timer per scheduled exit; must be finite and << N * N
if (setTimeoutCalls > N + 10) {
  console.error("FAIL timers=" + setTimeoutCalls);
  process.exit(5);
}
// Re-calling remove on full panel must not stack more timers on same nodes
const timersBefore = setTimeoutCalls;
removeOldestIfNeeded();
removeOldestIfNeeded();
if (setTimeoutCalls !== timersBefore) {
  console.error("FAIL reentry timers " + timersBefore + " -> " + setTimeoutCalls);
  process.exit(6);
}
// Fire all exit timers
for (const t of timers) {
  if (!t.fired) { t.fn(); t.fired = true; }
}
if (panel.children.length > maxCards) {
  console.error("FAIL after_exit children=" + panel.children.length);
  process.exit(7);
}
if (activeCount() > maxCards) {
  console.error("FAIL after_exit active=" + activeCount());
  process.exit(8);
}
console.log(JSON.stringify({
  ok: true,
  children: panel.children.length,
  active: activeCount(),
  timers: setTimeoutCalls,
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
    """Keep Node harness and app.js algorithm symbols aligned."""
    src = _app_js_text()
    for token in (
        "scheduleCardExit",
        "detachCard",
        "needExit",
        "hardLimit",
        "maxCards * 2",
    ):
        assert token in src, f"missing {token} in app.js"
