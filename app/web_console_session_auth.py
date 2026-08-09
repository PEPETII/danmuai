"""Session bootstrap and Bearer authorization for the local Web console.

Loopback binding limits the network surface, but ``Host``, ``Origin`` and
``Referer`` are request headers and therefore are not an identity proof for a
same-machine process.  The desktop launcher instead puts a short-lived,
one-time secret in the URL fragment.  The browser exchanges it for the normal
in-memory Bearer token over a request header; fragments are not sent in HTTP
requests or server access logs.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable

from fastapi import HTTPException


class SessionBootstrapStore:
    """Bounded, expiring, one-time secrets used by the desktop launcher."""

    def __init__(self, *, ttl_sec: float = 60.0, max_entries: int = 8) -> None:
        self._ttl_sec = max(1.0, float(ttl_sec))
        self._max_entries = max(1, int(max_entries))
        self._lock = threading.Lock()
        self._secrets: dict[str, float] = {}

    def _purge_expired(self, now: float) -> None:
        expired = [value for value, expires_at in self._secrets.items() if expires_at <= now]
        for value in expired:
            self._secrets.pop(value, None)

    def issue(self) -> str:
        value = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._purge_expired(now)
            while len(self._secrets) >= self._max_entries:
                oldest = next(iter(self._secrets))
                self._secrets.pop(oldest, None)
            self._secrets[value] = now + self._ttl_sec
        return value

    def consume(self, presented: str | None) -> bool:
        candidate = (presented or "").strip()
        if not candidate:
            return False
        now = time.monotonic()
        with self._lock:
            self._purge_expired(now)
            matched: str | None = None
            for value in self._secrets:
                if secrets.compare_digest(candidate, value):
                    matched = value
                    break
            if matched is None:
                return False
            del self._secrets[matched]
            return True


def enforce_session_authorization(
    *,
    authorization: str | None,
    expected_token: str,
    bootstrap: str | None = None,
    consume_bootstrap_secret: Callable[[str], bool] | None = None,
    # Kept as ignored compatibility parameters for older test/facade callers.
    # They are deliberately never inspected as an identity signal.
    origin: str | None = None,
    referer: str | None = None,
    host: str | None = None,
) -> None:
    """Authorize ``/api/session`` using Bearer or a one-time bootstrap secret.

    A missing credential is 401.  A malformed/invalid credential is 403.
    ``Host``/``Origin``/``Referer`` are intentionally ignored: callers cannot
    turn spoofable HTTP headers into a session token.
    """
    del origin, referer, host

    auth = (authorization or "").strip()
    if auth:
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=403, detail="令牌格式错误")
        presented = auth[len("Bearer ") :].strip()
        if expected_token and secrets.compare_digest(presented, expected_token):
            return
        raise HTTPException(status_code=403, detail="令牌无效")

    if bootstrap is not None:
        if consume_bootstrap_secret is not None and consume_bootstrap_secret(bootstrap):
            return
        raise HTTPException(status_code=403, detail="启动握手无效或已过期")

    raise HTTPException(status_code=401, detail="需要登录令牌")
