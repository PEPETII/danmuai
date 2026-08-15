import { apiFetch } from './transport.js';
import { t } from './i18n.js';
import { activateFocusTrap, deactivateFocusTrap } from './modal-focus-trap.js';
import { showKnowledgeToast } from './app-knowledge-state.js';

let confirmResolve = null;
let confirmCleanup = null;
let createCleanup = null;
let quickStartCleanup = null;

function showModal(modal) {
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function hideModal(modal) {
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

export function openKnowledgeConfirmModal({ title, message, confirmLabel, danger = true }) {
  const modal = document.getElementById('knowledgeConfirmModal');
  const titleEl = document.getElementById('knowledgeConfirmModalTitle');
  const messageEl = document.getElementById('knowledgeConfirmModalMessage');
  const okBtn = document.getElementById('btnKnowledgeConfirmOk');
  const cancelBtn = document.getElementById('btnKnowledgeConfirmCancel');
  if (!modal || !titleEl || !messageEl || !okBtn || !cancelBtn) {
    return Promise.resolve(false);
  }

  titleEl.textContent = title;
  messageEl.textContent = message;
  okBtn.textContent =
    confirmLabel || t('dynamic.appKnowledgePage.confirm.ok');
  okBtn.className = danger
    ? 'px-5 py-2 bg-red-500 text-white rounded-xl text-sm font-bold hover:bg-red-600 ui-button ui-button--danger ui-button--md'
    : 'btn-primary px-5 py-2 text-white rounded-xl text-sm font-bold ui-button ui-button--primary ui-button--md';

  return new Promise((resolve) => {
    if (typeof confirmCleanup === 'function') confirmCleanup();
    confirmResolve = resolve;

    const close = (result) => {
      hideModal(modal);
      deactivateFocusTrap();
      if (typeof confirmCleanup === 'function') confirmCleanup();
      confirmCleanup = null;
      confirmResolve = null;
      resolve(result);
    };

    const onOk = () => close(true);
    const onCancel = () => close(false);

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    confirmCleanup = () => {
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
    };

    showModal(modal);
    activateFocusTrap(modal, onCancel);
  });
}

export function openCreatePackageModal() {
  const modal = document.getElementById('knowledgeCreatePackageModal');
  const nameInput = document.getElementById('knowledgeCreatePackageName');
  const nameError = document.getElementById('knowledgeCreateNameError');
  const submitBtn = document.getElementById('btnKnowledgeCreatePackageSubmit');
  const cancelBtn = document.getElementById('btnKnowledgeCreatePackageCancel');
  if (!modal || !nameInput || !submitBtn || !cancelBtn) {
    return Promise.resolve(null);
  }

  nameInput.value = '';
  if (nameError) {
    nameError.textContent = '';
    nameError.classList.add('hidden');
  }

  return new Promise((resolve) => {
    if (typeof createCleanup === 'function') createCleanup();

    const close = (result) => {
      hideModal(modal);
      deactivateFocusTrap();
      if (typeof createCleanup === 'function') createCleanup();
      createCleanup = null;
      resolve(result);
    };

    const onCancel = () => close(null);
    const onSubmit = async () => {
      const name = nameInput.value.trim();
      if (!name) {
        if (nameError) {
          nameError.textContent = t('dynamic.appKnowledgePage.create.nameRequired');
          nameError.classList.remove('hidden');
        }
        nameInput.focus();
        return;
      }
      if (nameError) nameError.classList.add('hidden');
      submitBtn.disabled = true;
      try {
        const result = await apiFetch('/api/knowledge/packages', {
          method: 'POST',
          body: JSON.stringify({ name }),
        });
        showKnowledgeToast(t('dynamic.appKnowledgePage.packageCreated'));
        close(result);
      } catch (error) {
        showKnowledgeToast(error.message, true);
      } finally {
        submitBtn.disabled = false;
      }
    };

    submitBtn.addEventListener('click', () => void onSubmit());
    cancelBtn.addEventListener('click', onCancel);
    createCleanup = () => {
      submitBtn.removeEventListener('click', onSubmit);
      cancelBtn.removeEventListener('click', onCancel);
    };

    showModal(modal);
    activateFocusTrap(modal, onCancel);
    nameInput.focus();
  });
}

export function openKnowledgeQuickStartModal() {
  const modal = document.getElementById('knowledgeQuickStartModal');
  const closeBtn = document.getElementById('btnKnowledgeQuickStartClose');
  if (!modal || !closeBtn) return;

  if (typeof quickStartCleanup === 'function') quickStartCleanup();

  const close = () => {
    hideModal(modal);
    deactivateFocusTrap();
    if (typeof quickStartCleanup === 'function') quickStartCleanup();
    quickStartCleanup = null;
  };

  const onClose = () => close();
  closeBtn.addEventListener('click', onClose);
  quickStartCleanup = () => {
    closeBtn.removeEventListener('click', onClose);
  };

  showModal(modal);
  activateFocusTrap(modal, onClose);
}

export function bindKnowledgeQuickStartModalStatic() {
  document.getElementById('btnKnowledgeQuickStart')?.addEventListener('click', () => {
    openKnowledgeQuickStartModal();
  });
}

export function bindCreatePackageModalStatic() {
  document.getElementById('btnKnowledgeCreateFirstPackage')?.addEventListener('click', () => {
    void openCreatePackageModal().then((result) => {
      if (result?.package_id) {
        import('./app-knowledge-package-detail.js').then((m) =>
          m.openPackageDetail(result.package_id),
        );
      }
    });
  });
}
