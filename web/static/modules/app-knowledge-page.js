/**
 * 知识包页面编排层（Wave 5 A9 + UI rework）。
 */

import { initSettingsRhythmAccordion } from './settings-rhythm-accordion.js';
import { setKnowledgeToast } from './app-knowledge-state.js';
import {
  itemPage,
  itemTotalPages,
  setItemPage,
} from './app-knowledge-state.js';
import { loadKnowledgePage, createNewPackage } from './app-knowledge-package-list.js';
import {
  openPackageDetail,
  savePackageSettings,
  deleteCurrentPackage,
  bindDetailFieldWatchers,
} from './app-knowledge-package-detail.js';
import {
  startImport,
  bindSourceTypeCards,
  syncSourceFormVisibility,
} from './app-knowledge-import.js';
import {
  startKnowledgeJobPolling,
  stopKnowledgeJobPolling,
  openFirstActiveJobModal,
} from './app-knowledge-jobs.js';
import { loadItems } from './app-knowledge-items.js';
import { startPreview } from './app-knowledge-retrieval.js';
import { bindCreatePackageModalStatic } from './app-knowledge-modals.js';

export { loadKnowledgePage, createNewPackage } from './app-knowledge-package-list.js';
export { startKnowledgeJobPolling, stopKnowledgeJobPolling } from './app-knowledge-jobs.js';
export { isActiveToTerminalTransition } from './app-knowledge-status.js';

let handlersBound = false;

export function showListView() {
  document.getElementById('knowledgeListView')?.classList.remove('hidden');
  document.getElementById('knowledgePackageDetail')?.classList.add('hidden');
  document.getElementById('knowledgeRetrievalPreview')?.classList.add('hidden');
}

export function showDetailView() {
  document.getElementById('knowledgeListView')?.classList.add('hidden');
  document.getElementById('knowledgePackageDetail')?.classList.remove('hidden');
  document.getElementById('knowledgeRetrievalPreview')?.classList.add('hidden');
}

export function showRetrievalView() {
  document.getElementById('knowledgeListView')?.classList.add('hidden');
  document.getElementById('knowledgePackageDetail')?.classList.add('hidden');
  document.getElementById('knowledgeRetrievalPreview')?.classList.remove('hidden');
}

export function initKnowledgePage(deps = {}) {
  setKnowledgeToast(deps.showToast);
  if (handlersBound) return;
  handlersBound = true;

  initSettingsRhythmAccordion(document.getElementById('page-knowledge') || document);
  bindCreatePackageModalStatic();
  bindDetailFieldWatchers();
  bindSourceTypeCards();
  syncSourceFormVisibility();

  document.getElementById('btnKnowledgeNewPackage')?.addEventListener('click', () => {
    void createNewPackage();
  });
  document.getElementById('btnKnowledgeRefresh')?.addEventListener('click', () => {
    void loadKnowledgePage();
  });
  document.getElementById('btnKnowledgeOpenRetrievalPreview')?.addEventListener('click', () => {
    showRetrievalView();
  });

  document.getElementById('btnKnowledgeBackToList')?.addEventListener('click', () => {
    void loadKnowledgePage();
  });
  document.getElementById('btnKnowledgePreviewBack')?.addEventListener('click', () => {
    showDetailView();
  });

  document.getElementById('btnKnowledgeSavePackage')?.addEventListener('click', () => {
    void savePackageSettings();
  });
  document.getElementById('btnKnowledgeDeletePackage')?.addEventListener('click', () => {
    void deleteCurrentPackage();
  });

  document.getElementById('btnKnowledgeStartImport')?.addEventListener('click', () => {
    void startImport();
  });

  document.getElementById('btnKnowledgeSearchItems')?.addEventListener('click', () => {
    setItemPage(1);
    void loadItems();
  });
  document.getElementById('btnKnowledgeItemPrev')?.addEventListener('click', () => {
    if (itemPage > 1) {
      setItemPage(itemPage - 1);
      void loadItems();
    }
  });
  document.getElementById('btnKnowledgeItemNext')?.addEventListener('click', () => {
    if (itemPage < itemTotalPages) {
      setItemPage(itemPage + 1);
      void loadItems();
    }
  });

  document.getElementById('btnKnowledgeStartPreview')?.addEventListener('click', () => {
    void startPreview();
  });

  document.getElementById('btnKnowledgeViewProgress')?.addEventListener('click', () => {
    openFirstActiveJobModal();
  });
}
