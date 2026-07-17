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


def test_feedback_context_migration_exists():
    root = project_root()
    path = root / "supabase" / "migrations" / "010_feedback_context.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8")
    assert "context_json" in sql
    assert "logs_excerpt" in sql


def test_anon_table_grants_migration_exists():
    """BUG-021: anon must have explicit REVOKE ALL + minimal GRANT per table."""
    root = project_root()
    path = root / "supabase" / "migrations" / "011_anon_table_grants.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8").lower()
    assert "revoke all on public.feedback from anon" in sql
    assert "grant insert on public.feedback to anon" in sql
    assert "revoke all on public.error_reports from anon" in sql
    assert "grant insert on public.error_reports to anon" in sql
    assert "revoke all on public.announcements from anon" in sql
    assert "grant select on public.announcements to anon" in sql
    assert "revoke all on public.app_updates from anon" in sql
    assert "grant select on public.app_updates to anon" in sql
    assert "revoke all on public.tutorial_links from anon" in sql
    assert "grant select on public.tutorial_links to anon" in sql


def test_supabase_feedback_forwards_context_fields():
    text = (project_root() / "web" / "static" / "supabase-client.js").read_text(encoding="utf-8")
    func_start = text.index("async function submitFeedback(")
    func_end = text.index("\n  async function getErrorReportQuota()", func_start)
    func_body = text[func_start:func_end]
    assert "context_json" in func_body
    assert "logs_excerpt" in func_body


def test_logs_excerpt_hard_capped_at_8000():
    """logs_excerpt must hard-cap at 8000 so DB check constraint is never violated."""
    root = project_root()
    client = (root / "web" / "static" / "supabase-client.js").read_text(encoding="utf-8")
    reporting = (root / "web" / "static" / "modules" / "app-error-reporting.js").read_text(
        encoding="utf-8"
    )
    # Must not use the old suffix-overshoot pattern (7990 + marker > 8000).
    assert "slice(0, 7990)" not in client
    assert "slice(0, 7990)" not in reporting
    assert "slice(0, 8000)" in client
    assert "slice(0, 8000)" in reporting


def test_supabase_client_fetch_timeout_and_error_kinds():
    text = (project_root() / "web" / "static" / "supabase-client.js").read_text(encoding="utf-8")
    assert "AbortController" in text
    assert "DEFAULT_FETCH_TIMEOUT_MS" in text
    assert "8000" in text
    assert "sanitizeErrorMessage" in text
    assert "formatSupabaseError" in text
    assert "kind: 'timeout'" in text
    assert "kind: 'network_error'" in text
    assert "kind: 'not_configured'" in text
    assert "kind: 'rate_limit'" in text
    assert "SUPABASE_TIMEOUT_MSG" in text
    assert "SUPABASE_NETWORK_MSG" in text
    # User-facing timeout/network messages must not echo auth header patterns.
    timeout_msg_start = text.index("const SUPABASE_TIMEOUT_MSG = ")
    timeout_msg_end = text.index(";", timeout_msg_start)
    timeout_msg = text[timeout_msg_start:timeout_msg_end]
    assert "apikey" not in timeout_msg.lower()
    assert "authorization" not in timeout_msg.lower()
    assert "bearer" not in timeout_msg.lower()


def test_supabase_modules_use_format_supabase_error():
    root = project_root()
    announcements = (root / "web" / "static" / "modules" / "content-announcements.js").read_text(
        encoding="utf-8"
    )
    feedback = (root / "web" / "static" / "modules" / "content-feedback.js").read_text(
        encoding="utf-8"
    )
    error_reporting = (root / "web" / "static" / "modules" / "app-error-reporting.js").read_text(
        encoding="utf-8"
    )
    assert "formatSupabaseError" in announcements
    assert "formatSupabaseUserMessage" in feedback
    assert "formatErrorReportSupabaseMessage" in error_reporting
    assert "err?.kind" in feedback or "error?.kind" in feedback
    assert "err?.kind" in error_reporting or "error?.kind" in error_reporting


def test_app_update_banner_uses_backend_metadata_only():
    text = (project_root() / "web" / "static" / "modules" / "app-update-banner.js").read_text(
        encoding="utf-8"
    )
    assert "DEFAULT_RELEASE_URL" not in text
    assert "FALLBACK_CHANNELS" not in text
    assert "function compareVersions" not in text
    assert "/api/update/channels" in text
    assert "fetchAppUpdate" not in text
