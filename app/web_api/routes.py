"""扩展 FastAPI 路由：协议适配层，委托 DanmuApp 公开 façade 与 web_api 子模块。



线程模型：

- GET 路由：HTTP 线程直接执行（只读快照）

- PUT /api/config：在 web_console_runtime.py 经 save_config_via_bridge（pyqtSignal +

  threading.Event.wait）同步到主线程；**不是**本文件 invoke_main

- 其他写路由：经 bridge.invoke_on_main（QueuedConnection + Event.wait）同步到主线程，

  超时时返回 504（见 MainThreadInvokeTimeout）



边界约束：必须使用 DanmuApp 公开 façade，禁止访问内部私有属性：

- build_status_snapshot() / build_diagnostic_snapshot()

- apply_web_config_payload() / start() / stop()

- get/set_persona, get/set_custom_models, probe_model_config 等



/api/status 在 web_console 内注册，本文件不重复。

/api/diagnostics 在 diagnostics_routes 注册，须 build_diagnostic_snapshot()，与 status 分离。

写操作需 Bearer；须经 bridge.invoke_on_main（勿在 HTTP 线程直接写 Config / emit config_changed）。

"""



from __future__ import annotations



from typing import TYPE_CHECKING, Callable



from app.web_api import ai_butler as ai_butler_api

from app.web_api import font_registry as font_registry_api

from app.web_api import providers as providers_api

from app.web_api.capture_region_routes import register_capture_region_routes

from app.web_api.custom_models_routes import register_custom_models_routes

from app.web_api.danmu_pool_routes import register_danmu_pool_routes

from app.web_api.danmu_read_routes import register_danmu_read_routes

from app.web_api.diagnostics_routes import register_diagnostics_routes

from app.web_api.knowledge_routes import register_knowledge_routes

from app.web_api.meme_barrage_routes import register_meme_barrage_routes

from app.web_api.mic_routes import register_mic_routes

from app.web_api.misc_config_routes import register_misc_config_routes

from app.web_api.persona_routes import register_persona_routes

from app.web_api.pet_routes import register_pet_routes

from app.web_api.route_invoke import make_invoke_main

from app.web_api.update_routes import register_update_routes



if TYPE_CHECKING:

    from app.web_console import WebConsoleBridge



__all__ = [
    "register_web_routes",
]





def register_web_routes(app, bridge: "WebConsoleBridge", check_token: Callable) -> None:

    invoke_main = make_invoke_main(bridge)



    providers_api.register_provider_routes(app)

    ai_butler_api.register_ai_butler_route(app, bridge, check_token)



    register_diagnostics_routes(app, bridge, check_token)

    register_misc_config_routes(app, bridge, check_token, invoke_main)

    register_update_routes(app, check_token)

    register_meme_barrage_routes(app, bridge, check_token, invoke_main)

    register_danmu_read_routes(app, bridge, check_token, invoke_main)

    register_custom_models_routes(app, bridge, check_token, invoke_main)

    register_mic_routes(app, bridge, check_token, invoke_main)

    register_capture_region_routes(app, bridge, check_token)



    register_persona_routes(app, bridge, check_token, invoke_main)

    register_danmu_pool_routes(app, bridge, check_token, invoke_main)

    register_pet_routes(app, bridge, check_token, invoke_main)

    register_knowledge_routes(app, bridge, check_token, invoke_main)



    font_registry_api.register_font_registry_routes(app, bridge, check_token)


