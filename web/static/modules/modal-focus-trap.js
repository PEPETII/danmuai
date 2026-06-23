// modal-focus-trap.js — 通用模态框无障碍增强
//
// 提供 activateFocusTrap / deactivateFocusTrap，为任意模态框添加：
//   - Tab / Shift+Tab 焦点循环（不跳出模态框）
//   - Escape 键关闭
//   - 打开时聚焦首个可交互元素
//   - 关闭时归还焦点到触发元素

let _activeTrap = null; // { modalEl, closeFn, triggerEl, _onKeyDown }

/** 获取容器内所有可聚焦元素（按 DOM 顺序） */
function _getFocusableElements(container) {
  const selector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(', ');
  return Array.from(container.querySelectorAll(selector));
}

/** 拦截 Tab/Shift+Tab，使焦点在可聚焦元素列表内循环 */
function _handleTabKey(e, focusableEls) {
  if (e.key !== 'Tab' || !focusableEls.length) return;
  const first = focusableEls[0];
  const last = focusableEls[focusableEls.length - 1];
  if (e.shiftKey) {
    if (document.activeElement === first) {
      e.preventDefault();
      last.focus();
    }
  } else {
    if (document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
}

/** Escape 键 → 调用 closeFn */
function _handleEscape(e) {
  if (e.key === 'Escape' && _activeTrap) {
    e.preventDefault();
    e.stopPropagation();
    _activeTrap.closeFn();
  }
}

/**
 * 为模态框激活焦点陷阱
 * @param {HTMLElement} modalEl - 模态框容器（role="dialog" 的最外层 div）
 * @param {Function} closeFn - 关闭回调（无参，签名与现有 closeXxxModal 一致）
 * @returns {void}
 */
export function activateFocusTrap(modalEl, closeFn) {
  // 保存当前焦点（触发元素），以便关闭后归还
  const triggerEl = document.activeElement;

  // 先清理已有陷阱（防止嵌套或重复激活）
  if (_activeTrap) deactivateFocusTrap();

  const focusableEls = _getFocusableElements(modalEl);

  _activeTrap = { modalEl, closeFn, triggerEl };

  // 延迟一帧聚焦首元素（等待 display:flex 生效）
  requestAnimationFrame(() => {
    if (focusableEls.length && _activeTrap) {
      focusableEls[0].focus();
    }
  });

  const onKeyDown = (e) => {
    _handleTabKey(e, focusableEls);
    _handleEscape(e);
  };

  _activeTrap._onKeyDown = onKeyDown;
  document.addEventListener('keydown', onKeyDown);
}

/**
 * 释放当前焦点陷阱，归还焦点到触发元素。
 * 各模态框的 close 函数开头应调用此函数。
 */
export function deactivateFocusTrap() {
  if (!_activeTrap) return;
  if (_activeTrap._onKeyDown) {
    document.removeEventListener('keydown', _activeTrap._onKeyDown);
  }
  if (_activeTrap.triggerEl && typeof _activeTrap.triggerEl.focus === 'function') {
    _activeTrap.triggerEl.focus();
  }
  _activeTrap = null;
}
