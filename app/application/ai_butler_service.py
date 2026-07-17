"""W-AIBUTLER-CHAT-ONLY-001 — AI管家纯对话服务。

职责：
- 组装 system prompt（含当前配置只读快照，敏感字段掩码）
- 复用 ``app.ai_client_requests.stream_openai`` / ``stream_doubao`` + ``resolve_request_credentials``，
  采用 duck-typed worker 模式（非 QObject，不触 Qt / 主链路）
- 返回自然语言 ``{reply, tool_calls: []}`` — **不产生、不执行任何配置变更**

设计约束：
- **无状态**：每次请求由前端携带完整 messages 历史；后端不保存会话
- **只对话**：不返回可执行 tool_calls；设置修改请用户在设置页手动操作
- **非流式**：等完整生成后一次性返回
- **固定 thinking:disabled**：与主链路一致
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import httpx

from app.ai_client_requests import format_credential_error, resolve_request_credentials
from app.ai_client_requests import stream_doubao, stream_openai
from app.errors import AppError
from app.model_providers import resolve_api_transport
from app.providers import get_capabilities_for_endpoint, get_openai_adapter, provider_extra_headers
from app.providers.constants import THINKING_DISABLED
from app.providers.thinking import apply_thinking_disabled
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
_MAX_MESSAGES = 40  # 20 轮 = 40 条
_MAX_MESSAGE_CHARS = 1000

_FALLBACK_REPLY = "我没太理解您的意思，请换个说法试试。"

_FALLBACK_REPLY_EN = "I didn't quite catch that — please try rephrasing."

_SYSTEM_PROMPT_PREFIX = """你是「AI管家」，DanmuAI 的对话助手。用户可以用自然语言向你提问或闲聊。

# 你能做什么
- 解答 DanmuAI 功能与使用问题
- 根据下方「当前配置上下文」说明用户当前设置状态
- 指引用户到对应设置页自行修改（只给文字指引）

# 你不能做什么（绝对禁止）
- 禁止修改任何配置、主题、默认模型或敏感字段
- 禁止输出工具调用、JSON schema、或要求用户「确认执行」的变更清单
- 禁止声称你已经改好了设置；所有写操作只能由用户在设置页完成
- 禁止索要或复述 API Key

# 回复风格
- 直接用自然语言回复，不要 Markdown 代码块包裹整段回答
- 口语化、简短；reply 用中文
- 若用户要求改设置：说明应去哪个设置页，并说明你无法代改

# 当前配置上下文（只读，已为你查询）

"""

_SYSTEM_PROMPT_PREFIX_EN = """You are the "AI Butler", DanmuAI's conversational assistant. Users may ask questions or chat in natural language.

# What you can do
- Explain DanmuAI features and how to use them
- Describe the user's current settings using the read-only context below
- Guide users to the right settings page to change things themselves (text guidance only)

# What you must never do
- Do not change any config, theme, default model, or sensitive fields
- Do not output tool calls, JSON schemas, or change lists that ask the user to "confirm apply"
- Do not claim you already changed settings; all writes happen only on settings pages by the user
- Do not request or repeat API keys

# Reply style
- Reply in plain natural language; do not wrap the whole answer in Markdown fences
- Conversational and brief; reply in English
- If the user asks to change settings: point them to the right page and say you cannot apply changes

# Current config context (read-only, pre-fetched)

"""


def _is_english() -> bool:
    return Translator.get_language() == "en"


def _fallback_reply() -> str:
    return _FALLBACK_REPLY_EN if _is_english() else _FALLBACK_REPLY


def _build_system_prompt(config) -> str:
    """组装完整 system prompt（对话角色 + 当前配置只读上下文）。"""
    prefix = _SYSTEM_PROMPT_PREFIX_EN if _is_english() else _SYSTEM_PROMPT_PREFIX
    return prefix + _build_context(config)


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
# 上下文构建（只读，供对话回答）
# ---------------------------------------------------------------------------


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
    "mic_mode_enabled",
    "normal_recognition_interval_sec",
    "normal_reply_count",
)


def _effective_config_value(config, key: str) -> str:
    """读取配置当前有效值（含默认值回落），供上下文说明。"""
    raw = config.get(key, "")
    if str(raw).strip():
        return str(raw).strip()
    from app.config_defaults import CONFIG_DEFAULTS
    return str(CONFIG_DEFAULTS.get(key, "")).strip()


def _build_context(config) -> str:
    """读 config 快照 + custom_models（apiKey 掩码），合成上下文字符串。

    敏感字段（apiKey）永远掩码或不注入。仅供对话回答，不用于写配置。
    """
    if _is_english():
        lines: list[str] = [
            "## Current config values (read-only — describe only; never claim to change)",
        ]
        unset = "(unset)"
        theme_label = "console_theme (Web console theme)"
        default_label = "default_model_id (active model)"
        profiles_header = "## Current model profiles (apiKey masked, index from 0)"
        no_profiles = "- (no model profiles)"
        in_use = "(in use)"
    else:
        lines = ["## 当前配置值（只读 — 仅可描述，禁止声称已修改）"]
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
            from app.model_providers import custom_model_profile_id

            mid = custom_model_profile_id(model)
            name = (model.get("name") or "").strip()
            mode = (model.get("mode") or "").strip()
            is_default = in_use if mid == default_model_id else ""
            lines.append(
                f"- index={i}: name={name or '—'} / model_id={mid or '—'} / mode={mode} {is_default}"
            )

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
    # 纯对话：不强制 json_object
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(provider_extra_headers(endpoint))
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
# LLM 返回解析（纯文本；兼容旧 JSON reply 外壳）
# ---------------------------------------------------------------------------


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
    """宽松提取 JSON 对象（兼容旧管家 JSON 外壳）。"""
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

    if text.startswith("{") and "}{" in text:
        head = text.split("}{", 1)[0] + "}"
        obj = _try_load(head)
        if obj is not None:
            return obj

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

    if text.startswith("{"):
        for suffix in ("]}", "}", '"]}'):
            obj = _try_load(text + suffix)
            if obj is not None:
                return obj

    return None


def _parse_butler_response(raw: str, config=None) -> dict:
    """解析 LLM 返回 → {reply, tool_calls: []}。

    - 优先纯文本
    - 若为旧 JSON 外壳且含 reply，仅取 reply 文本
    - **恒** tool_calls=[]（改设置能力已移除；config 参数保留兼容调用方）
    """
    _ = config
    text = (raw or "").strip()
    if not text:
        return {"reply": _fallback_reply(), "tool_calls": []}

    obj = _extract_json(text)
    if obj is not None and "reply" in obj:
        reply = str(obj.get("reply") or "").strip()
        if reply:
            return {"reply": reply, "tool_calls": []}
        # 仅有 tool_calls 的旧 JSON：无有效 reply
        return {"reply": _fallback_reply(), "tool_calls": []}

    # 纯文本（含非 JSON 噪声）直接作为对话回复
    plain = _strip_markdown_fence(text).strip()
    if not plain:
        return {"reply": _fallback_reply(), "tool_calls": []}
    return {"reply": plain, "tool_calls": []}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def chat(config, messages: list[dict], model_id: str | None = None) -> dict:
    """AI管家对话主入口。

    Args:
        config: ConfigStore（只读快照）
        messages: 对话历史 [{role, content}, ...]
        model_id: 可选模型覆盖（暂不支持，忽略，始终用当前 default）

    Returns:
        {"ok": True, "reply": str, "tool_calls": []} 或
        {"ok": False, "error": str}
    """
    _ = model_id

    clean = _sanitize_messages(messages)
    if not clean:
        return {"ok": False, "error": "empty_messages"}

    if config is None:
        return {"ok": False, "error": "model_not_configured"}

    resolved = resolve_request_credentials(config)
    if resolved is None:
        return {"ok": False, "error": format_credential_error(config)}

    system_pt = _build_system_prompt(config)
    worker = _AiButlerWorker(config)
    try:
        raw = _stream_llm(worker, system_pt, clean)
        parsed = _parse_butler_response(raw or "", config)
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
        "tool_calls": [],  # 硬切断：永不返回可执行工具调用
    }
