let toast = () => {};
let handlersBound = false;

function initVirtualHostTabs() {
  document.querySelectorAll('.virtual-host-tabs .settings-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const tabId = tab.dataset.virtualHostTab;
      document.querySelectorAll('.virtual-host-tabs .settings-tab').forEach((item) => {
        const active = item.dataset.virtualHostTab === tabId;
        item.classList.toggle('active', active);
        item.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      document.querySelectorAll('[data-virtual-host-panel]').forEach((panel) => {
        const active = panel.dataset.virtualHostPanel === tabId;
        panel.classList.toggle('active', active);
        panel.hidden = !active;
      });
      if (tabId === 'vtuber-persona') {
        import('./app-vtuber-persona-page.js').then((mod) => {
          mod.initVtuberPersonaPage({ showToast: toast });
          mod.onVtuberPersonaTabActivated();
        }).catch(() => {});
      }
      if (tabId === 'vtuber-download') {
        import('./app-vtuber-download-page.js').then((mod) => {
          mod.initVtuberDownloadPage();
          mod.onVtuberDownloadTabActivated();
        }).catch(() => {});
      }
    });
  });
}

export function initVirtualHostPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;
  initVirtualHostTabs();
}

export async function loadVirtualHostPage() {
  return undefined;
}
