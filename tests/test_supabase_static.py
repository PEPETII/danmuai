"""Static assets for Supabase-backed announcements and feedback."""

import pytest
from app.bundle_paths import project_root


def test_supabase_example_and_client_exist():
    root = project_root()
    assert (root / "web" / "static" / "supabase-config.example.js").is_file()
    assert (root / "web" / "static" / "supabase-client.js").is_file()
    example = (root / "web" / "static" / "supabase-config.example.js").read_text(encoding="utf-8")
    assert "DANMU_SUPABASE" in example
    assert "YOUR_PROJECT_REF" in example


def test_supabase_config_js_optional_local():
    path = project_root() / "web" / "static" / "supabase-config.js"
    if not path.is_file():
        pytest.skip("supabase-config.js not present (copy from example for local dev)")
    text = path.read_text(encoding="utf-8")
    assert "DANMU_SUPABASE" in text
    assert "YOUR_PROJECT" not in text
