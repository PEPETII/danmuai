import { apiFetch } from './transport.js';
import { t } from './i18n.js';
import { activateFocusTrap, deactivateFocusTrap } from './modal-focus-trap.js';

// currentPersonaId：下拉框当前选择；loadedPersonaId：当前 DOM 内容实际所属的人格。
// 两者与 tpl.id 三者一致时才允许保存，避免旧异步响应被当成新选择的内容。
let currentPersonaId = '';
let loadedPersonaId = '';
let personaTemplateLoading = false;
let personaTemplateError = false;
let personaTemplateCanSave = true;
let personaTemplateSystemEditable = true;
let templateLoadGeneration = 0;
let templateLoadController = null;
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

async function personaFetch(path, options = {}) {
  return apiFetch(path, { cache: 'no-store', ...options });
}

function isAbortError(error) {
  return error?.name === 'AbortError';
}

function selectedPersonaId() {
  return document.getElementById('personaSelect')?.value || '';
}

/** generation 与当前 select 双重校验：任何一项不满足即视为过期响应。 */
function isCurrentTemplateLoad(generation, personaId) {
  return generation === templateLoadGeneration && selectedPersonaId() === personaId;
}

function clearPersonaEditorDom() {
  const contract = document.getElementById('personaContract');
  if (contract) contract.value = '';
  const custom = document.getElementById('personaSystemCustom');
  if (custom) custom.value = '';
}

/** 按当前身份/加载状态统一刷新保存、恢复、只读与 aria-busy。 */
function syncPersonaEditorControls() {
  const ready = Boolean(loadedPersonaId) && loadedPersonaId === selectedPersonaId();
  const btnSave = document.getElementById('btnSavePersona');
  if (btnSave) {
    btnSave.disabled = personaTemplateLoading
      || personaTemplateError
      || !ready
      || !personaTemplateCanSave;
  }
  const custom = document.getElementById('personaSystemCustom');
  if (custom) {
    custom.readOnly = personaTemplateLoading || !ready || !personaTemplateSystemEditable;
  }
  const btnRestore = document.getElementById('btnRestorePersona');
  if (btnRestore) btnRestore.disabled = personaTemplateLoading || !ready;
  const panel = document.getElementById('personaTab-manage');
  if (panel) panel.setAttribute('aria-busy', personaTemplateLoading ? 'true' : 'false');
}

function writePersonaTemplate(tpl) {
  const personaContract = document.getElementById('personaContract');
  if (personaContract) personaContract.value = tpl.reply_contract || '';
  const personaSystemCustom = document.getElementById('personaSystemCustom');
  if (personaSystemCustom) personaSystemCustom.value = tpl.system_custom || '';
  personaTemplateSystemEditable = tpl.system_editable ?? tpl.editable ?? true;
  personaTemplateCanSave = tpl.can_save !== false;
  const btnDeletePersona = document.getElementById('btnDeletePersona');
  if (btnDeletePersona) btnDeletePersona.style.display = tpl.builtin ? 'none' : '';
}

/** 让所有在途模板加载失效（递增 generation + abort）；供新选择、重载与销毁复用。 */
export function cancelPersonaTemplateLoad() {
  templateLoadGeneration += 1;
  templateLoadController?.abort();
  templateLoadController = null;
}

async function deletePersonaByName(name) {
  if (!confirm(t('dynamic.appPersonaTopicPage.确定删除人格_name_吗', { name }))) return;
  try {
    await apiFetch(`/api/personae/${enc(name)}`, { method: 'DELETE' });
    if (currentPersonaId === name) currentPersonaId = '';
    if (loadedPersonaId === name) loadedPersonaId = '';
    cancelPersonaTemplateLoad();
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

    // W-AUDIT-MODEL-IDENTITY-001：模型下拉 value 使用不可变 profile_id（与模型列表、
    // 虚拟主播视觉同一身份合同）；上游 model_id 仅作为绑定附属信息随请求提交。
    const select = document.createElement('select');
    select.className =
      'shrink-0 max-w-[9rem] px-2 py-1 bg-white border border-gray-200 rounded-lg text-xs font-normal ui-control ui-select';
    select.title = t('dynamic.appPersonaTopicPage.为该人格选择模型');
    const modelOptions = modelItems
      .map((m) => ({
        profileId: String(m.profile_id || '').trim(),
        modelId: String(m.default_model_id || m.modelId || '').trim(),
        label: String(m.name || m.default_model_id || m.modelId || '').trim(),
        complete: m.complete !== false,
      }))
      .filter((option) => option.profileId && option.modelId);
    const firstProfileId =
      (modelOptions.find((option) => option.complete) || modelOptions[0])?.profileId || '';
    if (!modelOptions.length) {
      const placeholderOpt = document.createElement('option');
      placeholderOpt.value = '';
      placeholderOpt.textContent = t('dynamic.appPersonaTopicPage.未绑定');
      placeholderOpt.disabled = true;
      select.appendChild(placeholderOpt);
    }
    modelOptions.forEach((option) => {
      const opt = document.createElement('option');
      opt.value = option.profileId;
      opt.textContent = option.complete
        ? option.label
        : t('dynamic.appPersonaTopicPage.m_name_mid_未完成', { label: option.label });
      select.appendChild(opt);
    });
    // 显式绑定失效（悬挂 / 歧义 / 档案不完整 / 所选模型被移除）时不静默回退首项，
    // 而是显示待重选占位项并给出可观察提示。
    const boundProfileId = String(item.profile_id || '').trim();
    const bindingStatus = String(item.binding_status || 'unbound');
    const bindingInvalid = [
      'unresolved',
      'profile_missing',
      'profile_incomplete',
      'model_removed',
    ].includes(bindingStatus);
    if (bindingInvalid && modelOptions.length) {
      const needsReselect = document.createElement('option');
      needsReselect.value = '';
      needsReselect.textContent = t('dynamic.appPersonaTopicPage.需重新选择模型');
      needsReselect.disabled = true;
      select.insertBefore(needsReselect, select.firstChild);
    }
    if (bindingInvalid) {
      const boundOptionExists = modelOptions.some((option) => option.profileId === boundProfileId);
      select.value = boundOptionExists ? boundProfileId : '';
    } else {
      const effectiveProfileId = boundProfileId || firstProfileId;
      select.value = effectiveProfileId;
      // ok/unbound 下绑定值不在选项（档案已切换）时仍回退首个完整档案。
      if (select.value !== effectiveProfileId) select.value = firstProfileId;
    }
    let lastBindingValue = select.value;
    let bindingWarn = null;
    const clearBindingWarning = () => {
      if (bindingWarn) {
        bindingWarn.remove();
        bindingWarn = null;
      }
    };
    const applyBinding = async (profileId) => {
      const option = modelOptions.find((entry) => entry.profileId === profileId);
      try {
        await apiFetch(`/api/personae/${enc(item.id)}/model`, {
          method: 'PUT',
          body: JSON.stringify({
            profile_id: profileId,
            model_id: option ? option.modelId : '',
          }),
        });
        lastBindingValue = profileId;
        clearBindingWarning();
        showToast(profileId ? t('dynamic.appPersonaTopicPage.模型已绑定') : t('dynamic.appPersonaTopicPage.已清除绑定'));
      } catch (error) {
        select.value = lastBindingValue;
        showToast(error.message, true);
      }
    };
    select.addEventListener('change', () => {
      applyBinding(select.value);
    });
    row.appendChild(select);
    if (bindingInvalid && item.binding_message) {
      bindingWarn = document.createElement('span');
      bindingWarn.className = 'shrink-0 text-amber-600 text-xs font-bold cursor-help';
      bindingWarn.textContent = '⚠';
      bindingWarn.title = item.binding_message;
      row.appendChild(bindingWarn);
    }

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

function resolveProfileDisplayName(model) {
  const def = String(model?.default_model_id || '').trim();
  const names =
    model?.model_names && typeof model.model_names === 'object'
      ? model.model_names
      : {};
  if (def && names[def]) return String(names[def]).trim();
  return String(model?.name || '').trim() || def || t('common.unnamed');
}

function closePersonaBulkModelModal() {
  const modal = document.getElementById('personaBulkModelModal');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
  deactivateFocusTrap();
}

async function applyBulkPersonaModel(profileId, modelId) {
  const pid = String(profileId || '').trim();
  if (!pid) return;
  const mid = String(modelId || '').trim();
  const data = await personaFetch('/api/personae');
  const personaIds = (data?.items || []).map((item) => item.id).filter(Boolean);
  if (!personaIds.length) return;
  await Promise.all(
    personaIds.map((personaId) =>
      apiFetch(`/api/personae/${enc(personaId)}/model`, {
        method: 'PUT',
        body: JSON.stringify({ profile_id: pid, model_id: mid }),
      }),
    ),
  );
  await loadPersonaeCheckboxes('personaActiveList');
  showToast(t('dynamic.appPersonaTopicPage.已一键切换_n_个人格模型', { count: personaIds.length }));
  showPersonaPageStatus(t('dynamic.appPersonaTopicPage.已一键切换_n_个人格模型', { count: personaIds.length }));
}

async function openPersonaBulkModelModal() {
  const modal = document.getElementById('personaBulkModelModal');
  const list = document.getElementById('personaBulkModelList');
  const empty = document.getElementById('personaBulkModelEmpty');
  if (!modal || !list || !empty) return;

  list.innerHTML = '';
  let modelItems = [];
  try {
    const models = await apiFetch('/api/custom-models');
    modelItems = Array.isArray(models?.items) ? models.items : [];
  } catch (error) {
    showToast(error.message, true);
    return;
  }

  const usable = modelItems.filter(
    (model) =>
      String(model?.profile_id || '').trim() && String(model?.default_model_id || '').trim(),
  );
  empty.classList.toggle('hidden', usable.length > 0);
  list.classList.toggle('hidden', usable.length === 0);

  usable.forEach((model) => {
    const profileId = String(model.profile_id || '').trim();
    const modelId = String(model.default_model_id || '').trim();
    const row = document.createElement('button');
    row.type = 'button';
    row.className =
      'persona-bulk-model-option w-full text-left flex flex-wrap items-center gap-3 p-3 bg-cream rounded-xl text-sm hover:bg-softPeach transition-colors ui-button ui-button--ghost';
    row.setAttribute('role', 'option');
    row.dataset.profileId = profileId;
    row.dataset.modelId = modelId;

    const nameWrap = document.createElement('span');
    nameWrap.className = 'font-semibold text-warmText min-w-0 flex-1 truncate';
    nameWrap.textContent = resolveProfileDisplayName(model);
    row.appendChild(nameWrap);

    const idWrap = document.createElement('span');
    idWrap.className = 'text-gray-500 text-xs font-mono truncate max-w-full';
    idWrap.textContent = modelId;
    row.appendChild(idWrap);

    if (model.complete === false) {
      const warn = document.createElement('span');
      warn.className = 'text-amber-600 text-xs font-bold shrink-0';
      warn.textContent = t('dynamic.settingsCustomModels.配置不完整');
      row.appendChild(warn);
    }

    row.addEventListener('click', async () => {
      closePersonaBulkModelModal();
      try {
        await applyBulkPersonaModel(profileId, modelId);
      } catch (error) {
        showToast(error.message || t('dynamic.appPersonaTopicPage.一键切换失败'), true);
        showPersonaPageStatus(error.message || t('dynamic.appPersonaTopicPage.一键切换失败'), true);
      }
    });
    list.appendChild(row);
  });

  modal.classList.remove('hidden');
  modal.classList.add('flex');
  activateFocusTrap(modal, closePersonaBulkModelModal);
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
  const name = selectedPersonaId();
  if (!name) {
    loadedPersonaId = '';
    personaTemplateLoading = false;
    personaTemplateError = false;
    clearPersonaEditorDom();
    syncPersonaEditorControls();
    return;
  }
  currentPersonaId = name;

  // 新选择先让旧请求失效：递增 generation 并 abort，再清掉旧人格残留 DOM。
  templateLoadController?.abort();
  const generation = ++templateLoadGeneration;
  const controller = new AbortController();
  templateLoadController = controller;

  loadedPersonaId = '';
  personaTemplateLoading = true;
  personaTemplateError = false;
  clearPersonaEditorDom();
  syncPersonaEditorControls();

  try {
    const tpl = await personaFetch(`/api/personae/${enc(name)}/template`, {
      signal: controller.signal,
    });
    // 双门禁：generation 必须仍然当前，且 select 未切走。
    if (!isCurrentTemplateLoad(generation, name)) return;
    // 身份门禁：响应必须声明它属于捕获到的人格。
    if (!tpl || tpl.id !== name) {
      loadedPersonaId = '';
      personaTemplateLoading = false;
      personaTemplateError = true;
      syncPersonaEditorControls();
      showToast(t('dynamic.appPersonaTopicPage.人格模板响应身份不匹配_已忽略'), true);
      return;
    }
    writePersonaTemplate(tpl);
    loadedPersonaId = name;
    personaTemplateLoading = false;
    personaTemplateError = false;
    syncPersonaEditorControls();
  } catch (error) {
    // 取消或过期响应静默失效；真实失败只有在仍是当前加载时才可见。
    if (isAbortError(error) || !isCurrentTemplateLoad(generation, name)) return;
    loadedPersonaId = '';
    personaTemplateLoading = false;
    personaTemplateError = true;
    syncPersonaEditorControls();
    showToast(error.message, true);
    showPersonaPageStatus(error.message, true);
    console.warn('[persona] loadPersonaTemplate failed', error);
  } finally {
    if (generation === templateLoadGeneration) templateLoadController = null;
  }
}

/** 只读快照，供测试断言加载代际与身份绑定（不改变生产行为）。 */
export function getPersonaEditorState() {
  return {
    selectedId: selectedPersonaId(),
    loadedPersonaId,
    loading: personaTemplateLoading,
    error: personaTemplateError,
  };
}

/**
 * 保存当前编辑内容。
 *
 * 保存开始时一次性捕获 targetPersonaId = loadedPersonaId 与 payload；只有它与当前
 * select 一致时才发送，且 URL 用捕获值构造——保存期间切换选择不会改写目标人格。
 */
export async function savePersonaTemplate() {
  const btn = document.getElementById('btnSavePersona');
  const targetPersonaId = loadedPersonaId;
  if (!targetPersonaId || targetPersonaId !== selectedPersonaId()) {
    // DOM 未加载完成 / 身份不一致：拒绝保存，提示重新加载。
    showToast(t('dynamic.appPersonaTopicPage.内容未就绪_请重新加载后再保存'), true);
    showPersonaPageStatus(t('dynamic.appPersonaTopicPage.内容未就绪_请重新加载后再保存'), true);
    syncPersonaEditorControls();
    return;
  }
  const payload = {
    system_custom: document.getElementById('personaSystemCustom')?.value ?? '',
  };
  try {
    await window.withLoadingState(btn, btn?.textContent, async () => {
      await apiFetch(`/api/personae/${enc(targetPersonaId)}/template`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      // 仅当用户仍停留在该人格时才回读；否则不覆盖新选择。
      if (selectedPersonaId() === targetPersonaId) {
        await loadPersonaTemplate();
      }
    }, t('dynamic.appPersonaTopicPage.已保存'));
    if (selectedPersonaId() === targetPersonaId) {
      showToast(t('dynamic.appPersonaTopicPage.人格已保存'));
      showPersonaPageStatus(t('dynamic.appPersonaTopicPage.人格已更新_下一次生成会使用新内容'));
    }
  } catch (error) {
    // 真实保存失败可见，且不清空用户尚未保存的正文。
    showToast(error.message, true);
    showPersonaPageStatus(error.message, true);
  } finally {
    // withLoadingState 会强制恢复 disabled，这里按编辑器身份状态再校正一次。
    syncPersonaEditorControls();
  }
}

export async function loadPersonaEditor() {
  // 页面（重新）进入时让上一轮在途模板加载失效，避免旧响应覆盖新一轮。
  cancelPersonaTemplateLoad();
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
  // DOM 所属人格若已不存在（删除/重载），必须让出身份，避免旧内容被当成新选择。
  if (!loadedPersonaId || !validIds.has(loadedPersonaId)) {
    loadedPersonaId = '';
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

  // 页面销毁/离开时让在途模板加载失效（生成代际仍然兜底）。
  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    window.addEventListener('pagehide', () => cancelPersonaTemplateLoad());
  }

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
  document.getElementById('btnSavePersona')?.addEventListener('click', () => {
    savePersonaTemplate().catch((error) => {
      showToast(error.message, true);
      showPersonaPageStatus(error.message, true);
    });
  });
  document.getElementById('btnRestorePersona')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const targetPersonaId = loadedPersonaId;
    if (!targetPersonaId || targetPersonaId !== selectedPersonaId()) {
      showToast(t('dynamic.appPersonaTopicPage.内容未就绪_请重新加载后再保存'), true);
      return;
    }
    try {
      await window.withLoadingState(btn, btn.textContent, async () => {
        const data = await apiFetch(`/api/personae/${enc(targetPersonaId)}/restore`, {
          method: 'POST',
        });
        // 恢复期间切走选择：不把旧人格默认值写进当前编辑器。
        if (selectedPersonaId() !== targetPersonaId) return;
        document.getElementById('personaSystemCustom').value = data.system_custom || '';
        showToast(t('dynamic.appPersonaTopicPage.已恢复默认'));
      });
    } catch (error) {
      showToast(error.message, true);
    } finally {
      syncPersonaEditorControls();
    }
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
  document.getElementById('btnBulkSwitchPersonaModels')?.addEventListener('click', () => {
    openPersonaBulkModelModal().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnPersonaBulkModelClose')?.addEventListener('click', closePersonaBulkModelModal);
  document.getElementById('personaBulkModelModal')?.addEventListener('click', (event) => {
    if (event.target === event.currentTarget) closePersonaBulkModelModal();
  });
}
