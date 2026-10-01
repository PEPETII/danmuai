import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const APP_PATH = new URL("../web/static/app.js", import.meta.url);

async function loadInitializer() {
  const source = await readFile(APP_PATH, "utf8");
  const start = source.indexOf("function initSidebarNavCategoryFilter()");
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
  const handlers = new Map();
  const buttons = ["common", "enhanced"].map((filter) => ({
    dataset: { navFilter: filter },
    classList: { toggle() {} },
    setAttribute() {},
    addEventListener(_event, handler) {
      handlers.set(filter, handler);
    },
  }));
  const items = ["common", "common", "enhanced"].map((scope, index) => ({
    dataset: { navScope: scope },
    hidden: true,
    className: index === 0 ? "sidebar-item active" : "sidebar-item",
  }));
  const filterRoot = {
    dataset: {},
    querySelectorAll(selector) {
      assert.equal(selector, "[data-nav-filter]");
      return buttons;
    },
  };
  const nav = {
    querySelectorAll(selector) {
      assert.equal(selector, "[data-nav-scope]");
      return items;
    },
  };
  globalThis.document = {
    getElementById(id) {
      return id === "sidebarNavFilter" ? filterRoot : nav;
    },
  };
  return { filterRoot, handlers, items };
}

test("sidebar filter defaults to common and switches to disjoint enhanced items", async () => {
  const initialize = await loadInitializer();
  const { filterRoot, handlers, items } = createHarness();
  initialize();

  assert.deepEqual(items.map((item) => item.hidden), [false, false, true]);
  assert.equal(filterRoot.dataset.activeFilter, "common");
  assert.equal(items[0].className, "sidebar-item active");

  handlers.get("enhanced")();
  assert.deepEqual(items.map((item) => item.hidden), [true, true, false]);
  assert.equal(filterRoot.dataset.activeFilter, "enhanced");
  assert.equal(items[0].className, "sidebar-item active");
});
