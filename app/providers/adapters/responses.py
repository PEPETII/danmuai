"""Responses API request adapter."""

from __future__ import annotations

from app.providers.adapters.default_openai import DefaultOpenAIAdapter
from app.providers.capabilities import ProviderCapabilities, temperature_allowed_for_request


class ResponsesAdapter(DefaultOpenAIAdapter):
    def build_body(self, request, caps: ProviderCapabilities, warnings: list[str] | None = None) -> dict:
        content: list[dict] = []
        if request.image_data_uri:
            content.append({"type": "input_image", "image_url": request.image_data_uri})
        if request.user_text:
            content.append({"type": "input_text", "text": request.user_text})
        if request.audio_data_uri:
            content.append({"type": "input_audio", "audio_url": request.audio_data_uri})
        if not content and request.purpose == "connection_probe":
            content = [{"type": "input_text", "text": request.user_text or "ping"}]
        data = {
            "model": request.model_id,
            "input": [{"type": "message", "role": "user", "content": content}],
            "stream": request.stream,
        }
        if request.system_text:
            data["instructions"] = request.system_text
        if request.max_output_tokens and request.max_output_tokens > 0:
            data["max_output_tokens"] = request.max_output_tokens
        self.add_optional_fields(data, request=request, caps=caps)
        return data

    def add_optional_fields(self, data: dict, *, request, caps: ProviderCapabilities) -> None:
        if (
            request.temperature is not None
            and request.temperature >= 0
            and temperature_allowed_for_request(caps, request.reasoning_effort)
        ):
            data["temperature"] = request.temperature
        if request.reasoning_effort is not None and caps.thinking_param_style in (
            "reasoning_effort_flat",
            "reasoning_object",
            "always_on",
        ):
            data["reasoning"] = {"effort": request.reasoning_effort}
        preference = request.response_format or request.structured_output
        if preference is not None and caps.structured_output is True:
            data["text"] = {"format": preference}

    def supports_endpoint(self, endpoint: str) -> bool:
        return True
