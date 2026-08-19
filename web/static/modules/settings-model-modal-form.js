import { apiFetch } from "./transport.js";
import { isMaskedApiKey } from "./settings-defaults.js";
import { t } from "./i18n.js";
import {
  findProvider,
  getProviderWebsite,
  isCustomProvider,
  getDefaultEndpoint,
  MODAL_PROVIDER_REGION_CHINA,
  MODAL_PROVIDER_REGION_INTERNATIONAL,
  inferModalProviderRegion,
  fillModelProviderSelect,
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
  addCatalogModelToList,
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
  setCatalogMultiselectVisible,
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

function setEndpointReadonly(readonly) {
  const el = document.getElementById("modelEndpoint");
  if (!el) return;
  if (readonly) {
    el.setAttribute("readonly", "");
    el.classList.add("bg-gray-100", "cursor-not-allowed");
  } else {
    el.removeAttribute("readonly");
    el.classList.remove("bg-gray-100", "cursor-not-allowed");
  }
}

function modeToSelectValue(mode, providerId = "") {
  const raw = String(mode ?? "")
    .trim()
    .toLowerCase();
  if (raw === "doubao") return "doubao";
  if (
    raw === "openai" ||
    raw === "openai-compatible" ||
    raw === "openai_compatible"
  ) {
    return "openai";
  }
  if (providerId) {
    const provider = findProvider(providerId);
    if (provider?.mode) {
      return provider.mode === "openai-compatible" ? "openai" : provider.mode;
    }
  }
  return "openai";
}

function initModelProviderRegionSelect(
  preferredValue = MODAL_PROVIDER_REGION_CHINA,
) {
  const el = document.getElementById("modelProviderRegion");
  if (!el) return;
  const value = preferredValue || el.value || MODAL_PROVIDER_REGION_CHINA;
  el.innerHTML = "";
  [
    {
      value: MODAL_PROVIDER_REGION_CHINA,
      label: t("dynamic.settingsCustomModels.国内"),
    },
    {
      value: MODAL_PROVIDER_REGION_INTERNATIONAL,
      label: t("dynamic.settingsCustomModels.国外"),
    },
  ].forEach(({ value: optionValue, label }) => {
    const opt = document.createElement("option");
    opt.value = optionValue;
    opt.textContent = label;
    el.appendChild(opt);
  });
  el.value = value;
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

function onModalProviderRegionChange() {
  const regionEl = document.getElementById("modelProviderRegion");
  const modalRegion = regionEl?.value || MODAL_PROVIDER_REGION_CHINA;
  const prevProviderId = document.getElementById("modelProvider")?.value || "";
  fillModelProviderSelect(modalRegion, prevProviderId);
  const providerId = document.getElementById("modelProvider")?.value || "";
  onProviderChangeInModal(providerId, { isEdit: false });
  refreshModalCapabilitiesState();
}

function onProviderChangeInModal(providerId, options = {}) {
  const { isEdit = false } = options;
  updateProviderWebsiteDisplay(providerId);

  const endpointEl = document.getElementById("modelEndpoint");
  const custom = isCustomProvider(providerId);
  if (custom) {
    if (!isEdit && endpointEl) endpointEl.value = "";
    setEndpointReadonly(false);
  } else {
    const defaultEp = getDefaultEndpoint(providerId);
    if (endpointEl) endpointEl.value = defaultEp;
    setEndpointReadonly(true);
  }

  const modeEl = document.getElementById("modelMode");
  if (modeEl) {
    modeEl.value = modeToSelectValue(
      findProvider(providerId)?.mode,
      providerId,
    );
  }

  setCatalogMultiselectVisible(!custom);
  if (!isEdit) {
    const defaultId =
      pickDefaultCatalogModelId(providerId) ||
      getModelCatalogModels(providerId)[0]?.id ||
      "";
    if (custom) {
      resetModelModalListState();
      renderModelListTable();
    } else {
      replaceListForProvider(providerId, { defaultCatalogId: defaultId });
    }
    buildCatalogMultiselect(providerId);
    renderModelListTable();
  } else {
    buildCatalogMultiselect(providerId);
    syncCatalogMultiselectChecks(providerId);
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

  const providerId = isEdit ? model.provider || "" : "doubao";
  const modalRegion = isEdit
    ? inferModalProviderRegion(providerId)
    : MODAL_PROVIDER_REGION_CHINA;
  initModelProviderRegionSelect(modalRegion);
  fillModelProviderSelect(modalRegion, providerId);
  const resolvedProviderId =
    document.getElementById("modelProvider")?.value || providerId;

  if (isEdit) {
    updateProviderWebsiteDisplay(resolvedProviderId);
    const endpointEl = document.getElementById("modelEndpoint");
    if (endpointEl) endpointEl.value = model.endpoint || "";
    setEndpointReadonly(!isCustomProvider(resolvedProviderId));
    initModelListFromProfile(model, resolvedProviderId);
    buildCatalogMultiselect(resolvedProviderId);
    syncCatalogMultiselectChecks(resolvedProviderId);
    renderModelListTable();
    setCatalogMultiselectVisible(!isCustomProvider(resolvedProviderId));

    const modeEl = document.getElementById("modelMode");
    if (modeEl) {
      modeEl.value = modeToSelectValue(
        model.mode || document.getElementById("api_mode")?.value,
        resolvedProviderId,
      );
    }
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
    thinkingEffortEl.value = ["off", "low", "medium", "high"].includes(value)
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
  const modal = document.getElementById("modelModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  resetModelApiKeyVisibility();
}

export function collectModelForm() {
  const modelIds = getModelIdsFromList();
  const defaultModelId = getDefaultModelIdFromList();
  const maxTokensRaw = parseInt(
    document.getElementById("modelMaxTokens")?.value || "512",
    10,
  );
  const maxTokens =
    Number.isNaN(maxTokensRaw) || maxTokensRaw < 512 ? 512 : maxTokensRaw;
  return {
    name: getProfileDisplayName(),
    model_ids: modelIds,
    model_names: getModelNamesMap(),
    default_model_id: defaultModelId,
    max_tokens: maxTokens,
    mode: document.getElementById("modelMode").value,
    endpoint: document.getElementById("modelEndpoint").value,
    apiKey: document.getElementById("modelApiKey").value,
    description: getEditDescription(),
    provider: document.getElementById("modelProvider").value,
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
  initModelProviderRegionSelect();
  initModelListBindings(() => refreshModalCapabilitiesState());

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

  const regionEl = document.getElementById("modelProviderRegion");
  if (regionEl) regionEl.addEventListener("change", onModalProviderRegionChange);

  const providerEl = document.getElementById("modelProvider");
  if (providerEl) {
    providerEl.addEventListener("change", (event) => {
      onProviderChangeInModal(event.target.value, { isEdit: isEditMode() });
      refreshModalCapabilitiesState();
    });
  }

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
