"""BUG-P0-001: PyInstaller exe name must match Velopack --mainExe (SSOT)."""

from __future__ import annotations

import re

from app.bundle_paths import project_root
from app.packaging_constants import (
    VELOPACK_PACK_ID,
    WINDOWS_APP_NAME,
    WINDOWS_DIST_DIR,
    WINDOWS_EXE_NAME,
)

ROOT = project_root()
SPEC_PATH = ROOT / "DanmuAI.spec"


def _read_script(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_packaging_constants_exe_matches_app_name() -> None:
    assert WINDOWS_EXE_NAME == f"{WINDOWS_APP_NAME}.exe"


def test_packaging_constants_dist_dir_matches_app_name() -> None:
    assert WINDOWS_DIST_DIR == WINDOWS_APP_NAME


def test_danmuai_spec_exe_name_matches_ssot() -> None:
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    assert "from app.packaging_constants import WINDOWS_APP_NAME" in spec_text
    assert 'name="DanmuAI"' not in spec_text
    exe_names = re.findall(r"name\s*=\s*WINDOWS_APP_NAME", spec_text)
    assert len(exe_names) >= 2, "EXE and COLLECT must both use WINDOWS_APP_NAME"


def test_velopack_pack_mainexe_uses_ssot() -> None:
    text = _read_script("velopack_pack.ps1")
    assert "Get-PackagingExeName" in text
    assert "--mainExe $MainExe" in text
    assert '[string]$MainExe = "DanmuAI.exe"' not in text


def test_build_exe_script_uses_ssot() -> None:
    text = _read_script("build_exe.ps1")
    assert "Get-PackagingDistPaths" in text
    assert 'Join-Path $distDir "DanmuAI.exe"' not in text
    assert 'dist\\DanmuAI"' not in text


def test_publish_windows_release_uses_ssot() -> None:
    text = _read_script("publish_windows_release.ps1")
    assert "Get-PackagingDistPaths" in text
    assert 'Join-Path $DistDir "DanmuAI.exe"' not in text
    assert 'dist\\DanmuAI"' not in text


def test_version_parse_exports_packaging_helpers() -> None:
    text = _read_script("version_parse.ps1")
    assert "function Get-PackagingExeName" in text
    assert "function Get-PackagingDistPaths" in text
    assert "packaging_constants" in text


def test_velopack_pack_id_matches_ssot() -> None:
    text = _read_script("velopack_pack.ps1")
    assert f'[string]$PackId = "{VELOPACK_PACK_ID}"' in text
