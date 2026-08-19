import { t } from "./i18n.js";

const CUSTOM_VALUE = "__custom__";
const MODEL_TEMPERATURE_MIN = 0;
const MODEL_TEMPERATURE_MAX = 2;

function getChips() {
  return Array.from(
    document.querySelectorAll("#modelIdsTags .tag-chip[data-value]"),
  );
}

function setChipDefault(chip, isDefault) {
  if (!chip) return;
  if (isDefault) chip.setAttribute("data-default", "1");
  else chip.removeAttribute("data-default");
  let mark = chip.querySelector(".tag-default-mark");
  if (isDefault && !mark) {
    mark = document.createElement("span");
    mark.className = "tag-default-mark";
    mark.textContent = t("common.defaultLabel");
    chip.insertBefore(mark, chip.querySelector(".tag-remove"));
  } else if (!isDefault && mark) mark.remove();
}

function syncDefaultSelect() {
  const select = document.getElementById("modelDefaultIdSelect");
  if (!select) return;
  const chips = getChips();
  const ids = chips.map((chip) => chip.dataset.value || "").filter(Boolean);
  const current =
    chips.find((chip) => chip.hasAttribute("data-default"))?.dataset.value ||
    ids[0] ||
    "";
  select.replaceChildren(
    ...ids.map((id) => {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      option.selected = id === current;
      return option;
    }),
  );
  select.classList.toggle("hidden", ids.length <= 1);
  select.value = current;
}

function setAdvancedOpen(open) {
  const root = document.querySelector(
    "#modelModal [data-settings-rhythm-accordion]",
  );
  const trigger = root?.querySelector(".settings-rhythm-accordion-trigger");
  const panel = root?.querySelector(".settings-rhythm-accordion-panel");
  if (!trigger || !panel) return;
  root
    .querySelector(".settings-rhythm-accordion-item")
    ?.classList.toggle("is-open", open);
  trigger.setAttribute("aria-expanded", String(open));
  panel.hidden = !open;
}

function syncModelThinkingEffort({ catalogModel = null } = {}) {
  const select = document.getElementById("modelThinkingEffort");
  const hint = document.getElementById("modelThinkingEffortHint");
  if (!select) return;

  const mode = String(catalogModel?.thinking_mode || "").trim().toLowerCase();
  if (mode === "off") {
    select.value = "off";
    select.disabled = true;
    if (hint) hint.textContent = t("dynamic.settingsCustomModels.该模型未声明思考能力");
  } else if (mode === "always") {
    select.value = "high";
    select.disabled = true;
    if (hint) hint.textContent = t("dynamic.settingsCustomModels.该模型始终开启思考");
  } else {
    select.disabled = false;
    if (hint) hint.textContent = t("dynamic.settingsCustomModels.思考程度提示");
  }
}

export function expandModelModalAdvanced() {
  setAdvancedOpen(true);
}

export function syncModelModalUIState({
  providerId = "",
  isEdit = false,
  catalogModels = [],
  customProvider = false,
} = {}) {
  const preset = document.getElementById("modelIdPreset");
  const selectedId = preset?.value || "";
  const catalogModel = catalogModels.find((model) => model.id === selectedId);
  const isCatalogPreset = Boolean(catalogModel) && selectedId !== CUSTOM_VALUE;
  const endpoint = document.getElementById("modelEndpoint");
  const modelIdsWrap = document.getElementById("modelIdsTagsWrap");
  const input = document.getElementById("modelIdsInput");
  const mic = document.getElementById("modelSupportsMic");
  const customIds =
    customProvider ||
    selectedId === CUSTOM_VALUE ||
    (isEdit && !isCatalogPreset);

  if (endpoint) {
    endpoint.readOnly = !customProvider;
    endpoint.classList.toggle("bg-gray-100", !customProvider);
    endpoint.classList.toggle("cursor-not-allowed", !customProvider);
  }
  if (modelIdsWrap) modelIdsWrap.classList.toggle("hidden", !customIds);
  if (input) {
    input.disabled = !customIds;
    input.placeholder = customIds
      ? t("dynamic.settingsCustomModels.例如_doubao_1_5_pro_32k_25")
      : "";
  }
  if (mic) {
    mic.disabled = false;
    // Catalog supports_mic is a default for new profiles only; saved supportsMic wins in edit mode.
    if (!isEdit && isCatalogPreset && catalogModel) {
      mic.checked = Boolean(catalogModel.supports_mic);
    }
  }
  syncModelThinkingEffort({ catalogModel: isCatalogPreset ? catalogModel : null });
  syncDefaultSelect();
  setAdvancedOpen(customIds || (isEdit && !isCatalogPreset));
  return { isCatalogPreset, customIds, catalogModel };
}

function coerceTemperatureValue(value) {
  const parsed = typeof value === "number" ? value : parseFloat(String(value));
  if (Number.isNaN(parsed)) return null;
  if (parsed < MODEL_TEMPERATURE_MIN) return MODEL_TEMPERATURE_MIN;
  if (parsed > MODEL_TEMPERATURE_MAX) return MODEL_TEMPERATURE_MAX;
  return Math.round(parsed * 10) / 10;
}

export function temperatureHintKey(value) {
  const temp = coerceTemperatureValue(value);
  if (temp === null) return "dynamic.settingsCustomModels.温度平衡";
  if (temp <= 0.5) return "dynamic.settingsCustomModels.温度精确";
  if (temp >= 1.2) return "dynamic.settingsCustomModels.温度创意";
  return "dynamic.settingsCustomModels.温度平衡";
}

export function syncModelTemperatureControls(value) {
  const normalized = coerceTemperatureValue(value);
  const numberEl = document.getElementById("modelTemperature");
  const rangeEl = document.getElementById("modelTemperatureRange");
  const hintEl = document.getElementById("modelTemperatureHintLabel");
  if (normalized === null) return;
  const text = String(normalized);
  if (numberEl && numberEl.value !== text) numberEl.value = text;
  if (rangeEl && rangeEl.value !== text) rangeEl.value = text;
  if (hintEl) hintEl.textContent = t(temperatureHintKey(normalized));
}

export function initModelTemperatureControls() {
  const numberEl = document.getElementById("modelTemperature");
  const rangeEl = document.getElementById("modelTemperatureRange");
  if (!numberEl || !rangeEl) return;

  const onChange = (value) => syncModelTemperatureControls(value);

  if (rangeEl.dataset.bound !== "true") {
    rangeEl.dataset.bound = "true";
    rangeEl.addEventListener("input", () => onChange(rangeEl.value));
  }
  if (numberEl.dataset.bound !== "true") {
    numberEl.dataset.bound = "true";
    numberEl.addEventListener("input", () => onChange(numberEl.value));
    numberEl.addEventListener("change", () => onChange(numberEl.value));
  }
}

export function resetModelApiKeyVisibility() {
  const input = document.getElementById("modelApiKey");
  const button = document.getElementById("btnModelApiKeyVisibility");
  if (input) input.type = "password";
  if (button) {
    button.setAttribute("aria-pressed", "false");
    button.setAttribute(
      "aria-label",
      t("dynamic.settingsCustomModels.显示_API_Key"),
    );
    button.setAttribute("title", t("dynamic.settingsCustomModels.显示"));
  }
}

export function initModelApiKeyVisibility() {
  const input = document.getElementById("modelApiKey");
  const button = document.getElementById("btnModelApiKeyVisibility");
  if (!input || !button || button.dataset.bound === "true") return;
  button.dataset.bound = "true";
  button.addEventListener("click", () => {
    const visible = input.type === "password";
    input.type = visible ? "text" : "password";
    button.setAttribute("aria-pressed", String(visible));
    button.setAttribute(
      "aria-label",
      t(`dynamic.settingsCustomModels.${visible ? "隐藏" : "显示"}_API_Key`),
    );
    button.setAttribute(
      "title",
      t(`dynamic.settingsCustomModels.${visible ? "隐藏" : "显示"}`),
    );
  });
}

export function syncModelDefaultSelect() {
  syncDefaultSelect();
}

export function setModelModalBusy(isBusy, label = "") {
  const save = document.getElementById("btnModelSave");
  const probe = document.getElementById("btnModelProbe");
  if (save) {
    if (isBusy) {
      save.dataset.defaultLabel = save.textContent || "";
      save.textContent = label || t("dynamic.settingsCustomModels.正在保存");
    } else if (save.dataset.defaultLabel) {
      save.textContent = save.dataset.defaultLabel;
      delete save.dataset.defaultLabel;
    }
    save.disabled = isBusy;
  }
  if (probe) probe.disabled = isBusy;
}

export function bindModelDefaultSelect() {
  const select = document.getElementById("modelDefaultIdSelect");
  if (!select || select.dataset.bound === "true") return;
  select.dataset.bound = "true";
  select.addEventListener("change", () => {
    const selected = select.value;
    getChips().forEach((chip) =>
      setChipDefault(chip, chip.dataset.value === selected),
    );
    syncDefaultSelect();
  });
}
