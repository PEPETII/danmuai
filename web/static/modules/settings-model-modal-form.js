import { apiFetch } from "./transport.js";
import { isMaskedApiKey } from "./settings-defaults.js";
import { t } from "./i18n.js";
import {
  findProvider,
  getDefaultEndpoint,
  getModalProviderLabel,
  getUnifiedModalProviders,
  searchModalProviders,
  isCustomProvider,
} from "./settings-providers.js";
import {
  getModelCatalogModels,
  pickDefaultCatalogModelId,
} from "./settings-model-catalog.js";
import {
  bindModelDefaultSelect,
  initModelApiKeyVisibility,
  initModelTemperatureControls,
  resetModelApiKeyVisibility,
  syncModelModalUIState,
  syncModelTemperatureControls,
  setModelModalBusy,
  expandModelModalAdvanced,
} from "./settings-model-modal-state.js";
import {
  clearModelValidationErrors,
  validateModelForm,
} from "./settings-model-modal-validation.js";
import {
  abortModelProbe,
  initModelModalProbe,
  probeModelConnection,
} from "./settings-model-modal-probe.js";
import { activateFocusTrap, deactivateFocusTrap } from "./modal-focus-trap.js";
import {
  TAG_MAX_LEN,
  buildCatalogMultiselect,
  getDefaultModelIdFromList,
  getEditDescription,
  getModelIdsFromList,
  getModelNamesMap,
  getProfileDisplayName,
  initModelListBindings,
  initModelListFromProfile,
  renderModelListTable,
  replaceListForProvider,
  resetModelModalListState,
  setEditDescription,
  syncCatalogMultiselectChecks,
} from "./settings-model-modal-list.js";

const MODEL_TEMPERATURE_MIN = 0;
const MODEL_TEMPERATURE_MAX = 2;
const MODEL_TEMPERATURE_DEFAULT = 0.8;

let formDeps = {
  showToast: () => {},
  reloadConfigFromServer: async () => ({}),
  loadCustomModels: async () => {},
};

let modalBindingsWired = false;

function coerceModelTemperature(value) {
  if (value === undefined || value === null || value === "") return null;
  const parsed = typeof value === "number" ? value : parseFloat(String(value));
  if (Number.isNaN(parsed)) return null;
  if (parsed < MODEL_TEMPERATURE_MIN) return MODEL_TEMPERATURE_MIN;
  if (parsed > MODEL_TEMPERATURE_MAX) return MODEL_TEMPERATURE_MAX;
  return parsed;
}

function resolveModelTemperatureFallback(existingValue) {
  const existing = coerceModelTemperature(existingValue);
  if (existing !== null) return existing;
  return MODEL_TEMPERATURE_DEFAULT;
}

export function parseModelTemperatureInput() {
  const raw = document.getElementById("modelTemperature")?.value;
  if (raw === undefined || raw === null || raw === "") {
    return MODEL_TEMPERATURE_DEFAULT;
  }
  const parsed = parseFloat(String(raw));
  if (Number.isNaN(parsed)) return MODEL_TEMPERATURE_DEFAULT;
  if (parsed < MODEL_TEMPERATURE_MIN) return MODEL_TEMPERATURE_MIN;
  if (parsed > MODEL_TEMPERATURE_MAX) return MODEL_TEMPERATURE_MAX;
  return parsed;
}

export function configureModelModalForm(deps) {
  formDeps = { ...formDeps, ...deps };
}

function getProviderWebsite(providerId) {
  const provider = findProvider(providerId);
  const website = provider?.website;
  return typeof website === "string" && website.trim() ? website.trim() : null;
}

function updateProviderWebsiteDisplay(providerId) {
  const nameEl = document.getElementById("modelProviderName");
  const webRow = document.getElementById("modelProviderWebsite");
  const webLink = document.getElementById("modelProviderWebsiteLink");
  const openBtn = document.getElementById("modelOpenWebsite");
  const migrationEl = document.getElementById("modelProviderMigrationWarning");
  const provider = findProvider(providerId);
  if (nameEl) {
    if (provider && provider.id) {
      nameEl.textContent = t(
        "dynamic.settingsCustomModels.当前预设_provider_label",
        { providerLabel: provider.label },
      );
      nameEl.classList.remove("hidden");
    } else {
      nameEl.textContent = "";
      nameEl.classList.add("hidden");
    }
  }
  const website = getProviderWebsite(providerId);
  if (webRow && webLink && openBtn) {
    if (website) {
      webLink.textContent = website;
      webLink.href = website;
      openBtn.dataset.website = website;
      webRow.classList.remove("hidden");
    } else {
      webLink.textContent = "";
      webLink.href = "";
      delete openBtn.dataset.website;
      webRow.classList.add("hidden");
    }
  }
  if (migrationEl) {
    const status = String(provider?.lifecycle_status || "")
      .trim()
      .toLowerCase();
    const notice = String(provider?.notice || "").trim();
    const migrationUrl = String(provider?.migration_url || "").trim();
    const sunsetDate = String(provider?.sunset_date || "").trim();
    if (status === "migrating" || status === "legacy") {
      const parts = [];
      if (notice) parts.push(notice);
      else if (sunsetDate) {
        parts.push(
          t("dynamic.settingsCustomModels.服务商停服提示", { date: sunsetDate }),
        );
      }
      if (migrationUrl) {
        parts.push(
          `<a class="underline text-amber-900" href="${migrationUrl}" target="_blank" rel="noopener noreferrer">${t(
            "dynamic.settingsCustomModels.查看迁移公告",
          )}</a>`,
        );
      }
      migrationEl.innerHTML = parts.join(" ");
      migrationEl.classList.remove("hidden");
    } else {
      migrationEl.textContent = "";
      migrationEl.classList.add("hidden");
    }
  }
}

function setEndpointReadonly() {}

function modeToSaveValue(mode, providerId = "") {
  const raw = String(mode ?? "")
    .trim()
    .toLowerCase();
  if (raw === "doubao") return "doubao";
  if (
    raw === "openai" ||
    raw === "openai-compatible" ||
    raw === "openai_compatible"
  ) {
    return "openai-compatible";
  }
  if (providerId) {
    const provider = findProvider(providerId);
    if (provider?.mode) return provider.mode;
  }
  return "openai-compatible";
}

function modeToSelectValue(mode, providerId = "") {
  return modeToSaveValue(mode, providerId) === "doubao" ? "doubao" : "openai";
}

function resolveVisibleProviderId(requestedId = "") {
  const wanted = String(requestedId || "").trim();
  const all = getUnifiedModalProviders();
  if (wanted) {
    if (wanted === "custom_doubao") return "custom_openai";
    if (all.some((provider) => provider?.id === wanted)) return wanted;
    if (wanted === "custom" || wanted.startsWith("custom_")) {
      return "custom_openai";
    }
  }
  const fallback = document.getElementById("modelProvider")?.value || "";
  if (fallback && all.some((provider) => provider?.id === fallback)) {
    return fallback;
  }
  return all[0]?.id || "custom_openai";
}

function setSelectedProviderId(providerId, { keepSearch = false } = {}) {
  const hidden = document.getElementById("modelProvider");
  if (hidden) hidden.value = providerId || "";
  const label = document.getElementById("modelProviderTriggerLabel");
  if (label) {
    label.textContent = providerId
      ? getModalProviderLabel(providerId)
      : t("dynamic.settingsCustomModels.请选择模型平台");
  }
  if (!keepSearch) {
    const search = document.getElementById("modelProviderSearch");
    if (search && document.activeElement !== search) search.value = "";
  }
}

function renderProviderOptions(keyword = "") {
  const root = document.getElementById("modelProviderOptions");
  const empty = document.getElementById("modelProviderEmpty");
  if (!root) return;
  root.replaceChildren();
  const selectedId = document.getElementById("modelProvider")?.value || "";
  const providers = searchModalProviders(keyword);
  providers.forEach((provider) => {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "model-provider-option";
    option.setAttribute("role", "option");
    option.dataset.providerId = provider.id;
    option.setAttribute(
      "aria-selected",
      String(provider.id === selectedId),
    );
    if (provider.id === selectedId) option.classList.add("is-selected");
    const name = document.createElement("span");
    name.className = "model-provider-option-label";
    name.textContent = provider.label || provider.id;
    const id = document.createElement("span");
    id.className = "model-provider-option-id font-mono text-xs text-gray-400";
    id.textContent = provider.id;
    option.append(name, id);
    option.addEventListener("click", () => {
      selectModalProvider(provider.id);
    });
    root.appendChild(option);
  });
  if (empty) empty.classList.toggle("hidden", providers.length > 0);
}

function isProviderPanelOpen() {
  const panel = document.getElementById("modelProviderPanel");
  if (!panel) return false;
  return !panel.classList.contains("hidden");
}

function openProviderPanel({ focusSearch = true } = {}) {
  const panel = document.getElementById("modelProviderPanel");
  const trigger = document.getElementById("modelProviderTrigger");
  if (!panel || !trigger) return;
  panel.classList.remove("hidden");
  trigger.setAttribute("aria-expanded", "true");
  renderProviderOptions(
    document.getElementById("modelProviderSearch")?.value || "",
  );
  if (focusSearch) {
    const search = document.getElementById("modelProviderSearch");
    if (search) search.focus();
  }
}

function closeProviderPanel({ restoreFocus = false } = {}) {
  const panel = document.getElementById("modelProviderPanel");
  const trigger = document.getElementById("modelProviderTrigger");
  if (panel) panel.classList.add("hidden");
  if (trigger) trigger.setAttribute("aria-expanded", "false");
  if (restoreFocus && trigger && document.activeElement !== trigger) {
    trigger.focus();
  }
}

function selectModalProvider(providerId, options = {}) {
  const resolved = resolveVisibleProviderId(providerId);
  setSelectedProviderId(resolved, { keepSearch: true });
  renderProviderOptions(
    document.getElementById("modelProviderSearch")?.value || "",
  );
  closeProviderPanel();
  onProviderChangeInModal(resolved, options);
  refreshModalCapabilitiesState();
  const search = document.getElementById("modelProviderSearch");
  if (search) search.value = "";
}

let providerPickerBindingsWired = false;

function initProviderPickerBindings() {
  if (providerPickerBindingsWired) return;
  providerPickerBindingsWired = true;
  const trigger = document.getElementById("modelProviderTrigger");
  if (trigger) {
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      if (isProviderPanelOpen()) closeProviderPanel();
      else openProviderPanel();
    });
    trigger.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openProviderPanel();
      } else if (event.key === "Escape") {
        closeProviderPanel({ restoreFocus: true });
      }
    });
  }
  const search = document.getElementById("modelProviderSearch");
  if (search) {
    search.addEventListener("input", () => {
      renderProviderOptions(search.value);
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        closeProviderPanel({ restoreFocus: true });
      } else if (event.key === "Enter") {
        event.preventDefault();
        const selectedId = document.getElementById("modelProvider")?.value || "";
        const fallback = document.querySelector(
          "#modelProviderOptions .model-provider-option",
        );
        const scoped = selectedId
          ? document.querySelector(
              `#modelProviderOptions .model-provider-option[data-provider-id="${selectedId}"]`,
            )
          : null;
        const target = scoped || fallback;
        if (target?.dataset.providerId) {
          selectModalProvider(target.dataset.providerId, {
            isEdit: isEditMode(),
          });
        }
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const options = Array.from(
          document.querySelectorAll("#modelProviderOptions .model-provider-option"),
        );
        if (!options.length) return;
        const active = document.activeElement;
        const currentIndex = options.indexOf(active);
        const nextIndex =
          event.key === "ArrowDown"
            ? (currentIndex + 1) % options.length
            : (currentIndex - 1 + options.length) % options.length;
        options[nextIndex]?.focus();
      }
    });
  }
  document.addEventListener("click", (event) => {
    const root = document.getElementById("modelProviderPicker");
    if (!root || !isProviderPanelOpen()) return;
    if (!root.contains(event.target)) closeProviderPanel();
  });
}

function syncProviderDependentVisibility(providerId) {
  const custom = isCustomProvider(providerId);
  const modeField = document.getElementById("modelModeField");
  if (modeField) modeField.classList.toggle("hidden", !custom);
  const modeValue = document.getElementById("modelModeValue");
  if (modeValue) modeValue.value = "openai";
  const endpointField = document.getElementById("modelEndpointField");
  if (endpointField) endpointField.classList.toggle("hidden", !custom);
}

function refreshModelModeReadonlyLabel() {
  const label = document.getElementById("modelModeReadonly");
  if (label) label.textContent = t("dynamic.settingsProviders.OpenAI_兼容接口");
}

function isEditMode() {
  return (
    parseInt(document.getElementById("modelEditIndex")?.value || "-1", 10) >= 0
  );
}

function refreshModalCapabilitiesState(options = {}) {
  const providerId = document.getElementById("modelProvider")?.value || "";
  syncModelModalUIState({
    providerId,
    isEdit: isEditMode(),
    catalogModels: getModelCatalogModels(providerId),
    customProvider: isCustomProvider(providerId),
    defaultModelId: getDefaultModelIdFromList(),
    preserveSavedCapabilities: Boolean(options.preserveSavedCapabilities),
  });
}

function onProviderChangeInModal(providerId, options = {}) {
  const { isEdit = false } = options;
  const resolvedId = resolveVisibleProviderId(providerId);
  if (resolvedId !== providerId) setSelectedProviderId(resolvedId, { keepSearch: true });
  updateProviderWebsiteDisplay(resolvedId);
  syncProviderDependentVisibility(resolvedId);

  const endpointEl = document.getElementById("modelEndpoint");
  const custom = isCustomProvider(resolvedId);
  if (custom) {
    if (!isEdit && endpointEl) endpointEl.value = "";
  } else {
    const defaultEp = getDefaultEndpoint(resolvedId);
    if (endpointEl) endpointEl.value = defaultEp;
  }

  if (!isEdit) {
    const defaultId =
      pickDefaultCatalogModelId(resolvedId) ||
      getModelCatalogModels(resolvedId)[0]?.id ||
      "";
    if (custom) {
      resetModelModalListState();
      renderModelListTable();
    } else {
      replaceListForProvider(resolvedId, { defaultCatalogId: defaultId });
    }
    buildCatalogMultiselect(resolvedId);
    renderModelListTable();
  } else {
    buildCatalogMultiselect(resolvedId);
    syncCatalogMultiselectChecks();
    renderModelListTable();
  }
}

export function openModelModal(index, model = {}) {
  const isEdit = index >= 0;
  resetModelModalListState();
  document.getElementById("modelEditIndex").value = String(index);
  document.getElementById("modelModalTitle").textContent = isEdit
    ? t("dynamic.settingsCustomModels.编辑模型")
    : t("dynamic.settingsCustomModels.新增模型");
  const subtitleEl = document.getElementById("modelModalSubtitle");
  if (subtitleEl) {
    subtitleEl.textContent = isEdit
      ? t("dynamic.settingsCustomModels.编辑模型说明")
      : t("dynamic.settingsCustomModels.新增模型说明");
  }
  closeProviderPanel();
  const searchEl = document.getElementById("modelProviderSearch");
  if (searchEl) searchEl.value = "";
  refreshModelModeReadonlyLabel();

  const requestedProviderId = isEdit
    ? String(model.provider || "").trim() ||
      (String(model.mode || "").trim().toLowerCase() === "doubao"
        ? "custom_openai"
        : String(model.endpoint || "").trim()
          ? "custom_openai"
          : "doubao")
    : "doubao";
  const resolvedProviderId = resolveVisibleProviderId(requestedProviderId);
  setSelectedProviderId(resolvedProviderId);
  renderProviderOptions("");

  if (isEdit) {
    updateProviderWebsiteDisplay(resolvedProviderId);
    syncProviderDependentVisibility(resolvedProviderId);
    const endpointEl = document.getElementById("modelEndpoint");
    if (endpointEl) {
      endpointEl.value = isCustomProvider(resolvedProviderId)
        ? model.endpoint || ""
        : getDefaultEndpoint(resolvedProviderId);
    }
    initModelListFromProfile(model, resolvedProviderId);
    buildCatalogMultiselect(resolvedProviderId);
    syncCatalogMultiselectChecks();
    renderModelListTable();
  } else {
    onProviderChangeInModal(resolvedProviderId, { isEdit: false });
  }

  document.getElementById("modelApiKey").value = isMaskedApiKey(model.apiKey)
    ? model.apiKey
    : model.apiKey || "";
  const maxTokensEl = document.getElementById("modelMaxTokens");
  if (maxTokensEl) {
    const raw = model.max_tokens;
    let val = 512;
    if (typeof raw === "number" && raw >= 512) val = raw;
    else if (raw) {
      const parsed = parseInt(raw, 10);
      if (!Number.isNaN(parsed) && parsed >= 512) val = parsed;
    }
    maxTokensEl.value = String(val);
  }
  const temperatureEl = document.getElementById("modelTemperature");
  if (temperatureEl) {
    const tempValue = resolveModelTemperatureFallback(
      isEdit ? model.temperature : undefined,
    );
    temperatureEl.value = String(tempValue);
    syncModelTemperatureControls(tempValue);
  }
  setEditDescription(isEdit ? model.description || "" : "");
  const supportsMicEl = document.getElementById("modelSupportsMic");
  if (supportsMicEl) supportsMicEl.checked = Boolean(model.supportsMic);
  const thinkingEffortEl = document.getElementById("modelThinkingEffort");
  if (thinkingEffortEl) {
    const value = String(model.thinking_effort || "off").trim().toLowerCase();
    thinkingEffortEl.value = [
      "off",
      "none",
      "minimal",
      "low",
      "medium",
      "high",
      "xhigh",
      "max",
    ].includes(value)
      ? value
      : "off";
  }

  const modal = document.getElementById("modelModal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  activateFocusTrap(modal, closeModelModal);
  clearModelValidationErrors();
  resetModelApiKeyVisibility();
  bindModelDefaultSelect();
  initModelModalProbe(collectModelForm);
  refreshModalCapabilitiesState({ preserveSavedCapabilities: isEdit });
}

export function closeModelModal() {
  abortModelProbe();
  setModelModalBusy(false);
  deactivateFocusTrap();
  closeProviderPanel();
  const modal = document.getElementById("modelModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  resetModelApiKeyVisibility();
}

export function collectModelForm() {
  const providerId = document.getElementById("modelProvider")?.value || "";
  const custom = isCustomProvider(providerId);
  const modelIds = getModelIdsFromList();
  const defaultModelId = getDefaultModelIdFromList();
  const maxTokensRaw = parseInt(
    document.getElementById("modelMaxTokens")?.value || "512",
    10,
  );
  const maxTokens =
    Number.isNaN(maxTokensRaw) || maxTokensRaw < 512 ? 512 : maxTokensRaw;
  const fallbackMode = modeToSaveValue(
    document.getElementById("api_mode")?.value,
    providerId,
  );
  const providerMode = modeToSaveValue(findProvider(providerId)?.mode, providerId);
  const endpointValue = custom
    ? document.getElementById("modelEndpoint")?.value || ""
    : getDefaultEndpoint(providerId);
  return {
    name: getProfileDisplayName(),
    model_ids: modelIds,
    model_names: getModelNamesMap(),
    default_model_id: defaultModelId,
    max_tokens: maxTokens,
    mode: custom ? "openai-compatible" : providerMode || fallbackMode,
    endpoint: endpointValue,
    apiKey: document.getElementById("modelApiKey").value,
    description: getEditDescription(),
    provider: providerId,
    supportsMic: Boolean(document.getElementById("modelSupportsMic")?.checked),
    thinking_effort:
      document.getElementById("modelThinkingEffort")?.value || "off",
    temperature: parseModelTemperatureInput(),
  };
}

export async function saveModel() {
  setModelModalBusy(true, t("dynamic.settingsCustomModels.正在保存"));
  try {
    const validation = validateModelForm();
    if (!validation.valid) {
      expandModelModalAdvanced();
      validation.firstInvalidElement?.focus();
      throw new Error(t("dynamic.settingsCustomModels.请检查表单错误"));
    }
    const index = parseInt(document.getElementById("modelEditIndex").value, 10);
    const body = collectModelForm();
    if (!body.model_ids.length) {
      throw new Error(t("dynamic.settingsCustomModels.请至少添加一个模型_ID"));
    }
    if (index >= 0) {
      await apiFetch(`/api/custom-models/${index}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
    } else {
      await apiFetch("/api/custom-models", {
        method: "POST",
        body: JSON.stringify(body),
      });
    }
    closeModelModal();
    formDeps.showToast(t("dynamic.settingsCustomModels.模型已保存"));
    await formDeps.loadCustomModels();
  } finally {
    setModelModalBusy(false);
  }
}

export async function probe() {
  return probeModelConnection(collectModelForm);
}

export function initModelModalBindings() {
  if (modalBindingsWired) return;
  modalBindingsWired = true;

  initModelApiKeyVisibility();
  initModelTemperatureControls();
  bindModelDefaultSelect();
  initModelModalProbe(collectModelForm);
  initProviderPickerBindings();
  initModelListBindings(() => refreshModalCapabilitiesState());
  refreshModelModeReadonlyLabel();

  const addBtn = document.getElementById("btnAddCustomModel");
  if (addBtn && addBtn.dataset.bound !== "true") {
    addBtn.dataset.bound = "true";
    addBtn.addEventListener("click", () => openModelModal(-1));
  }

  document
    .getElementById("btnModelClose")
    ?.addEventListener("click", closeModelModal);
  document
    .getElementById("btnModelCancel")
    ?.addEventListener("click", closeModelModal);

  const openBtn = document.getElementById("modelOpenWebsite");
  if (openBtn) {
    openBtn.addEventListener("click", () => {
      const website =
        openBtn.dataset.website ||
        getProviderWebsite(document.getElementById("modelProvider")?.value);
      if (website) window.open(website, "_blank");
    });
  }
}

export { TAG_MAX_LEN };
