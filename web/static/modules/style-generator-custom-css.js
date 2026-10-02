export function createStyleGeneratorCustomCss({
  apiFetch,
  apiFormFetch,
  t,
  showToast,
  readStr,
  setFieldValue,
  setPreviewCustomCss,
  syncPresetSelect,
  syncPresetVisibility,
  markDirty,
  scheduleStyleSave,
}) {
  let customCssFiles = [];
  let customCssTemplates = [];
  let customCssText = '';
  let customCssTemplateActive = null;

  function customCssTemplateById(id) {
    return customCssTemplates.find((item) => String(item.id) === String(id)) || null;
  }

  function showCustomCssTemplate(template) {
    if (!template) return;
    customCssTemplateActive = template;
    const modal = document.getElementById('sgCustomCssTemplateModal');
    const title = document.getElementById('sgCustomCssTemplateModalTitle');
    const description = document.getElementById('sgCustomCssTemplateDescription');
    const text = document.getElementById('sgCustomCssTemplateText');
    if (title) title.textContent = template.name || 'CSS 模板';
    if (description) description.textContent = template.description || '';
    if (text) text.value = template.css || '';
    if (modal) modal.hidden = false;
  }

  function closeCustomCssTemplate() {
    const modal = document.getElementById('sgCustomCssTemplateModal');
    if (modal) modal.hidden = true;
    customCssTemplateActive = null;
  }

  async function copyCustomCssText(text) {
    const value = String(text || '');
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const helper = document.createElement('textarea');
        helper.value = value;
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.appendChild(helper);
        helper.select();
        document.execCommand('copy');
        helper.remove();
      }
      showToast(t('dynamic.appStyleGenerator.CSS模板已复制'));
    } catch (error) {
      showToast(error.message || t('dynamic.appStyleGenerator.复制失败'), true);
    }
  }

  function renderCustomCssTemplateButtons() {
    const wrap = document.getElementById('sgCustomCssTemplateButtons');
    if (!wrap) return;
    wrap.textContent = '';
    customCssTemplates.forEach((template) => {
      const view = document.createElement('button');
      view.type = 'button';
      view.className = 'ui-button ui-button--secondary ui-button--sm';
      view.textContent = `查看${template.name || 'CSS 模板'}`;
      view.addEventListener('click', () => showCustomCssTemplate(template));
      wrap.appendChild(view);

      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'ui-button ui-button--secondary ui-button--sm';
      copy.textContent = `复制${template.name || 'CSS 模板'}`;
      copy.addEventListener('click', () => copyCustomCssText(template.css));
      wrap.appendChild(copy);
    });
  }

  function renderCustomCssFiles(files) {
    const list = document.getElementById('sgCustomCssFileList');
    const empty = document.getElementById('sgCustomCssFileEmpty');
    if (!list) return;
    list.textContent = '';
    const selected = readStr('floating_panel_custom_css_file', '');
    const entries = Array.isArray(files) ? files : [];
    if (empty) empty.hidden = entries.length > 0;
    entries.forEach((item) => {
      const fileName = String(item.file_name || item.name || '').trim();
      if (!fileName) return;
      const label = document.createElement('label');
      label.className = 'sg-custom-css-file-option';
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'sgCustomCssFileChoice';
      input.value = fileName;
      input.checked = fileName === selected;
      input.addEventListener('change', () => {
        if (!input.checked) return;
        setFieldValue('floating_panel_custom_css_file', fileName);
        setFieldValue('floating_panel_style_preset', 'custom_css');
        syncPresetSelect('custom_css');
        syncPresetVisibility('custom_css');
        markDirty();
        scheduleStyleSave();
        loadCustomCssFile(fileName).catch((error) => showToast(error.message, true));
      });
      const name = document.createElement('span');
      name.className = 'sg-custom-css-file-name';
      name.textContent = fileName;
      label.append(input, name);
      list.appendChild(label);
    });
  }

  async function loadCustomCssFile(fileName) {
    const name = String(fileName || '').trim();
    if (!name) {
      customCssText = '';
      setPreviewCustomCss('');
      return;
    }
    const data = await apiFetch(`/api/floating-panel/custom-css/${encodeURIComponent(name)}`);
    customCssText = String(data.css || '');
    if (readStr('floating_panel_style_preset', '') === 'custom_css'
        && readStr('floating_panel_custom_css_file', '') === name) {
      setPreviewCustomCss(customCssText);
    }
  }

  async function loadStyleGeneratorCustomCssResources(selectedFile = '') {
    try {
      const [files, templates] = await Promise.all([
        apiFetch('/api/floating-panel/custom-css'),
        apiFetch('/api/floating-panel/custom-css/templates'),
      ]);
      customCssFiles = Array.isArray(files?.files) ? files.files : [];
      customCssTemplates = Array.isArray(templates?.templates) ? templates.templates : [];
      renderCustomCssFiles(customCssFiles);
      renderCustomCssTemplateButtons();
      const selected = String(selectedFile || readStr('floating_panel_custom_css_file', '')).trim();
      if (selected) {
        await loadCustomCssFile(selected);
      } else {
        customCssText = '';
        setPreviewCustomCss('');
      }
    } catch (error) {
      customCssFiles = [];
      customCssTemplates = [];
      renderCustomCssFiles([]);
      renderCustomCssTemplateButtons();
      customCssText = '';
      setPreviewCustomCss('');
      console.warn('loadStyleGeneratorCustomCssResources failed:', error);
    }
  }

  async function importCustomCssFile() {
    const input = document.getElementById('sgCustomCssFileInput');
    const file = input?.files?.[0];
    if (!file) {
      showToast(t('dynamic.appStyleGenerator.请先选择CSS文件'), true);
      return;
    }
    const form = new FormData();
    form.append('file', file, file.name);
    try {
      const data = await apiFormFetch('/api/floating-panel/custom-css/import', form);
      const fileName = String(data.file_name || '');
      setFieldValue('floating_panel_style_preset', 'custom_css');
      setFieldValue('floating_panel_custom_css_file', fileName);
      syncPresetSelect('custom_css');
      syncPresetVisibility('custom_css');
      markDirty();
      await loadStyleGeneratorCustomCssResources(fileName);
      renderCustomCssFiles(customCssFiles);
      scheduleStyleSave();
      showToast(t('dynamic.appStyleGenerator.CSS文件已导入'));
    } catch (error) {
      showToast(error.message || t('dynamic.appStyleGenerator.导入失败'), true);
    } finally {
      if (input) input.value = '';
    }
  }

  async function openCustomCssFolder() {
    try {
      await apiFetch('/api/floating-panel/custom-css/open-folder', { method: 'POST' });
    } catch (error) {
      showToast(error.message || t('dynamic.appStyleGenerator.打开文件夹失败'), true);
    }
  }

  return {
    clearText() {
      customCssText = '';
    },
    getActiveTemplateCss() {
      return customCssTemplateActive?.css || '';
    },
    getText() {
      return customCssText;
    },
    closeCustomCssTemplate,
    copyCustomCssText,
    importCustomCssFile,
    loadStyleGeneratorCustomCssResources,
    openCustomCssFolder,
  };
}
