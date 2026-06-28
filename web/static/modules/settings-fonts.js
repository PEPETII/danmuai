import { API, apiFetch, apiFormFetch } from './transport.js';

let fontDeps = {
  showToast: () => {},
};

export function configureSettingsFonts(deps) {
  fontDeps = { ...fontDeps, ...deps };
}

export async function uploadFontFile() {
  const input = document.getElementById('font_file_input');
  const file = input?.files?.[0];
  if (!file) {
    fontDeps.showToast('请先选择一个 .ttf 或 .otf 文件', true);
    return;
  }
  const form = new FormData();
  form.append('file', file, file.name);
  try {
    if (!API.token) {
      throw new Error('未获取会话令牌，请刷新页面或重启 DanmuAI');
    }
    const data = await apiFormFetch('/api/fonts/import', form);
    fontDeps.showToast(`已导入字体：${data.family}`, false);
    await loadFontFamilies();
    if (input) input.value = '';
  } catch (error) {
    fontDeps.showToast(`导入失败：${error.message || error}`, true);
  }
}

export async function loadFontFamilies() {
  try {
    if (!API.token) return;
    const data = await apiFetch('/api/fonts');
    refreshFontSelect(data.families || []);
    renderImportedFontsList(data.imported || []);
  } catch (error) {
    console.warn('loadFontFamilies failed:', error);
  }
}

function refreshFontSelect(families) {
  const builtin = ['Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'DengXian', 'Arial', 'Segoe UI'];
  const danmuSel = document.getElementById('danmu_font_family');
  const fltSel = document.getElementById('floating_panel_font_family');
  if (!danmuSel || !fltSel) return;
  const danmuCurrent = danmuSel.value;
  const fltCurrent = fltSel.value;
  const merged = Array.from(new Set([...builtin, ...families]));
  const buildOptions = (current) => {
    const opts = ['<option value="">— 系统默认 —</option>'];
    merged.forEach((family) => {
      const safe = String(family).replace(/"/g, '&quot;');
      opts.push(`<option value="${safe}">${safe}</option>`);
    });
    if (current && !merged.includes(current)) {
      const safe = String(current).replace(/"/g, '&quot;');
      opts.push(`<option value="${safe}">自定义：${safe}</option>`);
    }
    return opts.join('');
  };
  danmuSel.innerHTML = buildOptions(danmuCurrent);
  fltSel.innerHTML = buildOptions(fltCurrent);
  danmuSel.value = danmuCurrent;
  fltSel.value = fltCurrent;
}

function renderImportedFontsList(imported) {
  const list = document.getElementById('importedFontsList');
  const tmpl = document.getElementById('fontRowTemplate');
  if (!list || !tmpl) return;
  list.innerHTML = '';
  imported.forEach((item) => {
    const node = tmpl.content.firstElementChild.cloneNode(true);
    node.querySelector('.font-family').textContent = item.family;
    node.querySelector('.font-meta').textContent =
      `（${item.original_name} · ${(item.size / 1024).toFixed(1)} KB）`;
    node.querySelector('.btn-delete-font').addEventListener('click', async () => {
      if (!confirm(`确认删除已导入字体「${item.family}」？此操作不可撤销。`)) return;
      try {
        await apiFetch(`/api/fonts/${item.sha256}`, { method: 'DELETE' });
        fontDeps.showToast(`已删除字体：${item.family}`, false);
        const danmuSel = document.getElementById('danmu_font_family');
        const fltSel = document.getElementById('floating_panel_font_family');
        if (danmuSel && danmuSel.value === item.family) danmuSel.value = '';
        if (fltSel && fltSel.value === item.family) fltSel.value = '';
        await loadFontFamilies();
      } catch (error) {
        fontDeps.showToast(`删除失败：${error.message || error}`, true);
      }
    });
    list.appendChild(node);
  });
}

const DANMU_COLOR_SWATCHES = [
  { hex: '#FF0000', name: '红' },
  { hex: '#FFA500', name: '橙' },
  { hex: '#FFFF00', name: '黄' },
  { hex: '#00FF00', name: '绿' },
  { hex: '#0000FF', name: '蓝' },
  { hex: '#4B0082', name: '靛' },
  { hex: '#800080', name: '紫' },
  { hex: '#FFFFFF', name: '默认' },
];

function getSelectedColors() {
  const container = document.getElementById('danmuFontColorSwatches');
  if (!container) return [];
  return Array.from(container.querySelectorAll('.color-swatch.selected')).map(
    (el) => el.dataset.color
  );
}

function updateHiddenSelected() {
  const el = document.getElementById('danmu_font_color_selected');
  if (el) el.value = JSON.stringify(getSelectedColors());
}

function updateHiddenMode() {
  const el = document.getElementById('danmu_font_color_mode');
  const radio = document.querySelector('input[name="danmu_font_color_mode_radio"]:checked');
  if (el && radio) el.value = radio.value;
}

function updateHiddenWeights() {
  const el = document.getElementById('danmu_font_color_weights');
  const weights = {};
  document.querySelectorAll('#danmuFontColorWeights .weight-input').forEach((input) => {
    const color = input.dataset.color;
    if (color) {
      const v = parseFloat(input.value);
      weights[color] = Number.isNaN(v) ? 0 : v;
    }
  });
  if (el) el.value = JSON.stringify(weights);
}

function normalizeWeights() {
  const inputs = Array.from(document.querySelectorAll('#danmuFontColorWeights .weight-input'));
  const values = inputs.map((input) => {
    const v = parseFloat(input.value);
    return Number.isNaN(v) ? 0 : v;
  });
  const total = values.reduce((a, b) => a + b, 0);
  inputs.forEach((input, idx) => {
    const label = input.parentElement?.querySelector('.weight-percent');
    if (!label) return;
    if (total > 0) {
      const pct = (values[idx] / total) * 100;
      label.textContent = `${pct.toFixed(1)}%`;
    } else {
      const equalPct = values.length > 0 ? 100 / values.length : 0;
      label.textContent = `${equalPct.toFixed(1)}%`;
    }
  });
}

function renderWeightInputs() {
  const container = document.getElementById('danmuFontColorWeights');
  if (!container) return;
  const selected = getSelectedColors();
  if (selected.length < 2) {
    container.classList.add('hidden');
    return;
  }
  const mode = document.querySelector('input[name="danmu_font_color_mode_radio"]:checked')?.value;
  if (mode !== 'weighted') {
    container.classList.add('hidden');
    return;
  }
  container.classList.remove('hidden');

  // 保留已有输入值
  const existing = {};
  container.querySelectorAll('.weight-input').forEach((input) => {
    if (input.dataset.color) existing[input.dataset.color] = input.value;
  });

  container.innerHTML = '';
  selected.forEach((color) => {
    const row = document.createElement('div');
    row.className = 'flex items-center gap-3';
    row.innerHTML = `
      <div class="w-6 h-6 rounded-md border border-gray-300 shrink-0" style="background-color:${color}"></div>
      <span class="text-sm text-warmText font-mono w-16">${color}</span>
      <input type="number" min="0" max="100" step="0.1" value="${existing[color] ?? '1'}"
        class="weight-input settings-field-control w-20 px-2 py-1 text-sm" data-color="${color}">
      <span class="weight-percent text-xs text-gray-500 w-12"></span>
    `;
    container.appendChild(row);
  });

  container.querySelectorAll('.weight-input').forEach((input) => {
    input.addEventListener('input', () => {
      normalizeWeights();
      updateHiddenWeights();
    });
  });
  normalizeWeights();
  updateHiddenWeights();
}

function initColorSwatches() {
  const container = document.getElementById('danmuFontColorSwatches');
  if (!container) return;
  container.innerHTML = '';
  DANMU_COLOR_SWATCHES.forEach(({ hex, name }) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'color-swatch w-10 h-10 rounded-lg border-2 transition transform hover:scale-105 focus:outline-none';
    btn.style.backgroundColor = hex;
    btn.style.borderColor = '#9ca3af';
    btn.dataset.color = hex;
    btn.title = name;
    btn.setAttribute('aria-pressed', 'false');
    btn.addEventListener('click', () => {
      btn.classList.toggle('selected');
      const isSelected = btn.classList.contains('selected');
      btn.setAttribute('aria-pressed', String(isSelected));
      if (isSelected) {
        btn.style.borderColor = '#000000';
        btn.style.transform = 'scale(1.05)';
      } else {
        btn.style.borderColor = '#9ca3af';
        btn.style.transform = '';
      }
      updateHiddenSelected();
      renderWeightInputs();
    });
    container.appendChild(btn);
  });
}

function initColorModeToggle() {
  document.querySelectorAll('input[name="danmu_font_color_mode_radio"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      updateHiddenMode();
      renderWeightInputs();
    });
  });
}

export function syncColorUIFromConfig(cfg) {
  // 回显色块
  const selectedRaw = cfg?.danmu_font_color_selected ?? '["#FFFFFF"]';
  let selected = [];
  try {
    selected = JSON.parse(selectedRaw);
  } catch {
    selected = ['#FFFFFF'];
  }
  if (!Array.isArray(selected) || selected.length === 0) {
    selected = ['#FFFFFF'];
  }
  const container = document.getElementById('danmuFontColorSwatches');
  if (container) {
    container.querySelectorAll('.color-swatch').forEach((btn) => {
      const hex = btn.dataset.color;
      const isSelected = selected.includes(hex);
      btn.classList.toggle('selected', isSelected);
      btn.setAttribute('aria-pressed', String(isSelected));
      if (isSelected) {
        btn.style.borderColor = '#000000';
        btn.style.transform = 'scale(1.05)';
      } else {
        btn.style.borderColor = '#9ca3af';
        btn.style.transform = '';
      }
    });
  }
  updateHiddenSelected();

  // 回显模式 radio
  const mode = cfg?.danmu_font_color_mode ?? 'equal';
  const equalRadio = document.getElementById('danmuFontColorModeEqual');
  const weightedRadio = document.getElementById('danmuFontColorModeWeighted');
  if (equalRadio) equalRadio.checked = mode !== 'weighted';
  if (weightedRadio) weightedRadio.checked = mode === 'weighted';
  updateHiddenMode();

  // 回显权重输入
  renderWeightInputs();
  const weightsRaw = cfg?.danmu_font_color_weights ?? '{}';
  let weightsMap = {};
  try {
    weightsMap = JSON.parse(weightsRaw);
  } catch {
    weightsMap = {};
  }
  if (typeof weightsMap === 'object' && weightsMap !== null) {
    document.querySelectorAll('#danmuFontColorWeights .weight-input').forEach((input) => {
      const color = input.dataset.color;
      if (color && weightsMap[color] !== undefined) {
        input.value = String(weightsMap[color]);
      }
    });
    normalizeWeights();
    updateHiddenWeights();
  }
}

export function bindFontControls() {
  document.getElementById('btnImportFont')?.addEventListener('click', uploadFontFile);
  initColorSwatches();
  initColorModeToggle();
  loadFontFamilies();
}
