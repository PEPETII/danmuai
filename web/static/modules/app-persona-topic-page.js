import { API, apiFetch, formatApiError, refreshSession } from './transport.js';

let currentPersonaId = '';
let toast = () => {};
let handlersBound = false;

function showToast(message, isError = false) {
  toast(message, isError);
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
  if (!confirm(`确定删除人格“${name}”吗？`)) return;
  try {
    await apiFetch(`/api/personae/${enc(name)}`, { method: 'DELETE' });
    if (currentPersonaId === name) currentPersonaId = '';
    showToast('已删除');
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
  data.items.forEach((item) => {
    const row = document.createElement('div');
    row.className =
      'flex items-center gap-2 px-3 py-2 bg-cream rounded-xl text-sm font-semibold text-warmText';
    const label = document.createElement('label');
    label.className = 'flex items-center gap-2 flex-1 min-w-0 cursor-pointer';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = item.id;
    cb.checked = !!item.active;
    cb.className = 'rounded accent-[#FFA5A5] shrink-0';
    const span = document.createElement('span');
    span.className = 'truncate';
    span.textContent = item.label;
    label.append(cb, span);
    row.appendChild(label);
    if (!item.builtin) {
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className =
        'shrink-0 px-2 py-1 border border-red-200 rounded-lg text-xs text-red-600 hover:bg-red-50';
      delBtn.textContent = '删除';
      delBtn.title = `删除人格“${item.label}”`;
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
  try {
    await apiFetch('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ live_topic: value }),
    });
    input.value = value;
    showToast(value ? '主题已保存' : '主题已清空');
  } catch (error) {
    showToast(error.message || '主题保存失败', true);
  }
}

async function loadPersonaNamePrefix() {
  const input = document.getElementById('personaNamePrefixEnabled');
  if (!input) return;
  try {
    const cfg = await apiFetch('/api/config');
    input.checked = String(cfg?.persona_name_prefix_enabled ?? '0') === '1';
  } catch (error) {
    console.warn('loadPersonaNamePrefix failed:', error);
  }
}

async function savePersonaNamePrefix() {
  const input = document.getElementById('personaNamePrefixEnabled');
  if (!input) return;
  const value = input.checked ? '1' : '0';
  try {
    await apiFetch('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ persona_name_prefix_enabled: value }),
    });
    showToast(value === '1' ? '名称显示已开启' : '名称显示已关闭');
  } catch (error) {
    showToast(error.message || '名称显示保存失败', true);
  }
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
  try {
    await apiFetch('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ user_nickname: value }),
    });
    input.value = value;
    showToast(value ? '昵称已保存' : '昵称已清空');
  } catch (error) {
    showToast(error.message || '昵称保存失败', true);
  }
}

export async function loadPersonaTemplate() {
  const name = document.getElementById('personaSelect')?.value;
  if (!name) return;
  currentPersonaId = name;
  const tpl = await personaFetch(`/api/personae/${enc(name)}/template`);
  document.getElementById('personaContract').value = tpl.reply_contract || '';
  document.getElementById('personaSystemCustom').value = tpl.system_custom || '';
  document.getElementById('personaSystemPtFull').value = tpl.system_pt_full || '';
  const systemEditable = tpl.system_editable ?? tpl.editable;
  document.getElementById('personaSystemCustom').readOnly = !systemEditable;
  document.getElementById('btnSavePersona').disabled = tpl.can_save === false;
  document.getElementById('btnDeletePersona').style.display = tpl.builtin ? 'none' : '';
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
  await loadPersonaNamePrefix();
}

export async function loadOverviewGlobalFields() {
  await loadLiveTopic();
  await loadUserNickname();
}

export function initPersonaTopicPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;

  document.getElementById('personaSelect')?.addEventListener('change', () => {
    loadPersonaTemplate().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnSaveLiveTopic')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    window.withLoadingState(btn, btn.textContent, () =>
      saveLiveTopic()
    ).catch((error) => showToast(error.message || '主题保存失败', true));
  });
  document.getElementById('btnSaveUserNickname')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    window.withLoadingState(btn, btn.textContent, () =>
      saveUserNickname()
    ).catch((error) => showToast(error.message || '昵称保存失败', true));
  });
  document.getElementById('personaNamePrefixEnabled')?.addEventListener('change', () => {
    savePersonaNamePrefix().catch((error) => showToast(error.message || '名称显示保存失败', true));
  });
  document.getElementById('btnSavePersona')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    await window.withLoadingState(btn, btn.textContent, async () => {
      const name = document.getElementById('personaSelect')?.value;
      try {
        await apiFetch(`/api/personae/${enc(name)}/template`, {
          method: 'PUT',
          body: JSON.stringify({
            system_custom: document.getElementById('personaSystemCustom').value,
          }),
        });
        showToast('人格已保存');
        loadPersonaTemplate().catch(console.error);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
  document.getElementById('btnRestorePersona')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    await window.withLoadingState(btn, btn.textContent, async () => {
      const name = document.getElementById('personaSelect')?.value;
      try {
        const data = await apiFetch(`/api/personae/${enc(name)}/restore`, { method: 'POST' });
        document.getElementById('personaSystemCustom').value = data.system_custom || '';
        showToast('已恢复默认');
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
  document.getElementById('btnNewPersona')?.addEventListener('click', async (e) => {
    const name = prompt('新人格名称：');
    if (!name?.trim()) return;
    if (/[/\\%#?]/.test(name)) {
      showToast('人格名称不能包含 / \\ % # ? 等特殊字符', true);
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
        showToast('新人格已创建');
        loadPersonaEditor().catch(console.error);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
  document.getElementById('btnDeletePersona')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const name = document.getElementById('personaSelect')?.value;
    if (name) await window.withLoadingState(btn, btn.textContent, () => deletePersonaByName(name));
  });
  document.getElementById('btnSavePersonaActive')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    await window.withLoadingState(btn, btn.textContent, async () => {
      const active = [];
      document.querySelectorAll('#personaActiveList input:checked').forEach((cb) => {
        active.push(cb.value);
      });
      try {
        await apiFetch('/api/personae/active', {
          method: 'PUT',
          body: JSON.stringify({ active }),
        });
        showToast('激活人格已更新');
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
}
