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
import threading
import time
from typing import Any

import httpx

from app.ai_client_requests import format_credential_error, resolve_request_credentials
from app.ai_client_requests import stream_doubao, stream_openai
from app.model_providers import resolve_api_transport
from app.providers import get_capabilities_for_endpoint, get_openai_adapter, provider_extra_headers
from app.providers.constants import THINKING_DISABLED

logger = logging.getLogger(__name__)

# 与 app.web_api.console_theme 保持一致（勿经 web_api 包 import，避免循环依赖）
_CONSOLE_THEME_KEY = "console_theme"


def _normalize_console_theme(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() == "dark":
        return "dark"
    return "light"


def _console_theme_from_config(config) -> str:
    raw = config.get(_CONSOLE_THEME_KEY, "light")
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


# 自动级 key（require_confirm=false）：用户高频微调，无需确认卡片
_AUTO_LEVEL_KEYS = frozenset({
    "danmu_font_bold",
    "danmu_speed",
    "danmu_lines",
    "opacity",
    "dedup_threshold",
    "font_size",
})

# 确认级 key（spec §4.2.4）：require_confirm=true
_CONFIRM_REQUIRED_KEYS = frozenset({
    "api_endpoint",
    "model",
    "api_mode",
    "screen_index",
    "bililive_dm_mode_enabled",
    "mic_mode_enabled",
    "mic_api_endpoint",
    "mic_api_mode",
    "mic_model",
    "mic_use_visual_model",
    "mic_window_sec",
    "normal_recognition_interval_sec",
    "normal_reply_count",
})


_JSON_OUTPUT_EXAMPLE = """{
  "reply": "口语化、简短的回复（说明你将做什么，或为什么不能做）",
  "tool_calls": [
    {"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":"弹幕速度: 5 → 8"}],"require_confirm":false}
  ]
}"""

_SYSTEM_PROMPT_PREFIX = """你是「AI管家」，DanmuAI 的自然语言设置代理。用户用自然语言描述需求，你解析意图并返回工具调用。

# 可用工具（返回 JSON 的 tool_calls 数组）

1. update_config — 修改设置项（WEB_CONFIG_KEYS 白名单内）
   参数：{"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":"弹幕速度: 5 → 8"}],"require_confirm":bool}
   - require_confirm=false：自动级（danmu_font_bold/danmu_speed/danmu_lines/opacity/dedup_threshold/font_size）
   - require_confirm=true：确认级（其余所有可写项，如 api_mode/screen_index/mic_mode_enabled 等）
   - 一句话可含多个 change

2. set_default_model — 切换当前使用模型档案
   参数：{"name":"set_default_model","index":1,"model_id":"mimo-v2.5","label":"视觉模型: doubao-seed → mimo-v2.5"}
   - index 是模型档案在列表中的序号（0 起），见下方「当前模型档案」
   - 此工具恒为确认级

3. set_console_theme — 切换 Web 控制台浅色/深色主题（不走 update_config）
   参数：{"name":"set_console_theme","theme":"light","label":"控制台主题: 深色 → 浅色"}
   - theme 仅允许 light 或 dark
   - 自动级（require_confirm=false）

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

_SYSTEM_PROMPT_SUFFIX = """
- 无工具调用时 tool_calls 为空数组 []
- 不要输出 JSON 以外的内容
- reply 用中文，口语化，不要解释技术细节

# 当前配置上下文（已为你查询，无需再问）

"""


def _build_system_prompt(config) -> str:
    """组装完整 system prompt（单花括号 JSON 示例 + 当前配置上下文）。"""
    return (
        _SYSTEM_PROMPT_PREFIX
        + _JSON_OUTPUT_EXAMPLE
        + _SYSTEM_PROMPT_SUFFIX
        + _build_context(config)
    )


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
                except Exception:
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


def _build_context(config) -> str:
    """读 config 快照 + custom_models（apiKey 掩码），合成上下文字符串。

    敏感字段（apiKey）永远掩码或不注入。``query_config`` 工具的结果由此合成，
    LLM 不真发 tool call 往返（spec §7.4）。
    """
    lines: list[str] = ["## 当前配置值"]
    for key in _CONTEXT_CONFIG_KEYS:
        value = config.get(key, "")
        if value == "":
            continue
        lines.append(f"- {key}: {value}")

    console_theme = _console_theme_from_config(config)
    lines.append(f"- console_theme（Web 控制台主题）: {console_theme}")

    default_model_id = (config.get_default_model_id() or "").strip()
    lines.append(f"- default_model_id（当前使用模型）: {default_model_id or '（未设置）'}")

    lines.append("")
    lines.append("## 当前模型档案列表（apiKey 已掩码，index 从 0 起）")
    try:
        models = config.get_custom_models()
    except Exception:
        models = []
    if not models:
        lines.append("- （无模型档案）")
    else:
        for i, model in enumerate(models):
            mid = (model.get("default_model_id") or model.get("modelId") or "").strip()
            name = (model.get("name") or "").strip()
            mode = (model.get("mode") or "").strip()
            is_default = "（当前使用）" if mid == default_model_id else ""
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
# LLM 返回解析
# ---------------------------------------------------------------------------


def _extract_json(raw: str) -> dict | None:
    """宽松提取首个 JSON 对象（LLM 可能包裹 markdown 代码块）。"""
    text = raw.strip()
    if not text:
        return None
    # 去掉 markdown 代码块
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    # 直接尝试
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # 提取首个 { 到末尾 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _validate_update_config_changes(changes: list) -> tuple[list, list[str]]:
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
        label = str(ch.get("label") or "").strip()
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
        valid.append({
            "key": key,
            "value": str(value),
            "label": label or f"{key} → {value}",
        })
    return valid, rejected


def _normalize_tool_calls(raw_calls: list) -> tuple[list[dict], list[str]]:
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
            valid_changes, rej = _validate_update_config_changes(changes)
            rejected.extend(rej)
            if not valid_changes:
                continue
            # require_confirm：任一 change 非自动级 → 整批确认级
            require_confirm = any(
                c["key"] not in _AUTO_LEVEL_KEYS for c in valid_changes
            )
            out.append({
                "name": "update_config",
                "changes": valid_changes,
                "require_confirm": require_confirm,
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
            label = str(call.get("label") or "").strip()
            theme_label = "浅色" if theme == "light" else "深色"
            out.append({
                "name": "set_console_theme",
                "theme": theme,
                "label": label or f"控制台主题 → {theme_label}",
                "require_confirm": False,
            })
        else:
            rejected.append(f"未知工具 {name}")
    return out, rejected


def _parse_butler_response(raw: str) -> dict:
    """解析 LLM 返回 → {reply, tool_calls}。失败降级。"""
    obj = _extract_json(raw)
    if obj is None:
        return {
            "reply": "我没太理解您的意思，请换个说法试试。",
            "tool_calls": [],
        }
    reply = str(obj.get("reply") or "").strip()
    if not reply:
        reply = "好的。"
    raw_calls = obj.get("tool_calls") or []
    if not isinstance(raw_calls, list):
        raw_calls = []
    tool_calls, rejected = _normalize_tool_calls(raw_calls)
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
    try:
        raw = _stream_llm(worker, system_pt, clean)
    except ValueError as exc:
        if str(exc) == "model_not_configured":
            return {"ok": False, "error": "model_not_configured"}
        logger.warning("ai_butler_service: stream ValueError %r", exc)
        return {"ok": False, "error": f"internal_error:{type(exc).__name__}"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout"}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": f"http_{exc.response.status_code}"}
    except Exception as exc:
        logger.warning("ai_butler_service: stream failed %r", exc)
        return {"ok": False, "error": f"internal_error:{type(exc).__name__}"}
    finally:
        worker.close()

    parsed = _parse_butler_response(raw or "")
    return {
        "ok": True,
        "reply": parsed["reply"],
        "tool_calls": parsed["tool_calls"],
    }
