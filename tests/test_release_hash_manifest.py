"""W-REL-READINESS-006: SHA256SUMS manifest generation and pre-upload verification."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.bundle_paths import project_root

ROOT = project_root()
MANIFEST_SCRIPT = ROOT / "scripts" / "write_release_hash_manifest.ps1"
PACK_ID = "PEPETII.DanmuAI"
MANIFEST_LINE_PATTERN = re.compile(r"^([0-9a-f]{64})  (.+)$")

REQUIRED_ARTIFACT_PATTERNS = [
    re.compile(rf"^{re.escape(PACK_ID)}-\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?-Setup\.exe$"),
    re.compile(rf"^{re.escape(PACK_ID)}-win-Setup\.exe$"),
    re.compile(rf"^{re.escape(PACK_ID)}-win-Portable\.zip$"),
    re.compile(rf"^{re.escape(PACK_ID)}-\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?-full\.nupkg$"),
    re.compile(r"^releases\.win\.json$"),
]


def _read_script(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def _sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_manifest_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(MANIFEST_SCRIPT),
            *args,
        ],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _create_fake_release_dir(tmp_path: Path, version: str = "9.9.9-test", *, with_delta: bool = False) -> Path:
    release_dir = tmp_path / "velopack"
    release_dir.mkdir(parents=True)

    artifacts = {
        f"{PACK_ID}-{version}-Setup.exe": b"setup-versioned",
        f"{PACK_ID}-win-Setup.exe": b"setup-win",
        f"{PACK_ID}-win-Portable.zip": b"portable-zip",
        f"{PACK_ID}-{version}-full.nupkg": b"full-nupkg",
        "releases.win.json": b'{"Assets":[{"Type":"Full","Version":"' + version.encode() + b'"}]}',
    }
    if with_delta:
        artifacts[f"{PACK_ID}-{version}-delta.nupkg"] = b"delta-nupkg"

    for name, payload in artifacts.items():
        (release_dir / name).write_bytes(payload)

    (release_dir / "VERSION.txt").write_text(
        "\n".join(
            [
                "DanmuAI Windows x64 (PyInstaller onedir + Velopack)",
                f"Version: {version}",
                "Built (UTC): 2026-07-07T00:00:00Z",
            ]
        ),
        encoding="utf-8",
    )
    return release_dir


def test_manifest_script_exists_with_core_symbols() -> None:
    text = _read_script("write_release_hash_manifest.ps1")
    assert "SHA256SUMS.txt" in text
    assert "Get-FileHash" in text
    assert "function Test-ReleaseHashManifest" in text
    assert "function Write-ReleaseHashManifest" in text
    assert "function Get-ReleaseManifestFiles" in text
    assert ".Hash.ToLowerInvariant()" in text


def test_publish_script_invokes_manifest_writer() -> None:
    text = _read_script("publish_windows_release.ps1")
    assert "write_release_hash_manifest.ps1" in text
    assert "-ReleaseDir $VelopackDir" in text
    assert 'Join-Path $VelopackDir "SHA256SUMS.txt"' in text


def test_upload_script_verifies_manifest_before_upload() -> None:
    text = _read_script("upload_r2_release.ps1")
    assert "write_release_hash_manifest.ps1" in text
    assert "Test-ReleaseHashManifest" in text
    assert "SHA256 manifest verification passed" in text
    assert "Upload artifact not listed in SHA256SUMS.txt" in text
    assert "ContentLength" in text


def test_manifest_script_documents_required_artifact_patterns() -> None:
    text = _read_script("write_release_hash_manifest.ps1")
    assert "$PackId-win-Setup.exe" in text
    assert "$PackId-win-Portable.zip" in text
    assert "$PackId-$AppVersion-full.nupkg" in text
    assert "$PackId-$AppVersion-Setup.exe" in text
    assert "$PackId-$AppVersion-delta.nupkg" in text
    assert "releases.win.json" in text


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell manifest script is Windows-only")
def test_write_and_verify_manifest_round_trip(tmp_path: Path) -> None:
    release_dir = _create_fake_release_dir(tmp_path, with_delta=True)
    version = "9.9.9-test"

    write = _run_manifest_script("-ReleaseDir", str(release_dir), "-Version", version)
    assert write.returncode == 0, write.stdout + write.stderr

    manifest_path = release_dir / "SHA256SUMS.txt"
    assert manifest_path.exists()

    lines = [line for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 6

    names = []
    for line in lines:
        match = MANIFEST_LINE_PATTERN.fullmatch(line)
        assert match is not None, line
        digest, name = match.groups()
        file_path = release_dir / name
        assert file_path.exists()
        assert digest == _sha256_hex(file_path)
        names.append(name)

    assert f"{PACK_ID}-{version}-delta.nupkg" in names
    for pattern in REQUIRED_ARTIFACT_PATTERNS:
        assert any(pattern.fullmatch(name) for name in names), pattern.pattern

    verify = _run_manifest_script("-ReleaseDir", str(release_dir), "-Version", version, "-VerifyOnly")
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert "SHA256 manifest verification passed" in verify.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell manifest script is Windows-only")
def test_verify_fails_after_tampering(tmp_path: Path) -> None:
    release_dir = _create_fake_release_dir(tmp_path)
    version = "9.9.9-test"

    write = _run_manifest_script("-ReleaseDir", str(release_dir), "-Version", version)
    assert write.returncode == 0, write.stdout + write.stderr

    target = release_dir / f"{PACK_ID}-win-Portable.zip"
    target.write_bytes(target.read_bytes() + b"tamper")

    verify = _run_manifest_script("-ReleaseDir", str(release_dir), "-Version", version, "-VerifyOnly")
    assert verify.returncode != 0
    output = verify.stdout + verify.stderr
    assert "Hash mismatch" in output
    assert f"{PACK_ID}-win-Portable.zip" in output
