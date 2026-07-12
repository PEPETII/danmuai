"""W-REL-READINESS-005: verify_windows_release_artifacts.ps1 structure and fixture checks."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.bundle_paths import project_root
from app.packaging_constants import VELOPACK_PACK_ID, WINDOWS_EXE_NAME

ROOT = project_root()
SCRIPT_PATH = ROOT / "scripts" / "verify_windows_release_artifacts.ps1"
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
FIXTURE_VERSION = "9.9.9"


def _read_script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _read_ci() -> str:
    return CI_PATH.read_text(encoding="utf-8")


def _run_verify(
    release_dir: Path,
    *,
    version: str = FIXTURE_VERSION,
    skip_dist_check: bool = True,
) -> subprocess.CompletedProcess[str]:
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT_PATH),
        "-ReleaseDir",
        str(release_dir),
        "-Version",
        version,
    ]
    if skip_dist_check:
        args.append("-SkipDistCheck")
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def _write_portable_zip(
    path: Path,
    *,
    include_internal: bool = True,
    exe_name: str = WINDOWS_EXE_NAME,
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(exe_name, b"stub")
        if include_internal:
            archive.writestr("_internal/stub.txt", b"stub")


def _write_feed(
    path: Path,
    version: str,
    *,
    include_delta: bool = False,
    full_versions: list[str] | None = None,
) -> None:
    assets: list[dict[str, str]] = [
        {
            "PackageId": VELOPACK_PACK_ID,
            "Version": full_version,
            "Type": "Full",
            "FileName": f"{VELOPACK_PACK_ID}-{full_version}-full.nupkg",
        }
        for full_version in (full_versions or [version])
    ]
    if include_delta:
        assets.append(
            {
                "PackageId": VELOPACK_PACK_ID,
                "Version": version,
                "Type": "Delta",
                "FileName": f"{VELOPACK_PACK_ID}-{version}-delta.nupkg",
            }
        )
    path.write_text(json.dumps({"Assets": assets}, indent=2), encoding="utf-8")


def _write_minimal_release(
    release_dir: Path,
    *,
    version: str = FIXTURE_VERSION,
    include_internal: bool = True,
    feed_version: str | None = None,
    include_delta_in_feed: bool = False,
    include_delta_file: bool = False,
    feed_versions: list[str] | None = None,
) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    (release_dir / f"{VELOPACK_PACK_ID}-win-Setup.exe").write_bytes(b"setup")
    (release_dir / f"{VELOPACK_PACK_ID}-{version}-full.nupkg").write_bytes(b"full")
    _write_portable_zip(
        release_dir / f"{VELOPACK_PACK_ID}-win-Portable.zip",
        include_internal=include_internal,
    )
    _write_feed(
        release_dir / "releases.win.json",
        feed_version if feed_version is not None else version,
        include_delta=include_delta_in_feed,
        full_versions=feed_versions,
    )
    if include_delta_file:
        (release_dir / f"{VELOPACK_PACK_ID}-{version}-delta.nupkg").write_bytes(b"delta")


def test_verify_script_exists_and_sources_helpers() -> None:
    text = _read_script()
    assert "resolve_build_python.ps1" in text
    assert "version_parse.ps1" in text
    assert "Get-AppVersionFromProject" in text
    assert "Get-LatestAppSemVersion" in text
    assert "[version]" not in text
    assert 'python -c "from app.version' not in text


def test_verify_script_contains_required_checks() -> None:
    text = _read_script()
    assert '*.msi' in text or '"*.msi"' in text
    assert "Portable" in text
    assert '_internal' in text
    assert 'Type -eq "Full"' in text
    assert 'Type -eq "Delta"' in text
    assert "Expand-Archive" in text


def test_ci_pack_windows_invokes_verify_script() -> None:
    text = _read_ci()
    assert "verify_windows_release_artifacts.ps1" in text
    assert 'python -c "from app.version' not in text


@pytest.mark.skipif(sys.platform != "win32", reason="verify script is Windows-only")
def test_verify_passes_minimal_valid_fixture(tmp_path: Path) -> None:
    rel_root = tmp_path / "release" / "velopack"
    _write_minimal_release(rel_root)
    completed = _run_verify(rel_root)
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0, output
    assert "Release artifact verification passed" in output


@pytest.mark.skipif(sys.platform != "win32", reason="verify script is Windows-only")
def test_verify_fails_on_msi(tmp_path: Path) -> None:
    rel_root = tmp_path / "release" / "velopack"
    _write_minimal_release(rel_root)
    (rel_root / "unexpected.msi").write_bytes(b"msi")
    completed = _run_verify(rel_root)
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode != 0
    assert "MSI" in output


@pytest.mark.skipif(sys.platform != "win32", reason="verify script is Windows-only")
def test_verify_fails_portable_missing_internal(tmp_path: Path) -> None:
    rel_root = tmp_path / "release" / "velopack"
    _write_minimal_release(rel_root, include_internal=False)
    completed = _run_verify(rel_root)
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode != 0
    assert "_internal" in output


@pytest.mark.skipif(sys.platform != "win32", reason="verify script is Windows-only")
def test_verify_fails_feed_version_mismatch(tmp_path: Path) -> None:
    rel_root = tmp_path / "release" / "velopack"
    _write_minimal_release(rel_root, feed_version="0.0.1")
    completed = _run_verify(rel_root)
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode != 0
    assert "does not match app version" in output


@pytest.mark.skipif(sys.platform != "win32", reason="verify script is Windows-only")
def test_verify_fails_delta_without_feed_entry(tmp_path: Path) -> None:
    rel_root = tmp_path / "release" / "velopack"
    _write_minimal_release(
        rel_root,
        include_delta_file=True,
        include_delta_in_feed=False,
    )
    completed = _run_verify(rel_root)
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode != 0
    assert "delta entries" in output.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="verify script is Windows-only")
@pytest.mark.parametrize(
    ("version", "feed_versions"),
    [
        ("9.9.9-rc.1", ["9.9.9-beta.1", "9.9.9-rc.1"]),
        ("9.9.9", ["9.9.9-beta.1", "9.9.9-rc.1", "9.9.9"]),
    ],
)
def test_verify_selects_latest_prerelease_or_stable(
    tmp_path: Path,
    version: str,
    feed_versions: list[str],
) -> None:
    rel_root = tmp_path / "release" / "velopack"
    _write_minimal_release(
        rel_root,
        version=version,
        feed_versions=feed_versions,
    )
    completed = _run_verify(rel_root, version=version)
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0, output
    assert f"Feed latest: {version}" in output


@pytest.mark.skipif(sys.platform != "win32", reason="verify script is Windows-only")
def test_verify_rejects_invalid_full_asset_version(tmp_path: Path) -> None:
    rel_root = tmp_path / "release" / "velopack"
    _write_minimal_release(
        rel_root,
        feed_versions=[FIXTURE_VERSION, "not-a-version"],
    )
    completed = _run_verify(rel_root)
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode != 0
    assert "Invalid version" in output
