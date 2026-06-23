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

export function bindFontControls() {
  document.getElementById('btnImportFont')?.addEventListener('click', uploadFontFile);
  loadFontFamilies();
}
