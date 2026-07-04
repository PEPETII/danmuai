"""Backend zh/en translation dictionary parity."""

from app.translations import TRANSLATIONS


def test_translation_key_parity():
    zh = set(TRANSLATIONS["zh"])
    en = set(TRANSLATIONS["en"])
    assert zh == en, f"missing en: {sorted(zh - en)[:10]}; missing zh: {sorted(en - zh)[:10]}"
