export function createStyleGeneratorFonts({
  API,
  apiFetch,
  apiFormFetch,
  populateFontSelect,
  showToast,
}) {
  async function loadStyleGeneratorFontFamilies() {
    try {
      if (!API.token) return;
      const data = await apiFetch('/api/fonts');
      refreshStyleGeneratorFontSelect(data.families || []);
      renderStyleGeneratorImportedFontsList(data.imported || []);
    } catch (error) {
      console.warn('loadStyleGeneratorFontFamilies failed:', error);
    }
  }

  function refreshStyleGeneratorFontSelect(families) {
    const sel = document.getElementById('sg-floating_panel_font_family');
    if (!sel) return;
    populateFontSelect(sel, families, sel.value);
  }

  function renderStyleGeneratorImportedFontsList(imported) {
    const list = document.getElementById('sg-importedFontsList');
    const tmpl = document.getElementById('sg-fontRowTemplate');
    if (!list || !tmpl) return;
    list.innerHTML = '';
    imported.forEach((item) => {
      const node = tmpl.content.firstElementChild.cloneNode(true);
      node.querySelector('.font-family').textContent = item.family;
      node.querySelector('.font-meta').textContent =
        `（${item.original_name} · ${(item.size / 1024).toFixed(1)} KB）`;
      node.querySelector('.btn-delete-font').addEventListener('click', async () => {
        if (!confirm(`确认删除已导入字体「${item.family}」？`)) return;
        try {
          await apiFetch(`/api/fonts/${item.sha256}`, { method: 'DELETE' });
          showToast(`已删除字体「${item.family}」`);
          const sgSel = document.getElementById('sg-floating_panel_font_family');
          if (sgSel && sgSel.value === item.family) sgSel.value = '';
          await loadStyleGeneratorFontFamilies();
        } catch (error) {
          showToast(error.message || '删除失败', true);
        }
      });
      list.appendChild(node);
    });
  }

  async function uploadStyleGeneratorFont() {
    const input = document.getElementById('sg-font_file_input');
    const file = input?.files?.[0];
    if (!file) {
      showToast('请先选择一个 .ttf 或 .otf 文件', true);
      return;
    }
    const form = new FormData();
    form.append('file', file, file.name);
    try {
      if (!API.token) throw new Error('未获取会话令牌，请刷新页面或重启 DanmuAI');
      const data = await apiFormFetch('/api/fonts/import', form);
      showToast(`已导入字体「${data.family}」`);
      await loadStyleGeneratorFontFamilies();
      if (input) input.value = '';
    } catch (error) {
      showToast(error.message || '导入失败', true);
    }
  }

  return {
    loadStyleGeneratorFontFamilies,
    uploadStyleGeneratorFont,
  };
}
