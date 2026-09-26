"""分级、脱敏的 API 探活；默认行为保持为最小 text probe。

W-AUDIT-PROBE-SECRET-001：本模块同时承载探测的**出站目标策略**——
只允许 http/https、loopback 与公网目标；私网 / link-local / 云元数据目标按
已记录策略拒绝，且默认关闭自动重定向（``follow_redirects=False``），
避免把已存密钥带向调用方临时替换的目标或跨 origin 跳转。

W-AUDIT-PROBE-PARITY-001：新增 ``vision_stream`` / ``business_parse`` / ``full``
阶段。``full`` 依次执行 local → auth_model → text → vision_stream → business_parse，
其中 ``vision_stream`` 复用正式视觉请求构造（图片 + system/user + streaming +
档案参数），``business_parse`` 复用正式 reply envelope / normalize 合同；只有
``business_parse`` 通过才算「完整视觉链路可用」。probe 全程只读：不进入
``_on_ai_reply``、不写统计、失败预算、reply buffer 或 Overlay。
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.doubao_responses_stream import stream_doubao_responses
from app.errors import AppError
from app.model_providers import normalize_endpoint, normalize_mode
from app.openai_chat_stream import stream_openai_chat
from app.providers.model_discovery import discover_models
from app.providers.request_planner import GenerationRequest, plan_http_request
from app.translations import tr

_STAGES = {
    "local", "auth_model", "text", "vision", "audio", "stream",
    # W-AUDIT-PROBE-PARITY-001：正式视觉流式 + 业务解析 + 完整阶段链
    "vision_stream", "business_parse", "full",
}

# 完整阶段链的稳定顺序（供 UI 逐项展示未执行阶段）。
_FULL_CHAIN_STAGES = ("local", "auth_model", "text", "vision_stream", "business_parse")

_CATEGORIES = {
    "invalid_endpoint", "auth_missing", "auth_invalid", "permission_denied", "model_not_found",
    "unsupported_api_family", "unsupported_parameter", "unsupported_modality", "invalid_content_part",
    "rate_limited", "quota_exhausted", "model_not_available_in_region", "timeout", "provider_unavailable", "malformed_stream",
    "empty_output", "unknown_provider_error",
    # W-AUDIT-PROBE-SECRET-001：出站策略分类（稳定错误分类，不含目标响应正文）
    "outbound_target_blocked", "outbound_redirect_blocked",
}
_SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA="
_PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/9pM5WQAAAABJRU5ErkJggg=="

# W-AUDIT-PROBE-PARITY-001：vision_stream / business_parse 的固定最小提示词。
# probe 只用内存中的固定测试图像与这段常量提示，不读取/保存用户屏幕。
_PROBE_VISION_SYSTEM = "连接测试：请在回复中说明你是否能看见随附图片。"
_PROBE_VISION_USER = "请用一句话描述这张图片。"


# 云元数据 IP：link-local（169.254.0.0/16）已由 is_link_local 覆盖，这里补充非
# link-local 的元数据地址，并对已知元数据地址做精确匹配双保险。
_CLOUD_METADATA_IPS: frozenset[str] = frozenset(
    {
        "169.254.169.254",  # AWS / Azure / GCP / OpenStack
        "100.100.100.200",  # Alibaba Cloud
        "fd00:ec2::254",  # AWS IPv6 元数据
    }
)

# 出站目标策略（已记录在 SECURITY.md）：
#   - 允许：http/https + 公网 IP、loopback（用户明确保存/输入的本地兼容服务）；
#   - 拒绝：私网（RFC1918 等）、link-local（含 169.254.0.0/16）、云元数据、
#     多播 / 未指定 / 保留地址。
# 禁用自动重定向；3xx 一律按 outbound_redirect_blocked 归类，不携带原
# Authorization 跨 origin 转发。


class ProbeScopeViolation(ValueError):
    """掩码/空 key 恢复时，探测目标越出已存凭据作用域。

    路由层把本异常映射为 4xx（``error_code`` 稳定），从而在发出任何 HTTP
    请求之前阻断"已存密钥 + 调用方临时 endpoint/provider/mode"的组合。
    """

    error_code = "probe_scope_violation"


def _is_allowed_probe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only for loopback and public addresses.

    loopback 允许，是因为用户可能明确保存/输入本地兼容模型服务；
    私网 / link-local / 云元数据 / 多播 / 未指定 / 保留地址一律拒绝。
    """
    if str(ip) in _CLOUD_METADATA_IPS:
        return False
    if ip.is_loopback:
        return True
    if (
        ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return False
    return True


def _resolve_probe_host_ips(host: str) -> list[Any] | None:
    """Resolve all A/AAAA addresses for ``host``.

    Returns ``None`` when resolution fails: DNS 不可用时不能判定目标越界，
    交给 httpx 报告真实连接错误，而不是把离线环境误判为策略拒绝。
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return None
    addresses: list[Any] = []
    for info in infos:
        addr = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    return addresses or None


def probe_target_policy_error(endpoint: str) -> str | None:
    """Return a stable error category when the probe target is not allowed.

    ``None`` 表示目标被允许（含"无法解析→交由 httpx 报错"）。非法 scheme 或
    缺失 host 返回 ``invalid_endpoint``。
    """
    parts = urlsplit(endpoint)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return "invalid_endpoint"
    host = parts.hostname or ""
    if not host:
        return "invalid_endpoint"
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return None if _is_allowed_probe_ip(literal) else "outbound_target_blocked"
    resolved = _resolve_probe_host_ips(host)
    if resolved is None:
        return None
    for ip in resolved:
        if not _is_allowed_probe_ip(ip):
            return "outbound_target_blocked"
    return None


@dataclass
class ProbeResult:
    ok: bool
    message: str
    status_code: int | None = None
    stage: str = "text"
    provider_id: str | None = None
    model_id: str | None = None
    error_category: str | None = None
    message_key: str | None = None
    capability_updates: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    request_id: str | None = None
    # W-AUDIT-PROBE-PARITY-001：多阶段探活的机器可读阶段结果与完成判定。
    # ``stages`` 每项为 {stage, status(passed/failed/skipped), ok, error_category,
    # message_key, status_code, warnings, capability_updates}；``complete`` 只在
    # business_parse（完整视觉链路）通过时为 True。
    stages: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _new_probe_client() -> httpx.Client:
    """探测 HTTP 客户端：固定超时并显式关闭自动重定向（W-AUDIT-PROBE-SECRET-001）。"""
    return httpx.Client(
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=False,
    )


def _stage_record(result: ProbeResult) -> dict[str, Any]:
    """把单阶段结果投影为机器可读记录（不含请求/响应正文或密钥）。"""
    return {
        "stage": result.stage,
        "status": "passed" if result.ok else "failed",
        "ok": result.ok,
        "error_category": result.error_category,
        "message_key": result.message_key,
        "status_code": result.status_code,
        "warnings": list(result.warnings),
        "capability_updates": dict(result.capability_updates),
    }


def _skipped_record(stage: str, warning: str) -> dict[str, Any]:
    """未执行阶段记录：明确标注 skipped，不伪造已执行结果。"""
    return {
        "stage": stage,
        "status": "skipped",
        "ok": False,
        "error_category": None,
        "message_key": None,
        "status_code": None,
        "warnings": [warning],
        "capability_updates": {},
    }


def parse_business_reply_items(text: str) -> list[str]:
    """把正式 stream parser 的可见文本再过一遍**正式业务解析合同**。

    W-AUDIT-PROBE-PARITY-001：直接复用 ``parse_ai_reply_envelope``（信封容错）
    与 ``normalize_reply_batch``（业务规范化/过滤）。**不注入运行态弹幕池**
    （``config=None``）——池补齐会掩盖「空正文 / reasoning-only / 全部被过滤」，
    使 probe 误报完整成功；因此 probe 只判定模型自身输出能否形成有效候选。
    """
    from app.reply_parser import normalize_reply_batch, parse_ai_reply_envelope

    envelope = parse_ai_reply_envelope(text)
    return normalize_reply_batch(envelope.items)


def probe_connection(
    endpoint: str,
    api_key: str,
    model_id: str,
    mode: str,
    *,
    stage: str = "text",
    profile_params: dict[str, Any] | None = None,
) -> ProbeResult:
    endpoint, api_key, model_id, mode = normalize_endpoint(endpoint), (api_key or "").strip(), (model_id or "").strip(), normalize_mode(mode)
    stage = (stage or "text").strip().lower()
    base = dict(stage=stage, provider_id=None, model_id=model_id or None)
    if stage not in _STAGES:
        return _result(False, "custom_model.test_failed", "unknown_provider_error", **base)
    if not endpoint:
        return _result(False, "custom_model.error_endpoint", "invalid_endpoint", **base)
    parts = urlsplit(endpoint)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return _result(False, "custom_model.error_endpoint", "invalid_endpoint", **base)
    if mode not in {"openai-compatible", "doubao"}:
        return _result(False, "ai.error_request_failed", "unsupported_api_family", **base)
    if not api_key:
        return _result(False, "custom_model.error_api_key", "auth_missing", **base)
    if not model_id:
        return _result(False, "custom_model.error_model_id", "model_not_found", **base)
    if stage == "local":
        return _probe_local(endpoint, api_key, model_id, mode)
    # W-AUDIT-PROBE-SECRET-001：任何真正出站的阶段先过目标策略。
    target_error = probe_target_policy_error(endpoint)
    if target_error is not None:
        return _result(False, "custom_model.error_target_blocked", target_error, **base)
    if stage == "full":
        try:
            return _probe_full_chain(endpoint, api_key, model_id, mode, profile_params)
        except Exception as exc:
            return _classify_exception(exc, **base)
    if stage in {"vision_stream", "business_parse"}:
        try:
            return _probe_vision_business_stage(
                stage, endpoint, api_key, model_id, mode, profile_params
            )
        except Exception as exc:
            return _classify_exception(exc, stage="vision_stream", provider_id=None, model_id=model_id or None)
    try:
        planned = plan_http_request(GenerationRequest(
            "connection_probe", model_id, endpoint, api_key, mode, user_text="ping", max_output_tokens=1,
            stream=stage in {"stream"}, force_thinking_off=True,
            image_data_uri=_PIXEL if stage == "vision" else None,
            audio_data_uri=_SILENT_WAV if stage == "audio" else None,
            supports_vision_override=True if stage == "vision" else None,
            supports_mic_override=True if stage == "audio" else None,
        ))
        base.update(provider_id=planned.provider_id)
        if stage == "auth_model":
            return _probe_models(endpoint, api_key, planned.provider_id, model_id, stage)
        return _post_probe(planned, **base)
    except Exception as exc:
        return _classify_exception(exc, **base)


def _probe_local(endpoint: str, api_key: str, model_id: str, mode: str) -> ProbeResult:
    """local：字段、endpoint/mode/provider 与 planner 可构造（不发起网络请求）。"""
    try:
        planned = plan_http_request(GenerationRequest("connection_probe", model_id, endpoint, api_key, mode, user_text="ping", max_output_tokens=1, stream=False, force_thinking_off=True))
        return _result(True, "custom_model.test_ok", None, provider_id=planned.provider_id, model_id=model_id or None, stage="local", warnings=planned.warnings)
    except Exception as exc:
        return _classify_exception(exc, stage="local", provider_id=None, model_id=model_id or None)


def _probe_text(client: httpx.Client, endpoint: str, api_key: str, model_id: str, mode: str) -> ProbeResult:
    """text：轻量文本请求；UI 只能据此显示「文本连接可用」。"""
    planned = plan_http_request(GenerationRequest(
        "connection_probe", model_id, endpoint, api_key, mode, user_text="ping", max_output_tokens=1,
        stream=False, force_thinking_off=True,
    ))
    return _post_probe(planned, stage="text", client=client, provider_id=planned.provider_id, model_id=model_id or None)


def _visual_planned_request(endpoint: str, api_key: str, model_id: str, mode: str, profile_params: dict[str, Any] | None):
    """构造正式视觉流式请求（复用正式 planner + 图片/system/user/stream/档案参数）。"""
    from app.ai_client_requests import (
        build_visual_planned_request,
        resolve_visual_tuning_from_params,
    )

    params = dict(profile_params or {})
    tuning = resolve_visual_tuning_from_params(
        model_id=model_id,
        endpoint=endpoint,
        api_mode=mode,
        temperature=params.get("temperature"),
        thinking_effort=str(params.get("thinking_effort") or "off"),
        max_tokens=int(params.get("max_tokens") or 512),
    )
    planned = build_visual_planned_request(
        model=model_id,
        endpoint=endpoint,
        api_key=api_key,
        api_mode=mode,
        system_text=_PROBE_VISION_SYSTEM,
        user_text=_PROBE_VISION_USER,
        image_data_uri=_PIXEL,
        max_output_tokens=tuning.max_output_tokens,
        temperature=tuning.temperature,
        reasoning_enabled=tuning.effective_use_thinking,
        reasoning_effort=tuning.thinking_effort,
    )
    return planned, tuning


def _stream_incomplete(parsed) -> bool:
    """SSE 未完成（畸形 / 截断 / 无终止标记）。

    只在解析器暴露 ``stream_completed`` 时判定，避免对不返回该标记的 provider
    结果误判为畸形流。
    """
    if not hasattr(parsed, "stream_completed"):
        return False
    return not bool(getattr(parsed, "stream_completed", False))


def _vision_stream_probe(client: httpx.Client, planned) -> tuple[ProbeResult, str]:
    """vision_stream：同一次请求携带图片 + system/user 并开启 streaming。

    返回 (阶段结果, 原始可见文本)。传输 / 解析层失败（HTTP 错误、parser error、
    畸形或截断的 SSE）归到本阶段；正文为空但流正常结束不在此判失败（由
    business_parse 判定），只附提示 warning。
    """
    try:
        parsed = _stream_transport(client, planned)
    except Exception as exc:
        return _classify_exception(exc, stage="vision_stream", provider_id=planned.provider_id, model_id=planned.model_id or None), ""
    text = str(getattr(parsed, "text", "") or "").strip()
    parser_error = bool(str(getattr(parsed, "error", "") or "").strip())
    reasoning_only = bool(getattr(parsed, "reasoning_only", False))
    updates = {
        "input_tokens": int(getattr(parsed, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(parsed, "output_tokens", 0) or 0),
    }
    if parser_error:
        return _result(
            False, "ai.error_request_failed", "malformed_stream",
            capability_updates={"stream": True, **updates}, warnings=["stream_parser_error"],
            stage="vision_stream", provider_id=planned.provider_id, model_id=planned.model_id or None,
        ), ""
    if not text and _stream_incomplete(parsed):
        return _result(
            False, "ai.error_request_failed", "malformed_stream",
            capability_updates={"stream": True, **updates}, warnings=["stream_incomplete"],
            stage="vision_stream", provider_id=planned.provider_id, model_id=planned.model_id or None,
        ), ""
    warnings = list(getattr(planned, "warnings", ()) or [])
    if reasoning_only:
        warnings.append("reasoning_only")
    if not text:
        warnings.append("no_visible_content")
    return _result(
        True, "custom_model.test_ok", None,
        capability_updates={"stream": True, **updates}, warnings=warnings,
        stage="vision_stream", provider_id=planned.provider_id, model_id=planned.model_id or None,
    ), text


def _business_parse_probe(text: str) -> ProbeResult:
    """business_parse：正式 stream parser 输出再经正式业务解析合同形成候选。"""
    if not text.strip():
        return _result(
            False, "ai.error_request_failed", "empty_output",
            warnings=["no_visible_content", "empty_business_items"], stage="business_parse",
        )
    items = parse_business_reply_items(text)
    if not items:
        return _result(
            False, "ai.error_request_failed", "empty_output",
            warnings=["empty_business_items"], stage="business_parse",
        )
    return _result(
        True, "custom_model.test_ok", None,
        capability_updates={"business_parse": True, "items": len(items)},
        warnings=[], stage="business_parse",
    )


def _probe_vision_business_stage(stage: str, endpoint: str, api_key: str, model_id: str, mode: str, profile_params) -> ProbeResult:
    """单阶段入口：``vision_stream`` 只跑请求；``business_parse`` 追加业务解析。"""
    try:
        planned, _tuning = _visual_planned_request(endpoint, api_key, model_id, mode, profile_params)
    except Exception as exc:
        return _classify_exception(exc, stage="vision_stream", provider_id=None, model_id=model_id or None)
    with _new_probe_client() as client:
        vision, raw_text = _vision_stream_probe(client, planned)
    if stage == "vision_stream":
        vision.stages = [_stage_record(vision)]
        vision.complete = False
        return vision
    if not vision.ok:
        vision.stages = [_stage_record(vision), _skipped_record("business_parse", "vision_stream_failed")]
        vision.complete = False
        return vision
    business = _business_parse_probe(raw_text)
    business.stages = [_stage_record(vision), _stage_record(business)]
    business.complete = business.ok
    return business


def _probe_full_chain(endpoint: str, api_key: str, model_id: str, mode: str, profile_params) -> ProbeResult:
    """完整阶段链：local → auth_model → text → vision_stream → business_parse。

    只有 business_parse 通过才算「完整视觉链路可用」（``complete=True``）。
    ``auth_model`` / ``text`` 为可诊断的阶段性检查：失败如实记录但不阻止后续
    真实视觉请求（模型列表接口并非所有 provider 都提供，认证是否有效最终由真实
    请求判定）；``local`` 失败则无法继续，后续阶段标记 skipped。全程 read-only。
    """
    records: list[dict[str, Any]] = []
    local = _probe_local(endpoint, api_key, model_id, mode)
    records.append(_stage_record(local))
    if not local.ok:
        for stage in _FULL_CHAIN_STAGES[1:]:
            records.append(_skipped_record(stage, "local_failed"))
        return _full_result(records, complete=False, provider_id=None, model_id=model_id or None)
    provider_id = local.provider_id
    with _new_probe_client() as client:
        auth = _probe_models(endpoint, api_key, provider_id or "", model_id, "auth_model", client=client)
        records.append(_stage_record(auth))
        text_result = _probe_text(client, endpoint, api_key, model_id, mode)
        records.append(_stage_record(text_result))
        try:
            planned, _tuning = _visual_planned_request(endpoint, api_key, model_id, mode, profile_params)
        except Exception as exc:
            vision = _classify_exception(exc, stage="vision_stream", provider_id=provider_id, model_id=model_id or None)
            records.append(_stage_record(vision))
            records.append(_skipped_record("business_parse", "vision_stream_failed"))
            return _full_result(records, complete=False, provider_id=provider_id, model_id=model_id or None)
        vision, raw_text = _vision_stream_probe(client, planned)
        records.append(_stage_record(vision))
        if not vision.ok:
            records.append(_skipped_record("business_parse", "vision_stream_failed"))
            return _full_result(records, complete=False, provider_id=provider_id, model_id=model_id or None)
        business = _business_parse_probe(raw_text)
        records.append(_stage_record(business))
    return _full_result(records, complete=business.ok, provider_id=provider_id, model_id=model_id or None)


def _full_result(records: list[dict[str, Any]], *, complete: bool, provider_id: str | None, model_id: str | None) -> ProbeResult:
    failed = next((item for item in records if item["status"] == "failed"), None)
    warnings = [f"{item['stage']}_failed" for item in records if item["status"] == "failed"]
    if complete:
        result = _result(True, "custom_model.test_ok", None, stage="full", warnings=warnings)
    else:
        key = (failed or {}).get("message_key") or "custom_model.test_failed"
        category = (failed or {}).get("error_category") or "unknown_provider_error"
        status_code = (failed or {}).get("status_code")
        result = _result(False, key, category, status_code, stage="full", warnings=warnings)
    result.provider_id = provider_id
    result.model_id = model_id
    result.stages = records
    result.complete = complete
    return result



def _probe_models(endpoint: str, api_key: str, provider_id: str, model_id: str, stage: str, *, client: httpx.Client | None = None) -> ProbeResult:
    try:
        if client is None:
            with _new_probe_client() as owned:
                return _probe_models(endpoint, api_key, provider_id, model_id, stage, client=owned)
        discovery = discover_models(provider_id, api_key, endpoint=endpoint, http_client=client)
        models = tuple(getattr(discovery, "models", ()) or ())
        if getattr(discovery, "discovery_kind", "") != "account_discovery" or not models:
            category, status_code = _discovery_failure(discovery)
            return _result(False, "ai.error_request_failed", category, status_code, stage=stage, provider_id=provider_id, model_id=model_id, warnings=["models_unavailable"])
        visible = {str(getattr(item, "id", "")) for item in models}
        if model_id not in visible:
            return _result(False, "ai.error_request_failed", "model_not_found", stage=stage, provider_id=provider_id, model_id=model_id, capability_updates={"model_visible": False, "vision": None})
        return _result(True, "custom_model.test_ok", None, stage=stage, provider_id=provider_id, model_id=model_id, capability_updates={"model_visible": True, "vision": None}, warnings=["vision_not_verified"])
    except Exception as exc:
        return _classify_exception(exc, stage=stage, provider_id=provider_id, model_id=model_id)


def _discovery_failure(discovery) -> tuple[str, int | None]:
    """Map discovery's safe status markers without exposing warning text."""
    status = str(getattr(discovery, "status", "") or "").lower()
    warnings = tuple(str(item).lower() for item in (getattr(discovery, "warnings", ()) or ()))
    warning_text = " ".join(warnings)
    status_code = None
    marker = next((item for item in warnings if item.startswith("http_status:")), "")
    if marker:
        try:
            status_code = int(marker.split(":", 1)[1])
        except (TypeError, ValueError):
            status_code = None
    if status_code == 401:
        return "auth_invalid", status_code
    if status_code == 403:
        return "permission_denied", status_code
    if status_code == 404:
        return "model_not_found", status_code
    if status_code == 402:
        return "quota_exhausted", status_code
    if status_code == 429:
        return "rate_limited", status_code
    if status_code and status_code >= 500:
        return "provider_unavailable", status_code
    if any(token in status or token in warning_text for token in ("timeout", "timed out", "connect", "network", "request_error")):
        return "provider_unavailable", status_code
    return "model_not_found", status_code


def _post_probe(planned, stage: str, *, client: httpx.Client | None = None, **base) -> ProbeResult:
    try:
        if client is None:
            # W-AUDIT-PROBE-SECRET-001：显式关闭自动重定向，不依赖 httpx 默认值漂移；
            # 3xx 不跟随，原 Authorization 不会跨 origin 转发。
            with _new_probe_client() as owned:
                return _post_probe(planned, stage, client=owned, **base)
        if stage == "stream":
            return _stream_probe(client, planned, **base)
        response = client.post(planned.url, headers=planned.headers, json=planned.json_body)
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and 300 <= status < 400:
            return _result(
                False,
                "custom_model.error_redirect_blocked",
                "outbound_redirect_blocked",
                status,
                stage=stage,
                **base,
            )
        response.raise_for_status()
        return _result(True, "custom_model.test_ok", None, response.status_code, request_id=_request_id(response), warnings=planned.warnings, capability_updates=_stage_capabilities(stage), stage=stage, **base)
    except Exception as exc:
        return _classify_exception(exc, stage=stage, **base)


def _stream_transport(client: httpx.Client, planned):
    """调用正式 stream parser（OpenAI Chat 或豆包 Responses），返回解析结果对象。"""
    if planned.api_family == "openai_responses":
        return stream_doubao_responses(client, planned.url, planned.headers, planned.json_body)
    return stream_openai_chat(client, planned.url, planned.headers, planned.json_body, endpoint=planned.url)


def _stream_probe(client, planned, **base) -> ProbeResult:
    parsed = _stream_transport(client, planned)
    text = str(getattr(parsed, "text", "") or "").strip()
    parser_error = bool(str(getattr(parsed, "error", "") or "").strip())
    reasoning_only = bool(getattr(parsed, "reasoning_only", False))
    updates = {
        "input_tokens": int(getattr(parsed, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(parsed, "output_tokens", 0) or 0),
    }
    if not text:
        if parser_error:
            return _result(False, "ai.error_request_failed", "malformed_stream", capability_updates={"stream": True, **updates}, warnings=["stream_parser_error"], stage="stream", **base)
        if reasoning_only:
            return _result(True, "custom_model.test_ok", None, capability_updates={"stream": True, **updates}, warnings=["reasoning_only", "no_visible_content"], stage="stream", **base)
        return _result(False, "ai.error_request_failed", "empty_output", capability_updates={"stream": True, **updates}, warnings=["empty_stream_content"], stage="stream", **base)
    warnings = list(getattr(planned, "warnings", ()) or ())
    if reasoning_only:
        warnings.append("reasoning_only")
    return _result(True, "custom_model.test_ok", None, capability_updates={"stream": True, **updates}, warnings=warnings, stage="stream", **base)


def _stage_capabilities(stage: str) -> dict[str, bool]:
    return {
        "text": {"text_input": True},
        "vision": {"vision": True, "image_input": True},
        "audio": {"mic_audio": True, "audio_input": True},
    }.get(stage, {})


def _classify_exception(exc: Exception, **base) -> ProbeResult:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    category = {400: "invalid_content_part", 401: "auth_invalid", 403: "permission_denied", 404: "model_not_found", 408: "timeout", 413: "unsupported_modality", 415: "unsupported_modality", 422: "unsupported_parameter", 429: "rate_limited", 402: "quota_exhausted"}.get(status)
    provider_hint = _private_error_hint(response) or str(exc).lower()
    if any(token in provider_hint for token in ("region", "geo", "location", "not available in your country")):
        category = "model_not_available_in_region"
    if status and status >= 500:
        category = "provider_unavailable"
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectTimeout)):
        category = "timeout"
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        category = "provider_unavailable"
    category = category or ("unknown_provider_error" if not isinstance(exc, AppError) else "unknown_provider_error")
    key = "ai.error_timeout" if category == "timeout" else ("ai.error_connection_failed" if isinstance(exc, httpx.ConnectError) else "ai.error_request_failed")
    return _result(False, key, category, status, request_id=_request_id(response), **base)


def _private_error_hint(response) -> str:
    """Read only bounded classification hints; never return or log the payload."""
    if response is None:
        return ""
    try:
        text = response.text
    except Exception:
        return ""
    if not isinstance(text, str):
        return ""
    return text[:2048].lower()


def _result(ok: bool, key: str, category: str | None, status_code: int | None = None, **kwargs) -> ProbeResult:
    message = tr(key)
    if key == "ai.error_request_failed":
        message = tr(key).format(error=category or "request failed")
    return ProbeResult(ok, message, status_code, error_category=category, message_key=key, **kwargs)


def _request_id(response) -> str | None:
    if response is None:
        return None
    for key in ("x-request-id", "request-id", "x-amzn-requestid"):
        value = response.headers.get(key)
        if isinstance(value, str) and value and len(value) <= 128 and all(ord(c) >= 32 for c in value):
            return value
    return None
