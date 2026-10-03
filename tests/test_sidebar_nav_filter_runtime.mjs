import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const APP_PATH = new URL("../web/static/app.js", import.meta.url);

async function loadInitializer() {
  const source = await readFile(APP_PATH, "utf8");
  const start = source.indexOf("function initSidebarNavDisclosure()");
  const braceStart = source.indexOf("{", start);
  let depth = 0;
  let end = -1;
  for (let index = braceStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) {
        end = index + 1;
        break;
      }
    }
  }
  assert.ok(start >= 0 && end > start);
  return Function(`return (${source.slice(start, end)})`)();
}

function createHarness() {
  let clickHandler;
  const attributes = new Map();
  const labels = [
    { dataset: { sidebarDisclosureLabel: "expand" }, hidden: false, textContent: "展开高级功能与工具" },
    { dataset: { sidebarDisclosureLabel: "collapse" }, hidden: true, textContent: "收起高级功能与工具" },
  ];
  const toggle = {
    classList: { toggle() {} },
    querySelectorAll(selector) {
      assert.equal(selector, "[data-sidebar-disclosure-label]");
      return labels;
    },
    setAttribute(name, value) {
      attributes.set(name, value);
    },
    addEventListener(_event, handler) {
      clickHandler = handler;
    },
  };
  const enhancedItems = { hidden: true };
  globalThis.document = {
    getElementById(id) {
      if (id === "btnSidebarEnhancedToggle") return toggle;
      if (id === "sidebarEnhancedItems") return enhancedItems;
      return null;
    },
  };
  return { attributes, clickHandler: () => clickHandler(), enhancedItems, labels };
}

test("sidebar enhanced disclosure defaults collapsed and toggles without navigation", async () => {
  const initialize = await loadInitializer();
  const { attributes, clickHandler, enhancedItems, labels } = createHarness();
  initialize();

  assert.equal(enhancedItems.hidden, true);
  assert.equal(attributes.get("aria-expanded"), "false");
  assert.equal(attributes.get("data-i18n-aria-label"), "nav.expandEnhanced");
  assert.equal(attributes.get("aria-label"), "展开高级功能与工具");
  assert.deepEqual(labels.map((label) => label.hidden), [false, true]);

  clickHandler();
  assert.equal(enhancedItems.hidden, false);
  assert.equal(attributes.get("aria-expanded"), "true");
  assert.equal(attributes.get("data-i18n-aria-label"), "nav.collapseEnhanced");
  assert.equal(attributes.get("aria-label"), "收起高级功能与工具");
  assert.deepEqual(labels.map((label) => label.hidden), [true, false]);

  clickHandler();
  assert.equal(enhancedItems.hidden, true);
  assert.equal(attributes.get("aria-expanded"), "false");
});
