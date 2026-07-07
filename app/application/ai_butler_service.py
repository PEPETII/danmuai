"""W-AIBUTLER-001 — AI管家自然语言设置代理：LLM 意图解析服务。

职责：
- 定义工具 schema（update_config / set_default_model；query_config 由后端合成进上下文，不让 LLM 真发 tool call）
- 组装 system prompt（含当前配置快照，敏感字段掩码）
- 复用 ``app.ai_client_requests.stream_openai`` / ``stream_doubao`` + ``resolve_request_credentials``，
  采用 ``bililive_dm_bridge_service._BridgeStreamWorker`` 的 duck-typed worker 模式（非 QObject，不触 Qt / 主链路）
- 解析 LLM 返回 JSON → ``{reply, tool_calls}``
- 校验工具参数（WEB_CONFIG_KEYS 白名单 + 禁止黑名单）

设计约束（与 spec `docs/ai-butler-spec.md` 一致）：
- **无状态**：每次请求由前端携带完整 messages 历史；后端不保存会话
- **不执行变更**：仅返回结构化结果；变更执行由前端调既有 ``PUT /api/config`` / ``POST /api/custom-models/{index}/default``
- **非流式**：等完整生成后一次性返回（工具调用需完整 JSON）
- **固定 thinking:disabled**：与主链路一致
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

import httpx

from app.ai_client_requests import format_credential_error, resolve_request_credentials
from app.ai_client_requests import stream_doubao, stream_openai
from app.model_providers import resolve_api_transport
from app.providers import get_capabilities_for_endpoint, get_openai_adapter, provider_extra_headers
from app.providers.constants import THINKING_DISABLED
from app.providers.thinking import apply_thinking_disabled
from app.errors import AppError
from app.translations import Translator

logger = logging.getLogger(__name__)

# 与 app.web_api.console_theme 保持一致（勿经 web_api 包 import，避免循环依赖）
_CONSOLE_THEME_KEY = "console_theme"


def _normalize_console_theme(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() == "light":
        return "light"
    return "dark"


def _console_theme_from_config(config) -> str:
    raw = config.get(_CONSOLE_THEME_KEY, "dark")
    return _normalize_console_theme(raw)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SEC = 15.0
_MAX_MESSAGES = 40  # spec §8.3：20 轮 = 40 条
_MAX_MESSAGE_CHARS = 1000

# spec §4.3：工具层完全不暴露的字段（即使 LLM 误返回也丢弃）
FORBIDDEN_CONFIG_KEYS = frozenset({
    "api_key",
    "mic_api_key",
    "use_thinking",
    "persona_model_bindings",
    "region_x",
    "region_y",
    "region_w",
    "region_h",
    "default_model_id",  # 经 set_default_model 工具，不走 update_config
})

# 允许 update_config 写入的 key（取自 WEB_CONFIG_KEYS 白名单，运行时 import 避免循环）
def _allowed_config_keys() -> frozenset[str]:
    from app.application.config_service import WEB_CONFIG_KEYS
    return frozenset(WEB_CONFIG_KEYS)



_FALLBACK_REPLY = "我没太理解您的意思，请换个说法试试。"

_FALLBACK_REPLY_EN = "I didn't quite catch that — please try rephrasing."

_REPAIR_SUFFIX = (
    "\n\n【重要】你必须只输出一个 JSON 对象（含 reply 与 tool_calls 字段），"
    "不要 Markdown 代码块，不要 JSON 以外的任何文字。"
)

_REPAIR_SUFFIX_EN = (
    "\n\n[Important] You must output exactly one JSON object (with reply and tool_calls), "
    "no Markdown fences, and no text outside JSON."
)

_CHANGE_KEY_LABELS: dict[str, str] = {
    "danmu_speed": "弹幕速度",
    "danmu_lines": "弹幕行数",
    "danmu_max_chars": "弹幕最大字数",
    "font_size": "弹幕字号",
    "opacity": "弹幕透明度",
    "dedup_threshold": "去重阈值",
    "danmu_font_bold": "弹幕加粗",
    "layout_mode": "布局模式",
    "danmu_render_mode": "弹幕渲染模式",
    "mic_mode_enabled": "麦克风模式",
    "screen_index": "显示器",
    "api_mode": "API 模式",
    "normal_reply_count": "普通模式回复条数",
    "normal_recognition_interval_sec": "识图间隔",
}

_CHANGE_KEY_LABELS_EN: dict[str, str] = {
    "danmu_speed": "Danmu speed",
    "danmu_lines": "Danmu lines",
    "danmu_max_chars": "Max danmu length",
    "font_size": "Danmu font size",
    "opacity": "Danmu opacity",
    "dedup_threshold": "Dedup threshold",
    "danmu_font_bold": "Danmu bold",
    "layout_mode": "Layout mode",
    "danmu_render_mode": "Danmu render mode",
    "mic_mode_enabled": "Mic mode",
    "screen_index": "Display",
    "api_mode": "API mode",
    "normal_reply_count": "Normal reply count",
    "normal_recognition_interval_sec": "Capture interval",
}


def _is_english() -> bool:
    return Translator.get_language() == "en"


def _fallback_reply() -> str:
    return _FALLBACK_REPLY_EN if _is_english() else _FALLBACK_REPLY


def _repair_suffix() -> str:
    return _REPAIR_SUFFIX_EN if _is_english() else _REPAIR_SUFFIX


def _change_key_labels() -> dict[str, str]:
    return _CHANGE_KEY_LABELS_EN if _is_english() else _CHANGE_KEY_LABELS


_JSON_OUTPUT_EXAMPLE = """{
  "reply": "口语化、简短的回复（说明你将做什么，或为什么不能做）",
  "tool_calls": [
    {"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":"弹幕速度: 5 → 8"}],"require_confirm":true}
  ]
}"""

_JSON_OUTPUT_EXAMPLE_EN = """{
  "reply": "Short, conversational reply (what you will do, or why you cannot)",
  "tool_calls": [
    {"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":"Danmu speed: 5 → 8"}],"require_confirm":true}
  ]
}"""

_SYSTEM_PROMPT_PREFIX = """你是「AI管家」，DanmuAI 的自然语言设置代理。用户用自然语言描述需求，你解析意图并返回工具调用。

# 可用工具（返回 JSON 的 tool_calls 数组）

1. update_config — 修改设置项（WEB_CONFIG_KEYS 白名单内）
   参数：{"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":"弹幕速度: 5 → 8"}],"require_confirm":true}
   - **所有变更均需用户确认**（require_confirm 恒为 true）
   - label 中的当前值必须以「当前配置值」为准；目标值写入 value
   - 一句话可含多个 change

2. set_default_model — 切换当前使用模型档案
   参数：{"name":"set_default_model","index":1,"model_id":"mimo-v2.5","label":"视觉模型: doubao-seed → mimo-v2.5"}
   - index 是模型档案在列表中的序号（0 起），见下方「当前模型档案」
   - 恒为确认级（require_confirm=true）

3. set_console_theme — 切换 Web 控制台浅色/深色主题（不走 update_config）
   参数：{"name":"set_console_theme","theme":"light","label":"控制台主题: 深色 → 浅色"}
   - theme 仅允许 light 或 dark
   - 恒为确认级（require_confirm=true）

# 常见自然语言 → 配置项（优先用 update_config 的 key）

- 弹幕太多/行数太多 → danmu_lines（减小数值）
- 弹幕太快/太慢 → danmu_speed
- 字体太大/太小 → font_size（Overlay 弹幕字号，常见 12–72，默认 24）
- 弹幕太透明/不透明 → opacity
- 重复弹幕太多 → dedup_threshold
- 单条弹幕太长 → danmu_max_chars
- 布局/横竖屏 → layout_mode
- 浅色模式/深色模式/黑夜模式 → set_console_theme（禁止用 update_config 写 theme）

# 权限边界（绝对不能做）

- 禁止修改 api_key / mic_api_key（不暴露；用户要改请回复「请在【弹幕设置 → API 与模型】页面修改」）
- 禁止用 update_config 修改 theme/console_theme（必须用 set_console_theme）
- 禁止修改 use_thinking（运行时固定关闭，改了无效）
- 禁止修改 persona_model_bindings / region_x/y/w/h
- 禁止删除模型档案 / 重置所有设置 / 清空弹幕池（只给文字指引，不产生工具调用）
- screen_index 切换会使当前生成中的 AI 回复失效，label 需注明

# 输出格式（严格 JSON，不要 Markdown 代码块）

"""

_SYSTEM_PROMPT_PREFIX_EN = """You are the "AI Butler", DanmuAI's natural-language settings agent. Users describe needs in plain language; you parse intent and return tool calls.

# Available tools (return a tool_calls array in JSON)

1. update_config — change a setting (WEB_CONFIG_KEYS whitelist only)
   Params: {"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":"Danmu speed: 5 → 8"}],"require_confirm":true}
   - **All changes require user confirmation** (require_confirm is always true)
   - label current values must match "current config values" below; target value goes in value
   - One utterance may include multiple changes

2. set_default_model — switch the active model profile
   Params: {"name":"set_default_model","index":1,"model_id":"mimo-v2.5","label":"Vision model: doubao-seed → mimo-v2.5"}
   - index is the profile position in the list (0-based); see "Current model profiles" below
   - Always confirmation-level (require_confirm=true)

3. set_console_theme — switch Web console light/dark theme (not via update_config)
   Params: {"name":"set_console_theme","theme":"light","label":"Console theme: dark → light"}
   - theme must be light or dark only
   - Always confirmation-level (require_confirm=true)

# Common natural language → config keys (prefer update_config keys)

- Too many danmu / too many lines → danmu_lines (decrease)
- Danmu too fast / too slow → danmu_speed
- Font too big / too small → font_size (overlay danmu size, often 12–72, default 24)
- Danmu too transparent / opaque → opacity
- Too many duplicate danmu → dedup_threshold
- Single danmu too long → danmu_max_chars
- Layout / orientation → layout_mode
- Light mode / dark mode → set_console_theme (do not use update_config for theme)

# Boundaries (never do these)

- Do not change api_key / mic_api_key (not exposed; tell users to edit under Danmu Settings → API & Models)
- Do not use update_config for theme/console_theme (must use set_console_theme)
- Do not change use_thinking (disabled at runtime; changes have no effect)
- Do not change persona_model_bindings / region_x/y/w/h
- Do not delete model profiles / reset all settings / clear danmu pool (text guidance only, no tool calls)
- Changing screen_index invalidates in-flight AI replies; note that in label

# Output format (strict JSON, no Markdown code fences)

"""

_SYSTEM_PROMPT_SUFFIX = """
- 无工具调用时 tool_calls 为空数组 []
- 不要输出 JSON 以外的内容
- reply 用中文，口语化，不要解释技术细节

# 当前配置上下文（已为你查询，无需再问）

"""

_SYSTEM_PROMPT_SUFFIX_EN = """
- When no tools apply, tool_calls is an empty array []
- Do not output anything outside JSON
- reply in English, conversational, avoid technical jargon

# Current config context (pre-fetched; do not ask again)

"""


def _build_system_prompt(config) -> str:
    """组装完整 system prompt（单花括号 JSON 示例 + 当前配置上下文）。"""
    if _is_english():
        prefix = _SYSTEM_PROMPT_PREFIX_EN
        example = _JSON_OUTPUT_EXAMPLE_EN
        suffix = _SYSTEM_PROMPT_SUFFIX_EN
    else:
        prefix = _SYSTEM_PROMPT_PREFIX
        example = _JSON_OUTPUT_EXAMPLE
        suffix = _SYSTEM_PROMPT_SUFFIX
    return prefix + example + suffix + _build_context(config)


# ---------------------------------------------------------------------------
# duck-typed worker（仿 _BridgeStreamWorker）
# ---------------------------------------------------------------------------


class _AiButlerWorker:
    """duck-typed worker for stream_openai / stream_doubao（非 QObject）。

    只暴露 stream_* 函数需要的属性：``_stopping`` / ``_request_deadline_at`` /
    ``_request_started_at`` / ``_resolve_request_credentials`` / ``_get_http_client``。
    不实例化 ``AiWorker``，不触 Qt / 主链路。
    """

    def __init__(self, config) -> None:
        self.config = config
        self._stopping = threading.Event()
        self._thread_local = threading.local()
        self._client_lock = threading.Lock()
        self._clients: set[httpx.Client] = set()
        self._request_started_at = time.monotonic()
        self._request_deadline_at = self._request_started_at + _DEFAULT_TIMEOUT_SEC

    def _resolve_request_credentials(self):
        return resolve_request_credentials(self.config)

    def _get_http_client(self) -> httpx.Client:
        client = getattr(self._thread_local, "client", None)
        if client is None:
            client = httpx.Client(
                timeout=httpx.Timeout(_DEFAULT_TIMEOUT_SEC, connect=5.0),
            )
            with self._client_lock:
                self._clients.add(client)
            self._thread_local.client = client
        return client

    def close(self) -> None:
        with self._client_lock:
            for client in self._clients:
                try:
                    client.close()
                except OSError:
                    pass
            self._clients.clear()


# ---------------------------------------------------------------------------
# 上下文构建（query_config 合成进 system prompt，spec §7.4）
# ---------------------------------------------------------------------------


# 注入上下文的非敏感 config 键（apiKey 永远不注入）
_CONTEXT_CONFIG_KEYS = (
    "api_mode",
    "api_endpoint",
    "model",
    "screen_index",
    "danmu_speed",
    "danmu_lines",
    "danmu_max_chars",
    "font_size",
    "danmu_font_family",
    "danmu_font_bold",
    "layout_mode",
    "danmu_render_mode",
    "opacity",
    "dedup_threshold",
    "bililive_dm_mode_enabled",
    "mic_mode_enabled",
    "normal_recognition_interval_sec",
    "normal_reply_count",
)


def _effective_config_value(config, key: str) -> str:
    """读取配置当前有效值（含默认值回落），供上下文与 label 校正。"""
    raw = config.get(key, "")
    if str(raw).strip():
        return str(raw).strip()
    from app.config_defaults import CONFIG_DEFAULTS
    return str(CONFIG_DEFAULTS.get(key, "")).strip()


def _format_change_label(key: str, current: str, new_value: str) -> str:
    name = _change_key_labels().get(key, key)
    if _is_english():
        cur_display = current if current else "(default)"
    else:
        cur_display = current if current else "（默认）"
    return f"{name}: {cur_display} → {new_value}"


def _build_context(config) -> str:
    """读 config 快照 + custom_models（apiKey 掩码），合成上下文字符串。

    敏感字段（apiKey）永远掩码或不注入。``query_config`` 工具的结果由此合成，
    LLM 不真发 tool call 往返（spec §7.4）。
    """
    if _is_english():
        lines: list[str] = [
            "## Current config values (authoritative — label/reply current values must match)",
        ]
        unset = "(unset)"
        theme_label = "console_theme (Web console theme)"
        default_label = "default_model_id (active model)"
        profiles_header = "## Current model profiles (apiKey masked, index from 0)"
        no_profiles = "- (no model profiles)"
        in_use = "(in use)"
    else:
        lines = ["## 当前配置值（权威来源，label 与 reply 中的当前值必须与此一致）"]
        unset = "（未设置）"
        theme_label = "console_theme（Web 控制台主题）"
        default_label = "default_model_id（当前使用模型）"
        profiles_header = "## 当前模型档案列表（apiKey 已掩码，index 从 0 起）"
        no_profiles = "- （无模型档案）"
        in_use = "（当前使用）"

    for key in _CONTEXT_CONFIG_KEYS:
        value = _effective_config_value(config, key)
        if not value:
            continue
        lines.append(f"- {key}: {value}")

    console_theme = _console_theme_from_config(config)
    lines.append(f"- {theme_label}: {console_theme}")

    default_model_id = (config.get_default_model_id() or "").strip()
    lines.append(f"- {default_label}: {default_model_id or unset}")

    lines.append("")
    lines.append(profiles_header)
    try:
        models = config.get_custom_models()
    except (RuntimeError, ValueError, OSError):
        models = []
    if not models:
        lines.append(no_profiles)
    else:
        for i, model in enumerate(models):
            mid = (model.get("default_model_id") or model.get("modelId") or "").strip()
            name = (model.get("name") or "").strip()
            mode = (model.get("mode") or "").strip()
            is_default = in_use if mid == default_model_id else ""
            lines.append(f"- index={i}: name={name or '—'} / model_id={mid or '—'} / mode={mode} {is_default}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# messages 转换（多轮对话支持）
# ---------------------------------------------------------------------------


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """裁剪过长历史与单条过长内容。"""
    out: list[dict] = []
    for msg in messages[-_MAX_MESSAGES:]:
        role = str(msg.get("role") or "user").strip().lower()
        if role not in ("user", "assistant", "system"):
            role = "user"
        content = str(msg.get("content") or "")[:_MAX_MESSAGE_CHARS]
        if not content.strip():
            continue
        out.append({"role": role, "content": content})
    return out


def _build_openai_messages(system_pt: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system_pt}]
    for msg in messages:
        out.append({"role": msg["role"], "content": msg["content"]})
    return out


def _build_doubao_input(messages: list[dict]) -> list[dict]:
    """转换通用 messages 为 doubao Responses input 格式。

    doubao content 项：user/system 用 input_text，assistant 用 output_text。
    """
    out: list[dict] = []
    for msg in messages:
        role = msg["role"]
        content_type = "output_text" if role == "assistant" else "input_text"
        out.append({
            "type": "message",
            "role": role,
            "content": [{"type": content_type, "text": msg["content"]}],
        })
    return out


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------


def _stream_llm(worker: _AiButlerWorker, system_pt: str, messages: list[dict]) -> str:
    """按 api_mode 选 doubao 或 openai 路径，返回完整文本。"""
    resolved = worker._resolve_request_credentials()
    if resolved is None:
        raise ValueError("model_not_configured")
    endpoint, api_key, model, api_mode = resolved
    http_client = worker._get_http_client()
    transport = resolve_api_transport(endpoint, api_mode)

    if transport == "doubao":
        data: dict[str, Any] = {
            "model": model,
            "input": _build_doubao_input(messages),
            "stream": True,
            "thinking": dict(THINKING_DISABLED),
            "max_output_tokens": 1024,
        }
        if system_pt:
            data["instructions"] = system_pt
        url = f"{endpoint}/responses"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        text, _, _, _ = stream_doubao(worker, http_client, url, headers, data)
        return text

    caps = get_capabilities_for_endpoint(endpoint, api_mode)
    adapter = get_openai_adapter(endpoint, api_mode)
    data = {
        "model": model,
        "messages": _build_openai_messages(system_pt, messages),
        "stream": True,
    }
    adapter.patch_openai_chat_body(data, max_tokens=1024, caps=caps)
    apply_thinking_disabled(data, caps=caps)
    data["response_format"] = {"type": "json_object"}
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(provider_extra_headers(endpoint))
    try:
        text, _, _ = stream_openai(
            worker,
            http_client,
            url,
            headers,
            data,
            endpoint=endpoint,
            api_mode=api_mode,
        )
        return text
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 400 or "response_format" not in data:
            raise
        data.pop("response_format", None)
        text, _, _ = stream_openai(
            worker,
            http_client,
            url,
            headers,
            data,
            endpoint=endpoint,
            api_mode=api_mode,
        )
        return text


# ---------------------------------------------------------------------------
# LLM 返回解析
# ---------------------------------------------------------------------------


def _last_user_message(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "").strip()
    return ""


def _format_danmu_speed(value: float) -> str:
    from app.config_defaults import DANMU_SPEED_MAX, DANMU_SPEED_MIN
    speed = max(DANMU_SPEED_MIN, min(float(value), DANMU_SPEED_MAX))
    return f"{speed:.3f}".rstrip("0").rstrip(".")


def _build_local_update_result(
    config,
    key: str,
    new_value: str,
    reply: str,
) -> dict | None:
    changes, _ = _validate_update_config_changes(
        [{"key": key, "value": new_value}],
        config,
    )
    if not changes:
        return None
    tool_calls, _ = _normalize_tool_calls(
        [{"name": "update_config", "changes": changes}],
        config,
    )
    if not tool_calls:
        return None
    return {"reply": reply, "tool_calls": tool_calls}


def _try_local_intent(user_text: str, config) -> dict | None:
    """规则兜底：LLM 输出不可解析时，匹配高频设置话术。"""
    text = user_text.strip()
    if not text:
        return None

    # --- danmu_speed ---
    speed_up = any(w in text for w in ("调快", "加快", "快点", "快一点", "更快", "提速"))
    speed_down = any(w in text for w in ("调慢", "减慢", "慢点", "慢一点", "更慢", "降速"))
    too_fast = "太快" in text and not speed_up
    too_slow = "太慢" in text and not speed_down
    if "速度" in text or ("弹幕" in text and ("快" in text or "慢" in text)):
        if speed_up or too_slow:
            cur = float(_effective_config_value(config, "danmu_speed") or "2")
            new_val = _format_danmu_speed(cur * 1.25 if cur < 8 else cur + 0.5)
            return _build_local_update_result(
                config, "danmu_speed", new_val, "好的，我帮你把弹幕速度调快一些。",
            )
        if speed_down or too_fast:
            cur = float(_effective_config_value(config, "danmu_speed") or "2")
            new_val = _format_danmu_speed(cur * 0.8 if cur > 1 else cur - 0.25)
            return _build_local_update_result(
                config, "danmu_speed", new_val, "好的，我帮你把弹幕速度调慢一些。",
            )

    # --- danmu_lines ---
    from app.danmu_engine import clamp_danmu_lines
    if any(w in text for w in ("太多", "刷屏", "太密", "行数太多", "太挤")):
        cur = int(float(_effective_config_value(config, "danmu_lines") or "20"))
        new_val = str(clamp_danmu_lines(max(cur - 5, cur // 2 or 1)))
        return _build_local_update_result(
            config, "danmu_lines", new_val, "好的，我帮你减少弹幕显示行数。",
        )
    if any(w in text for w in ("太少", "行数太少", "太稀疏")):
        cur = int(float(_effective_config_value(config, "danmu_lines") or "20"))
        new_val = str(clamp_danmu_lines(cur + 5))
        return _build_local_update_result(
            config, "danmu_lines", new_val, "好的，我帮你增加弹幕显示行数。",
        )
    if "行" in text and any(w in text for w in ("变成", "改为", "调到", "设为", "改成")):
        m = re.search(r"(\d+)\s*行", text)
        if m:
            new_val = str(clamp_danmu_lines(int(m.group(1))))
            return _build_local_update_result(
                config, "danmu_lines", new_val, f"好的，我把弹幕行数调整为 {new_val} 行。",
            )

    # --- font_size ---
    if "字体" in text or "字号" in text:
        cur = int(float(_effective_config_value(config, "font_size") or "24"))
        if any(w in text for w in ("太大", "偏大", "缩小", "小一点", "调小")):
            new_val = str(max(12, cur - 4))
            return _build_local_update_result(
                config, "font_size", new_val, "好的，我帮你把弹幕字号调小一些。",
            )
        if any(w in text for w in ("太小", "偏小", "放大", "大一点", "调大")):
            new_val = str(min(72, cur + 4))
            return _build_local_update_result(
                config, "font_size", new_val, "好的，我帮你把弹幕字号调大一些。",
            )

    # --- console theme ---
    if any(w in text for w in ("浅色", "亮色", "白天模式", "浅色模式")):
        tool_calls, _ = _normalize_tool_calls(
            [{"name": "set_console_theme", "theme": "light"}],
            config,
        )
        if tool_calls:
            return {"reply": "好的，我帮你切换到浅色模式。", "tool_calls": tool_calls}
    if any(w in text for w in ("深色", "暗色", "黑夜", "深色模式", "暗黑")):
        tool_calls, _ = _normalize_tool_calls(
            [{"name": "set_console_theme", "theme": "dark"}],
            config,
        )
        if tool_calls:
            return {"reply": "好的，我帮你切换到深色模式。", "tool_calls": tool_calls}

    # --- mic ---
    if "麦克风" in text and any(w in text for w in ("开启", "打开", "启用", "开")):
        return _build_local_update_result(
            config, "mic_mode_enabled", "1", "好的，我帮你开启麦克风模式。",
        )
    if "麦克风" in text and any(w in text for w in ("关闭", "关掉", "停用")):
        return _build_local_update_result(
            config, "mic_mode_enabled", "0", "好的，我帮你关闭麦克风模式。",
        )

    return None


def _strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json(raw: str) -> dict | None:
    """宽松提取 JSON 对象（LLM 可能包裹 markdown、夹杂说明文字）。"""
    text = _strip_markdown_fence(raw.strip())
    if not text:
        return None

    def _try_load(candidate: str) -> dict | None:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None

    obj = _try_load(text)
    if obj is not None:
        return obj

    # 流式重复 ``}{`` 拼接时取首段
    if text.startswith("{") and "}{" in text:
        head = text.split("}{", 1)[0] + "}"
        obj = _try_load(head)
        if obj is not None:
            return obj

    # 括号平衡提取首个完整对象
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    obj = _try_load(text[start : idx + 1])
                    if obj is not None:
                        return obj
                    break

    # 尾部缺失时的常见补全
    if text.startswith("{"):
        for suffix in ("]}", "}", '"]}'):
            obj = _try_load(text + suffix)
            if obj is not None:
                return obj

    return None


def _validate_update_config_changes(
    changes: list,
    config=None,
) -> tuple[list, list[str]]:
    """校验 update_config 的 changes，丢弃非法 key。返回 (合法 changes, 拒绝说明列表)。"""
    allowed = _allowed_config_keys()
    valid: list[dict] = []
    rejected: list[str] = []
    for ch in changes:
        if not isinstance(ch, dict):
            rejected.append("非对象变更项")
            continue
        key = str(ch.get("key") or "").strip()
        value = ch.get("value")
        if not key:
            rejected.append("缺少 key")
            continue
        if key in FORBIDDEN_CONFIG_KEYS:
            rejected.append(f"{key}（禁止修改）")
            continue
        if key not in allowed:
            rejected.append(f"{key}（不在白名单）")
            continue
        if value is None:
            rejected.append(f"{key}（缺少 value）")
            continue
        new_value = str(value)
        if config is not None:
            current = _effective_config_value(config, key)
            label = _format_change_label(key, current, new_value)
        else:
            label = str(ch.get("label") or "").strip() or f"{key} → {new_value}"
        valid.append({
            "key": key,
            "value": new_value,
            "label": label,
        })
    return valid, rejected


def _normalize_tool_calls(
    raw_calls: list,
    config=None,
) -> tuple[list[dict], list[str]]:
    """规范化工具调用，校验参数。返回 (合法 tool_calls, 拒绝说明)。"""
    out: list[dict] = []
    rejected: list[str] = []
    for call in raw_calls:
        if not isinstance(call, dict):
            rejected.append("非对象工具调用")
            continue
        name = str(call.get("name") or "").strip()
        if name == "update_config":
            changes = call.get("changes")
            if not isinstance(changes, list) or not changes:
                rejected.append("update_config 缺少 changes 数组")
                continue
            valid_changes, rej = _validate_update_config_changes(changes, config)
            rejected.extend(rej)
            if not valid_changes:
                continue
            out.append({
                "name": "update_config",
                "changes": valid_changes,
                "require_confirm": True,
            })
        elif name == "set_default_model":
            index = call.get("index")
            if not isinstance(index, int) or index < 0:
                rejected.append("set_default_model index 非法")
                continue
            model_id = str(call.get("model_id") or "").strip()
            label = str(call.get("label") or "").strip()
            out.append({
                "name": "set_default_model",
                "index": index,
                "model_id": model_id,
                "label": label or f"切换到 index={index}",
                "require_confirm": True,
            })
        elif name == "set_console_theme":
            theme = _normalize_console_theme(call.get("theme"))
            if config is not None:
                current = _console_theme_from_config(config)
                cur_label = "浅色" if current == "light" else "深色"
                new_label = "浅色" if theme == "light" else "深色"
                label = f"控制台主题: {cur_label} → {new_label}"
            else:
                theme_label = "浅色" if theme == "light" else "深色"
                label = str(call.get("label") or "").strip() or f"控制台主题 → {theme_label}"
            out.append({
                "name": "set_console_theme",
                "theme": theme,
                "label": label,
                "require_confirm": True,
            })
        else:
            rejected.append(f"未知工具 {name}")
    return out, rejected


def _parse_butler_response(raw: str, config=None) -> dict:
    """解析 LLM 返回 → {reply, tool_calls}。失败降级。"""
    obj = _extract_json(raw)
    if obj is None:
        logger.info(
            "ai_butler: json_parse_failed raw_len=%s preview=%r",
            len(raw or ""),
            (raw or "")[:240],
        )
        return {
            "reply": _fallback_reply(),
            "tool_calls": [],
        }
    reply = str(obj.get("reply") or "").strip()
    if not reply:
        reply = "好的。"
    raw_calls = obj.get("tool_calls") or []
    if not isinstance(raw_calls, list):
        raw_calls = []
    tool_calls, rejected = _normalize_tool_calls(raw_calls, config)
    if rejected:
        reply += f"（已忽略不支持的项：{'; '.join(rejected)}）"
    return {"reply": reply, "tool_calls": tool_calls}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def chat(config, messages: list[dict], model_id: str | None = None) -> dict:
    """AI管家对话主入口。

    Args:
        config: ConfigStore（只读快照）
        messages: 对话历史 [{role, content}, ...]
        model_id: 可选模型覆盖（W-001 暂不支持，忽略，始终用当前 default）

    Returns:
        {"ok": True, "reply": str, "tool_calls": list} 或
        {"ok": False, "error": str}
    """
    # model_id 覆盖暂不支持（前端切 default 后后端自动用新模型）
    _ = model_id

    clean = _sanitize_messages(messages)
    if not clean:
        return {"ok": False, "error": "empty_messages"}

    if config is None:
        return {"ok": False, "error": "model_not_configured"}

    resolved = resolve_request_credentials(config)
    if resolved is None:
        return {"ok": False, "error": format_credential_error(config)}

    # 用 _build_system_prompt 拼接单花括号 JSON 示例与上下文
    system_pt = _build_system_prompt(config)
    worker = _AiButlerWorker(config)
    last_user = _last_user_message(clean)
    try:
        raw = _stream_llm(worker, system_pt, clean)
        parsed = _parse_butler_response(raw or "", config)

        if not parsed.get("tool_calls"):
            local = _try_local_intent(last_user, config)
            if local:
                parsed = local
            elif parsed.get("reply") == _fallback_reply() and last_user:
                repair_pt = system_pt + _repair_suffix()
                raw_retry = _stream_llm(
                    worker,
                    repair_pt,
                    [{"role": "user", "content": last_user}],
                )
                parsed_retry = _parse_butler_response(raw_retry or "", config)
                if parsed_retry.get("tool_calls") or parsed_retry.get("reply") != _fallback_reply():
                    parsed = parsed_retry
                else:
                    local = _try_local_intent(last_user, config)
                    if local:
                        parsed = local
    except ValueError as exc:
        if str(exc) == "model_not_configured":
            return {"ok": False, "error": "model_not_configured"}
        logger.warning("ai_butler_service: stream ValueError %r", exc)
        return {"ok": False, "error": f"internal_error:{type(exc).__name__}"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout"}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": f"http_{exc.response.status_code}"}
    except AppError as exc:
        logger.warning("ai_butler_service: app_error %r", exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # boundary: unexpected stream failure
        logger.warning("ai_butler_service: stream failed %r", exc)
        return {"ok": False, "error": f"internal_error:{type(exc).__name__}"}
    finally:
        worker.close()

    return {
        "ok": True,
        "reply": parsed["reply"],
        "tool_calls": parsed["tool_calls"],
    }
