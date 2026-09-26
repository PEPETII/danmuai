"""自定义模型 CRUD；模型档案顺序决定未绑定人格的运行时回退。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/custom-models``：返回全部自定义模型，``apiKey`` 字段**掩码**为 ``MASKED_KEY``。
- ``POST /api/custom-models`` / ``PUT /api/custom-models/{id}``：写入前经
  ``validate_model_config`` 校验 name/model_ids/endpoint/apiKey 完整性。
- ``DELETE /api/custom-models/{id}``：删除后清理人格对该档案的悬挂绑定。

W-ARCH-MODEL-PROFILE-CANONICAL-004：公开契约含 canonical 字段
（``model_ids`` / ``default_model_id`` / ``max_tokens``）及档案级 ``temperature``；
legacy ``modelId`` 仅由持久化 adapter 在读取历史 JSON 时内部消费。

设计约束：GET 必须返回掩码 apiKey（防泄漏）；**不**在 ``web_api/custom_models.py`` 内
直接读 ``DanmuApp._config`` 私有字段，统一经 ``app.config`` 公开 façade。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.config_store.crypto import (
    CustomModelApiKeyConflictError,
    assert_custom_model_api_key_aliases_consistent,
    canonicalize_custom_model_profile,
    custom_model_profile_id_type_error,
    duplicate_custom_model_profile_ids,
    new_custom_model_profile_id,
    read_custom_model_api_key,
    read_custom_model_profile_id,
)
from app.model_providers import (
    is_model_config_complete,
    normalize_endpoint,
    normalize_mode,
    validate_model_config,
)
from app.model_selection import catalog_display_name
from app.translations import tr

if TYPE_CHECKING:
    from main import DanmuApp

# 掩码：前端拿到的 apiKey 都是这个常量；原始 key 只在写入时使用，不对外暴露
MASKED_KEY = "********"
THINKING_EFFORT_VALUES = ("off", "none", "minimal", "low", "medium", "high", "xhigh", "max")
DEFAULT_TEMPERATURE = 0.8
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0


def _coerce_temperature(raw) -> float | None:
    """Parse temperature; ``0`` is valid. Returns None when missing or invalid."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            value = float(text)
        except (TypeError, ValueError):
            return None
    if value < TEMPERATURE_MIN or value > TEMPERATURE_MAX:
        return None
    return value


def _global_temperature_fallback(app: "DanmuApp | None") -> float:
    if app is not None:
        return app.config.get_float("temperature", DEFAULT_TEMPERATURE)
    return DEFAULT_TEMPERATURE


def _normalize_description(payload: dict, existing: dict | None) -> str:
    if "description" in payload:
        return (payload.get("description") or "").strip()
    if existing is not None:
        return (existing.get("description") or "").strip()
    return ""


def _normalize_model_names(
    payload: dict,
    existing: dict | None,
    model_ids: list[str],
    default_model_id: str,
    provider: str,
) -> dict[str, str]:
    raw = payload.get("model_names")
    if isinstance(raw, dict):
        incoming = {
            str(key).strip(): str(value).strip()
            for key, value in raw.items()
            if str(key).strip()
        }
    elif existing is not None and isinstance(existing.get("model_names"), dict):
        incoming = {
            str(key).strip(): str(value).strip()
            for key, value in existing["model_names"].items()
            if str(key).strip()
        }
    else:
        incoming = {}

    profile_name = (payload.get("name") or "").strip()
    if not profile_name and existing is not None:
        profile_name = (existing.get("name") or "").strip()

    result: dict[str, str] = {}
    for mid in model_ids:
        name = incoming.get(mid, "").strip()
        if not name and mid == default_model_id and profile_name:
            name = profile_name
        if not name:
            catalog_name = catalog_display_name(provider, mid)
            name = (catalog_name or mid).strip()
        result[mid] = name
    return result


def _derive_profile_name(
    model_names: dict[str, str],
    default_model_id: str,
    model_ids: list[str],
) -> str:
    if default_model_id and model_names.get(default_model_id):
        return model_names[default_model_id]
    if model_ids:
        first = model_ids[0]
        return model_names.get(first, first)
    return ""


def _mask_model(model: dict) -> dict:
    out = dict(model)
    if read_custom_model_api_key(out):
        out["apiKey"] = MASKED_KEY
    out.pop("api_key", None)
    return out


def _resolve_new_profile_id(existing: dict | None) -> str:
    """``profile_id`` 不可编辑：更新保留已有身份，创建分配新身份（忽略入参）。"""
    if existing is not None:
        existing_id = read_custom_model_profile_id(existing)
        if existing_id:
            return existing_id
    return new_custom_model_profile_id()


def _persona_binding_diagnostics(app: "DanmuApp", models: list[dict]) -> list[dict]:
    """列出无法解析的显式人格绑定（悬挂 / 歧义 / 不完整 / 模型被移除）。"""
    from app.persona_manager import describe_persona_model_binding

    raw = app.config.get("persona_model_bindings", "{}")
    try:
        bindings = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return [{"persona": "", "status": "unparsable", "profile_id": "", "model_id": ""}]
    if not isinstance(bindings, dict):
        return [{"persona": "", "status": "unparsable", "profile_id": "", "model_id": ""}]
    issues: list[dict] = []
    for persona, value in bindings.items():
        status = describe_persona_model_binding(value, models)
        if status["status"] in ("unbound", "ok"):
            continue
        issues.append({"persona": persona, **status})
    return issues


def custom_model_identity_diagnostics(app: "DanmuApp", models: list[dict]) -> dict:
    """档案身份 + 人格绑定引用的诊断（供 Web UI 提示重新选择，不含密钥）。"""
    profile_issues: list[dict] = []
    for index, model in enumerate(models):
        if custom_model_profile_id_type_error(model):
            profile_issues.append({"index": index, "code": "profile_id_type_invalid"})
        elif not read_custom_model_profile_id(model):
            profile_issues.append({"index": index, "code": "profile_id_missing"})
    for profile_id in sorted(duplicate_custom_model_profile_ids(models)):
        profile_issues.append({"code": "profile_id_duplicate", "profile_id": profile_id})
    return {
        "profiles": profile_issues,
        "persona_bindings": _persona_binding_diagnostics(app, models),
    }


def list_custom_models(app: "DanmuApp") -> dict[str, Any]:
    models = app.config.get_custom_models()
    return {
        "items": [
            {**_mask_model(m), "complete": is_model_config_complete(m)}
            for m in models
        ],
        "identity_diagnostics": custom_model_identity_diagnostics(app, models),
    }


def _resolve_api_key(payload: dict, existing: dict | None, app: "DanmuApp") -> str:
    try:
        assert_custom_model_api_key_aliases_consistent(payload)
    except CustomModelApiKeyConflictError as exc:
        raise ValueError(str(exc)) from None
    key = read_custom_model_api_key(payload)
    if key == MASKED_KEY:
        # Masked key means "keep stored key" only when editing an existing entry.
        return read_custom_model_api_key(existing)
    if key:
        return key
    return ""


def _locate_existing_model(
    models: list[dict],
    payload: dict,
    index: int,
    *,
    allow_model_id_fallback: bool = True,
) -> int | None:
    """定位 payload 对应的既有档案下标。

    W-AUDIT-MODEL-IDENTITY-001：主路径是调用方声明的 ``profile_id``；``index`` 仅作
    兼容定位（旧 UI / 直接调用）。按可重复的 ``default_model_id`` 反查只在没有
    profile_id 时兜底（迁移 / 探测等旧路径），并且**对重复项返回歧义（None）而不是
    首项**；写入路径会关闭该兜底（``allow_model_id_fallback=False``），避免以模型名
    建立第二套定位。
    """
    profile_id = str(payload.get("profile_id") or "").strip()
    if profile_id:
        for position, model in enumerate(models):
            if read_custom_model_profile_id(model) == profile_id:
                return position
        return None
    if 0 <= index < len(models):
        return index
    if not allow_model_id_fallback:
        return None
    model_id = (payload.get("default_model_id") or "").strip()
    if not model_id:
        return None
    matches = [
        position
        for position, model in enumerate(models)
        if (model.get("default_model_id") or "").strip() == model_id
    ]
    return matches[0] if len(matches) == 1 else None


def _find_existing_model(models: list[dict], payload: dict, index: int) -> dict | None:
    position = _locate_existing_model(models, payload, index)
    return models[position] if position is not None else None


def _normalize_supports_mic(payload: dict, existing: dict | None) -> bool:
    if "supportsMic" in payload:
        value = payload.get("supportsMic")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if existing is not None:
        return bool(existing.get("supportsMic"))
    return False


def _normalize_thinking_effort(payload: dict, existing: dict | None) -> str:
    """Normalize the per-model thinking selector to its four public values."""
    if "thinking_effort" in payload:
        raw = payload.get("thinking_effort")
    elif existing is not None:
        raw = existing.get("thinking_effort")
    else:
        raw = None
    value = str(raw or "off").strip().lower()
    return value if value in THINKING_EFFORT_VALUES else "off"


def _normalize_temperature(
    payload: dict,
    existing: dict | None,
    app: "DanmuApp | None" = None,
) -> float:
    """Normalize per-model temperature; ``0`` is valid and must not be treated as missing."""
    if "temperature" in payload:
        coerced = _coerce_temperature(payload.get("temperature"))
        if coerced is not None:
            return coerced
    elif existing is not None and "temperature" in existing:
        coerced = _coerce_temperature(existing.get("temperature"))
        if coerced is not None:
            return coerced
    return _global_temperature_fallback(app)


def _assert_canonical_http_payload(payload: dict, existing: dict | None) -> None:
    """Reject legacy-only HTTP bodies that omit canonical ``model_ids``."""
    if isinstance(payload.get("model_ids"), list):
        return
    if existing is not None and isinstance(existing.get("model_ids"), list):
        return
    raise ValueError(tr("custom_model.error_model_id"))


def _merge_payload_for_canonicalization(payload: dict, existing: dict | None) -> dict:
    """HTTP 写入场景：按 payload vs existing 优先级合并字段，再交 adapter canonical 化。

    W-004：payload 侧不接受 legacy modelId；无 model_ids list 时仅从 existing 继承。
    """
    base = dict(existing) if existing else {}

    raw_ids = payload.get("model_ids")
    if isinstance(raw_ids, list):
        model_ids = [str(mid).strip() for mid in raw_ids if str(mid or "").strip()]
    elif existing and isinstance(existing.get("model_ids"), list):
        model_ids = [
            str(mid).strip() for mid in existing["model_ids"] if str(mid or "").strip()
        ]
    else:
        model_ids = []

    raw_default = (payload.get("default_model_id") or "").strip()
    if raw_default:
        default_model_id = raw_default
    elif model_ids:
        default_model_id = model_ids[0]
    elif existing:
        default_model_id = (existing.get("default_model_id") or "").strip()
    else:
        default_model_id = ""

    raw_mt = payload.get("max_tokens")
    if raw_mt is not None:
        try:
            max_tokens = int(raw_mt)
        except (TypeError, ValueError):
            max_tokens = 512
    elif existing is not None:
        existing_raw = existing.get("max_tokens")
        if isinstance(existing_raw, int):
            max_tokens = existing_raw
        elif existing_raw is not None:
            try:
                max_tokens = int(existing_raw)
            except (TypeError, ValueError):
                max_tokens = 512
        else:
            max_tokens = 512
    else:
        max_tokens = 512

    base["model_ids"] = model_ids
    base["default_model_id"] = default_model_id
    base["max_tokens"] = max_tokens
    return base


def _normalize_payload(payload: dict, existing: dict | None = None, app: "DanmuApp | None" = None) -> dict:
    canonical = canonicalize_custom_model_profile(
        _merge_payload_for_canonicalization(payload, existing)
    )
    default_model_id = canonical["default_model_id"]
    model_ids = canonical["model_ids"]
    provider = (payload.get("provider") or (existing or {}).get("provider") or "").strip()
    model_names = _normalize_model_names(
        payload,
        existing,
        model_ids,
        default_model_id,
        provider,
    )
    profile_name = _derive_profile_name(model_names, default_model_id, model_ids)
    if not profile_name:
        profile_name = (payload.get("name") or "").strip()
    if not profile_name and existing is not None:
        profile_name = (existing.get("name") or "").strip()
    return {
        "name": profile_name,
        "profile_id": _resolve_new_profile_id(existing),
        "model_ids": model_ids,
        "model_names": model_names,
        "default_model_id": default_model_id,
        "max_tokens": canonical["max_tokens"],
        "mode": normalize_mode((payload.get("mode") or "doubao").strip()),
        "endpoint": normalize_endpoint((payload.get("endpoint") or "").strip()),
        "apiKey": _resolve_api_key(payload, existing, app),
        "description": _normalize_description(payload, existing),
        "provider": provider,
        "supportsMic": _normalize_supports_mic(payload, existing),
        "thinking_effort": _normalize_thinking_effort(payload, existing),
        "temperature": _normalize_temperature(payload, existing, app),
    }


def _normalized_provider(value) -> str:
    return str(value or "").strip().lower()


def _probe_identity_matches_profile(
    existing: dict | None, resolved: dict, requested_profile_id: str = ""
) -> bool:
    """W-AUDIT-PROBE-SECRET-001 / W-AUDIT-MODEL-IDENTITY-001：掩码 key 可恢复性的**唯一身份判据**。

    身份按不可变 ``profile_id`` 判定（不再依赖 index / 模型名 / 首档案回退形成的
    第二套身份）：

    - 必须先命中同一 ``existing`` 档案；调用方显式声明的 ``profile_id`` 与档案身份
      不一致时视为越界。
    - 归一化后的 endpoint / provider / mode 必须与档案已存凭据作用域全等（掩码 key
      表示"沿用同一目标"，不允许把它发给新的出站目标）。
    - 探测 model 必须在档案 ``model_ids`` allowlist 内。

    任一条件不成立即视为"越出作用域"，调用方按 ``probe_scope_violation`` 拒绝。
    """
    if existing is None:
        return False
    existing_profile_id = read_custom_model_profile_id(existing)
    if requested_profile_id and requested_profile_id != existing_profile_id:
        return False
    if normalize_endpoint(existing.get("endpoint", "")) != str(resolved.get("endpoint") or ""):
        return False
    if normalize_mode(existing.get("mode", "")) != str(resolved.get("mode") or ""):
        return False
    if _normalized_provider(existing.get("provider")) != _normalized_provider(
        resolved.get("provider")
    ):
        return False
    allowed = {
        str(mid).strip()
        for mid in (existing.get("model_ids") or [])
        if str(mid or "").strip()
    }
    probe_model = str(resolved.get("default_model_id") or "").strip()
    return bool(probe_model) and probe_model in allowed


def _requests_stored_key(payload: dict) -> bool:
    """True when the caller asks to reuse the stored key via the masked value."""
    return read_custom_model_api_key(payload) == MASKED_KEY


def _assert_probe_identity_within_scope(
    existing: dict | None, resolved: dict, requested_profile_id: str = ""
) -> None:
    """掩码 key 只有在同一档案作用域内才允许恢复，否则要求重新输入 key。"""
    if existing is None:
        # 没有可恢复的已存记录：解析出的 key 为空，probe 会返回 auth_missing。
        return
    if _probe_identity_matches_profile(existing, resolved, requested_profile_id):
        return
    from app.api_probe import ProbeScopeViolation

    raise ProbeScopeViolation(tr("custom_model.error_probe_scope_rekey"))


def resolve_probe_credentials(app: "DanmuApp", payload: dict, index: int = -1) -> dict:
    """Resolve probe credentials the same way as save (masked key + endpoint normalization).

    probe 入参 ``{profile_index, model_id?}``；``model_id`` 缺省时取档案的
    ``default_model_id``。

    W-AUDIT-PROBE-SECRET-001：掩码 key 表示"沿用档案 key"，因此只有身份命中
    同一档案（W-AUDIT-MODEL-IDENTITY-001：按 ``profile_id``）且
    endpoint/provider/mode/model 未越出已存作用域时才允许恢复；调用方替换
    endpoint、provider、mode 或选用档案外 model 时抛 ``ProbeScopeViolation``
    （路由层映射为 4xx），不会把已存密钥发往新目标。
    """
    models = list(app.config.get_custom_models())
    existing = _find_existing_model(models, payload, index)
    _assert_canonical_http_payload(payload, existing)
    resolved = _normalize_payload(payload, existing, app)
    probe_model_id = (payload.get("model_id") or "").strip()
    if probe_model_id:
        resolved["default_model_id"] = probe_model_id
    if _requests_stored_key(payload):
        requested_profile_id = str(payload.get("profile_id") or "").strip()
        _assert_probe_identity_within_scope(existing, resolved, requested_profile_id)
    return resolved


def probe_custom_model(app: "DanmuApp", payload: dict, index: int = -1, stage: str = "text") -> dict:
    """档案连接测试的单一入口（W-AUDIT-PROBE-PARITY-001）。

    先按 ``profile_id`` 解析出**不可变凭据/参数快照**（掩码 key 作用域校验仍在
    ``resolve_probe_credentials`` 内，越界抛 ``ProbeScopeViolation``），再把该快照
    交给 ``probe_connection`` 执行分阶段探测：``full`` 会跑
    local → auth_model → text → vision_stream → business_parse，其中
    ``vision_stream`` 复用正式视觉请求构造，``business_parse`` 复用正式 reply
    envelope / normalize 合同。probe 只读，不进入主链路或统计。

    结果额外携带 ``profile_id``，供 UI 把结果绑定到触发时的档案身份。
    """
    resolved = resolve_probe_credentials(app, payload, index)
    from app.api_probe import probe_connection

    result = probe_connection(
        str(resolved.get("endpoint") or ""),
        str(resolved.get("apiKey") or ""),
        str(resolved.get("default_model_id") or ""),
        str(resolved.get("mode") or ""),
        stage=stage or "text",
        profile_params={
            "temperature": resolved.get("temperature"),
            "thinking_effort": resolved.get("thinking_effort"),
            "max_tokens": resolved.get("max_tokens"),
        },
    ).to_dict()
    result["profile_id"] = str(resolved.get("profile_id") or "")
    return result


def create_custom_model(app: "DanmuApp", payload: dict) -> dict:
    _assert_canonical_http_payload(payload, existing=None)
    model = _normalize_payload(payload, app=app)
    errors = validate_model_config(model)
    if errors:
        raise ValueError(tr(errors[0]))

    models = list(app.config.get_custom_models())
    models.append(model)
    app.config.set_custom_models(models)
    app.config_changed.emit()
    return {"index": len(models) - 1, "item": _mask_model(model)}


def update_custom_model(app: "DanmuApp", index: int, payload: dict) -> dict:
    models = list(app.config.get_custom_models())
    position = _locate_existing_model(
        models, payload, index, allow_model_id_fallback=False
    )
    if position is None:
        profile_id = str(payload.get("profile_id") or "").strip()
        if profile_id:
            raise ValueError(tr("customModel.profileUnknown"))
        raise ValueError(tr("customModel.indexInvalid"))

    existing = models[position]
    _assert_canonical_http_payload(payload, existing)
    model = _normalize_payload(payload, existing, app)
    errors = validate_model_config(model)
    if errors:
        raise ValueError(tr(errors[0]))

    models[position] = model
    app.config.set_custom_models(models)
    app.config_changed.emit()
    return {"index": position, "item": _mask_model(model)}


def delete_custom_model(app: "DanmuApp", index: int) -> None:
    models = list(app.config.get_custom_models())
    if index < 0 or index >= len(models):
        raise ValueError(tr("customModel.indexInvalid"))

    removed = models.pop(index)
    app.config.set_custom_models(models)
    removed_profile_id = read_custom_model_profile_id(removed)
    removed_model_id = (removed.get("default_model_id") or "").strip()
    # W-AUDIT-MODEL-IDENTITY-001：只清理被删档案自身的引用；不再按可重复的
    # ``default_model_id`` 批量清理其他共享同一模型名的档案。
    from app.persona_manager import purge_model_bindings_for_profile

    purge_model_bindings_for_profile(
        app.config, removed_profile_id, removed_model_id, models
    )
    from app.virtual_host.model_config import purge_virtual_host_model_refs

    purge_virtual_host_model_refs(app.config, removed_profile_id, removed_model_id)
    app.config_changed.emit()
