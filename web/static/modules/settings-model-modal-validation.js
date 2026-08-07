import { isMaskedApiKey } from "./settings-defaults.js";
import { t } from "./i18n.js";

const TAG_MAX_LEN = 200;

const FIELD_RULES = [
  { id: "modelProvider", error: "modelProviderError" },
  { id: "modelIdPreset", error: "modelIdError" },
  { id: "modelEndpoint", error: "modelEndpointError" },
  { id: "modelApiKey", error: "modelApiKeyError" },
  { id: "modelMaxTokens", error: "modelMaxTokensError" },
];

function setError(id, message) {
  const input = document.getElementById(id);
  const error = document.getElementById(`${id}Error`);
  if (error) error.textContent = message || "";
  if (input) {
    input.setAttribute("aria-invalid", message ? "true" : "false");
    input.classList.toggle("is-invalid", Boolean(message));
  }
}

function readModelIds() {
  return Array.from(
    document.querySelectorAll("#modelIdsTags .tag-chip[data-value]"),
  )
    .map((chip) => String(chip.dataset.value || "").trim())
    .filter(Boolean);
}

function isCustomProvider(provider) {
  return !provider || provider.startsWith("custom_") || provider === "custom";
}

function validateEndpoint(value) {
  if (!value.trim()) return t("dynamic.settingsCustomModels.接口地址不能为空");
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol))
      throw new Error("protocol");
  } catch (_error) {
    return t("dynamic.settingsCustomModels.接口地址必须是_HTTP_或_HTTPS_URL");
  }
  return "";
}

export function validateModelForm() {
  FIELD_RULES.forEach(({ id }) => setError(id, ""));
  const listError = document.getElementById("modelIdListError");
  if (listError) listError.textContent = "";
  const provider = document.getElementById("modelProvider")?.value || "";
  const ids = readModelIds();
  const defaultId =
    ids.find((id) =>
      document
        .querySelector(
          `#modelIdsTags .tag-chip[data-value="${CSS.escape(id)}"]`,
        )
        ?.hasAttribute("data-default"),
    ) ||
    ids[0] ||
    "";
  const invalid = [];
  const add = (id, message) => {
    if (message) {
      setError(id, message);
      invalid.push(document.getElementById(id));
    }
  };
  const addModelIdError = (message) => {
    if (!message) return;
    const error = document.getElementById("modelIdError");
    const input = document.getElementById("modelIdPreset");
    if (error) error.textContent = message;
    if (input) input.setAttribute("aria-invalid", "true");
    invalid.push(input);
  };

  add(
    "modelProvider",
    provider ? "" : t("dynamic.settingsCustomModels.请选择模型平台"),
  );
  if (!ids.length) {
    if (listError)
      listError.textContent = t(
        "dynamic.settingsCustomModels.请至少添加一个模型_ID",
      );
    invalid.push(document.getElementById("modelIdsInput"));
  } else if (
    new Set(ids).size !== ids.length ||
    ids.some((id) => id.length > TAG_MAX_LEN)
  ) {
    if (listError)
      listError.textContent = ids.some((id) => id.length > TAG_MAX_LEN)
        ? t("dynamic.settingsCustomModels.模型_ID_长度超过_TAG_MAX_LEN", {
            maxLen: TAG_MAX_LEN,
          })
        : t("dynamic.settingsCustomModels.模型_ID_不能重复");
    invalid.push(document.getElementById("modelIdsInput"));
  }
  const select = document.getElementById("modelDefaultIdSelect");
  addModelIdError(
    defaultId &&
      (!ids.includes(defaultId) ||
        (select?.value && !ids.includes(select.value)))
      ? t("dynamic.settingsCustomModels.默认模型必须在模型_ID_列表中")
      : "",
  );
  if (isCustomProvider(provider))
    add(
      "modelEndpoint",
      validateEndpoint(document.getElementById("modelEndpoint")?.value || ""),
    );
  const key = document.getElementById("modelApiKey")?.value || "";
  add(
    "modelApiKey",
    key || isMaskedApiKey(key)
      ? ""
      : t("dynamic.settingsCustomModels.API_Key_不能为空"),
  );
  const maxRaw = document.getElementById("modelMaxTokens")?.value || "";
  const max = Number(maxRaw);
  add(
    "modelMaxTokens",
    maxRaw && Number.isInteger(max) && max >= 512
      ? ""
      : t("dynamic.settingsCustomModels.max_tokens_必须是_512_以上整数"),
  );

  return {
    valid: invalid.length === 0,
    firstInvalidElement: invalid.find(Boolean),
    modelIds: ids,
    defaultModelId: defaultId,
  };
}

export function clearModelValidationErrors() {
  FIELD_RULES.forEach(({ id }) => setError(id, ""));
  const listError = document.getElementById("modelIdListError");
  if (listError) listError.textContent = "";
}
