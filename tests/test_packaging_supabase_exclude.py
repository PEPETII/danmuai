"""Packaging hygiene: Supabase credential files must not ship in PyInstaller bundles."""

from __future__ import annotations

import subprocess

import pytest

from app.bundle_paths import project_root

# Keep in sync with DanmuAI.spec:_should_exclude_supabase_config
def _should_exclude_supabase_config(name: str) -> bool:
    if name == "supabase-config.example.js":
        return False
    return name == "supabase-config.js" or name.startswith("supabase-config.js.")


@pytest.mark.parametrize(
    ("filename", "excluded"),
    [
        ("supabase-config.js", True),
        ("supabase-config.js.codex-release-backup", True),
        ("supabase-config.js.bak", True),
        ("supabase-config.example.js", False),
        ("supabase-client.js", False),
    ],
)
def test_should_exclude_supabase_config_predicate(filename: str, excluded: bool) -> None:
    assert _should_exclude_supabase_config(filename) is excluded


def test_danmuai_spec_excludes_supabase_config_variants() -> None:
    spec_text = (project_root() / "DanmuAI.spec").read_text(encoding="utf-8")
    assert "_should_exclude_supabase_config" in spec_text
    assert "exclude_name_predicates=(_should_exclude_supabase_config,)" in spec_text
    assert 'frozenset({"supabase-config.js"})' not in spec_text


def test_web_static_has_no_supabase_config_backup_variants() -> None:
    static_dir = project_root() / "web" / "static"
    variants = [
        path
        for path in static_dir.iterdir()
        if path.is_file() and path.name.startswith("supabase-config.js.")
    ]
    assert variants == [], (
        "Remove Supabase config backup variants from web/static: "
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
