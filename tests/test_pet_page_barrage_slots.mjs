import assert from 'node:assert/strict';
import { test } from 'node:test';

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...names) {
    names.forEach((name) => this.values.add(name));
  }

  contains(name) {
    return this.values.has(name);
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.className = '';
    this.classList = new FakeClassList();
    this.dataset = {};
    this.children = [];
    this.textContent = '';
    this.innerHTML = '';
    this.attributes = {};
    this._src = '';
    this._alt = '';
  }

  get src() {
    return this._src;
  }

  set src(value) {
    this._src = value;
    this.attributes.src = value;
  }

  get alt() {
    return this._alt;
  }

  set alt(value) {
    this._alt = value;
    this.attributes.alt = value;
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  appendChild(node) {
    this.children.push(node);
    return node;
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }
}

class FakeDocument {
  createElement(tagName) {
    return new FakeElement(tagName);
  }
}

globalThis.document = new FakeDocument();
globalThis.t = (key) => {
  const labels = {
    'dynamic.appPetPage.默认桌宠': '默认桌宠',
    'dynamic.appPetPage.内置默认': '内置默认',
  };
  return labels[key] || key;
};

const { createBarrageSlotCard } = await import('../web/static/modules/app-pet-page.js');

function collectText(node) {
  const parts = [node.textContent || ''];
  for (const child of node.children || []) {
    parts.push(collectText(child));
  }
  return parts.join('');
}

function findElements(node, tagName) {
  const matches = node.tagName === tagName.toUpperCase() ? [node] : [];
  for (const child of node.children || []) {
    matches.push(...findElements(child, tagName));
  }
  return matches;
}

test('malicious barrage slot metadata renders as plain text', () => {
  const payload = {
    display_name: '<img src=x onerror=alert(1)>',
    resource_label: '<script>alert(1)</script>',
    error: '"><svg onload=alert(1)>',
  };
  const slot = { asset_path: 'javascript:alert(1)' };
  const card = createBarrageSlotCard(0, slot, payload);

  assert.equal(card.innerHTML, '');
  assert.match(collectText(card), /<img src=x onerror=alert\(1\)>/);
  assert.match(collectText(card), /<script>alert\(1\)<\/script>/);
  assert.match(collectText(card), /javascript:alert\(1\)/);
  assert.match(collectText(card), /"><svg onload=alert\(1\)>/);

  const images = findElements(card, 'img');
  assert.equal(images.length, 1);
  assert.equal(images[0].attributes.src, '/api/pet/barrage-slots/0/preview');

  const buttons = findElements(card, 'button');
  assert.equal(buttons.length, 2);
  assert.equal(buttons[0].dataset.slotId, '0');
  assert.equal(buttons[1].dataset.slotAction, 'reset');
});

test('normal barrage slot metadata keeps readable labels', () => {
  const card = createBarrageSlotCard(
    2,
    { asset_path: 'C:/桌宠/小猫' },
    { display_name: '小猫', resource_label: '本地目录', error: '' },
  );

  const text = collectText(card);
  assert.match(text, /槽位 3/);
  assert.match(text, /小猫/);
  assert.match(text, /本地目录/);
  assert.match(text, /C:\/桌宠\/小猫/);
});
