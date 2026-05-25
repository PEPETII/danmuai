"""Register extended FastAPI routes on the web console app."""

from typing import TYPE_CHECKING, Callable
from urllib.parse import unquote

from fastapi import File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from app.image_compress import compress_image_bytes
from app.web_api import custom_models as cm_api
from app.web_api import persona as persona_api

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


def register_preview_compress_route(app, check_token: Callable) -> None:
    """Module-level registration so UploadFile resolves under Python 3.14 + Pydantic v2."""

    @app.post("/api/preview/compress")
    async def preview_compress(
        file: UploadFile = File(...),
        max_width: int = Form(768),
        quality: int = Form(85),
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片太大了，请换一张小一点的~")
        try:
            return compress_image_bytes(data, max_width=max_width, quality=quality)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"小助手读不懂这张图：{exc}") from exc


def register_web_routes(app, bridge: "WebConsoleBridge", check_token: Callable) -> None:
    register_preview_compress_route(app, check_token)

    class PersonaCreatePayload(BaseModel):
        name: str

    class PersonaSavePayload(BaseModel):
        system_custom: str = ""
        user_pt: str = ""

    class PersonaRollbackPayload(BaseModel):
        version: int

    class CustomModelPayload(BaseModel):
        name: str = ""
        modelId: str = ""
        mode: str = "doubao"
        endpoint: str = ""
        apiKey: str = ""
        description: str = ""
        provider: str = ""

    class ActivePersonaePayload(BaseModel):
        active: list[str]

    class MicTestPayload(BaseModel):
        duration_sec: float = 3.0
        send_to_ai: bool = False

    class ProbePayload(BaseModel):
        api_endpoint: str = ""
        api_key: str = ""
        model: str = ""
        api_mode: str = "doubao"

    def _danmu():
        return bridge.danmu_app

    def _run_main(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/personae/{name}/template")
    def get_persona_template(name: str):
        return _run_main(persona_api.get_template_detail, _danmu(), unquote(name))

    @app.get("/api/personae/{name}/versions")
    def get_persona_versions(name: str):
        return _run_main(persona_api.list_versions, _danmu(), unquote(name))

    @app.put("/api/personae/{name}/template")
    def put_persona_template(
        name: str,
        body: PersonaSavePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        _run_main(
            persona_api.save_template,
            _danmu(),
            unquote(name),
            body.system_custom,
            body.user_pt,
        )
        return {"ok": True}

    @app.post("/api/personae/{name}/rollback")
    def post_persona_rollback(name: str, body: PersonaRollbackPayload):
        return _run_main(persona_api.rollback_preview, _danmu(), unquote(name), body.version)

    @app.post("/api/personae")
    def post_persona(body: PersonaCreatePayload, authorization: str | None = Header(default=None)):
        check_token(authorization)
        return _run_main(persona_api.create_persona, _danmu(), body.name)

    @app.delete("/api/personae/{name}")
    def delete_persona(name: str, authorization: str | None = Header(default=None)):
        check_token(authorization)
        _run_main(persona_api.delete_persona, _danmu(), unquote(name))
        return {"ok": True}

    @app.post("/api/personae/{name}/restore")
    def restore_persona(name: str, authorization: str | None = Header(default=None)):
        check_token(authorization)
        return _run_main(persona_api.restore_builtin_default, _danmu(), unquote(name))

    @app.put("/api/personae/active")
    def put_active_personae(
        body: ActivePersonaePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        if not body.active:
            raise HTTPException(status_code=400, detail="请至少选择一个人格")
        _danmu().personae.set_active(body.active)
        _danmu().config_changed.emit()
        return {"ok": True}

    @app.get("/api/custom-models")
    def get_custom_models():
        return cm_api.list_custom_models(_danmu())

    @app.post("/api/custom-models")
    def post_custom_model(
        body: CustomModelPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _run_main(cm_api.create_custom_model, _danmu(), body.model_dump())

    @app.put("/api/custom-models/{index}")
    def put_custom_model(
        index: int,
        body: CustomModelPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _run_main(cm_api.update_custom_model, _danmu(), index, body.model_dump())

    @app.delete("/api/custom-models/{index}")
    def delete_custom_model_route(
        index: int,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        _run_main(cm_api.delete_custom_model, _danmu(), index)
        return {"ok": True}

    @app.post("/api/custom-models/{index}/default")
    def set_default_custom_model(
        index: int,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _run_main(cm_api.set_default_custom_model, _danmu(), index)

    @app.post("/api/probe")
    def probe_api_connection(
        body: ProbePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        from app.api_probe import probe_connection

        config = _danmu().config
        api_key = body.api_key or ""
        if api_key == cm_api.MASKED_KEY:
            api_key = config.get_api_key()
        result = probe_connection(
            body.api_endpoint or config.get("api_endpoint", ""),
            api_key,
            body.model or config.get("model", ""),
            body.api_mode or config.get("api_mode", "doubao"),
        )
        return {
            "ok": result.ok,
            "message": result.message,
            "status_code": result.status_code,
        }

    @app.post("/api/custom-models/probe")
    def probe_custom_model(
        body: CustomModelPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        from app.api_probe import probe_connection

        config = _danmu().config
        payload = body.model_dump()
        api_key = payload.get("apiKey") or ""
        if api_key == cm_api.MASKED_KEY:
            api_key = config.get_api_key()
        result = probe_connection(
            payload.get("endpoint") or config.get("api_endpoint", ""),
            api_key,
            payload.get("modelId") or config.get("model", ""),
            payload.get("mode") or config.get("api_mode", "doubao"),
        )
        return {
            "ok": result.ok,
            "message": result.message,
            "status_code": result.status_code,
        }

    def _mic_test_response(body: MicTestPayload):
        from dataclasses import asdict

        danmu_app = _danmu()
        if body.send_to_ai:
            from app.mic_test_send import run_mic_test_send

            resolved = danmu_app.ai_worker._resolve_request_credentials()
            active_model = resolved[2] if resolved else ""
            result = run_mic_test_send(danmu_app, body.duration_sec)
            danmu_app.logger.info(
                "mic test send "
                f"model={active_model or 'unknown'} "
                f"ok={result.ok} level={result.level} pcm_bytes={result.pcm_bytes} "
                f"rms={result.rms} audio_attached={result.audio_attached} "
                f"input_tokens={result.input_tokens} output_tokens={result.output_tokens} "
                f"error={result.error or 'none'}"
            )
            return asdict(result)

        from app.mic_service import mic_mode_enabled
        from app.mic_test import run_mic_test

        keep_running = mic_mode_enabled(danmu_app.config)
        result = run_mic_test(
            danmu_app._mic_service,
            body.duration_sec,
            keep_running=keep_running,
        )
        danmu_app.logger.info(
            "mic test "
            f"ok={result.ok} level={result.level} pcm_bytes={result.pcm_bytes} "
            f"rms={result.rms} peak={result.peak} wav_ok={result.wav_ok} "
            f"device={result.default_input or 'unknown'}"
        )
        return asdict(result)

    @app.post("/api/mic/test")
    def mic_test(
        body: MicTestPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _mic_test_response(body)

    @app.post("/api/mic/test-send")
    def mic_test_send(
        body: MicTestPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        body = MicTestPayload(duration_sec=body.duration_sec, send_to_ai=True)
        return _mic_test_response(body)
