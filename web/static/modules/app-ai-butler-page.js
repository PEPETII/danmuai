/**
 * 模块：app-ai-butler-page — AI管家对话页。
 *
 * W-AIBUTLER-002：对话页骨架 + 模型下拉（Tailwind 内联类，已废弃）
 * W-AIBUTLER-003：确认卡片 + 变更执行 + 状态机（idle/awaiting_llm/awaiting_confirm/applying/done/cancelled/failed）
 *                  切换 W-002 的 Tailwind 内联类为 warm-tokens 专属 CSS 类
 * W-AIBUTLER-004：异常边界 toast 差异化（spec §6.3 / §6.4）+ 侧栏切换静默取消（spec §6.1 / §7.3，MutationObserver）
 *                  + DOM 节点裁剪 + 首次 init 调 resetAiButlerConversation + 暗黑模式验证（无 CSS 变更）
 *
 * 职责：
 *   1) 渲染模型下拉（GET /api/custom-models），切换走 POST /api/custom-models/{index}/default
 *   2) 维护对话历史 messages（user/assistant 角色），上限 40 条（spec §8）
 *   3) 渲染消息气泡（用户靠右、AI 靠左）+ 「思考中」临时气泡
 *   4) 渲染确认卡片（spec §3.1 / §5.1），按用户选择调既有写端点
 *   5) 状态机管理（spec §7.1）；所有 tool_calls 须经确认卡片，禁止自动应用
 *   6) LLM 失败 / 配置写入失败 toast 差异化（spec §6.3 / §6.4）
 *   7) 侧栏切换静默取消未确认卡片（MutationObserver，不改 app.js）
 *   8) DOM 节点裁剪（MAX_DOM_NODES=60，避免长对话 DOM 膨胀）
 *
 * 不做（留给后续工单）：
 *   - markdown 渲染（纯文本）
 *   - 流式（非流式）
 *   - 多工具事务回滚（spec 未要求）
 *   - 暗黑模式 CSS 补丁（W-003 已用 token 引用；W-004 仅验证；如异常记入已知问题留后续工单）
 *
 * 复用：transport.apiFetch（自动注入 Bearer token）+ warm-tokens 设计系统（.card / .btn-primary / .settings-field-control）
 */

import { apiFetch } from './transport.js';
import { applyTheme, THEME_STORAGE_KEY } from './theme.js';

let toast = () => {};
let handlersBound = false;

/**
 * 解析 tool_call 工具名（后端 W-001 用 name；兼容旧字段 tool）。
 * @param {object} tc
 * @returns {string}
 */
function resolveToolName(tc) {
  return (tc && (tc.name || tc.tool)) || '';
}

/**
 * 收集确认卡片展示的变更行文案。
 * @param {object} tc
 * @returns {string[]}
 */
function collectChangeLabels(tc) {
  const toolName = resolveToolName(tc);
  if (toolName === 'update_config' && Array.isArray(tc.changes) && tc.changes.length) {
    return tc.changes.map((c) => c.label || `${c.key} → ${c.value}`);
  }
  if (tc.label) return [tc.label];
  return [JSON.stringify(tc)];
}

// 对话历史（user/assistant 角色），上限 40 条（spec §8）
const MAX_MESSAGES = 40;
// DOM 节点裁剪上限（W-004）：2x MAX_MESSAGES 给系统消息 + 确认卡片留 buffer
const MAX_DOM_NODES = 60;
let messages = [];
// 当前选中的 model index（用于切换时恢复），-1 表示未初始化
let currentSelectedIndex = -1;
// 是否正在发送中（防止并发）
let sending = false;

// 状态机（spec §7.1）：idle / awaiting_llm / awaiting_confirm / applying / done / cancelled / failed
// awaiting_confirm 时若用户输入新消息，会先取消当前计划再开始新解析（spec §6.1）
let state = 'idle';
// 当前确认卡片引用（awaiting_confirm 态持有，cancelled/done/failed 后置 null）
let currentConfirmCard = null;
// 当前 tool_calls 引用（applying/failed 态持有，用于重试）
let currentToolCalls = null;

// MutationObserver 实例引用（initAiButlerPage 时创建，避免重复创建）
let navObserver = null;

// ---------------------------------------------------------------------------
// 错误文案映射（W-004，spec §6.3 / §6.4）
// ---------------------------------------------------------------------------

/**
 * 将 LLM 请求失败（POST /api/ai-butler/chat）的 error 字段映射为用户可读 toast 文案。
 * 后端 W-001 返回结构化 {ok:false, error}，6 类降级：
 *   empty_messages / model_not_configured / credential_missing:... / timeout / http_<status> / internal_error:<ExcName>
 * 网络异常（fetch 抛出）无 error 字段，统一映射到「网络开小差了」。
 *
 * @param {string} error - 后端返回的 error 字段
 * @returns {string} toast 文案
 */
function mapLlmErrorToToast(error) {
  if (!error) return '网络开小差了，请重试';
  if (error === 'timeout') return '网络开小差了，请重试';
  if (error === 'model_not_configured')
    return '未配置模型，请先到「弹幕设置 → API 与模型」配置';
  if (error.startsWith('credential_missing'))
    return '凭证缺失，请检查 API Key 与端点配置';
  if (error.startsWith('http_'))
    return `AI 服务返回错误（${error}），请稍后再试`;
  if (error.startsWith('internal_error'))
    return 'AI 管家内部错误，请重试';
  if (error === 'empty_messages') return '请输入内容后再发送';
  return `AI 管家请求失败：${error}`;
}

/**
 * 将配置写入失败（PUT /api/config / POST /api/custom-models/{index}/default）的错误信息
 * 映射为用户可读 toast / 系统消息文案。
 * 前端字符串匹配（不修改后端），best-effort；未命中回落到 W-003 现状文案。
 *
 * spec §6.4：
 *   - apply_config_patch 错误 → 「设置保存失败：{error.message}」
 *   - ConfigStore 加密异常 → 「配置存储异常，请重启应用」
 *   - 网络请求超时 → 「应用设置超时，请重试」
 *
 * @param {Error|*} error
 * @returns {string} 系统消息文案（已含 ❌ 前缀）
 */
function mapConfigWriteErrorToMessage(error) {
  const msg = (error && (error.message || error)) || '未知错误';
  const lower = String(msg).toLowerCase();
  if (lower.includes('timeout') || lower.includes('timed out'))
    return '❌ 应用设置超时，请重试';
  if (
    lower.includes('encrypt') ||
    lower.includes('fernet') ||
    lower.includes('.key') ||
    lower.includes('crypto')
  )
    return '❌ 配置存储异常，请重启应用';
  return `❌ 设置保存失败：${msg}`;
}

// ---------------------------------------------------------------------------
// DOM 节点裁剪（W-004，spec §7.3：避免长对话 DOM 膨胀）
// ---------------------------------------------------------------------------

/**
 * 裁剪消息容器子节点到 MAX_DOM_NODES 上限。
 * 从最早子节点开始移除；跳过 empty hint（避免裁剪到空提示）。
 * 不在 showThinkingBubble 后调用（避免裁剪刚追加的思考中气泡）。
 *
 * @param {HTMLElement} container - #aiButlerMessages 容器
 */
function pruneContainerChildren(container) {
  if (!container) return;
  while (container.children.length > MAX_DOM_NODES) {
    const first = container.firstElementChild;
    if (!first) break;
    // 跳过 empty hint（理论上 empty hint 在有消息时已被移除，此处兜底）
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

/**
 * 设置状态机状态。
 * @param {string} newState
 */
function setState(newState) {
  state = newState;
}

/**
 * 渲染模型下拉选项。
 * @param {Array} items - custom_models 列表
 * @param {string} defaultModelId - 当前 default_model_id
 */
function renderModelSelect(items, defaultModelId) {
  const select = document.getElementById('aiButlerModelSelect');
  if (!select) return;

  const prevValue = select.value;
  select.innerHTML = '';

  if (!items || !items.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '（暂无模型档案，请到「弹幕设置 → API 与模型」添加）';
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    currentSelectedIndex = -1;
    return;
  }

  items.forEach((model, index) => {
    const opt = document.createElement('option');
    opt.value = String(index);
    const name = model.name || '未命名';
    const mid = model.default_model_id || model.modelId || '';
    const isDefault = mid === defaultModelId;
    opt.textContent = `${name}${mid ? `（${mid}）` : ''}${isDefault ? ' ✓' : ''}`;
    if (isDefault) {
      opt.selected = true;
      currentSelectedIndex = index;
    }
    select.appendChild(opt);
  });

  // 若没有匹配 default 的项，保持第一个选中
  if (currentSelectedIndex === -1 && items.length > 0) {
    select.selectedIndex = 0;
    currentSelectedIndex = 0;
  } else if (prevValue !== '' && select.value === '') {
    // 恢复上次选中（避免切换失败后被重置）
    select.value = prevValue;
  }
}

/**
 * 拉取模型列表并渲染下拉。
 */
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
    opt.textContent = '加载失败，请刷新页面重试';
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    showToast(error.message || '加载模型列表失败', true);
  }
}

/**
 * 切换默认模型档案。
 * @param {number} index
 */
async function switchDefaultModel(index) {
  if (index < 0) return;
  const select = document.getElementById('aiButlerModelSelect');
  const prevIndex = currentSelectedIndex;
  try {
    const res = await apiFetch(`/api/custom-models/${index}/default`, { method: 'POST' });
    showToast(`已切换为默认模型：${res.default_model_id || ''}`);
    // 重新拉列表刷新选中态（确保与服务端一致）
    await refreshModelSelect();
  } catch (error) {
    showToast(error.message || '切换模型失败', true);
    // 恢复 select 到之前的选中项
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
 * 创建消息气泡元素。
 *
 * W-003 切换为 warm-tokens 专属 CSS 类（W-002 Tailwind 内联已废弃）：
 *   - 用户气泡：`ai-butler-msg is-user` + `ai-butler-chat-bubble ai-butler-msg-user`
 *   - AI 气泡：`ai-butler-msg is-ai` + `ai-butler-chat-bubble ai-butler-msg-ai`
 *   - 思考中：复用 AI 气泡 + `is-thinking`
 *
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

/**
 * 追加一条消息到对话区并滚动到底部。
 */
function appendMessage(role, text) {
  const container = document.getElementById('aiButlerMessages');
  if (!container) return null;
  // 移除空提示
  const emptyHint = container.querySelector('.ai-butler-empty-hint');
  if (emptyHint) emptyHint.remove();
  const el = createMessageBubble(role, text);
  container.appendChild(el);
  pruneContainerChildren(container);
  container.scrollTop = container.scrollHeight;
  return el;
}

/**
 * 追加系统消息（取消/成功/失败提示）。
 * @param {string} text - 已含 emoji（✅ / ❌ / 「已取消」）
 */
function appendSystemMessage(text) {
  const container = document.getElementById('aiButlerMessages');
  if (!container) return null;
  const emptyHint = container.querySelector('.ai-butler-empty-hint');
  if (emptyHint) emptyHint.remove();
  const el = document.createElement('div');
  el.className = 'ai-butler-system-msg';
  el.textContent = text;
  container.appendChild(el);
  pruneContainerChildren(container);
  container.scrollTop = container.scrollHeight;
  return el;
}

/**
 * 渲染「思考中」临时气泡（返回元素引用，便于后续移除）。
 * @returns {HTMLElement|null}
 */
function showThinkingBubble() {
  return appendMessage('thinking', '思考中…');
}

function removeElement(el) {
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

// ---------------------------------------------------------------------------
// 确认卡片（spec §3.1 / §5.1）
// ---------------------------------------------------------------------------

/**
 * 渲染确认卡片。
 * @param {Array} toolCalls - [{tool, ...params, label, require_confirm}]
 * @returns {HTMLElement} 卡片元素引用
 */
function renderConfirmCard(toolCalls) {
  const container = document.getElementById('aiButlerMessages');
  if (!container) return null;
  const emptyHint = container.querySelector('.ai-butler-empty-hint');
  if (emptyHint) emptyHint.remove();

  const card = document.createElement('div');
  card.className = 'ai-butler-confirm-card';
  card.setAttribute('data-role', 'confirm-card');

  const count = toolCalls.length;
  const title = document.createElement('p');
  title.className = 'ai-butler-confirm-title';
  title.textContent = count > 1 ? `📋 变更预览（共 ${count} 项）` : '📋 变更预览';
  card.appendChild(title);

  // 变更行
  toolCalls.forEach((tc) => {
    collectChangeLabels(tc).forEach((text) => {
      const row = document.createElement('div');
      row.className = 'ai-butler-change-row';
      row.textContent = text;
      card.appendChild(row);
    });
  });

  // 按钮区
  const btnRow = document.createElement('div');
  btnRow.className = 'ai-butler-btn-row';

  const confirmBtn = document.createElement('button');
  confirmBtn.type = 'button';
  confirmBtn.className = 'ai-butler-btn-confirm';
  confirmBtn.textContent = '确认执行';
  confirmBtn.addEventListener('click', () => {
    applyToolCalls(toolCalls, card).catch((err) =>
      showToast(`执行异常：${err.message || err}`, true),
    );
  });

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'ai-butler-btn-cancel';
  cancelBtn.textContent = '取消';
  cancelBtn.addEventListener('click', () => {
    cancelCurrentPlan(card);
  });

  btnRow.appendChild(confirmBtn);
  btnRow.appendChild(cancelBtn);
  card.appendChild(btnRow);

  container.appendChild(card);
  pruneContainerChildren(container);
  container.scrollTop = container.scrollHeight;
  return card;
}

/**
 * 将「确认执行」按钮切换为 loading 态。
 * @param {HTMLElement} card
 * @returns {{confirmBtn: HTMLElement|null, cancelBtn: HTMLElement|null}}
 */
function setCardLoading(card) {
  const confirmBtn = card.querySelector('.ai-butler-btn-confirm');
  const cancelBtn = card.querySelector('.ai-butler-btn-cancel');
  if (!confirmBtn) return { confirmBtn: null, cancelBtn: null };

  confirmBtn.className = 'ai-butler-btn-loading';
  confirmBtn.textContent = '应用中...';
  const spinner = document.createElement('span');
  spinner.className = 'ai-butler-spinner';
  confirmBtn.appendChild(spinner);
  confirmBtn.disabled = true;
  if (cancelBtn) cancelBtn.disabled = true;
  return { confirmBtn, cancelBtn };
}

/**
 * 取消当前变更计划。
 * @param {HTMLElement} card - 待移除的卡片
 */
function cancelCurrentPlan(card) {
  setState('cancelled');
  removeElement(card);
  if (currentConfirmCard === card) currentConfirmCard = null;
  currentToolCalls = null;
  appendSystemMessage('已取消');
  setState('idle');
}

/**
 * 执行 tool_calls（按顺序），任一失败停止后续。
 * 成功 → 卡片转「完成」+ 系统消息「✅ ... 已应用」+ 1.5s 后淡出
 * 失败 → 卡片保留 + 按钮转「重试」红色 + 错误信息显示
 *
 * @param {Array} toolCalls
 * @param {HTMLElement} card
 */
async function applyToolCalls(toolCalls, card) {
  setState('applying');
  currentToolCalls = toolCalls;
  const { confirmBtn, cancelBtn } = setCardLoading(card);
  // 移除上次失败的错误信息（若有）
  const oldErr = card.querySelector('.ai-butler-error-text');
  if (oldErr) oldErr.remove();

  let hasSetDefaultModel = false;
  const successLabels = [];
  for (let i = 0; i < toolCalls.length; i++) {
    const tc = toolCalls[i];
    try {
      await executeSingleToolCall(tc);
      const labels = collectChangeLabels(tc);
      successLabels.push(labels.length === 1 ? labels[0] : labels.join('、'));
      if (resolveToolName(tc) === 'set_default_model') hasSetDefaultModel = true;
    } catch (error) {
      // 失败：保留卡片，按钮转「重试」红色，显示错误信息
      if (confirmBtn) {
        const newBtn = document.createElement('button');
        newBtn.type = 'button';
        newBtn.className = 'ai-butler-btn-confirm is-failed';
        newBtn.textContent = '重试';
        newBtn.addEventListener('click', () => {
          applyToolCalls(currentToolCalls, card).catch((err) =>
            showToast(`执行异常：${err.message || err}`, true),
          );
        });
        confirmBtn.replaceWith(newBtn);
      }
      if (cancelBtn) cancelBtn.disabled = false;
      const errBox = document.createElement('div');
      errBox.className = 'ai-butler-error-text';
      errBox.textContent = `第 ${i + 1} 项失败：${error.message || error}`;
      card.appendChild(errBox);
      setState('failed');
      // W-004：配置写入失败 toast 差异化（spec §6.4）
      appendSystemMessage(mapConfigWriteErrorToMessage(error));
      return;
    }
  }

  // 全部成功
  setState('done');
  if (confirmBtn) {
    const newBtn = document.createElement('button');
    newBtn.type = 'button';
    newBtn.className = 'ai-butler-btn-confirm is-success';
    newBtn.textContent = '完成';
    newBtn.disabled = true;
    confirmBtn.replaceWith(newBtn);
  }
  if (cancelBtn) cancelBtn.disabled = true;

  const labelText =
    successLabels.length > 3
      ? `${successLabels.slice(0, 3).join('、')} 等 ${successLabels.length} 项`
      : successLabels.join('、');
  appendSystemMessage(`✅ ${labelText} 已应用`);

  // 含 set_default_model 时刷新模型下拉
  if (hasSetDefaultModel) {
    refreshModelSelect().catch(() => {});
  }

  // 1.5s 后淡出卡片
  setTimeout(() => {
    card.classList.add('is-fading');
    setTimeout(() => {
      removeElement(card);
      if (currentConfirmCard === card) currentConfirmCard = null;
      currentToolCalls = null;
    }, 300);
  }, 1500);
  setState('idle');
}

/**
 * 执行单个 tool_call。
 * @param {object} tc - {tool, ...params}
 * @throws {Error} 执行失败时抛出
 */
async function executeSingleToolCall(tc) {
  const toolName = resolveToolName(tc);
  if (toolName === 'update_config') {
    // 聚合 changes 为 {key: value} payload，调 PUT /api/config
    const changes = Array.isArray(tc.changes) ? tc.changes : [];
    if (!changes.length) throw new Error('changes 为空');
    const payload = {};
    changes.forEach((c) => {
      if (c.key) payload[c.key] = c.value;
    });
    await apiFetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return;
  }
  if (toolName === 'set_console_theme') {
    const theme = tc.theme === 'dark' ? 'dark' : 'light';
    await apiFetch('/api/console-theme', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme }),
    });
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      /* ignore quota / private mode */
    }
    applyTheme(theme);
    return;
  }
  if (toolName === 'set_default_model') {
    const index = Number(tc.index);
    if (!Number.isInteger(index) || index < 0) throw new Error('model index 非法');
    await apiFetch(`/api/custom-models/${index}/default`, { method: 'POST' });
    return;
  }
  throw new Error(`未知工具：${toolName || 'undefined'}`);
}

// ---------------------------------------------------------------------------
// 发送逻辑
// ---------------------------------------------------------------------------

/**
 * 发送当前输入框内容。
 */
async function sendMessage() {
  if (sending) return;
  const input = document.getElementById('aiButlerInput');
  const sendBtn = document.getElementById('btnAiButlerSend');
  if (!input || !sendBtn) return;

  const text = input.value.trim();
  if (!text) return;

  // awaiting_confirm 态：用户输入新消息 → 取消当前计划（spec §6.1）
  if (state === 'awaiting_confirm' && currentConfirmCard) {
    cancelCurrentPlan(currentConfirmCard);
  }

  // 渲染用户气泡 + 推入历史 + 清空输入框 + disable
  sending = true;
  setState('awaiting_llm');
  input.disabled = true;
  sendBtn.disabled = true;
  sendBtn.classList.add('opacity-60', 'cursor-progress');
  const userBubble = appendMessage('user', text);
  messages.push({ role: 'user', content: text });
  // 上限裁剪（spec §8：保留 20 轮 = 40 条）
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
      const reply = res.reply || '';
      const hasToolCalls = Array.isArray(res.tool_calls) && res.tool_calls.length > 0;

      // W-004（spec §6.3）：LLM 返回空 reply 且无 tool_calls → 降级为「无法识别意图」提示
      if (!reply && !hasToolCalls) {
        const fallback = '我目前可以帮您调整弹幕设置，您可以试试说「把弹幕速度调快」';
        appendMessage('assistant', fallback);
        messages.push({ role: 'assistant', content: fallback });
        if (messages.length > MAX_MESSAGES) {
          messages = messages.slice(-MAX_MESSAGES);
        }
        setState('idle');
        return;
      }

      // 渲染 AI 文本回复（始终追加，即使含 tool_calls）
      appendMessage('assistant', reply);
      messages.push({ role: 'assistant', content: reply });
      if (messages.length > MAX_MESSAGES) {
        messages = messages.slice(-MAX_MESSAGES);
      }

      if (hasToolCalls) {
        const toolCalls = res.tool_calls;
        // 所有变更均需用户确认（禁止自动应用）
        setState('awaiting_confirm');
        currentToolCalls = toolCalls;
        currentConfirmCard = renderConfirmCard(toolCalls);
      } else {
        setState('idle');
      }
    } else {
      // ok:false → toast 错误，回滚用户气泡 + 历史 + 恢复输入框
      // W-004：按 error 字段差异化 toast（spec §6.3）
      const errMsg = (res && res.error) || '';
      showToast(mapLlmErrorToToast(errMsg), true);
      removeElement(userBubble);
      messages.pop(); // 移除刚推入的 user 消息
      input.value = text; // 恢复输入框（spec §6.3：保留输入框内容）
      setState('idle');
    }
  } catch (error) {
    removeElement(thinkingBubble);
    // W-004：网络异常（fetch 抛出）统一映射为「网络开小差了」（spec §6.3）
    showToast(mapLlmErrorToToast(''), true);
    // 回滚用户气泡 + 历史 + 恢复输入框
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
 * 初始化 AI管家页（绑定事件，防重复）。
 * @param {object} deps - { showToast }
 */
export function initAiButlerPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;

  // W-004：首次 init 时调用一次 resetAiButlerConversation() 确保初始状态干净
  // （正常路径下 messages = [] 已是初始值，调用是 no-op；防 module 重导入残留）
  resetAiButlerConversation();

  const sendBtn = document.getElementById('btnAiButlerSend');
  const input = document.getElementById('aiButlerInput');
  const select = document.getElementById('aiButlerModelSelect');

  sendBtn?.addEventListener('click', () => {
    sendMessage().catch((error) => showToast(error.message, true));
  });

  input?.addEventListener('keydown', (ev) => {
    // Enter 发送（Shift+Enter 换行）
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

  // W-004：侧栏切换静默取消未确认卡片（spec §6.1 / §7.3）
  // 用 MutationObserver 监听 #page-ai-butler 的 class 属性，当 active 被移除
  // 且当前处于 awaiting_confirm 态时，静默取消并追加「已取消」系统消息。
  // 不修改 app.js（工单禁止区）；MutationObserver 异步触发，不阻塞 navigate。
  setupNavObserver();
}

/**
 * 设置侧栏切换监听器（W-004，spec §6.1 / §7.3）。
 *
 * 观察目标：document.getElementById('page-ai-butler')
 * 触发条件：panel.classList 不再含 'active' && state === 'awaiting_confirm' && currentConfirmCard 非空
 * 动作：调 cancelCurrentPlan(currentConfirmCard)（已实现「追加『已取消』系统消息」+ 移除卡片 + 回到 idle）
 * 幂等性：cancelCurrentPlan 置 currentConfirmCard = null，下次回调直接 return
 * 不阻塞导航：MutationObserver 在 microtask 中异步触发，navigate 同步流程已结束
 */
function setupNavObserver() {
  if (navObserver) navObserver.disconnect();
  const panel = document.getElementById('page-ai-butler');
  if (!panel || typeof MutationObserver === 'undefined') return;

  navObserver = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type !== 'attributes' || m.attributeName !== 'class') continue;
      const isActive = panel.classList.contains('active');
      if (!isActive && state === 'awaiting_confirm' && currentConfirmCard) {
        cancelCurrentPlan(currentConfirmCard);
      }
    }
  });
  navObserver.observe(panel, { attributes: true, attributeFilter: ['class'] });
}

/**
 * 加载 AI管家页（拉模型列表渲染下拉）。
 */
export async function loadAiButlerPage() {
  await refreshModelSelect();
}

/**
 * 重置对话历史与 UI（W-004：initAiButlerPage 首次调用；防 module 重导入残留）。
 */
export function resetAiButlerConversation() {
  messages = [];
  state = 'idle';
  currentConfirmCard = null;
  currentToolCalls = null;
  const container = document.getElementById('aiButlerMessages');
  if (container) {
    container.innerHTML = '';
    const hint = document.createElement('p');
    hint.className = 'ai-butler-empty-hint';
    hint.textContent = '告诉我你想调整什么设置，例如「把弹幕速度调快」';
    container.appendChild(hint);
  }
}
