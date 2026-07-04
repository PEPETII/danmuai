"""Packaging hygiene: Supabase credential files must not ship in PyInstaller bundles."""

from __future__ import annotations

import subprocess

import pytest

from app.bundle_paths import project_root

# Keep in sync with DanmuAI.spec:_should_exclude_supabase_config
_ALLOWED_SUPABASE_FILES = frozenset({
    "supabase-config.example.js",  # Template (no credentials)
    "supabase-client.js",           # Legitimate client code (no credentials)
})


def _should_exclude_supabase_config(name: str) -> bool:
    """Default-deny (BUG-005): exclude any file containing 'supabase-config' unless allowlisted."""
    if name in _ALLOWED_SUPABASE_FILES:
        return False
    return "supabase-config" in name.lower()


@pytest.mark.parametrize(
    ("filename", "excluded"),
    [
        # Canonical credential file and its dot-variants (covered by old rule).
        ("supabase-config.js", True),
        ("supabase-config.js.codex-release-backup", True),
        ("supabase-config.js.bak", True),
        ("supabase-config.js.swp", True),
        # BUG-005: creative variants missed by the old prefix whitelist.
        ("supabase-config-local.js", True),
        ("supabase-config.local.js", True),
        ("my-supabase-config.js", True),
        ("supabase-config-backup.js", True),
        ("SUPABASE-CONFIG.JS", True),  # case-insensitive
        # Allowlist: template and client code must be kept.
        ("supabase-config.example.js", False),
        ("supabase-client.js", False),
        # Unrelated files are unaffected.
        ("app.js", False),
        ("warm-tokens.css", False),
    ],
)
def test_should_exclude_supabase_config_predicate(filename: str, excluded: bool) -> None:
    assert _should_exclude_supabase_config(filename) is excluded


def test_danmuai_spec_excludes_supabase_config_variants() -> None:
    spec_text = (project_root() / "DanmuAI.spec").read_text(encoding="utf-8")
    assert "_should_exclude_supabase_config" in spec_text
    assert "exclude_name_predicates=(_should_exclude_supabase_config,)" in spec_text
    # BUG-005: verify default-deny allowlist structure is in place.
    assert "_ALLOWED_SUPABASE_FILES" in spec_text
    assert "supabase-config.example.js" in spec_text
    assert "supabase-client.js" in spec_text
    # The old prefix-whitelist approach must not be present.
    assert 'frozenset({"supabase-config.js"})' not in spec_text


def test_publish_script_uses_default_deny_guard() -> None:
    """BUG-005: publish_windows_release.ps1 must catch all *supabase-config* variants."""
    ps_text = (
        project_root() / "scripts" / "publish_windows_release.ps1"
    ).read_text(encoding="utf-8")
    # The old -Filter "supabase-config.js.*" only caught dot-variants; the new
    # default-deny guard uses -like "*supabase-config*" with an explicit allowlist.
    assert "*supabase-config*" in ps_text
    assert "supabase-config.example.js" in ps_text
    assert "supabase-client.js" in ps_text


def test_web_static_has_no_supabase_config_backup_variants() -> None:
    """Only supabase-config.js (real credentials, excluded from packaging) and the
    allowlist (example.js, client.js) may exist in web/static. Any other file whose
    name contains 'supabase-config' is a leftover backup/temp variant that must be
    removed — it could be accidentally packaged if the exclude rule regresses.
    """
    static_dir = project_root() / "web" / "static"
    allowed_in_dir = _ALLOWED_SUPABASE_FILES | {"supabase-config.js"}
    variants = [
        path
        for path in static_dir.iterdir()
        if path.is_file()
        and "supabase-config" in path.name.lower()
        and path.name not in allowed_in_dir
    ]
    assert variants == [], (
        "Remove Supabase config backup/temp variants from web/static: "
        + ", ".join(p.name for p in variants)
    )


def test_git_does_not_track_supabase_credential_files() -> None:
    root = project_root()
    tracked = subprocess.run(
        ["git", "ls-files", "web/static"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    tracked_names = {line.rsplit("/", 1)[-1] for line in tracked if line.strip()}
    leaked = sorted(name for name in tracked_names if _should_exclude_supabase_config(name))
    assert leaked == [], f"Git must not track Supabase credential files: {leaked}"
