import { t } from "./i18n.js";
import {
  getModelCatalogModels,
  getModelNameFromCatalog,
} from "./settings-model-catalog.js";

export const TAG_MAX_LEN = 200;

/** @typedef {{ id: string, displayName: string, isCustom: boolean }} ModelListEntry */

/** @type {ModelListEntry[]} */
let listEntries = [];
let defaultModelId = "";
let editDescription = "";
let listChangeHandler = null;
let multiselectBindingsWired = false;

export function resetModelModalListState() {
  listEntries = [];
  defaultModelId = "";
  editDescription = "";
}

export function setEditDescription(value) {
  editDescription = String(value || "");
}

export function getEditDescription() {
  return editDescription;
}

export function getModelListEntries() {
  return listEntries.slice();
}

export function getModelIdsFromList() {
  return listEntries.map((entry) => entry.id.trim()).filter(Boolean);
}

export function getDefaultModelIdFromList() {
  const ids = getModelIdsFromList();
  if (defaultModelId && ids.includes(defaultModelId)) return defaultModelId;
  return ids[0] || "";
}

export function getModelNamesMap() {
  const map = {};
  listEntries.forEach((entry) => {
    const id = entry.id.trim();
    if (!id) return;
    const name = (entry.displayName || "").trim();
    map[id] = name || id;
  });
  return map;
}

export function getProfileDisplayName() {
  const def = getDefaultModelIdFromList();
  const hit = listEntries.find((entry) => entry.id === def);
  if (hit) {
    const name = (hit.displayName || "").trim();
    if (name) return name;
  }
  return def || "";
}

export function initModelListFromProfile(model, providerId) {
  const modelIds = Array.isArray(model?.model_ids) ? model.model_ids : [];
  const def = String(model?.default_model_id || modelIds[0] || "").trim();
  const rawNames =
    model?.model_names && typeof model.model_names === "object"
      ? model.model_names
      : {};
  const profileName = String(model?.name || "").trim();
  const catalogIds = new Set(
    getModelCatalogModels(providerId).map((item) => item.id),
  );

  listEntries = [];
  modelIds.forEach((rawId) => {
    const id = String(rawId || "").trim();
    if (!id) return;
    let displayName = String(rawNames[id] || "").trim();
    if (!displayName && id === def && profileName) displayName = profileName;
    if (!displayName) displayName = getModelNameFromCatalog(providerId, id) || id;
    listEntries.push({
      id,
      displayName,
      isCustom: !catalogIds.has(id),
    });
  });
  defaultModelId = def;
  editDescription = String(model?.description || "");
}

function notifyListChanged() {
  if (typeof listChangeHandler === "function") listChangeHandler();
}

function catalogIdsForProvider(providerId) {
  return new Set(getModelCatalogModels(providerId).map((item) => item.id));
}

export function addCatalogModelToList(modelId, providerId) {
  const id = String(modelId || "").trim();
  if (!id || id.length > TAG_MAX_LEN) return false;
  if (listEntries.some((entry) => entry.id === id)) return false;
  const displayName = getModelNameFromCatalog(providerId, id) || id;
  listEntries.push({ id, displayName, isCustom: false });
  if (!defaultModelId) defaultModelId = id;
  return true;
}

export function removeModelFromList(modelId) {
  const id = String(modelId || "").trim();
  if (!id) return;
  const wasDefault = defaultModelId === id;
  listEntries = listEntries.filter((entry) => entry.id !== id);
  if (wasDefault) {
    defaultModelId = listEntries[0]?.id || "";
  }
}

export function addCustomModelRow() {
  listEntries.push({ id: "", displayName: "", isCustom: true });
  notifyListChanged();
  renderModelListTable();
}

export function setDefaultModel(modelId) {
  const id = String(modelId || "").trim();
  if (!id || !listEntries.some((entry) => entry.id === id)) return;
  defaultModelId = id;
  renderModelListTable();
  notifyListChanged();
}

export function updateModelEntryId(index, newId) {
  const entry = listEntries[index];
  if (!entry) return;
  const trimmed = String(newId || "").trim();
  const prevId = entry.id;
  entry.id = trimmed;
  if (trimmed && !entry.displayName.trim()) {
    const providerId = document.getElementById("modelProvider")?.value || "";
    entry.displayName = getModelNameFromCatalog(providerId, trimmed) || trimmed;
  }
  if (prevId === defaultModelId && trimmed) defaultModelId = trimmed;
  if (!trimmed && prevId === defaultModelId) {
    defaultModelId = listEntries.find((item) => item.id)?.id || "";
  }
}

export function updateModelEntryDisplayName(index, name) {
  const entry = listEntries[index];
  if (!entry) return;
  entry.displayName = String(name || "");
}

export function removeModelEntryAt(index) {
  const entry = listEntries[index];
  if (!entry) return;
  if (entry.id) removeModelFromList(entry.id);
  else listEntries.splice(index, 1);
  renderModelListTable();
  syncCatalogMultiselectChecks(document.getElementById("modelProvider")?.value || "");
  notifyListChanged();
}

export function replaceListForProvider(providerId, { defaultCatalogId = "" } = {}) {
  listEntries = [];
  defaultModelId = "";
  const id = String(defaultCatalogId || "").trim();
  if (id) {
    addCatalogModelToList(id, providerId);
    defaultModelId = id;
  }
}

export function renderModelListTable() {
  const tbody = document.getElementById("modelListTableBody");
  if (!tbody) return;
  tbody.replaceChildren();

  listEntries.forEach((entry, index) => {
    const row = document.createElement("tr");
    row.className = "model-list-row";

    const defaultCell = document.createElement("td");
    defaultCell.className = "model-list-col-default";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "model_list_default";
    radio.value = entry.id || `__pending_${index}`;
    radio.checked = entry.id && entry.id === getDefaultModelIdFromList();
    radio.disabled = !entry.id;
    radio.addEventListener("change", () => {
      if (entry.id) setDefaultModel(entry.id);
    });
    defaultCell.appendChild(radio);

    const idCell = document.createElement("td");
    idCell.className = "model-list-col-id";
    if (entry.isCustom || !entry.id) {
      const idInput = document.createElement("input");
      idInput.type = "text";
      idInput.className = "ui-control ui-input model-list-id-input";
      idInput.value = entry.id;
      idInput.placeholder = t(
        "dynamic.settingsCustomModels.例如_doubao_1_5_pro_32k_25",
      );
      idInput.addEventListener("input", () => {
        updateModelEntryId(index, idInput.value);
      });
      idInput.addEventListener("change", () => {
        updateModelEntryId(index, idInput.value);
        renderModelListTable();
        syncCatalogMultiselectChecks(
          document.getElementById("modelProvider")?.value || "",
        );
        notifyListChanged();
      });
      idCell.appendChild(idInput);
    } else {
      const idSpan = document.createElement("span");
      idSpan.className = "model-list-id-text font-mono text-sm";
      idSpan.textContent = entry.id;
      idCell.appendChild(idSpan);
    }

    const nameCell = document.createElement("td");
    nameCell.className = "model-list-col-name";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.className = "ui-control ui-input model-list-name-input";
    nameInput.value = entry.displayName || "";
    nameInput.placeholder = t("dynamic.settingsCustomModels.模型名称");
    nameInput.addEventListener("input", () => {
      updateModelEntryDisplayName(index, nameInput.value);
    });
    nameCell.appendChild(nameInput);

    const actionCell = document.createElement("td");
    actionCell.className = "model-list-col-action";
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className =
      "ui-button ui-button--ghost ui-button--sm model-list-remove";
    removeBtn.textContent = t("common.delete");
    removeBtn.addEventListener("click", () => removeModelEntryAt(index));
    actionCell.appendChild(removeBtn);

    row.append(defaultCell, idCell, nameCell, actionCell);
    tbody.appendChild(row);
  });
}

function closeMultiselectPanel() {
  const panel = document.getElementById("modelCatalogMultiselectPanel");
  const trigger = document.getElementById("modelCatalogMultiselectTrigger");
  if (panel) panel.classList.add("hidden");
  if (trigger) trigger.setAttribute("aria-expanded", "false");
}

function openMultiselectPanel() {
  const panel = document.getElementById("modelCatalogMultiselectPanel");
  const trigger = document.getElementById("modelCatalogMultiselectTrigger");
  if (panel) panel.classList.remove("hidden");
  if (trigger) trigger.setAttribute("aria-expanded", "true");
}

function updateMultiselectTriggerLabel() {
  const trigger = document.getElementById("modelCatalogMultiselectTrigger");
  if (!trigger) return;
  const count = getModelIdsFromList().length;
  trigger.textContent =
    count > 0
      ? t("dynamic.settingsCustomModels.已选模型数量", { count })
      : t("dynamic.settingsCustomModels.选择模型");
}

export function buildCatalogMultiselect(providerId) {
  const panel = document.getElementById("modelCatalogMultiselectPanel");
  if (!panel) return;
  panel.replaceChildren();
  const models = getModelCatalogModels(providerId);
  models.forEach((model) => {
    const row = document.createElement("label");
    row.className = "model-catalog-multiselect-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = model.id;
    checkbox.checked = listEntries.some((entry) => entry.id === model.id);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        addCatalogModelToList(model.id, providerId);
      } else {
        removeModelFromList(model.id);
      }
      renderModelListTable();
      syncCatalogMultiselectChecks(providerId);
      updateMultiselectTriggerLabel();
      notifyListChanged();
    });
    const text = document.createElement("span");
    text.textContent = model.name || model.id;
    row.append(checkbox, text);
    panel.appendChild(row);
  });
  updateMultiselectTriggerLabel();
}

export function syncCatalogMultiselectChecks(providerId) {
  const panel = document.getElementById("modelCatalogMultiselectPanel");
  if (!panel) return;
  const selected = new Set(getModelIdsFromList());
  panel.querySelectorAll("input[type=checkbox]").forEach((node) => {
    node.checked = selected.has(node.value);
  });
  updateMultiselectTriggerLabel();
}

export function setCatalogMultiselectVisible(visible) {
  const wrap = document.getElementById("modelCatalogMultiselect");
  if (!wrap) return;
  wrap.classList.toggle("hidden", !visible);
  if (!visible) closeMultiselectPanel();
}

export function initModelListBindings(onChange) {
  listChangeHandler = onChange;

  const addBtn = document.getElementById("btnAddCustomModelId");
  if (addBtn && addBtn.dataset.bound !== "true") {
    addBtn.dataset.bound = "true";
    addBtn.addEventListener("click", () => addCustomModelRow());
  }

  if (!multiselectBindingsWired) {
    multiselectBindingsWired = true;
    const trigger = document.getElementById("modelCatalogMultiselectTrigger");
    if (trigger) {
      trigger.addEventListener("click", (event) => {
        event.preventDefault();
        const panel = document.getElementById("modelCatalogMultiselectPanel");
        if (panel?.classList.contains("hidden")) openMultiselectPanel();
        else closeMultiselectPanel();
      });
    }
    document.addEventListener("click", (event) => {
      const root = document.getElementById("modelCatalogMultiselect");
      if (!root || root.classList.contains("hidden")) return;
      if (!root.contains(event.target)) closeMultiselectPanel();
    });
  }
}

export function clearModelListValidationError() {
  const error = document.getElementById("modelIdListError");
  if (error) error.textContent = "";
}

export function setModelListValidationError(message) {
  const error = document.getElementById("modelIdListError");
  if (error) error.textContent = message || "";
}
