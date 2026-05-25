"""Model catalog enrichment and Doubao data tests."""

from app.model_catalog import (
    DASHSCOPE_MODELS,
    DOUBAO_MODELS,
    SILICONFLOW_MODELS,
    enrich_platform_models,
    get_catalog_for_provider,
    list_platform_catalogs,
)


def test_doubao_cheapest_is_flash():
    enriched = enrich_platform_models(DOUBAO_MODELS)
    cheapest = [m for m in enriched if m["cheapest"]]
    assert len(cheapest) == 1
    assert cheapest[0]["id"] == "doubao-seed-1-6-flash-250828"
    assert cheapest[0]["price"]["input"] == 0.15


def test_doubao_supports_mic_from_audio_price():
    enriched = enrich_platform_models(DOUBAO_MODELS)
    by_id = {m["id"]: m for m in enriched}
    assert by_id["doubao-seed-2-0-lite-260428"]["supports_mic"] is True
    assert by_id["doubao-seed-2-0-mini-260428"]["supports_mic"] is True
    assert by_id["doubao-seed-1-6-flash-250828"]["supports_mic"] is False
    assert by_id["doubao-seed-2-0-pro-260215"]["supports_mic"] is False


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


def test_list_platform_catalogs_has_three_platforms():
    platforms = list_platform_catalogs()
    assert len(platforms) == 3
    doubao = _platform_by_id(platforms, "doubao")
    assert doubao["provider_id"] == "doubao"
    assert len(doubao["models"]) == 6
    dashscope = _platform_by_id(platforms, "dashscope")
    assert dashscope["provider_id"] == "dashscope"
    assert dashscope["platform_label"] == "DashScope"
    assert len(dashscope["models"]) == 8
    siliconflow = _platform_by_id(platforms, "siliconflow")
    assert siliconflow["provider_id"] == "siliconflow"
    assert siliconflow["platform_label"] == "轨迹流动"
    assert len(siliconflow["models"]) == 9
    all_models = doubao["models"] + dashscope["models"] + siliconflow["models"]
    for model in all_models:
        assert "name" in model
        assert "id" in model
        assert "price" in model
        assert "cheapest" in model
        assert "supports_mic" in model


def test_dashscope_cheapest_is_qwen3_vl_flash():
    enriched = enrich_platform_models(DASHSCOPE_MODELS)
    cheapest = [m for m in enriched if m["cheapest"]]
    assert len(cheapest) == 1
    assert cheapest[0]["id"] == "qwen3-vl-flash"
    assert cheapest[0]["price"]["input"] == 0.15


def test_dashscope_supports_mic_omni_models():
    enriched = enrich_platform_models(DASHSCOPE_MODELS)
    by_id = {m["id"]: m for m in enriched}
    assert by_id["qwen-omni-turbo"]["supports_mic"] is True
    assert by_id["qwen2.5-omni-7b"]["supports_mic"] is True
    assert by_id["qwen3-vl-flash"]["supports_mic"] is False
    assert by_id["qwen-vl-max"]["supports_mic"] is False


def test_get_catalog_for_provider_doubao():
    catalog = get_catalog_for_provider("doubao")
    assert catalog is not None
    assert catalog["platform_label"] == "Doubao"


def test_get_catalog_for_provider_dashscope():
    catalog = get_catalog_for_provider("dashscope")
    assert catalog is not None
    assert catalog["platform_label"] == "DashScope"
    assert len(catalog["models"]) == 8


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
    assert catalog["platform_label"] == "轨迹流动"
    assert len(catalog["models"]) == 9


def test_get_catalog_for_provider_unknown():
    assert get_catalog_for_provider("unknown") is None
