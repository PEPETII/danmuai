import { apiFetch } from "./transport.js";
import { t } from "./i18n.js";
import { catalogModelSupportsMic } from "./settings-model-catalog.js";
import { findProvider } from "./settings-providers.js";
import {
  configureModelModalForm,
  closeModelModal,
  collectModelForm,
  initModelModalBindings,
  openModelModal,
  probe,
  saveModel,
  TAG_MAX_LEN,
} from "./settings-model-modal-form.js";
import { activateFocusTrap, deactivateFocusTrap } from "./modal-focus-trap.js";

let customModelDeps = {
  showToast: () => {},
  reloadConfigFromServer: async () => ({}),
  syncVisionModelPickerFromForm: () => {},
  updateModelActiveSourceBanner: () => {},
};

let cachedCustomModels = [];
let cachedActiveProfileId = "";
let activationInFlight = false;
let modelModalBindingsWired = false;

export function getCachedCustomModels() {
  return cachedCustomModels;
}

function resolveProfileDisplayName(model) {
  const def = String(model?.default_model_id || "").trim();
  const names =
    model?.model_names && typeof model.model_names === "object"
      ? model.model_names
      : {};
  if (def && names[def]) return String(names[def]).trim();
  return String(model?.name || "").trim() || t("common.unnamed");
}

function profileDefaultSupportsMic(model) {
  const def = String(model?.default_model_id || "").trim();
  if (!def) return false;
  if (!catalogModelSupportsMic(def)) return false;
  return Boolean(model?.supportsMic);
}

export function customModelSupportsMic(modelId) {
  const id = (modelId || "").trim();
  if (!id) return false;
  if (!catalogModelSupportsMic(id)) return false;
  const hit = cachedCustomModels.find((model) => {
    const ids = Array.isArray(model.model_ids)
      ? model.model_ids.map((x) => String(x || "").trim())
      : [];
    const def = (model.default_model_id || "").trim();
    return ids.includes(id) || def === id;
  });
  if (!hit) return catalogModelSupportsMic(id);
  return Boolean(hit.supportsMic);
}

export function configureSettingsCustomModels(deps) {
  customModelDeps = { ...customModelDeps, ...deps };
  configureModelModalForm({
    showToast: customModelDeps.showToast,
    reloadConfigFromServer: customModelDeps.reloadConfigFromServer,
    loadCustomModels: loadCustomModels,
  });
}

export async function loadCustomModels() {
  if (!modelModalBindingsWired) {
    modelModalBindingsWired = true;
    try {
      initModelModalBindings();
    } catch (_e) {
      /* DOM not ready yet */
    }
  }
  const data = await apiFetch("/api/custom-models");
  cachedCustomModels = Array.isArray(data?.items) ? data.items : [];
  cachedActiveProfileId = String(data?.active_profile_id || "").trim();
  const list = document.getElementById("customModelsList");
  if (!list) return;
  list.innerHTML = "";
  if (!cachedCustomModels.length) {
    list.innerHTML = t("dynamic.settingsCustomModels.p_class_text_sm_text_g");
    return;
  }
  cachedCustomModels.forEach((model, index) => {
    const row = document.createElement("div");
    row.className =
      "custom-model-row flex flex-wrap items-center gap-3 p-3 bg-cream rounded-xl text-sm";

    const colName = document.createElement("div");
    colName.className = "flex items-center gap-2 min-w-0 flex-1";
    const nameSpan = document.createElement("span");
    nameSpan.className = "font-semibold text-warmText truncate";
    nameSpan.textContent = resolveProfileDisplayName(model);
    colName.appendChild(nameSpan);
    const providerId = model.provider || "";
    const provider = providerId ? findProvider(providerId) : null;
    if (provider && provider.label) {
      const chip = document.createElement("span");
      chip.className =
        "custom-model-provider-chip px-2 py-0.5 rounded-full bg-softPeach text-warmText text-xs font-semibold";
      chip.textContent = provider.label;
      colName.appendChild(chip);
    }
    if (profileDefaultSupportsMic(model)) {
      const mic = document.createElement("span");
      mic.className = "text-sky-600 text-xs font-bold";
      mic.textContent = t("dynamic.settingsCustomModels.支持麦克风");
      colName.appendChild(mic);
    }
    if (model.complete === false) {
      const warn = document.createElement("span");
      warn.className = "text-amber-600 text-xs font-bold";
      warn.textContent = t("dynamic.settingsCustomModels.配置不完整");
      colName.appendChild(warn);
    }

    const colModelId = document.createElement("div");
    colModelId.className =
      "custom-model-id-col text-gray-500 text-xs whitespace-nowrap";
    const modelIds = Array.isArray(model.model_ids) ? model.model_ids : [];
    const defaultId = model.default_model_id || "";
    const extra = Math.max(0, modelIds.length - 1);
    const idSpan = document.createElement("span");
    idSpan.className = "font-mono";
    idSpan.textContent = defaultId;
    colModelId.appendChild(idSpan);
    if (extra > 0) {
      const extraSpan = document.createElement("span");
      extraSpan.className = "text-gray-400";
      extraSpan.textContent = ` (+${extra})`;
      colModelId.appendChild(extraSpan);
    }

    const colActions = document.createElement("div");
    colActions.className = "custom-model-actions flex items-center gap-2";
    const isActive = String(model?.profile_id || "").trim() === cachedActiveProfileId;
    const activateBtn = document.createElement("button");
    activateBtn.type = "button";
    activateBtn.className = isActive
      ? "ui-button ui-button--primary ui-button--sm"
      : "ui-button ui-button--secondary ui-button--sm";
    activateBtn.textContent = isActive
      ? t("dynamic.settingsCustomModels.使用中")
      : t("dynamic.settingsCustomModels.启动");
    activateBtn.disabled =
      isActive || model.complete === false || !String(model?.profile_id || "").trim();
    if (model.complete === false && !isActive) {
      activateBtn.title = t("dynamic.settingsCustomModels.配置不完整");
    }
    activateBtn.onclick = async () => {
      if (activateBtn.disabled || activationInFlight) return;
      activationInFlight = true;
      activateBtn.disabled = true;
      activateBtn.textContent = t("dynamic.settingsCustomModels.启动中");
      try {
        await apiFetch("/api/custom-models/active", {
          method: "PUT",
          body: JSON.stringify({ profile_id: String(model.profile_id || "").trim() }),
        });
        await loadCustomModels();
      } catch (error) {
        activateBtn.disabled = false;
        activateBtn.textContent = t("dynamic.settingsCustomModels.启动");
        customModelDeps.showToast(error.message, true);
      } finally {
        activationInFlight = false;
      }
    };
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "px-3 py-1 border border-gray-200 rounded-lg text-xs";
    editBtn.textContent = t("common.edit");
    editBtn.onclick = () => openModelModal(index, model);
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className =
      "px-3 py-1 border border-red-200 rounded-lg text-xs text-red-600";
    delBtn.textContent = t("common.delete");
    delBtn.onclick = () => openDeleteModelConfirm(model, index);
    colActions.appendChild(activateBtn);
    colActions.appendChild(editBtn);
    colActions.appendChild(delBtn);

    row.appendChild(colName);
    row.appendChild(colModelId);
    row.appendChild(colActions);
    list.appendChild(row);
  });
}

export function formatDeleteModelMessage(profile) {
  const display = resolveProfileDisplayName(profile);
  const ids = Array.isArray(profile?.model_ids) ? profile.model_ids : [];
  const n = ids.length || 1;
  const base = t("dynamic.settingsCustomModels.确定删除模型_display_吗_该档案包", {
    display,
    n,
  });
  if (String(profile?.profile_id || "").trim() !== cachedActiveProfileId) return base;
  return `${base} ${t(cachedCustomModels.length > 1
    ? "dynamic.settingsCustomModels.删除后将自动切换"
    : "dynamic.settingsCustomModels.删除后无可用模型")}`;
}

let _deleteModelConfirmCleanup = null;

export function openDeleteModelConfirm(profile, index) {
  const modal = document.getElementById("deleteModelConfirmModal");
  if (!modal) return;
  const messageEl = document.getElementById("deleteModelConfirmMessage");
  if (messageEl) messageEl.textContent = formatDeleteModelMessage(profile);

  if (typeof _deleteModelConfirmCleanup === "function") {
    _deleteModelConfirmCleanup();
    _deleteModelConfirmCleanup = null;
  }

  modal.classList.remove("hidden");
  modal.classList.add("flex");
  activateFocusTrap(modal, closeDeleteModelConfirm);

  const okBtn = document.getElementById("btnDeleteModelConfirmOk");
  const cancelBtn = document.getElementById("btnDeleteModelConfirmCancel");

  const close = () => closeDeleteModelConfirm();

  const onConfirm = async () => {
    try {
      await apiFetch(`/api/custom-models/${index}`, { method: "DELETE" });
      closeDeleteModelConfirm();
      customModelDeps.showToast(t("dynamic.settingsCustomModels.已删除_2"));
      loadCustomModels();
    } catch (error) {
      closeDeleteModelConfirm();
      customModelDeps.showToast(error.message, true);
    }
  };

  const onBackdropClick = (e) => {
    if (e.target === modal) close();
  };

  okBtn?.addEventListener("click", onConfirm, { once: true });
  cancelBtn?.addEventListener("click", close, { once: true });
  modal.addEventListener("click", onBackdropClick);

  _deleteModelConfirmCleanup = () => {
    okBtn?.removeEventListener("click", onConfirm);
    cancelBtn?.removeEventListener("click", close);
    modal.removeEventListener("click", onBackdropClick);
    _deleteModelConfirmCleanup = null;
  };
}

export function closeDeleteModelConfirm() {
  const modal = document.getElementById("deleteModelConfirmModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
  if (typeof _deleteModelConfirmCleanup === "function") {
    _deleteModelConfirmCleanup();
    _deleteModelConfirmCleanup = null;
  }
  deactivateFocusTrap();
}

export {
  closeModelModal,
  collectModelForm,
  openModelModal,
  probe,
  saveModel,
  TAG_MAX_LEN,
};
