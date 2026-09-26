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

// W-AUDIT-PROBE-PARITY-001：默认「测试连接」执行完整阶段链；逐项展示通过/失败/未执行。
export const MODEL_PROBE_STAGE_ORDER = Object.freeze([
  "local",
  "auth_model",
  "text",
  "vision_stream",
  "business_parse",
]);

const PROBE_STAGE_LABEL_KEYS = Object.freeze({
  local: "阶段_本地校验",
  auth_model: "阶段_鉴权与模型",
  text: "阶段_文本连接",
  vision: "阶段_视觉非流式",
  audio: "阶段_音频输入",
  stream: "阶段_流式文本",
  vision_stream: "阶段_视觉流式请求",
  business_parse: "阶段_业务解析",
});

let activeController = null;
let requestToken = 0;
let lastProbeFingerprint = "";
let bound = false;
let collectFormFn = () => ({});
// W-AUDIT-PROBE-SECRET-001：登记"沿用已存 key"时的凭据作用域；作用域字段一旦
// 改变即清除掩码 key，避免把已存密钥绑定到新的 endpoint/provider/model/mode。
let storedKeyScope = "";
let storedKeyMasked = false;

function el(id) {
  return document.getElementById(id);
}

function hasApiKey(value) {
  const key = String(value || "");
  return Boolean(key) && !/^\*+$/.test(key) && !/^•+$/.test(key);
}

export function buildProbeFingerprint(form = {}) {
  return JSON.stringify({
    // W-AUDIT-PROBE-PARITY-001：绑定触发时的不可变档案身份与档案参数。
    profile_id: form.profile_id || "",
    provider: form.provider || "",
    model_ids: Array.isArray(form.model_ids) ? form.model_ids : [],
    default_model_id: form.default_model_id || "",
    endpoint: form.endpoint || "",
    mode: form.mode || "",
    max_tokens: form.max_tokens || 0,
    thinking_effort: form.thinking_effort || "off",
    temperature: form.temperature ?? null,
    supportsMic: Boolean(form.supportsMic),
    apiKeyPresent: hasApiKey(form.apiKey),
  });
}

/** Credential-scope portion of the form; endpoint/provider/model/mode identity. */
export function buildProbeScopeFingerprint(form = {}) {
  return JSON.stringify({
    provider: form.provider || "",
    endpoint: form.endpoint || "",
    mode: form.mode || "",
    model_ids: Array.isArray(form.model_ids) ? form.model_ids : [],
    default_model_id: form.default_model_id || "",
  });
}

function isMaskedKeyText(value) {
  const text = String(value || "");
  return /^\*+$/.test(text) || /^•+$/.test(text);
}

/**
 * 打开弹窗、把档案 key 回填为掩码值时调用：记住该作用域。
 * 之后修改 endpoint/provider/model/mode 会使"沿用旧 key"失效。
 */
export function markModelModalStoredKey() {
  storedKeyMasked = isMaskedKeyText(el("modelApiKey")?.value);
  storedKeyScope = buildProbeScopeFingerprint(collectFormFn());
}

function clearStoredKeyIfScopeChanged() {
  const input = el("modelApiKey");
  if (!input) return false;
  if (!storedKeyMasked || !isMaskedKeyText(input.value)) return false;
  if (buildProbeScopeFingerprint(collectFormFn()) === storedKeyScope) return false;
  input.value = "";
  storedKeyMasked = false;
  renderModelProbeResult({
    state: MODEL_PROBE_STATES.ERROR,
    title: t("dynamic.settingsCustomModels.探测目标已修改"),
    message: t("dynamic.settingsCustomModels.探测目标已修改_请重新输入_API_Key"),
  });
  return true;
}

function setResultClass(state) {
  const result = el("modelProbeResult");
  if (!result) return;
  result.className = `model-probe-result model-probe-result--${state}`;
  result.dataset.state = state;
  result.classList.toggle("hidden", state === MODEL_PROBE_STATES.IDLE);
}

function stageLabel(stage) {
  const key = PROBE_STAGE_LABEL_KEYS[stage];
  return key ? t(`dynamic.settingsCustomModels.${key}`) : String(stage || "");
}

function stageStatusLabel(status) {
  if (status === "passed") return t("dynamic.settingsCustomModels.阶段状态_通过");
  if (status === "skipped") return t("dynamic.settingsCustomModels.阶段状态_未执行");
  return t("dynamic.settingsCustomModels.阶段状态_失败");
}

/** 逐项渲染阶段结果；空列表时隐藏容器（不伪造任何阶段）。 */
function renderProbeStages(stages) {
  const list = el("modelProbeStages");
  if (!list) return;
  const items = Array.isArray(stages) ? stages : [];
  if (typeof list.replaceChildren === "function") list.replaceChildren();
  list.classList.toggle("hidden", items.length === 0);
  if (typeof document.createElement !== "function") return;
  items.forEach((item) => {
    const status = String(item?.status || "failed");
    const li = document.createElement("li");
    li.className = `model-probe-stage model-probe-stage--${status}`;
    li.dataset.stage = String(item?.stage || "");
    li.dataset.status = status;
    const name = document.createElement("span");
    name.className = "model-probe-stage-name";
    name.textContent = stageLabel(item?.stage);
    const state = document.createElement("span");
    state.className = "model-probe-stage-status";
    state.textContent = stageStatusLabel(status);
    li.append(name, state);
    list.append(li);
  });
}

export function renderModelProbeResult({
  state = MODEL_PROBE_STATES.IDLE,
  title = "",
  message = "",
  meta = "",
  technicalDetail = "",
  problemCode = "",
  stages = [],
} = {}) {
  setResultClass(state);
  const titleEl = el("modelProbeResultTitle");
  const messageEl = el("modelProbeResultMessage");
  const metaEl = el("modelProbeResultMeta");
  const detailBtn = el("btnModelProbeTechnicalDetail");
  if (titleEl) titleEl.textContent = title;
  if (messageEl) messageEl.textContent = message;
  if (metaEl) metaEl.textContent = meta;
  renderProbeStages(stages);
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
    "probe_policy: fixed 10s client timeout, no stream first-content timeout",
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
  // 作用域变更 → 先让"沿用旧 key"失效并提示重新输入（后端仍是最终校验者）。
  if (clearStoredKeyIfScopeChanged()) return;
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
    "modelProviderTrigger",
    "modelProviderSearch",
    "modelEndpoint",
    "modelApiKey",
    "modelModeValue",
    "modelMaxTokens",
    "modelSupportsMic",
    "modelListTable",
    "modelListTableBody",
    "modelCatalogOptions",
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
    // W-AUDIT-PROBE-PARITY-001：默认「测试连接」执行完整阶段链。
    const result = await apiFetch("/api/custom-models/probe", {
      method: "POST",
      body: JSON.stringify({
        ...form,
        index,
        model_id: form.default_model_id,
        stage: "full",
      }),
      signal: controller.signal,
    });
    if (token !== requestToken) return result;
    // 结果必须绑定触发时的档案身份；身份漂移时丢弃（不覆盖新结果）。
    if (
      form.profile_id &&
      result?.profile_id !== undefined &&
      String(result.profile_id || "") !== String(form.profile_id || "")
    ) {
      return result;
    }
    const elapsed = performance.now() - started;
    const [title, suggestion] = categoryCopy(
      result.error_category,
      result.status_code,
    );
    const detail = technicalDetail(result, form, elapsed);
    const stages = Array.isArray(result.stages) ? result.stages : [];
    const passedCount = stages.filter((item) => item.status === "passed").length;
    lastProbeFingerprint = fingerprint;
    if (result.ok && result.complete) {
      // 只有 business_parse 通过（完整视觉链路）才显示完整成功。
      renderModelProbeResult({
        state: MODEL_PROBE_STATES.SUCCESS,
        title: t("dynamic.settingsCustomModels.连接测试成功"),
        message: t("dynamic.settingsCustomModels.完整视觉链路可用"),
        meta: `${Math.round(elapsed)} ms · ${form.default_model_id}`,
        stages,
      });
    } else {
      const textPassed = stages.some(
        (item) => item.stage === "text" && item.status === "passed",
      );
      const partial = passedCount > 0;
      renderModelProbeResult({
        state: MODEL_PROBE_STATES.ERROR,
        title: partial
          ? t("dynamic.settingsCustomModels.连接测试未完全通过")
          : t(`dynamic.settingsCustomModels.${title}`) ===
              `dynamic.settingsCustomModels.${title}`
            ? title
            : t(`dynamic.settingsCustomModels.${title}`),
        message: partial
          ? textPassed
            ? t("dynamic.settingsCustomModels.文本连接可用_完整视觉链路未通过")
            : t("dynamic.settingsCustomModels.部分阶段通过_请查看下方明细")
          : result.message || suggestion,
        // 超时属 probe 短超时策略差异，不能据此断言生产一定失败。
        meta:
          String(result.error_category || "") === "timeout"
            ? `${suggestion} ${t("dynamic.settingsCustomModels.探测使用较短超时_不代表生产失败")}`.trim()
            : suggestion,
        stages,
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
