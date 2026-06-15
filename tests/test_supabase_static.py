"""Static assets for Supabase-backed announcements, feedback, and error reports."""

import pytest
from app.bundle_paths import project_root


def test_supabase_example_and_client_exist():
    root = project_root()
    assert (root / "web" / "static" / "supabase-config.example.js").is_file()
    assert (root / "web" / "static" / "supabase-client.js").is_file()
    example = (root / "web" / "static" / "supabase-config.example.js").read_text(encoding="utf-8")
    assert "DANMU_SUPABASE" in example
    assert "YOUR_PROJECT_REF" in example


def test_error_reports_migration_exists():
    root = project_root()
    path = root / "supabase" / "migrations" / "002_error_reports.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8")
    assert "error_reports" in sql
    assert "error_reports_quota" in sql


def test_error_reports_user_note_migration_exists():
    root = project_root()
    path = root / "supabase" / "migrations" / "008_error_reports_user_note.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8")
    assert "user_note" in sql
    assert "contact" in sql


def test_app_updates_migration_exists():
    root = project_root()
    path = root / "supabase" / "migrations" / "003_app_updates.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8")
    assert "app_updates" in sql
    assert "anon_read_enabled_app_updates" in sql


def test_tutorial_links_migration_exists():
    root = project_root()
    path = root / "supabase" / "migrations" / "009_tutorial_links.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8")
    assert "tutorial_links" in sql
    assert "anon_read_enabled_tutorial_links" in sql
    assert "正在紧急赶制中" in sql


def test_supabase_client_exports_error_report_api():
    text = (project_root() / "web" / "static" / "supabase-client.js").read_text(encoding="utf-8")
    assert "submitErrorReport" in text
    assert "getErrorReportQuota" in text
    assert "/rest/v1/error_reports" in text
    assert "user_note" in text
    assert "userNote" in text
    assert "fetchAppUpdate" in text
    assert "/rest/v1/app_updates" in text
    assert "fetchTutorialVideoLink" in text
    assert "/rest/v1/tutorial_links" in text


def test_supabase_config_js_optional_local():
    path = project_root() / "web" / "static" / "supabase-config.js"
    if not path.is_file():
        pytest.skip("supabase-config.js not present (copy from example for local dev)")
    text = path.read_text(encoding="utf-8")
    assert "DANMU_SUPABASE" in text
    assert "YOUR_PROJECT" not in text


def test_app_update_banner_uses_backend_metadata_only():
    text = (project_root() / "web" / "static" / "modules" / "app-update-banner.js").read_text(
        encoding="utf-8"
    )
    assert "DEFAULT_RELEASE_URL" not in text
    assert "FALLBACK_CHANNELS" not in text
    assert "function compareVersions" not in text
    assert "/api/update/channels" in text
    assert "fetchAppUpdate" not in text
