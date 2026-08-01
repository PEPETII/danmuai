import pytest
from app.model_catalog import PLATFORM_CATALOGS
from app.providers.endpoint_resolver import API_FAMILY_OPENAI_RESPONSES, join_api_path
from app.providers.request_planner import GenerationRequest, plan_http_request
from app.providers.stream_parser import parser_id_for_api_family


def _catalog_cases():
    return tuple(
        (catalog.provider_id, catalog.models[0].id)
        for catalog in PLATFORM_CATALOGS
    )


@pytest.mark.parametrize("provider_id,model_id", _catalog_cases())
def test_each_catalog_platform_has_a_deterministic_offline_request_plan(provider_id, model_id):
    from app.providers.platform_registry import get_provider_definition

    definition = get_provider_definition(provider_id)
    request = GenerationRequest(
        purpose="visual_danmu",
        model_id=model_id,
        endpoint=definition.endpoint.default_url,
        api_key="sk-golden-contract",
        api_mode=definition.endpoint.api_mode,
        provider_id=provider_id,
        system_text="system contract",
        user_text="user contract",
        image_data_uri="data:image/png;base64,AAAA",
        max_output_tokens=64,
        stream=True,
        stream_options={"include_usage": True},
    )

    planned = plan_http_request(request)

    assert planned.provider_id == provider_id
    assert planned.model_id == model_id
    assert planned.api_family == definition.endpoint.api_family
    assert planned.url == join_api_path(definition.endpoint.default_url, planned.api_family)
    assert planned.parser_id == parser_id_for_api_family(planned.api_family)
    assert planned.json_body["model"] == model_id
    assert planned.json_body["stream"] is True
    assert "sk-golden-contract" not in repr(planned.json_body)
    assert "sk-golden-contract" not in repr(planned.url)

    if planned.api_family == API_FAMILY_OPENAI_RESPONSES:
        assert "input" in planned.json_body
        assert planned.json_body["max_output_tokens"] == 64
    else:
        assert "messages" in planned.json_body
        assert planned.json_body["messages"][-1]["role"] == "user"


def test_doubao_responses_golden_shape_uses_current_catalog_model():
    catalog = next(item for item in PLATFORM_CATALOGS if item.provider_id == "doubao")
    definition_endpoint = "https://ark.cn-beijing.volces.com/api/v3"
    planned = plan_http_request(
        GenerationRequest(
            "visual_danmu",
            catalog.models[0].id,
            definition_endpoint,
            "sk-golden-contract",
            api_mode="doubao",
            provider_id="doubao",
            user_text="text",
            image_data_uri="data:image/png;base64,AAAA",
            max_output_tokens=32,
            stream=True,
        )
    )

    assert planned.api_family == API_FAMILY_OPENAI_RESPONSES
    content = planned.json_body["input"][0]["content"]
    assert [part["type"] for part in content] == ["input_image", "input_text"]
    # ResponsesAdapter only injects this field for connection probes or an
    # explicit force_thinking_off request; visual requests must not infer it.
    assert "thinking" not in planned.json_body
    assert "stream_options" not in planned.json_body


def test_mimo_chat_golden_shape_uses_current_catalog_model():
    catalog = next(item for item in PLATFORM_CATALOGS if item.provider_id == "mimo")
    planned = plan_http_request(
        GenerationRequest(
            "visual_danmu",
            catalog.models[0].id,
            "https://api.xiaomimimo.com/v1",
            "sk-golden-contract",
            api_mode="openai-compatible",
            provider_id="mimo",
            user_text="text",
            image_data_uri="data:image/png;base64,AAAA",
            audio_data_uri="data:audio/wav;base64,AAAA",
            max_output_tokens=32,
            stream=True,
            stream_options={"include_usage": True},
        )
    )

    content = planned.json_body["messages"][-1]["content"]
    assert [part["type"] for part in content] == ["image_url", "text", "input_audio"]
    assert planned.json_body["max_completion_tokens"] == 32
    assert planned.json_body["thinking"] == {"type": "disabled"}
    assert "max_tokens" not in planned.json_body
    assert "stream_options" not in planned.json_body
