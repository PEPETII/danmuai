import { t } from "./i18n.js";

const CUSTOM_VALUE = "__custom__";

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

function renderPresetMeta(model) {
  const meta = document.getElementById("modelPresetMeta");
  if (!meta) return;
  meta.replaceChildren();
  if (!model) {
    meta.textContent = t(
      "dynamic.settingsCustomModels.暂未获取到该模型的能力信息",
    );
    meta.classList.remove("hidden");
    return;
  }
  const title = document.createElement("strong");
  title.textContent = `${model.name || model.id || ""}${model.main_flow_recommended ? ` · ${t("dynamic.settingsCustomModels.推荐")}` : ""}`;
  const id = document.createElement("span");
  id.textContent = model.id || "";
  const badges = document.createElement("span");
  badges.textContent = [
    model.supports_mic ? t("dynamic.settingsCustomModels.支持麦克风") : "",
    ...(model.input_modalities || []).filter((item) =>
      ["image", "audio"].includes(item),
    ),
    model.thinking_mode ? String(model.thinking_mode) : "",
    model.status ? String(model.status) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  [title, id, badges].forEach((node) => meta.appendChild(node));
  meta.classList.remove("hidden");
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
  if (input) {
    input.disabled = isCatalogPreset;
    input.placeholder = isCatalogPreset
      ? ""
      : t("dynamic.settingsCustomModels.例如_doubao_1_5_pro_32k_25");
  }
  if (mic && isCatalogPreset) {
    mic.checked = Boolean(catalogModel.supports_mic);
    mic.disabled = true;
  } else if (mic) mic.disabled = false;
  renderPresetMeta(
    isCatalogPreset
      ? catalogModel
      : selectedId && selectedId !== CUSTOM_VALUE
        ? null
        : null,
  );
  syncDefaultSelect();
  setAdvancedOpen(customIds || (isEdit && !isCatalogPreset));
  return { isCatalogPreset, customIds, catalogModel };
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
    button.textContent = t("dynamic.settingsCustomModels.显示");
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
    button.textContent = t(
      `dynamic.settingsCustomModels.${visible ? "隐藏" : "显示"}`,
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
