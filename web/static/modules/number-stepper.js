const STEPPER_SELECTOR = '.settings-rhythm-stepper';
const BOUND_ATTR = 'data-stepper-bound';

function resolveFieldLabel(input) {
  if (input.id) {
    const explicit = document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
    if (explicit) return explicit.textContent.trim();
  }
  const field = input.closest('.settings-rhythm-accordion-field, .settings-field');
  const label = field?.querySelector('.settings-field-label');
  if (label) return label.textContent.trim();
  return '';
}

function stepButtonAriaLabel(input, direction) {
  const label = resolveFieldLabel(input);
  const verb = direction < 0 ? '减小' : '增大';
  return label ? `${verb}${label}` : `${verb}数值`;
}

function syncStepButtons(stepper) {
  const input = stepper.querySelector('input[type="number"]');
  if (!(input instanceof HTMLInputElement)) return;

  const value = input.valueAsNumber;
  const min = input.min === '' ? null : Number(input.min);
  const max = input.max === '' ? null : Number(input.max);

  stepper.querySelectorAll('[data-step-dir]').forEach((button) => {
    const direction = Number(button.dataset.stepDir);
    button.disabled = !Number.isFinite(value)
      || (direction < 0 && min !== null && value <= min)
      || (direction > 0 && max !== null && value >= max);
  });
}

function stepInput(input, direction) {
  if (!Number.isFinite(input.valueAsNumber)) input.value = input.min || '0';
  if (direction > 0) input.stepUp();
  else input.stepDown();
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

export function wrapNumberInput(input) {
  if (!(input instanceof HTMLInputElement)) return null;
  if (input.type !== 'number') return null;
  if (input.hasAttribute('data-no-stepper')) return null;
  if (input.closest(STEPPER_SELECTOR)) return input.closest(STEPPER_SELECTOR);

  const stepper = document.createElement('div');
  stepper.className = 'settings-rhythm-stepper';
  if (input.classList.contains('w-full')) {
    stepper.classList.add('settings-rhythm-stepper--wide');
  }
  if (input.classList.contains('w-20') || input.classList.contains('weight-input')) {
    stepper.classList.add('settings-rhythm-stepper--compact');
  }

  const decButton = document.createElement('button');
  decButton.type = 'button';
  decButton.className = 'settings-rhythm-step-button';
  decButton.dataset.stepDir = '-1';
  decButton.setAttribute('aria-label', stepButtonAriaLabel(input, -1));
  decButton.textContent = '−';

  const incButton = document.createElement('button');
  incButton.type = 'button';
  incButton.className = 'settings-rhythm-step-button';
  incButton.dataset.stepDir = '1';
  incButton.setAttribute('aria-label', stepButtonAriaLabel(input, 1));
  incButton.textContent = '+';

  const parent = input.parentNode;
  if (!parent) return null;

  parent.insertBefore(stepper, input);
  stepper.append(decButton, input, incButton);
  return stepper;
}

export function bindNumberStepper(stepper) {
  if (!(stepper instanceof HTMLElement)) return;
  if (stepper.getAttribute(BOUND_ATTR) === 'true') return;

  const input = stepper.querySelector('input[type="number"]');
  if (!(input instanceof HTMLInputElement)) return;

  stepper.querySelectorAll('[data-step-dir]').forEach((button) => {
    button.addEventListener('click', () => {
      stepInput(input, Number(button.dataset.stepDir));
      syncStepButtons(stepper);
    });
  });
  input.addEventListener('input', () => syncStepButtons(stepper));
  syncStepButtons(stepper);
  stepper.setAttribute(BOUND_ATTR, 'true');
}

export function initNumberSteppers(root = document) {
  root.querySelectorAll('input[type="number"]:not([data-no-stepper])').forEach((input) => {
    const stepper = wrapNumberInput(input);
    if (stepper) bindNumberStepper(stepper);
  });
}