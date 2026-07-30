import { API, apiFetch, formatApiError, refreshSession } from './transport.js';
import { t } from './i18n.js';

let currentPersonaId = '';
let toast = () => {};
let handlersBound = false;

function showToast(message, isError = false) {
  toast(message, isError);
}

function showPersonaPageStatus(message, isError = false) {
  const banner = document.getElementById('personaSaveStatusBanner');
  if (!banner) return;
  banner.textContent = message;
  banner.className = `mb-4 px-4 py-2 rounded-xl text-sm font-semibold ${
    isError
      ? 'bg-red-50 border border-red-200 text-red-700'
      : 'bg-green-50 border border-green-200 text-green-700'
  }`;
  banner.classList.remove('hidden');
  if (banner._hideTimer) {
    clearTimeout(banner._hideTimer);
    banner._hideTimer = null;
  }
  banner._hideTimer = setTimeout(() => {
    banner.classList.add('hidden');
    banner._hideTimer = null;
  }, 4000);
}

function enc(name) {
  return encodeURIComponent(name);
}

async function personaFetch(path) {
  if (!API.base) await refreshSession();
  const response = await fetch(`${API.base}${path}`, { cache: 'no-store' });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(formatApiError(error.detail, response.statusText));
  }
  return response.json();
}

async function deletePersonaByName(name) {
  if (!confirm(t('dynamic.appPersonaTopicPage.确定删除人格_name_吗', { name }))) return;
  try {
    await apiFetch(`/api/personae/${enc(name)}`, { method: 'DELETE' });
    if (currentPersonaId === name) currentPersonaId = '';
    showToast(t('dynamic.appPersonaTopicPage.已删除'));
    await loadPersonaEditor();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function loadPersonaeCheckboxes(containerId) {
  const data = await personaFetch('/api/personae');
  const box = document.getElementById(containerId);
  if (!box) return data;
  box.innerHTML = '';

  // W-PERSONA-MODEL-BIND-001：取自定义模型档案列表，渲染每行模型下拉
  let modelItems = [];
  try {
    const models = await apiFetch('/api/custom-models');
    modelItems = Array.isArray(models?.items) ? models.items : [];
  } catch (e) {
    console.warn('loadPersonaeCheckboxes: fetch custom-models failed:', e);
  }

  data.items.forEach((item) => {
    const row = document.createElement('div');
    row.className =
      'flex items-center gap-2 px-3 py-2 bg-cream rounded-xl text-sm font-semibold text-warmText';
    const label = document.createElement('label');
    label.className = 'toggle-switch flex items-center gap-2 flex-1 min-w-0 cursor-pointer';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.setAttribute('role', 'switch');
    cb.value = item.id;
    cb.checked = !!item.active;
    cb.className = 'shrink-0';
    const span = document.createElement('span');
    span.className = 'truncate';
    span.textContent = item.label;
    label.append(cb, span);
    row.appendChild(label);

    // 模型下拉：只显示该人格的显式绑定，未绑定时保持未绑定状态
    const select = document.createElement('select');
    select.className =
      'shrink-0 max-w-[9rem] px-2 py-1 bg-white border border-gray-200 rounded-lg text-xs font-normal ui-control ui-select';
    select.title = t('dynamic.appPersonaTopicPage.为该人格选择模型');
    const placeholderOpt = document.createElement('option');
    placeholderOpt.value = '';
    placeholderOpt.textContent = t('dynamic.appPersonaTopicPage.未绑定');
    placeholderOpt.disabled = true;
    select.appendChild(placeholderOpt);
    modelItems.forEach((m) => {
      const opt = document.createElement('option');
      const mid = (m.default_model_id || m.modelId || '').trim();
      opt.value = mid;
      const incomplete = m.complete === false;
      opt.textContent = incomplete
        ? t('dynamic.appPersonaTopicPage.m_name_mid_未完成', { label: m.name || mid })
        : (m.name || mid);
      select.appendChild(opt);
    });
    const boundModelId = (item.model_id || '').trim();
    if (boundModelId) {
      select.value = boundModelId;
      // 若绑定值不在选项中（模型已删但绑定未清），回退到 placeholder
      if (!Array.from(select.options).some((o) => o.value === boundModelId)) {
        select.value = '';
      }
    } else {
      select.value = '';
    }
    const applyBinding = async (newModelId, rollbackTo) => {
      try {
        await apiFetch(`/api/personae/${enc(item.id)}/model`, {
          method: 'PUT',
          body: JSON.stringify({ model_id: newModelId }),
        });
        showToast(newModelId ? t('dynamic.appPersonaTopicPage.模型已绑定') : t('dynamic.appPersonaTopicPage.已清除绑定'));
      } catch (error) {
        if (rollbackTo !== undefined) select.value = rollbackTo;
        showToast(error.message, true);
      }
    };
    const previousValue = select.value;
    select.addEventListener('change', () => {
      applyBinding(select.value, previousValue);
    });
    row.appendChild(select);

    if (!item.builtin) {
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className =
        'shrink-0 px-2 py-1 border border-red-200 rounded-lg text-xs text-red-600 hover:bg-red-50 ui-button ui-button--secondary ui-button--sm';
      delBtn.textContent = t('common.delete');
      delBtn.title = t('dynamic.appPersonaTopicPage.删除人格_item_label', { label: item.label });
      delBtn.addEventListener('click', (event) => {
        event.preventDefault();
        deletePersonaByName(item.id);
      });
      row.appendChild(delBtn);
    }
    box.appendChild(row);
  });
  return data;
}

async function loadLiveTopic() {
  const input = document.getElementById('liveTopicInput');
  if (!input) return;
  try {
    const cfg = await apiFetch('/api/config');
    input.value = cfg?.live_topic ?? '';
  } catch (error) {
    console.warn('loadLiveTopic failed:', error);
  }
}

async function saveLiveTopic() {
  const input = document.getElementById('liveTopicInput');
  if (!input) return;
  const value = (input.value || '').trim().slice(0, 200);
  await apiFetch('/api/config', {
    method: 'PUT',
    body: JSON.stringify({ live_topic: value }),
  });
  input.value = value;
}

async function loadUserNickname() {
  const input = document.getElementById('userNicknameInput');
  if (!input) return;
  try {
    const cfg = await apiFetch('/api/config');
    input.value = cfg?.user_nickname ?? '';
  } catch (error) {
    console.warn('loadUserNickname failed:', error);
  }
}

async function saveUserNickname() {
  const input = document.getElementById('userNicknameInput');
  if (!input) return;
  const value = (input.value || '').trim().slice(0, 20);
  await apiFetch('/api/config', {
    method: 'PUT',
    body: JSON.stringify({ user_nickname: value }),
  });
  input.value = value;
}

export async function loadPersonaTemplate() {
  const name = document.getElementById('personaSelect')?.value;
  if (!name) return;
  currentPersonaId = name;
  const tpl = await personaFetch(`/api/personae/${enc(name)}/template`);
  const personaContract = document.getElementById('personaContract');
  if (personaContract) personaContract.value = tpl.reply_contract || '';
  const personaSystemCustom = document.getElementById('personaSystemCustom');
  if (personaSystemCustom) personaSystemCustom.value = tpl.system_custom || '';
  const personaSystemPtFull = document.getElementById('personaSystemPtFull');
  if (personaSystemPtFull) personaSystemPtFull.value = tpl.system_pt_full || '';
  const displayNameInput = document.getElementById('personaDisplayName');
  if (displayNameInput) displayNameInput.value = tpl.label || '';
  const systemEditable = tpl.system_editable ?? tpl.editable;
  if (personaSystemCustom) personaSystemCustom.readOnly = !systemEditable;
  const btnSavePersona = document.getElementById('btnSavePersona');
  if (btnSavePersona) btnSavePersona.disabled = tpl.can_save === false;
  const btnDeletePersona = document.getElementById('btnDeletePersona');
  if (btnDeletePersona) btnDeletePersona.style.display = tpl.builtin ? 'none' : '';
}

export async function loadPersonaEditor() {
  const data = await personaFetch('/api/personae');
  const select = document.getElementById('personaSelect');
  if (!select) return;
  select.innerHTML = '';
  const validIds = new Set(data.items.map((item) => item.id));
  data.items.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = item.label;
    select.appendChild(option);
  });
  // 如果当前选中的人格已被移除（如测试2），回退到第一个可用人格
  if (!currentPersonaId || !validIds.has(currentPersonaId)) {
    currentPersonaId = data.items.length ? data.items[0].id : '';
  }
  if (currentPersonaId) select.value = currentPersonaId;
  try {
    await loadPersonaTemplate();
  } catch (e) {
    console.warn('loadPersonaTemplate failed:', e);
  }
  await loadPersonaeCheckboxes('personaActiveList');
}

export async function loadOverviewGlobalFields() {
  await loadLiveTopic();
  await loadUserNickname();
}

function initPersonaTabs() {
  document.querySelectorAll('.persona-tabs .settings-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const tabId = tab.dataset.personaTab;
      document.querySelectorAll('.persona-tabs .settings-tab').forEach((t) => {
        const active = t.dataset.personaTab === tabId;
        t.classList.toggle('active', active);
        t.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      document.querySelectorAll('[data-persona-panel]').forEach((panel) => {
        const active = panel.dataset.personaPanel === tabId;
        panel.classList.toggle('active', active);
        panel.hidden = !active;
      });
    });
  });
}

export function initPersonaTopicPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;
  initPersonaTabs();

  document.getElementById('personaSelect')?.addEventListener('change', () => {
    loadPersonaTemplate().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnSaveLiveTopic')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    try {
      await window.withLoadingState(btn, btn.textContent, () => saveLiveTopic(), t('dynamic.appPersonaTopicPage.已保存'));
      showToast(t('dynamic.appPersonaTopicPage.主题已保存'));
      showPersonaPageStatus(t('dynamic.appPersonaTopicPage.主题已更新_下一次生成会使用新内容'));
    } catch (error) {
      showToast(error.message || t('dynamic.appPersonaTopicPage.主题保存失败'), true);
      showPersonaPageStatus(error.message || t('dynamic.appPersonaTopicPage.主题保存失败'), true);
    }
  });
  document.getElementById('btnSaveUserNickname')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    try {
      await window.withLoadingState(btn, btn.textContent, () => saveUserNickname(), t('dynamic.appPersonaTopicPage.已保存'));
      showToast(t('dynamic.appPersonaTopicPage.昵称已保存'));
      showPersonaPageStatus(t('dynamic.appPersonaTopicPage.昵称已更新_下一次生成会使用新内容'));
    } catch (error) {
      showToast(error.message || t('dynamic.appPersonaTopicPage.昵称保存失败'), true);
      showPersonaPageStatus(error.message || t('dynamic.appPersonaTopicPage.昵称保存失败'), true);
    }
  });
  document.getElementById('btnSavePersona')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    try {
      await window.withLoadingState(btn, btn.textContent, async () => {
        const name = document.getElementById('personaSelect')?.value;
        // 仅当存在 #personaDisplayName 时才随模板提交 label，避免缺失 DOM 时误清空展示名
        const displayNameEl = document.getElementById('personaDisplayName');
        const payload = {
          system_custom: document.getElementById('personaSystemCustom').value,
        };
        if (displayNameEl) {
          payload.label = displayNameEl.value?.trim() || '';
        }
        await apiFetch(`/api/personae/${enc(name)}/template`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
        loadPersonaTemplate().catch(console.error);
      }, t('dynamic.appPersonaTopicPage.已保存'));
      showToast(t('dynamic.appPersonaTopicPage.人格已保存'));
      showPersonaPageStatus(t('dynamic.appPersonaTopicPage.人格已更新_下一次生成会使用新内容'));
    } catch (error) {
      showToast(error.message, true);
      showPersonaPageStatus(error.message, true);
    }
  });
  document.getElementById('btnRestorePersona')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    await window.withLoadingState(btn, btn.textContent, async () => {
      const name = document.getElementById('personaSelect')?.value;
      try {
        const data = await apiFetch(`/api/personae/${enc(name)}/restore`, { method: 'POST' });
        document.getElementById('personaSystemCustom').value = data.system_custom || '';
        showToast(t('dynamic.appPersonaTopicPage.已恢复默认'));
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
  document.getElementById('btnNewPersona')?.addEventListener('click', async (e) => {
    const name = prompt(t('dynamic.appPersonaTopicPage.新人格名称'));
    if (!name?.trim()) return;
    if (/[/\\%#?]/.test(name)) {
      showToast(t('dynamic.appPersonaTopicPage.人格名称不能包含_等特殊字'), true);
      return;
    }
    const btn = e.currentTarget;
    await window.withLoadingState(btn, btn.textContent, async () => {
      try {
        await apiFetch('/api/personae', {
          method: 'POST',
          body: JSON.stringify({ name: name.trim() }),
        });
        currentPersonaId = name.trim();
        showToast(t('dynamic.appPersonaTopicPage.新人格已创建'));
        loadPersonaEditor().catch(console.error);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
  document.getElementById('btnRenamePersona')?.addEventListener('click', async (e) => {
    const name = document.getElementById('personaSelect')?.value;
    if (!name) return;
    const select = document.getElementById('personaSelect');
    const currentLabel =
      select?.selectedOptions?.[0]?.textContent?.trim() ||
      document.getElementById('personaDisplayName')?.value?.trim() ||
      name;
    const nextLabel = prompt(t('dynamic.appPersonaTopicPage.新显示名称'), currentLabel);
    if (nextLabel === null) return;
    const cleaned = (nextLabel || '').trim();
    if (!cleaned) {
      showToast(t('dynamic.appPersonaTopicPage.显示名称不能为空'), true);
      return;
    }
    if (/[/\\%#?]/.test(cleaned)) {
      showToast(t('dynamic.appPersonaTopicPage.人格名称不能包含_等特殊字'), true);
      return;
    }
    const btn = e.currentTarget;
    try {
      await window.withLoadingState(btn, btn.textContent, async () => {
        await apiFetch(`/api/personae/${enc(name)}/label`, {
          method: 'PUT',
          body: JSON.stringify({ label: cleaned }),
        });
        currentPersonaId = name;
        await loadPersonaEditor();
      }, t('dynamic.appPersonaTopicPage.已保存'));
      showToast(t('dynamic.appPersonaTopicPage.显示名称已更新'));
      showPersonaPageStatus(t('dynamic.appPersonaTopicPage.显示名称已更新_下一次生成会使用新内容'));
    } catch (error) {
      showToast(error.message, true);
      showPersonaPageStatus(error.message, true);
    }
  });
  document.getElementById('btnDeletePersona')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const name = document.getElementById('personaSelect')?.value;
    if (name) await window.withLoadingState(btn, btn.textContent, () => deletePersonaByName(name));
  });
  document.getElementById('btnSavePersonaActive')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    try {
      await window.withLoadingState(btn, btn.textContent, async () => {
        const active = [];
        document.querySelectorAll('#personaActiveList input:checked').forEach((cb) => {
          active.push(cb.value);
        });
        await apiFetch('/api/personae/active', {
          method: 'PUT',
          body: JSON.stringify({ active }),
        });
      }, t('dynamic.appPersonaTopicPage.已保存'));
      showToast(t('dynamic.appPersonaTopicPage.激活人格已更新'));
      showPersonaPageStatus(t('dynamic.appPersonaTopicPage.激活人格已更新_下一次生成会使用新内容'));
    } catch (error) {
      showToast(error.message, true);
      showPersonaPageStatus(error.message, true);
    }
  });
}
