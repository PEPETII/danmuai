"""Batch 2 model metadata and legacy round-trip contracts."""

from app.model_catalog import CatalogModel, ModelPrice, get_catalog_for_provider
from app.providers.platform_registry import list_model_definitions_for_provider


def test_catalog_model_metadata_round_trip_preserves_legacy_fields():
    model = CatalogModel(
        "Example", "example", ModelPrice(1, 2), supports_mic=True,
        status="active", replacement_model_id="example-next",
        source_kind="curated", source_url="https://example.com/docs",
        verified_at="2026-08-01", input_modalities=("text", "image"),
        output_modalities=("text",),
    )
    payload = model.to_dict()
    assert payload["name"] == "Example"
    assert payload["id"] == "example"
    assert payload["price"] == {"input": 1, "audio": None, "output": 2, "currency": "CNY"}
    assert "supports_mic" in payload
    assert payload["status"] == "active"
    assert payload["replacement_model_id"] == "example-next"
    assert payload["source_kind"] == "curated"
    assert payload["verified_at"] == "2026-08-01"
    assert payload["input_modalities"] == ["text", "image"]


def test_v2_registry_exposes_catalog_metadata_without_keys():
    models = list_model_definitions_for_provider("mimo")
    assert len(models) == 1
    payload = models[0].to_dict()
    assert payload["id"] == "mimo-v2.5"
    assert "supports_mic" in payload
    assert "status" in payload
    assert "verified_at" in payload
    assert "key" not in str(payload).lower()


def test_catalog_api_keeps_legacy_fields_and_adds_metadata():
    catalog = get_catalog_for_provider("doubao")
    assert catalog is not None
    model = catalog["models"][0]
    for field in ("name", "id", "price", "modality", "supports_vision", "thinking_mode", "supports_mic"):
        assert field in model
    for field in ("status", "replacement_model_id", "source_kind", "source_url", "verified_at", "input_modalities", "output_modalities"):
        assert field in model
