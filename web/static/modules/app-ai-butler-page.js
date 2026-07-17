/**
 * 模块：app-ai-butler-page — AI管家对话页（纯对话，不修改设置）。
 *
 * W-AIBUTLER-CHAT-ONLY-001：移除确认卡片与 tool_calls 执行；保留多轮对话与模型下拉。
 *
 * 职责：
 *   1) 渲染模型下拉（GET /api/custom-models），切换走 POST /api/custom-models/{index}/default
 *   2) 维护对话历史 messages（user/assistant），上限 40 条
 *   3) 渲染消息气泡 + 「思考中」临时气泡
 *   4) POST /api/ai-butler/chat 取纯文本 reply（忽略 tool_calls）
 *   5) LLM 失败 toast 差异化
 *   6) DOM 节点裁剪（MAX_DOM_NODES=60）
 *
 * 不做：
 *   - 配置变更确认卡 / PUT /api/config / 主题工具执行
 *   - markdown / 流式
 */

import { apiFetch } from './transport.js';
import { t } from './i18n.js';

let toast = () => {};
let handlersBound = false;

// 对话历史（user/assistant 角色），上限 40 条
const MAX_MESSAGES = 40;
// DOM 节点裁剪上限
const MAX_DOM_NODES = 60;
let messages = [];
// 当前选中的 model index（用于切换时恢复），-1 表示未初始化
let currentSelectedIndex = -1;
// 是否正在发送中（防止并发）
let sending = false;

// 状态机：idle / awaiting_llm
let state = 'idle';

// ---------------------------------------------------------------------------
// 错误文案映射
// ---------------------------------------------------------------------------

/**
 * 将 LLM 请求失败（POST /api/ai-butler/chat）的 error 字段映射为用户可读 toast 文案。
 * @param {string} error
 * @returns {string}
 */
function mapLlmErrorToToast(error) {
  if (!error) return t('dynamic.appAiButlerPage.网络开小差了_请重试');
  if (error === 'timeout') return t('dynamic.appAiButlerPage.网络开小差了_请重试');
  if (error === 'model_not_configured')
    return t('dynamic.appAiButlerPage.未配置模型_请先到_弹幕设置_API_与模型');
  if (error.startsWith('credential_missing'))
    return t('dynamic.appAiButlerPage.凭证缺失_请检查_API_Key_与端点配置');
  if (error.startsWith('http_'))
    return t('dynamic.appAiButlerPage.AI_服务返回错误_error_请稍后再', { error: error.slice(5) || error });
  if (error.startsWith('internal_error'))
    return t('dynamic.appAiButlerPage.AI_管家内部错误_请重试');
  if (error === 'empty_messages') return t('dynamic.appAiButlerPage.请输入内容后再发送');
  return t('dynamic.appAiButlerPage.AI_管家请求失败_error', { error });
}

// ---------------------------------------------------------------------------
// DOM 节点裁剪
// ---------------------------------------------------------------------------

/**
 * @param {HTMLElement} container - #aiButlerMessages 容器
 */
function pruneContainerChildren(container) {
  if (!container) return;
  while (container.children.length > MAX_DOM_NODES) {
    const first = container.firstElementChild;
    if (!first) break;
    if (first.classList && first.classList.contains('ai-butler-empty-hint')) {
      const next = first.nextElementSibling;
      if (!next) break;
      container.removeChild(next);
    } else {
      container.removeChild(first);
    }
  }
}

function showToast(message, isError = false) {
  toast(message, isError);
}

function setState(newState) {
  state = newState;
}

/**
 * @param {Array} items
 * @param {string} defaultModelId
 */
function renderModelSelect(items, defaultModelId) {
  const select = document.getElementById('aiButlerModelSelect');
  if (!select) return;

  const prevValue = select.value;
  select.innerHTML = '';

  if (!items || !items.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = t('dynamic.appAiButlerPage.暂无模型档案_请到_弹幕设置_API_与模');
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    currentSelectedIndex = -1;
    return;
  }

  items.forEach((model, index) => {
    const opt = document.createElement('option');
    opt.value = String(index);
    const name = model.name || t('common.unnamed');
    const mid = model.default_model_id || model.modelId || '';
    const isDefault = mid === defaultModelId;
    opt.textContent = `${name}${mid ? `（${mid}）` : ''}${isDefault ? ' ✓' : ''}`;
    if (isDefault) {
      opt.selected = true;
      currentSelectedIndex = index;
    }
    select.appendChild(opt);
  });

  if (currentSelectedIndex === -1 && items.length > 0) {
    select.selectedIndex = 0;
    currentSelectedIndex = 0;
  } else if (prevValue !== '' && select.value === '') {
    select.value = prevValue;
  }
}

async function refreshModelSelect() {
  const select = document.getElementById('aiButlerModelSelect');
  if (!select) return;
  try {
    const data = await apiFetch('/api/custom-models');
    renderModelSelect(data.items || [], data.default_model_id || '');
  } catch (error) {
    select.innerHTML = '';
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = t('dynamic.appAiButlerPage.加载失败_请刷新页面重试');
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    showToast(error.message || t('dynamic.appAiButlerPage.加载模型列表失败'), true);
  }
}

/**
 * 用户手动切换默认模型档案（对话用模型，非 LLM 工具改设置）。
 * @param {number} index
 */
async function switchDefaultModel(index) {
  if (index < 0) return;
  const select = document.getElementById('aiButlerModelSelect');
  const prevIndex = currentSelectedIndex;
  try {
    const res = await apiFetch(`/api/custom-models/${index}/default`, { method: 'POST' });
    showToast(t('dynamic.appAiButlerPage.switchedDefaultModel', { modelId: res.default_model_id || '' }));
    await refreshModelSelect();
  } catch (error) {
    showToast(error.message || t('dynamic.appAiButlerPage.切换模型失败'), true);
    if (select && prevIndex >= 0) {
      select.value = String(prevIndex);
      currentSelectedIndex = prevIndex;
    } else {
      await refreshModelSelect();
    }
  }
}

// ---------------------------------------------------------------------------
// 消息渲染
// ---------------------------------------------------------------------------

/**
 * @param {string} role - 'user' | 'assistant' | 'thinking'
 * @param {string} text
 * @returns {HTMLElement}
 */
function createMessageBubble(role, text) {
  const wrap = document.createElement('div');
  if (role === 'user') {
    wrap.className = 'ai-butler-msg is-user';
    const bubble = document.createElement('div');
    bubble.className = 'ai-butler-chat-bubble ai-butler-msg-user';
    bubble.textContent = text;
    wrap.appendChild(bubble);
  } else {
    wrap.className = 'ai-butler-msg is-ai';
    const bubble = document.createElement('div');
    const thinking = role === 'thinking';
    bubble.className = 'ai-butler-chat-bubble ai-butler-msg-ai' + (thinking ? ' is-thinking' : '');
    bubble.textContent = text;
    wrap.appendChild(bubble);
  }
  return wrap;
}

function appendMessage(role, text) {
  const container = document.getElementById('aiButlerMessages');
  if (!container) return null;
  const emptyHint = container.querySelector('.ai-butler-empty-hint');
  if (emptyHint) emptyHint.remove();
  const el = createMessageBubble(role, text);
  container.appendChild(el);
  pruneContainerChildren(container);
  container.scrollTop = container.scrollHeight;
  return el;
}

function removeElement(el) {
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

function showThinkingBubble() {
  return appendMessage('thinking', t('dynamic.appAiButlerPage.思考中'));
}

// ---------------------------------------------------------------------------
// 发送逻辑（纯对话）
// ---------------------------------------------------------------------------

async function sendMessage() {
  if (sending) return;
  const input = document.getElementById('aiButlerInput');
  const sendBtn = document.getElementById('btnAiButlerSend');
  if (!input || !sendBtn) return;

  const text = input.value.trim();
  if (!text) return;

  sending = true;
  setState('awaiting_llm');
  input.disabled = true;
  sendBtn.disabled = true;
  sendBtn.classList.add('opacity-60', 'cursor-progress');
  const userBubble = appendMessage('user', text);
  messages.push({ role: 'user', content: text });
  if (messages.length > MAX_MESSAGES) {
    messages = messages.slice(-MAX_MESSAGES);
  }
  input.value = '';
  const thinkingBubble = showThinkingBubble();

  try {
    const res = await apiFetch('/api/ai-butler/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    });
    removeElement(thinkingBubble);

    if (res && res.ok) {
      let reply = (res.reply || '').trim();
      // 硬切断：忽略任何 tool_calls（后端亦恒返回 []）
      if (!reply) {
        reply = t('dynamic.appAiButlerPage.我没听清_请换个说法再试试');
      }
      appendMessage('assistant', reply);
      messages.push({ role: 'assistant', content: reply });
      if (messages.length > MAX_MESSAGES) {
        messages = messages.slice(-MAX_MESSAGES);
      }
      setState('idle');
    } else {
      const errMsg = (res && res.error) || '';
      showToast(mapLlmErrorToToast(errMsg), true);
      removeElement(userBubble);
      messages.pop();
      input.value = text;
      setState('idle');
    }
  } catch (error) {
    removeElement(thinkingBubble);
    showToast(mapLlmErrorToToast(''), true);
    removeElement(userBubble);
    messages.pop();
    input.value = text;
    setState('idle');
  } finally {
    sending = false;
    input.disabled = false;
    sendBtn.disabled = false;
    sendBtn.classList.remove('opacity-60', 'cursor-progress');
    input.focus();
  }
}

// ---------------------------------------------------------------------------
// init / load
// ---------------------------------------------------------------------------

/**
 * @param {object} deps - { showToast }
 */
export function initAiButlerPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;

  resetAiButlerConversation();

  const sendBtn = document.getElementById('btnAiButlerSend');
  const input = document.getElementById('aiButlerInput');
  const select = document.getElementById('aiButlerModelSelect');

  sendBtn?.addEventListener('click', () => {
    sendMessage().catch((error) => showToast(error.message, true));
  });

  input?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      sendMessage().catch((error) => showToast(error.message, true));
    }
  });

  select?.addEventListener('change', () => {
    const index = Number(select.value);
    if (Number.isNaN(index) || index < 0) return;
    switchDefaultModel(index).catch((error) => showToast(error.message, true));
  });
}

export async function loadAiButlerPage() {
  await refreshModelSelect();
}

export function resetAiButlerConversation() {
  messages = [];
  state = 'idle';
  const container = document.getElementById('aiButlerMessages');
  if (container) {
    container.innerHTML = '';
    const hint = document.createElement('p');
    hint.className = 'ai-butler-empty-hint';
    hint.textContent = t('dynamic.appAiButlerPage.有什么想问的_例如_弹幕速度在哪改');
    container.appendChild(hint);
  }
}
