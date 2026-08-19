import { apiFetch } from "./transport.js";
import { t } from "./i18n.js";
import {
  buildFrontendInternalProblem,
  showProblemDialog,
} from "./app-problem-dialog.js";
import {
  expandModelModalAdvanced,
  setModelModalBusy,
} from "./settings-model-modal-state.js";
import { validateModelForm } from "./settings-model-modal-validation.js";

export const MODEL_PROBE_STATES = Object.freeze({
  IDLE: "idle",
  LOADING: "loading",
  SUCCESS: "success",
  ERROR: "error",
});

let activeController = null;
let requestToken = 0;
let lastProbeFingerprint = "";
let bound = false;
let collectFormFn = () => ({});

function el(id) {
  return document.getElementById(id);
}

function hasApiKey(value) {
  const key = String(value || "");
  return Boolean(key) && !/^\*+$/.test(key) && !/^•+$/.test(key);
}

export function buildProbeFingerprint(form = {}) {
  return JSON.stringify({
    provider: form.provider || "",
    model_ids: Array.isArray(form.model_ids) ? form.model_ids : [],
    default_model_id: form.default_model_id || "",
    endpoint: form.endpoint || "",
    mode: form.mode || "",
    max_tokens: form.max_tokens || 0,
    supportsMic: Boolean(form.supportsMic),
    apiKeyPresent: hasApiKey(form.apiKey),
  });
}

function setResultClass(state) {
  const result = el("modelProbeResult");
  if (!result) return;
  result.className = `model-probe-result model-probe-result--${state}`;
  result.dataset.state = state;
  result.classList.toggle("hidden", state === MODEL_PROBE_STATES.IDLE);
}

export function renderModelProbeResult({
  state = MODEL_PROBE_STATES.IDLE,
  title = "",
  message = "",
  meta = "",
  technicalDetail = "",
  problemCode = "",
} = {}) {
  setResultClass(state);
  const titleEl = el("modelProbeResultTitle");
  const messageEl = el("modelProbeResultMessage");
  const metaEl = el("modelProbeResultMeta");
  const detailBtn = el("btnModelProbeTechnicalDetail");
  if (titleEl) titleEl.textContent = title;
  if (messageEl) messageEl.textContent = message;
  if (metaEl) metaEl.textContent = meta;
  if (detailBtn) {
    detailBtn.classList.toggle("hidden", !technicalDetail);
    detailBtn.dataset.detail = technicalDetail || "";
    detailBtn.dataset.problemCode = problemCode || "";
  }
}

function categoryCopy(category, statusCode) {
  const categoryName = String(category || "").toLowerCase();
  const status = Number(statusCode) || 0;
  if (categoryName === "invalid_endpoint")
    return ["API_地址格式不正确", "请检查协议、域名和路径。"];
  if (
    categoryName === "auth_missing" ||
    categoryName === "auth_invalid" ||
    status === 401
  )
    return ["API_Key_无效或已过期", "请确认 Key 未过期，并检查服务商权限。"];
  if (categoryName === "permission_denied" || status === 403)
    return ["没有访问权限", "请确认账号、模型和接口权限。"];
  if (categoryName === "model_not_found" || status === 404)
    return ["模型_ID_不存在", "请检查模型 ID，或从模型目录重新选择。"];
  if (categoryName.startsWith("unsupported_") || status === 400)
    return ["接口协议或参数不兼容", "请检查接口协议、模型能力和请求参数。"];
  if (categoryName === "rate_limited" || status === 429)
    return ["请求过于频繁", "请稍后重试，或检查服务商的速率限制。"];
  if (categoryName === "provider_unavailable" || status >= 500)
    return ["服务暂时不可用", "请稍后重试，或检查服务商状态。"];
  if (categoryName === "timeout")
    return ["请求超时", "请检查网络和接口地址后重试。"];
  return ["连接测试失败", "请检查配置和网络后重试。"];
}

function safeEndpoint(endpoint) {
  try {
    const url = new URL(endpoint || "");
    return `${url.protocol}//${url.host}${url.pathname}`;
  } catch {
    return endpoint ? "[invalid endpoint]" : "";
  }
}

function technicalDetail(result, form, elapsedMs) {
  return [
    `status_code: ${result.status_code ?? "n/a"}`,
    `request_id: ${result.request_id || "n/a"}`,
    `endpoint: ${safeEndpoint(form.endpoint) || "n/a"}`,
    `model_id: ${form.default_model_id || "n/a"}`,
    `error_category: ${result.error_category || "n/a"}`,
    `client_latency_ms: ${Math.round(elapsedMs)}`,
  ].join("\n");
}

function setProbeBusy(isBusy) {
  const button = el("btnModelProbe");
  if (!button) return;
  if (isBusy) {
    button.dataset.defaultLabel = button.textContent || "";
    button.textContent = t("dynamic.settingsCustomModels.正在测试连接");
  } else if (button.dataset.defaultLabel) {
    button.textContent = button.dataset.defaultLabel;
    delete button.dataset.defaultLabel;
  }
}

function invalidateIfChanged() {
  if (!lastProbeFingerprint) return;
  const current = buildProbeFingerprint(collectFormFn());
  if (current !== lastProbeFingerprint) {
    renderModelProbeResult({
      state: MODEL_PROBE_STATES.ERROR,
      title: t("dynamic.settingsCustomModels.配置已更改"),
      message: t("dynamic.settingsCustomModels.配置已更改_请重新测试连接"),
    });
  }
}

function bindChangeInvalidation() {
  if (bound) return;
  bound = true;
  [
    "modelProvider",
    "modelCatalogMultiselect",
    "modelCatalogMultiselectTrigger",
    "modelEndpoint",
    "modelApiKey",
    "modelMode",
    "modelMaxTokens",
    "modelSupportsMic",
    "modelListTable",
    "modelListTableBody",
  ].forEach((id) => {
    const node = el(id);
    node?.addEventListener("input", invalidateIfChanged);
    node?.addEventListener("change", invalidateIfChanged);
  });
  el("btnModelProbeTechnicalDetail")?.addEventListener("click", () => {
    const detail = el("btnModelProbeTechnicalDetail")?.dataset.detail || "";
    if (!detail) return;
    const problem = buildFrontendInternalProblem(
      t("dynamic.settingsCustomModels.探活技术详情"),
      detail,
    );
    problem.code =
      el("btnModelProbeTechnicalDetail")?.dataset.problemCode || "MODEL-PROBE";
    problem.title = t("dynamic.settingsCustomModels.探活技术详情");
    showProblemDialog(problem, { force: true });
  });
}

export function initModelModalProbe(collectForm) {
  if (typeof collectForm === "function") collectFormFn = collectForm;
  bindChangeInvalidation();
}

export function abortModelProbe() {
  requestToken += 1;
  activeController?.abort();
  activeController = null;
  setProbeBusy(false);
}

export async function probeModelConnection(collectForm) {
  initModelModalProbe(collectForm);
  const validation = validateModelForm();
  if (!validation.valid) {
    expandModelModalAdvanced();
    validation.firstInvalidElement?.focus();
    renderModelProbeResult({
      state: MODEL_PROBE_STATES.ERROR,
      title: t("dynamic.settingsCustomModels.请先修正上方配置"),
      message: t("dynamic.settingsCustomModels.请先修正上方配置_探活"),
    });
    return null;
  }

  abortModelProbe();
  const controller = new AbortController();
  activeController = controller;
  const token = requestToken;
  const form = collectForm();
  const fingerprint = buildProbeFingerprint(form);
  const index = parseInt(el("modelEditIndex")?.value || "-1", 10);
  const started = performance.now();
  setModelModalBusy(true, t("dynamic.settingsCustomModels.正在测试连接"));
  setProbeBusy(true);
  renderModelProbeResult({
    state: MODEL_PROBE_STATES.LOADING,
    title: t("dynamic.settingsCustomModels.正在测试连接"),
    message: t("dynamic.settingsCustomModels.请稍候"),
  });

  try {
    const result = await apiFetch("/api/custom-models/probe", {
      method: "POST",
      body: JSON.stringify({ ...form, index, model_id: form.default_model_id }),
      signal: controller.signal,
    });
    if (token !== requestToken) return result;
    const elapsed = performance.now() - started;
    const [title, suggestion] = categoryCopy(
      result.error_category,
      result.status_code,
    );
    const detail = technicalDetail(result, form, elapsed);
    lastProbeFingerprint = fingerprint;
    if (result.ok) {
      renderModelProbeResult({
        state: MODEL_PROBE_STATES.SUCCESS,
        title: t("dynamic.settingsCustomModels.连接测试成功"),
        message: result.message || t("common.connectionSuccess"),
        meta: `${Math.round(elapsed)} ms · ${form.default_model_id}`,
      });
    } else {
      renderModelProbeResult({
        state: MODEL_PROBE_STATES.ERROR,
        title:
          t(`dynamic.settingsCustomModels.${title}`) ===
          `dynamic.settingsCustomModels.${title}`
            ? title
            : t(`dynamic.settingsCustomModels.${title}`),
        message: result.message || suggestion,
        meta: suggestion,
        technicalDetail: detail,
        problemCode: `MODEL-PROBE-${String(result.error_category || "UNKNOWN").toUpperCase()}`,
      });
    }
    return result;
  } catch (error) {
    if (error?.name === "AbortError" || token !== requestToken) return null;
    const elapsed = performance.now() - started;
    const detail = `client_error: ${String(error?.message || error)}\nclient_latency_ms: ${Math.round(elapsed)}`;
    renderModelProbeResult({
      state: MODEL_PROBE_STATES.ERROR,
      title: t("dynamic.settingsCustomModels.连接测试失败"),
      message: error?.message || t("common.connectionFailed"),
      technicalDetail: detail,
      problemCode: "MODEL-PROBE-CLIENT",
    });
    throw error;
  } finally {
    if (token === requestToken) {
      activeController = null;
      setProbeBusy(false);
      setModelModalBusy(false);
    }
  }
}
