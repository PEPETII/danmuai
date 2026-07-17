const ROOT_SELECTOR = '[data-settings-rhythm-accordion]';
const ITEM_SELECTOR = '.settings-rhythm-accordion-item';
const TRIGGER_SELECTOR = '.settings-rhythm-accordion-trigger';
const PANEL_SELECTOR = '.settings-rhythm-accordion-panel';

function bindAccordionItem(item) {
  const trigger = item.querySelector(TRIGGER_SELECTOR);
  const panel = item.querySelector(PANEL_SELECTOR);
  if (!(trigger instanceof HTMLButtonElement) || !panel) return;

  const syncState = (isOpen) => {
    item.classList.toggle('is-open', isOpen);
    trigger.setAttribute('aria-expanded', String(isOpen));
    panel.hidden = !isOpen;
  };

  syncState(trigger.getAttribute('aria-expanded') === 'true');
  trigger.addEventListener('click', () => {
    syncState(trigger.getAttribute('aria-expanded') !== 'true');
  });
}

function bindAccordionRoot(accordion) {
  if (accordion.dataset.bound === 'true') return;

  accordion.querySelectorAll(ITEM_SELECTOR).forEach((item) => {
    bindAccordionItem(item);
  });
  accordion.dataset.bound = 'true';
}

export function initSettingsRhythmAccordion(root = document) {
  root.querySelectorAll(ROOT_SELECTOR).forEach((accordion) => {
    bindAccordionRoot(accordion);
  });
}