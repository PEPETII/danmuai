/**
 * Desktop responsive console shell: compact rail + drawer navigation.
 * Does not change hash routing; only toggles body.shell-nav-open.
 */

const DRAWER_MQ = '(max-width: 959px)';
const OPEN_CLASS = 'shell-nav-open';

let _mq = null;
let _bound = false;

function isDrawerViewport() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia(DRAWER_MQ).matches;
}

function getEls() {
  return {
    body: document.body,
    toggle: document.getElementById('btnShellNavToggle'),
    closeBtn: document.getElementById('btnShellNavClose'),
    backdrop: document.getElementById('shellNavBackdrop'),
    sidebar: document.getElementById('consoleSidebar'),
  };
}

function setOpenAttrs(open) {
  const { toggle, backdrop, sidebar } = getEls();
  if (toggle) {
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  if (backdrop) {
    if (open) {
      backdrop.removeAttribute('hidden');
    } else {
      backdrop.setAttribute('hidden', '');
    }
  }
  if (sidebar && isDrawerViewport()) {
    sidebar.setAttribute('aria-hidden', open ? 'false' : 'true');
  } else if (sidebar) {
    sidebar.removeAttribute('aria-hidden');
  }
}

export function isShellNavOpen() {
  return document.body.classList.contains(OPEN_CLASS);
}

export function openShellNav() {
  if (!isDrawerViewport()) return;
  const { body, sidebar } = getEls();
  body.classList.add(OPEN_CLASS);
  setOpenAttrs(true);
  requestAnimationFrame(() => {
    const first = sidebar?.querySelector('#nav [data-page], #nav a[href]');
    if (first && typeof first.focus === 'function') {
      first.focus();
    }
  });
}

export function closeShellNav({ restoreFocus = true } = {}) {
  const { body, toggle } = getEls();
  const wasOpen = body.classList.contains(OPEN_CLASS);
  body.classList.remove(OPEN_CLASS);
  setOpenAttrs(false);
  if (wasOpen && restoreFocus && toggle && typeof toggle.focus === 'function') {
    toggle.focus();
  }
}

/** Close drawer after in-app navigation when in drawer breakpoint. */
export function closeShellNavIfDrawer() {
  if (isDrawerViewport() && isShellNavOpen()) {
    closeShellNav({ restoreFocus: false });
  }
}

function onKeyDown(event) {
  if (event.key !== 'Escape') return;
  if (!isDrawerViewport() || !isShellNavOpen()) return;
  event.preventDefault();
  closeShellNav({ restoreFocus: true });
}

function onMqChange() {
  if (!isDrawerViewport()) {
    closeShellNav({ restoreFocus: false });
  } else {
    setOpenAttrs(isShellNavOpen());
  }
}

export function initResponsiveShell() {
  if (_bound) return;
  const { toggle, closeBtn, backdrop } = getEls();
  if (!toggle && !document.getElementById('consoleSidebar')) return;

  toggle?.addEventListener('click', () => {
    if (isShellNavOpen()) {
      closeShellNav({ restoreFocus: true });
    } else {
      openShellNav();
    }
  });
  closeBtn?.addEventListener('click', () => closeShellNav({ restoreFocus: true }));
  backdrop?.addEventListener('click', () => closeShellNav({ restoreFocus: true }));
  document.addEventListener('keydown', onKeyDown);

  if (typeof window.matchMedia === 'function') {
    _mq = window.matchMedia(DRAWER_MQ);
    if (typeof _mq.addEventListener === 'function') {
      _mq.addEventListener('change', onMqChange);
    } else if (typeof _mq.addListener === 'function') {
      _mq.addListener(onMqChange);
    }
  }

  setOpenAttrs(false);
  _bound = true;
}
