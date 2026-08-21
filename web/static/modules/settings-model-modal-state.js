import { t } from "./i18n.js";
import { getModelNameFromCatalog } from "./settings-model-catalog.js";

const MODEL_TEMPERATURE_MIN = 0;
const MODEL_TEMPERATURE_MAX = 2;

function resolveCatalogModel(defaultModelId, catalogModels) {
  const id = String(defaultModelId || "").trim();
  if (!id) return null;
  return catalogModels.find((model) => model.id === id) || null;
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

  if (!catalogModel) {
    select.value = "off";
    select.disabled = true;
    if (hint) {
      hint.textContent = t(
        "dynamic.settingsCustomModels.暂未获取到该模型的能力信息",
      );
    }
    return;
  }

  const mode = String(catalogModel.thinking_mode || "").trim().toLowerCase();
  const declaredEfforts = Array.isArray(catalogModel.reasoning_effort_values)
    ? catalogModel.reasoning_effort_values
        .map((value) => String(value || "").trim().toLowerCase())
        .filter(Boolean)
    : [];
  const values =
    mode === "off"
      ? ["off"]
      : mode === "always"
        ? ["high"]
        : declaredEfforts.length
          ? [
              "off",
              ...declaredEfforts.filter(
                (value) => value !== "none" && value !== "off",
              ),
            ]
          : ["off", "low", "medium", "high"];
  const previousValue = String(select.value || "off").trim().toLowerCase();
  select.replaceChildren(
    ...values.map((value) => {
      const option = document.createElement("option");
      option.value = value;
      const labelKey =
        {
          off: "dynamic.settingsCustomModels.关闭思考",
          low: "dynamic.settingsCustomModels.低",
          medium: "dynamic.settingsCustomModels.中",
          high: "dynamic.settingsCustomModels.高",
          minimal: "dynamic.settingsCustomModels.最低",
          xhigh: "dynamic.settingsCustomModels.极高",
          max: "dynamic.settingsCustomModels.最大",
        }[value] || value;
      option.dataset.i18n = labelKey;
      option.textContent = t(labelKey);
      return option;
    }),
  );
  select.value = values.includes(previousValue) ? previousValue : values[0];
  if (mode === "off") {
    select.value = "off";
    select.disabled = true;
    if (hint) {
      hint.textContent = t(
        "dynamic.settingsCustomModels.该模型未声明思考能力",
      );
    }
  } else if (mode === "always") {
    select.value = "high";
    select.disabled = true;
    if (hint) {
      hint.textContent = t("dynamic.settingsCustomModels.该模型始终开启思考");
    }
  } else {
    select.disabled = false;
    if (hint) {
      hint.textContent = t("dynamic.settingsCustomModels.思考程度提示");
    }
  }
}

function syncModelTemperatureCapability({ catalogModel = null } = {}) {
  const numberEl = document.getElementById("modelTemperature");
  const rangeEl = document.getElementById("modelTemperatureRange");
  const hintEl = document.getElementById("modelTemperatureHint");
  const hintLabelEl = document.getElementById("modelTemperatureHintLabel");
  const thinkingEl = document.getElementById("modelThinkingEffort");
  const support = String(catalogModel?.temperature_support || "always");
  const reasoningOff = ["off", "none"].includes(
    String(thinkingEl?.value || "off").toLowerCase(),
  );
  const disabled =
    support === "never" || (support === "reasoning_none_only" && !reasoningOff);
  [numberEl, rangeEl].forEach((element) => {
    if (!element) return;
    element.disabled = disabled;
    element.setAttribute("aria-disabled", String(disabled));
  });
  if (hintEl) {
    if (support === "never") {
      hintEl.textContent = t(
        "dynamic.settingsCustomModels.模型不支持_Temperature",
      );
    } else if (support === "reasoning_none_only") {
      hintEl.textContent = t(
        "dynamic.settingsCustomModels.Temperature_仅在关闭思考时发送",
      );
    } else if (!disabled) {
      hintEl.textContent = t("dynamic.settingsCustomModels.温度提示");
    }
  }
  if (hintLabelEl && disabled) {
    hintLabelEl.textContent = t("dynamic.settingsCustomModels.不适用");
  } else if (hintLabelEl && !disabled) {
    hintLabelEl.textContent = t(temperatureHintKey(numberEl?.value));
  }
}

function syncModelMicForDefault({
  catalogModel = null,
  preserveSaved = false,
} = {}) {
  const mic = document.getElementById("modelSupportsMic");
  if (!mic) return;

  if (!catalogModel) {
    mic.checked = false;
    mic.disabled = true;
    return;
  }

  if (!catalogModel.supports_mic) {
    mic.checked = false;
    mic.disabled = true;
    return;
  }

  mic.disabled = false;
  if (!preserveSaved) {
    mic.checked = Boolean(catalogModel.supports_mic);
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
  defaultModelId = "",
  preserveSavedCapabilities = false,
} = {}) {
  const catalogModel = resolveCatalogModel(defaultModelId, catalogModels);
  const endpoint = document.getElementById("modelEndpoint");
  const customIds = customProvider;

  if (endpoint) {
    endpoint.readOnly = !customProvider;
    endpoint.classList.toggle("bg-gray-100", !customProvider);
    endpoint.classList.toggle("cursor-not-allowed", !customProvider);
  }

  syncModelMicForDefault({
    catalogModel,
    preserveSaved: preserveSavedCapabilities,
  });
  syncModelThinkingEffort({ catalogModel });
  const thinkingSelect = document.getElementById("modelThinkingEffort");
  if (thinkingSelect && thinkingSelect.dataset.temperatureCapabilityBound !== "true") {
    thinkingSelect.dataset.temperatureCapabilityBound = "true";
    thinkingSelect.addEventListener("change", () =>
      syncModelTemperatureCapability(),
    );
  }
  syncModelTemperatureCapability({ catalogModel });
  setAdvancedOpen(customIds);
  return { catalogModel, customIds };
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
  /* default model radios live in the model list table */
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
  /* handled by settings-model-modal-list.js */
}

export function resolveDefaultModelCatalog(providerId, defaultModelId) {
  const id = String(defaultModelId || "").trim();
  if (!id) return null;
  const name = getModelNameFromCatalog(providerId, id);
  return name ? { id, name } : { id, name: id };
}
