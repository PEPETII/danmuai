"""`/api/session` 鉴权策略。

bug-audit/bug-03.md 缺陷 1：`/api/session` 端点未鉴权即返回 Bearer Token，
任意本机进程 `curl 127.0.0.1:18765/api/session` 即可拿到控制台写接口的 Token。

设计（与 frontend transport.js::refreshSession() 启动握手兼容）：

1. **强校验路径**：携带正确 `Authorization: Bearer <token>` 时直接放行；
   任何 Origin / 来源均可 — 已掌握 token 的调用方属于已鉴权。
2. **同源握手路径**：控制台页面同源 loopback fetch（Origin 与 Host 都是
   127.0.0.1/localhost）启动时，前端 `refreshSession()` 尚未持有 token。
   允许 `Origin` 头与 Host 头同为 loopback 域时免 token 返回 token。
3. **其他情况**：缺头、Origin 不匹配、非 loopback、错误 token → 拒绝。

无 Origin/Referer 头的调用（curl / 第三方进程）一律 401；非 loopback 来源
即便有 Origin 也 401；正确 token 不受来源限制。

调用方：`app/web_console_runtime.py::read_console_session`。
"""

from __future__ import annotations

from fastapi import HTTPException

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _normalize_host(value: str | None) -> str:
    """Strip optional :port and lower-case for loopback comparison."""
    if not value:
        return ""
    raw = value.strip().lower()
    if raw.startswith("["):
        # IPv6 form: [::1]:18765
        end = raw.find("]")
        if end != -1:
            return raw[1:end]
    # Strip port suffix if present
    if ":" in raw and not raw.startswith(":"):
        return raw.rsplit(":", 1)[0]
    return raw


def is_loopback_host(host: str | None) -> bool:
    """Return True if host header value refers to a loopback address."""
    return _normalize_host(host) in _LOOPBACK_HOSTS


def enforce_session_authorization(
    *,
    authorization: str | None,
    origin: str | None,
    referer: str | None,
    host: str | None,
    expected_token: str,
) -> None:
    """校验 `/api/session` 的访问来源；命中拒绝条件抛 HTTPException。

    - 携带正确 `Authorization: Bearer <token>`：放行
    - 同源 loopback（Origin 或 Referer 与 Host 同为 loopback）：放行
    - 其他：401（缺/格式错）或 403（来源不匹配 / token 错误）
    """
    if expected_token:
        auth = (authorization or "").strip()
        if auth.startswith("Bearer "):
            presented = auth[len("Bearer ") :].strip()
            if presented == expected_token:
                return
            raise HTTPException(status_code=403, detail="令牌无效")
        if auth:
            # 头存在但非 Bearer → 视作错误 token 来源
            raise HTTPException(status_code=403, detail="令牌格式错误")

    # 走到这里说明未携带正确 token；仅在同源 loopback 时才放行
    request_host = _normalize_host(host)
    if not request_host or request_host not in _LOOPBACK_HOSTS:
        # 非 loopback：必须带 token
        raise HTTPException(status_code=401, detail="需要登录令牌")

    if not (origin or referer):
        # curl/无头调用：拒绝
        raise HTTPException(status_code=401, detail="需要登录令牌")

    # 校验 Origin / Referer 是否与请求 host 同源 loopback
    candidate = origin or referer or ""
    candidate = candidate.strip().lower()
    if not candidate.startswith(("http://", "https://")):
        raise HTTPException(status_code=401, detail="来源不合法")

    # 提取 Origin/Referer 中的 host 部分
    try:
        # 简易解析：scheme://host[:port][/...]
        rest = candidate.split("://", 1)[1]
        origin_host = rest.split("/", 1)[0]
        origin_host = origin_host.split("@")[-1]  # 处理 userinfo
        origin_host = _normalize_host(origin_host)
    except (IndexError, ValueError):
        raise HTTPException(status_code=401, detail="来源不合法")

    if origin_host != request_host:
        raise HTTPException(status_code=403, detail="来源不匹配")
