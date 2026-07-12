"""W-PACK-008 / BUG-H-001: publish/velopack scripts must parse semver and resolve build Python."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from app import version as app_version
from app.bundle_paths import project_root

# Mirror scripts/version_parse.ps1 (PowerShell uses equivalent .NET regex).
APP_VERSION_PATTERN = re.compile(
    r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
VERSION_PY_CAPTURE_PATTERN = re.compile(
    r"""__version__\s*=\s*["'](\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)["']"""
)

ROOT = project_root()
VENV_BUILD_PYTHON = ROOT / ".venv-build" / "Scripts" / "python.exe"


def _read_script(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def _line_number(text: str, needle: str) -> int:
    for index, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return index
    raise AssertionError(f"needle not found: {needle!r}")


def _run_version_helper(command: str) -> subprocess.CompletedProcess[str]:
    helper = ROOT / "scripts" / "version_parse.ps1"
    escaped_helper = str(helper).replace("'", "''")
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f". '{escaped_helper}'; {command}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def test_version_parse_ps1_exports_prerelease_patterns() -> None:
    text = _read_script("version_parse.ps1")
    assert r"\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?" in text
    assert 'python -c "from app.' not in text
    assert "Invoke-BuildPythonExpression" in text
    assert "function Get-AppVersionFromProject" in text
    assert "function Compare-AppSemVersion" in text
    assert "function Get-LatestAppSemVersion" in text


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell helper is Windows-only")
@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("0.4.0-beta.1", "0.4.0-rc.1", -1),
        ("0.4.0-rc.1", "0.4.0", -1),
        ("0.4.0-beta.2", "0.4.0-beta.1", 1),
        ("0.4.0-beta.10", "0.4.0-beta.2", 1),
        ("999999999999999999999999.0.0", "1000000000000000000000000.0.0", -1),
        ("v0.4.0", "0.4.0", 0),
    ],
)
def test_shared_semver_compare(left: str, right: str, expected: int) -> None:
    completed = _run_version_helper(
        f"Compare-AppSemVersion -Left '{left}' -Right '{right}'"
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0, output
    assert completed.stdout.strip() == str(expected)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell helper is Windows-only")
@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        (["0.4.0-beta.1", "0.4.0-rc.1"], "0.4.0-rc.1"),
        (["0.4.0-beta.1", "0.4.0-rc.1", "0.4.0"], "0.4.0"),
        (["0.4.0-beta.2", "0.4.0-beta.10"], "0.4.0-beta.10"),
    ],
)
def test_shared_semver_selects_latest(versions: list[str], expected: str) -> None:
    values = ", ".join(f"'{version}'" for version in versions)
    completed = _run_version_helper(
        f"Get-LatestAppSemVersion -Versions @({values})"
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0, output
    assert completed.stdout.strip() == expected


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell helper is Windows-only")
@pytest.mark.parametrize(
    "version",
    ["0.4.0+build", "0.4.0-beta..1", "not-a-version"],
)
def test_shared_semver_rejects_invalid_versions(version: str) -> None:
    completed = _run_version_helper(f"Normalize-AppSemVersion -Version '{version}'")
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode != 0
    assert "Invalid version" in output


def test_publish_script_dot_sources_version_parse_and_supports_dryrun() -> None:
    text = _read_script("publish_windows_release.ps1")
    assert "version_parse.ps1" in text
    assert "resolve_build_python.ps1" in text
    assert "Assert-BuildPython" in text
    assert "Get-AppVersionFromProject" in text
    assert "Get-PackagingDistPaths -Root $Root" in text
    assert "[switch]$DryRun" in text
    assert "[DryRun] App version:" in text
    assert "-BuildPython $BuildPython" in text
    assert 'python -c "from app.version' not in text


def test_velopack_pack_uses_build_python_for_version() -> None:
    text = _read_script("velopack_pack.ps1")
    assert "resolve_build_python.ps1" in text
    assert "Assert-BuildPython" in text
    assert "Invoke-BuildPythonExpression" in text
    assert "[pscustomobject]$BuildPython" in text
    assert 'python -c "from app.version' not in text
    assert 'python -c "from app.' not in text


def test_resolve_build_python_exports_venv_candidates() -> None:
    text = _read_script("resolve_build_python.ps1")
    assert "function Resolve-BuildPythonCommand" in text
    assert "function Assert-BuildPython" in text
    assert "function Invoke-BuildPythonExpression" in text
    assert r".venv-build\Scripts\python.exe" in text
    assert r".venv-build-312\Scripts\python.exe" in text


def test_build_exe_dot_sources_resolve_build_python_before_packaging_helpers() -> None:
    text = _read_script("build_exe.ps1")
    assert "resolve_build_python.ps1" in text
    assert "Resolve-BuildPythonCommand" in text
    assert "function Resolve-PythonCommand" not in text
    assert "Get-PackagingDistPaths -Root $Root" in text
    resolve_line = _line_number(text, "resolve_build_python.ps1")
    packaging_line = _line_number(text, "Get-PackagingDistPaths")
    assert resolve_line < packaging_line


def test_velopack_pack_dot_sources_resolve_python_before_packaging_helpers() -> None:
    text = _read_script("velopack_pack.ps1")
    assert "version_parse.ps1" in text
    assert "$AppVersionPattern" in text
    assert "x.y.z-prerelease" in text
    assert "Get-PackagingExeName -Root $Root" in text
    resolve_line = _line_number(text, "resolve_build_python.ps1")
    exe_line = _line_number(text, "Get-PackagingExeName")
    assert resolve_line < exe_line


@pytest.mark.parametrize("script_name", ["upload_r2_release.ps1", "upload_github_release.ps1"])
def test_upload_scripts_use_shared_python_resolution(script_name: str) -> None:
    text = _read_script(script_name)
    assert "resolve_build_python.ps1" in text
    assert "version_parse.ps1" in text
    assert "Resolve-BuildPythonCommand" in text
    assert "Get-AppVersionFromProject" in text
    assert 'python -c "from app.version' not in text


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="publish_windows_release.ps1 is Windows-only",
)
@pytest.mark.skipif(
    not VENV_BUILD_PYTHON.exists(),
    reason="needs .venv-build for publish DryRun integration",
)
def test_publish_dryrun_reads_version_with_build_python() -> None:
    script = ROOT / "scripts" / "publish_windows_release.ps1"
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-DryRun",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert f"[DryRun] App version: {app_version.__version__}" in output


@pytest.mark.parametrize(
    "version",
    ["0.3.1", "0.3.1-beta", "1.0.0-rc.1", "v0.3.6-gha"],
)
def test_app_version_pattern_accepts_valid_versions(version: str) -> None:
    normalized = version[1:] if version.startswith("v") else version
    assert APP_VERSION_PATTERN.fullmatch(normalized)


@pytest.mark.parametrize(
    "version",
    [
        "0.3.x",
        "beta",
        "0.3.1-beta+build",
        "0.3.1-beta..1",
        "0.3.1-",
        "not-a-version",
    ],
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
