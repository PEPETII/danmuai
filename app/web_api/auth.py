"""Web API 鉴权装饰器：封装 ``check_token`` 闭包，避免路由处理函数内联重复调用。

``check_token`` 契约：``Callable[[str | None], None]``，失败时抛出 ``HTTPException``（不返回值）。
"""

from __future__ import annotations

import inspect
from functools import wraps
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


def require_auth(
    check_token: Callable[[str | None], None],
    *,
    param: str = "authorization",
) -> Callable[[F], F]:
    """在 handler 执行前调用 ``check_token(kwargs[param])``。"""

    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                check_token(kwargs.get(param))
                return await func(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            check_token(kwargs.get(param))
            return func(*args, **kwargs)

        return sync_wrapper  # type: ignore[return-value]

    return decorator


def require_auth_query(
    check_token: Callable[[str | None], None],
    *,
    param: str = "token",
) -> Callable[[F], F]:
    """SSE 等无法带 Header 的路由：从 query 参数鉴权。"""
    return require_auth(check_token, param=param)
