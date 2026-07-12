"""Model catalog enrichment and Doubao data tests."""

from app.model_catalog import (
    DASHSCOPE_MODELS,
    DASHSCOPE_INTL_MODELS,
    DOUBAO_MODELS,
    FIREWORKS_MODELS,
    GOOGLE_GEMINI_MODELS,
    MIMO_MODELS,
    MISTRAL_MODELS,
    OPENAI_MODELS,
    SILICONFLOW_MODELS,
    TOGETHER_MODELS,
    XAI_MODELS,
    ZAI_MODELS,
    catalog_model_ids,
    catalog_model_supports_mic,
    catalog_model_supports_thinking_toggle,
    catalog_provider_ids_for_model,
    default_catalog_model_id,
    enrich_platform_models,
    get_catalog_for_provider,
    get_thinking_mode_for_model,
    is_catalog_model_for_provider,
    list_platform_catalogs,
)


def test_doubao_cheapest_is_flash():
    enriched = enrich_platform_models(DOUBAO_MODELS)
    cheapest = [m for m in enriched if m["cheapest"]]
    assert len(cheapest) == 1
    assert cheapest[0]["id"] == "doubao-seed-1-6-flash-250828"
    assert cheapest[0]["price"]["input"] == 0.15


def test_catalog_model_supports_mic():
    assert catalog_model_supports_mic("doubao-seed-2-0-mini-260428")
    assert catalog_model_supports_mic("mimo-v2.5")
    assert not catalog_model_supports_mic("doubao-seed-1-6-flash-250828")
    assert not catalog_model_supports_mic("unknown-model")


def test_enriched_catalog_includes_thinking_metadata():
    enriched = enrich_platform_models(DASHSCOPE_MODELS, provider_id="dashscope")
    by_id = {m["id"]: m for m in enriched}
    assert by_id["qwen3-vl-flash"]["thinking_mode"] == "hybrid"
    assert by_id["qwen3-vl-flash"]["supports_thinking_toggle"] is True
    assert by_id["qwen-vl-max"]["thinking_mode"] == "off"
    assert catalog_model_supports_thinking_toggle("qwen3-vl-flash")
    assert not catalog_model_supports_thinking_toggle("qwen-vl-max")
    assert get_thinking_mode_for_model("unknown") == "off"


def test_doubao_supports_mic_from_audio_price():
    enriched = enrich_platform_models(DOUBAO_MODELS)
    by_id = {m["id"]: m for m in enriched}
    assert by_id["doubao-seed-2-0-pro-260215"]["supports_mic"] is True
    assert by_id["doubao-seed-2-0-lite-260428"]["supports_mic"] is True
    assert by_id["doubao-seed-2-0-mini-260428"]["supports_mic"] is True
    assert by_id["doubao-seed-1-6-flash-250828"]["supports_mic"] is False


def test_cheapest_tie_break_first_in_catalog_order():
    from app.model_catalog import CatalogModel, ModelPrice

    models = (
        CatalogModel("A", "model-a", ModelPrice(input=1.0, output=1.0)),
        CatalogModel("B", "model-b", ModelPrice(input=1.0, output=2.0)),
    )
    enriched = enrich_platform_models(models)
    assert sum(1 for m in enriched if m["cheapest"]) == 1
    assert enriched[0]["cheapest"] is True
    assert enriched[1]["cheapest"] is False


def _platform_by_id(platforms, platform_id):
    return next(p for p in platforms if p["platform_id"] == platform_id)


def test_list_platform_catalogs_has_vision_platforms():
    platforms = list_platform_catalogs()
    assert len(platforms) == 18
    international = {
        "openai",
        "google_gemini",
        "xai",
        "mistral",
        "together",
        "fireworks",
        "dashscope_intl",
        "openrouter",
        "zai",
    }
    for platform in platforms:
        assert platform["region"] in ("china", "international", "global")
        if platform["provider_id"] in international:
            assert platform["region"] == "international"
        elif platform["provider_id"] == "mimo":
            assert platform["region"] == "global"
        elif platform["provider_id"] == "doubao":
            assert platform["region"] == "china"
    doubao = _platform_by_id(platforms, "doubao")
    assert doubao["provider_id"] == "doubao"
    assert len(doubao["models"]) == 7
    dashscope = _platform_by_id(platforms, "dashscope")
    assert dashscope["provider_id"] == "dashscope"
    assert dashscope["platform_label"] == "DashScope"
    assert len(dashscope["models"]) == 10
    openai = _platform_by_id(platforms, "openai")
    assert openai["provider_id"] == "openai"
    assert len(openai["models"]) == 5
    gemini = _platform_by_id(platforms, "google-gemini")
    assert gemini["provider_id"] == "google_gemini"
    assert len(gemini["models"]) == 5
    xai = _platform_by_id(platforms, "xai")
    assert xai["provider_id"] == "xai"
    assert len(xai["models"]) == 5
    mistral = _platform_by_id(platforms, "mistral")
    assert mistral["provider_id"] == "mistral"
    assert len(mistral["models"]) == 5
    together = _platform_by_id(platforms, "together")
    assert together["provider_id"] == "together"
    assert len(together["models"]) == 5
    fireworks = _platform_by_id(platforms, "fireworks")
    assert fireworks["provider_id"] == "fireworks"
    assert len(fireworks["models"]) == 5
    dashscope_intl = _platform_by_id(platforms, "dashscope-intl")
    assert dashscope_intl["provider_id"] == "dashscope_intl"
    assert len(dashscope_intl["models"]) == 5
    siliconflow = _platform_by_id(platforms, "siliconflow")
    assert siliconflow["provider_id"] == "siliconflow"
    assert siliconflow["platform_label"] == "硅基流动"
    assert len(siliconflow["models"]) == 10
    mimo = _platform_by_id(platforms, "mimo")
    assert mimo["provider_id"] == "mimo"
    assert mimo["platform_label"] == "小米 MiMo"
    assert len(mimo["models"]) == 1
    zai = _platform_by_id(platforms, "zai")
    assert zai["provider_id"] == "zai"
    assert zai["platform_label"] == "Z.AI / 智谱"
    assert len(zai["models"]) == 2
    all_models = (
        doubao["models"]
        + dashscope["models"]
        + openai["models"]
        + gemini["models"]
        + xai["models"]
        + mistral["models"]
        + together["models"]
        + fireworks["models"]
        + dashscope_intl["models"]
        + siliconflow["models"]
        + mimo["models"]
        + zai["models"]
    )
    for model in all_models:
        assert "name" in model
        assert "id" in model
        assert "price" in model
        assert "currency" in model["price"]
        assert "modality" in model
        assert model["supports_vision"] is True
        assert model["main_flow_recommended"] is True
        assert "cheapest" in model
        assert "supports_mic" in model


def test_dashscope_cheapest_is_qwen3_vl_flash():
    enriched = enrich_platform_models(DASHSCOPE_MODELS)
    cheapest = [m for m in enriched if m["cheapest"]]
    assert len(cheapest) == 1
    assert cheapest[0]["id"] == "qwen3-vl-flash"
    assert cheapest[0]["price"]["input"] == 0.15


def test_dashscope_catalog_has_no_mic_flagged_models():
    """Omni models removed from catalog (W-MODEL-CATALOG-PROBE-001); VL-only list."""
    enriched = enrich_platform_models(DASHSCOPE_MODELS)
    assert all(not m["supports_mic"] for m in enriched)


def test_international_catalog_presets_have_five_models_each():
    expected = {
        "openai": (OPENAI_MODELS, {"gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-4.1"}),
        "google_gemini": (
            GOOGLE_GEMINI_MODELS,
            {
                "gemini-3.5-flash",
                "gemini-3.1-pro",
                "gemini-3-flash",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
            },
        ),
        "xai": (
            XAI_MODELS,
            {
                "grok-4.3",
                "grok-4.20-multi-agent-0309",
                "grok-4.20-0309-reasoning",
                "grok-4.20-0309-non-reasoning",
                "grok-build-0.1",
            },
        ),
        "mistral": (
            MISTRAL_MODELS,
            {
                "mistral-large-2512",
                "mistral-medium-2508",
                "mistral-small-2506",
                "ministral-14b-2512",
                "ministral-8b-2512",
            },
        ),
        "together": (
            TOGETHER_MODELS,
            {
                "Qwen/Qwen3.5-9B",
                "google/gemma-4-31B-it",
                "MiniMaxAI/MiniMax-M3",
                "moonshotai/Kimi-K2.7-Code",
                "moonshotai/Kimi-K2.6",
            },
        ),
        "fireworks": (
            FIREWORKS_MODELS,
            {
                "accounts/fireworks/models/kimi-k2p6",
                "accounts/fireworks/models/qwen3p6-plus",
                "accounts/fireworks/models/step-3p7-flash-nvfp4",
                "accounts/fireworks/models/gemma-4-31b-it",
                "accounts/fireworks/models/qwen3-omni-30b-a3b-instruct",
            },
        ),
        "dashscope_intl": (
            DASHSCOPE_INTL_MODELS,
            {"qwen3-vl-flash", "qwen3-vl-plus", "qwen-vl-plus", "qwen-vl-max", "qwen3.5-omni-plus"},
        ),
    }
    for provider_id, (models, ids) in expected.items():
        assert len(models) == 5
        assert {m.id for m in models} == ids
        catalog = get_catalog_for_provider(provider_id)
        assert catalog is not None
        assert len(catalog["models"]) == 5
        assert catalog["region"] == "international"


def test_get_catalog_for_provider_doubao():
    catalog = get_catalog_for_provider("doubao")
    assert catalog is not None
    assert catalog["platform_label"] == "Doubao"


def test_get_catalog_for_provider_dashscope():
    catalog = get_catalog_for_provider("dashscope")
    assert catalog is not None
    assert catalog["platform_label"] == "DashScope"
    assert len(catalog["models"]) == 10


def test_siliconflow_cheapest_is_qwen3_vl_8b_instruct():
    enriched = enrich_platform_models(SILICONFLOW_MODELS)
    cheapest = [m for m in enriched if m["cheapest"]]
    assert len(cheapest) == 1
    assert cheapest[0]["id"] == "Qwen/Qwen3-VL-8B-Instruct"
    assert cheapest[0]["price"]["input"] == 0.5


def test_siliconflow_no_mic_without_audio_price():
    enriched = enrich_platform_models(SILICONFLOW_MODELS)
    assert all(not m["supports_mic"] for m in enriched)


def test_get_catalog_for_provider_siliconflow():
    catalog = get_catalog_for_provider("siliconflow")
    assert catalog is not None
    assert catalog["platform_label"] == "硅基流动"
    assert len(catalog["models"]) == 10


def test_doubao_catalog_uses_current_official_ids():
    ids = {m.id for m in DOUBAO_MODELS}
    assert "doubao-seed-2-0-pro-260215" in ids
    assert "doubao-seed-1-6-vision-250815" in ids
    assert "doubao-seed-2-0-pro-260428" not in ids
    assert "doubao-seed-1-6-vision-250615" not in ids


def test_dashscope_catalog_excludes_qwen3_vl_max():
    ids = {m.id for m in DASHSCOPE_MODELS}
    assert "qwen3-vl-max" not in ids
    assert "qwen-vl-max" in ids


def test_siliconflow_catalog_excludes_deprecated_glm_4_6v():
    ids = {m.id for m in SILICONFLOW_MODELS}
    assert "zai-org/GLM-4.6V" not in ids


def test_mimo_cheapest_is_v2_5():
    enriched = enrich_platform_models(MIMO_MODELS)
    cheapest = [m for m in enriched if m["cheapest"]]
    assert len(cheapest) == 1
    assert cheapest[0]["id"] == "mimo-v2.5"


def test_zai_cheapest_is_glm_4_5v():
    enriched = enrich_platform_models(ZAI_MODELS)
    cheapest = [m for m in enriched if m["cheapest"]]
    assert len(cheapest) == 1
    assert cheapest[0]["id"] == "glm-4.6v"


def test_get_catalog_for_provider_mimo():
    catalog = get_catalog_for_provider("mimo")
    assert catalog is not None
    assert catalog["platform_label"] == "小米 MiMo"
    assert {m["id"] for m in catalog["models"]} == {"mimo-v2.5"}
    by_id = {m["id"]: m for m in catalog["models"]}
    assert by_id["mimo-v2.5"]["name"] == "MiMo-V2.5"
    assert by_id["mimo-v2.5"]["price"]["input"] == 1.0
    assert by_id["mimo-v2.5"]["price"]["output"] == 2.0


def test_get_catalog_for_provider_zai():
    catalog = get_catalog_for_provider("zai")
    assert catalog is not None
    assert catalog["platform_label"] == "Z.AI / 智谱"
    assert {m["id"] for m in catalog["models"]} == {"glm-4.6v", "glm-4.5v"}
    by_id = {m["id"]: m for m in catalog["models"]}
    assert by_id["glm-4.6v"]["name"] == "GLM-4.6V"
    assert by_id["glm-4.5v"]["name"] == "GLM-4.5V"
    assert by_id["glm-4.5v"]["price"]["currency"] == "USD"
    assert by_id["glm-4.5v"]["modality"] == "图片输入 + 文本输入 → 文本输出"


def test_get_catalog_for_provider_unknown():
    assert get_catalog_for_provider("unknown") is None


def test_catalog_model_ids_doubao():
    ids = catalog_model_ids("doubao")
    assert "doubao-seed-1-6-flash-250828" in ids
    assert len(ids) == len(DOUBAO_MODELS)


def test_default_catalog_model_id_uses_cheapest():
    assert default_catalog_model_id("doubao") == "doubao-seed-1-6-flash-250828"
    assert default_catalog_model_id("dashscope") == "qwen3-vl-flash"
    assert default_catalog_model_id("openai") == "gpt-5-nano"
    assert default_catalog_model_id("google_gemini") == "gemini-3.5-flash"
    assert default_catalog_model_id("xai") == "grok-build-0.1"
    assert default_catalog_model_id("mistral") == "ministral-8b-2512"
    assert default_catalog_model_id("together") == "Qwen/Qwen3.5-9B"
    assert default_catalog_model_id("fireworks") == "accounts/fireworks/models/step-3p7-flash-nvfp4"
    assert default_catalog_model_id("dashscope_intl") == "qwen3-vl-flash"
    assert default_catalog_model_id("siliconflow") == "Qwen/Qwen3-VL-8B-Instruct"
    assert default_catalog_model_id("mimo") == "mimo-v2.5"
    assert default_catalog_model_id("zai") == "glm-4.6v"


def test_default_catalog_model_id_unknown_provider():
    assert default_catalog_model_id("zhipu") == ""
    assert default_catalog_model_id("") == ""


def test_is_catalog_model_for_provider():
    assert is_catalog_model_for_provider("dashscope", "qwen3-vl-flash")
    assert not is_catalog_model_for_provider("dashscope", "doubao-seed-1-6-flash-250828")
    assert not is_catalog_model_for_provider("zhipu", "qwen3-vl-flash")


def test_catalog_provider_ids_for_model():
    assert catalog_provider_ids_for_model("glm-4.6v") == frozenset({"zai"})
    assert catalog_provider_ids_for_model("qwen3-vl-flash") == frozenset({"dashscope", "dashscope_intl"})
    assert catalog_provider_ids_for_model("ep-20260618-custom-vision") == frozenset()
