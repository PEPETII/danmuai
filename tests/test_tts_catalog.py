from app.tts_catalog import (
    default_voice_for_provider,
    list_catalog_for_api,
    normalize_catalog_voice,
)
from app.tts_providers import TTS_PROVIDER_DASHSCOPE_QWEN, TTS_PROVIDER_MIMO


def test_list_catalog_for_api_has_providers():
    data = list_catalog_for_api()
    ids = {p["id"] for p in data}
    assert TTS_PROVIDER_MIMO in ids
    assert TTS_PROVIDER_DASHSCOPE_QWEN in ids
    assert "doubao" in ids
    assert "minimax" in ids
    assert "custom_openai" not in ids


def test_catalog_projects_descriptor_prices_and_voice_metadata():
    data = {provider["id"]: provider for provider in list_catalog_for_api()}
    minimax = next(
        model for model in data["minimax"]["models"] if model["id"] == "speech-2.8-turbo"
    )
    dashscope = data["dashscope"]
    cosy_flash = next(
        model for model in dashscope["models"] if model["id"] == "cosyvoice-v3.5-flash"
    )
    cosy_plus = next(
        model for model in dashscope["models"] if model["id"] == "cosyvoice-v3.5-plus"
    )
    doubao = data["doubao"]["models"][0]
    assert minimax["pricing"]["amount"] == 2.0
    assert minimax["pricing"]["source_url"].startswith("https://platform.minimaxi.com/")
    assert [voice["id"] for voice in minimax["voices"]] == [
        "Chinese (Mandarin)_BashfulGirl",
        "Chinese (Mandarin)_Mature_Woman",
        "Chinese_worker_female",
        "Chinese (Mandarin)_Warm_Bestie",
        "Chinese (Mandarin)_Sweet_Lady",
        "Chinese_crisp_podcaster_nv1",
        "Chinese (Mandarin)_IntellectualGirl",
        "Chinese (Mandarin)_Warm_HeartedGirl",
        "Chinese (Mandarin)_ExplorativeGirl",
    ]
    assert cosy_flash["pricing"]["amount"] == 0.8
    assert cosy_plus["pricing"]["amount"] == 1.5
    assert cosy_flash["pricing"]["source_url"].endswith("cosyvoice-v3-5-flash")
    assert len(doubao["voices"]) == 10
    assert doubao["pricing"]["amount"] == 5.0
    assert doubao["voices"][0]["id"]
    assert doubao["voices"][0]["name"]


def test_catalog_omits_non_selectable_models_but_keeps_active_models():
    data = list_catalog_for_api()
    models = [model for provider in data for model in provider["models"]]

    assert models
    assert all(model["status"] == "active" for model in models)
    assert not any("目录" in model["label"] for model in models)
    assert not any(model["status"] in {"historical", "catalog_only"} for model in models)
    assert "mimo-v2.5-tts-voiceclone" not in {model["id"] for model in models}
    assert "speech-2.6-turbo" not in {model["id"] for model in models}


def test_normalize_catalog_voice_dashscope():
    voice = normalize_catalog_voice(
        "invalid",
        provider_id=TTS_PROVIDER_DASHSCOPE_QWEN,
        model_id="qwen3-tts-flash-2025-11-27",
    )
    assert voice == "Cherry"


def test_default_voice_mimo():
    assert default_voice_for_provider(TTS_PROVIDER_MIMO) == "mimo_default"
