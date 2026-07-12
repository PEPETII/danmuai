"""Web 写路由共用的主线程 invoke 包装。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from fastapi import HTTPException

from app.errors import AppError
from app.translations import tr
from app.web_console import MainThreadInvokeTimeout

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge

logger = logging.getLogger(__name__)


def make_invoke_main(bridge: "WebConsoleBridge") -> Callable:
    """写 API：经 WebConsoleBridge.invoke_on_main 在主线程执行。"""

    def invoke_main(fn, *args, **kwargs):
        try:
            return bridge.invoke_on_main(fn, *args, **kwargs)
        except MainThreadInvokeTimeout as exc:
            logger.error(
                "invoke_on_main timed out for %r after %.1fs",
                fn,
                exc.timeout_sec,
            )
            raise HTTPException(
                status_code=504,
                detail={"ok": False, "error": "main_thread_timeout", "detail": tr("common.mainThreadTimeout")},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AppError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("invoke_on_main failed for %r", fn)
            raise HTTPException(status_code=500, detail="internal error") from exc

    return invoke_main
