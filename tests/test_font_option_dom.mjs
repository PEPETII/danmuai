import assert from 'node:assert/strict';
import test from 'node:test';

class FakeOption {
  constructor() {
    this.tagName = 'OPTION';
    this.children = [];
    this.value = '';
    this.textContent = '';
  }
}

class FakeSelect {
  constructor(value = '') {
    this.tagName = 'SELECT';
    this.children = [];
    this.value = value;
    this.replaceChildrenCalls = 0;
  }

  get options() {
    return this.children;
  }

  replaceChildren(...children) {
    this.replaceChildrenCalls += 1;
    this.children = children;
  }
}

class FakeDocument {
  constructor() {
    this.createdTags = [];
  }

  createElement(tagName) {
    this.createdTags.push(tagName);
    assert.equal(tagName, 'option');
    return new FakeOption();
  }
}

globalThis.document = new FakeDocument();
const { populateFontSelect } = await import('../web/static/modules/settings-fonts.js');

const builtinFamilies = [
  'Microsoft YaHei',
  'SimHei',
  'SimSun',
  'KaiTi',
  'DengXian',
  'Arial',
  'Segoe UI',
];

function optionSignature(select) {
  return select.options.map((option) => ({
    value: option.value,
    text: option.textContent,
    childCount: option.children.length,
  }));
}

test('both font selects preserve raw family values through DOM options', () => {
  const families = [
    'Imported 中文 😀',
    '  Noto Sans  ',
    '<>&"\'',
    '</option><img src=x onerror=alert(1)>',
    '',
    'Imported 中文 😀',
  ];
  const expectedFamilies = Array.from(new Set([...builtinFamilies, ...families]));
  const danmuSelect = new FakeSelect('  Noto Sans  ');
  const floatingSelect = new FakeSelect('</option><img src=x onerror=alert(1)>');

  populateFontSelect(danmuSelect, families);
  populateFontSelect(floatingSelect, families);

  for (const select of [danmuSelect, floatingSelect]) {
    assert.equal(select.replaceChildrenCalls, 1);
    assert.equal(select.options.length, expectedFamilies.length + 1);
    assert.deepEqual(select.options.slice(1).map((option) => option.value), expectedFamilies);
    assert.deepEqual(select.options.slice(1).map((option) => option.textContent), expectedFamilies);
    assert.equal(select.options[0].value, '');
    assert.equal(select.options[0].textContent, '系统默认');
    assert.equal(select.options[0].textContent.includes('<option'), false);
    assert.ok(select.options.every((option) => option.tagName === 'OPTION'));
    assert.ok(select.options.every((option) => option.children.length === 0));
  }

  assert.equal(danmuSelect.value, '  Noto Sans  ');
  assert.equal(floatingSelect.value, '</option><img src=x onerror=alert(1)>');
  assert.deepEqual(optionSignature(danmuSelect), optionSignature(floatingSelect));
});

test('a configured family missing from the API list is appended without HTML parsing', () => {
  const current = 'Persisted <custom> "font"';
  const select = new FakeSelect(current);

  populateFontSelect(select, ['Arial']);

  const custom = select.options.at(-1);
  assert.equal(custom.value, current);
  assert.equal(custom.textContent, current);
  assert.equal(custom.children.length, 0);
  assert.equal(select.value, current);
  assert.equal(select.options.filter((option) => option.value === current).length, 1);
});
