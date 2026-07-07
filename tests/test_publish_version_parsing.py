"""W-PACK-008: publish/velopack scripts must parse semver prerelease versions."""

from __future__ import annotations

import re

import pytest

from app.bundle_paths import project_root

# Mirror scripts/version_parse.ps1 (PowerShell uses equivalent .NET regex).
APP_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?$")
VERSION_PY_CAPTURE_PATTERN = re.compile(
    r"""__version__\s*=\s*["'](\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)["']"""
)


def _read_script(name: str) -> str:
    return (project_root() / "scripts" / name).read_text(encoding="utf-8")


def test_version_parse_ps1_exports_prerelease_patterns() -> None:
    text = _read_script("version_parse.ps1")
    assert r"\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?" in text
    assert r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?" in text


def test_publish_script_dot_sources_version_parse_and_supports_dryrun() -> None:
    text = _read_script("publish_windows_release.ps1")
    assert "version_parse.ps1" in text
    assert "resolve_build_python.ps1" in text
    assert "Assert-BuildPython" in text
    assert "$VersionPyCapturePattern" in text
    assert "[switch]$DryRun" in text
    assert "[DryRun] App version:" in text
    assert 'python -c "from app.version' not in text
    # Old fallback that dropped prerelease suffix must not remain.
    assert "__version__\\s*=\\s*[\"'](\\d+\\.\\d+\\.\\d+)[\"']" not in text


def test_velopack_pack_uses_build_python_for_version() -> None:
    text = _read_script("velopack_pack.ps1")
    assert "resolve_build_python.ps1" in text
    assert "Assert-BuildPython" in text
    assert 'python -c "from app.version' not in text


def test_resolve_build_python_exports_venv_candidates() -> None:
    text = _read_script("resolve_build_python.ps1")
    assert "function Resolve-BuildPythonCommand" in text
    assert "function Assert-BuildPython" in text
    assert r".venv-build\Scripts\python.exe" in text
    assert r".venv-build-312\Scripts\python.exe" in text


def test_build_exe_dot_sources_resolve_build_python() -> None:
    text = _read_script("build_exe.ps1")
    assert "resolve_build_python.ps1" in text
    assert "Resolve-BuildPythonCommand" in text
    assert "function Resolve-PythonCommand" not in text


def test_velopack_pack_dot_sources_version_parse() -> None:
    text = _read_script("velopack_pack.ps1")
    assert "version_parse.ps1" in text
    assert "$AppVersionPattern" in text
    assert "x.y.z-prerelease" in text


@pytest.mark.parametrize(
    "version",
    ["0.3.1", "0.3.1-beta", "1.0.0-rc.1", "v0.3.6-gha"],
)
def test_app_version_pattern_accepts_valid_versions(version: str) -> None:
    normalized = version[1:] if version.startswith("v") else version
    assert APP_VERSION_PATTERN.fullmatch(normalized)


@pytest.mark.parametrize(
    "version",
    ["0.3.x", "beta", "0.3.1-beta+build", "not-a-version"],
)
def test_app_version_pattern_rejects_invalid_versions(version: str) -> None:
    assert APP_VERSION_PATTERN.fullmatch(version) is None


def test_version_py_capture_extracts_prerelease_suffix() -> None:
    content = '__version__ = "0.3.1-beta"\n'
    match = VERSION_PY_CAPTURE_PATTERN.search(content)
    assert match is not None
    assert match.group(1) == "0.3.1-beta"


def test_version_py_capture_accepts_release_without_prerelease() -> None:
    content = "__version__ = '0.3.8'\n"
    match = VERSION_PY_CAPTURE_PATTERN.search(content)
    assert match is not None
    assert match.group(1) == "0.3.8"
