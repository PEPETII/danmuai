"""P2-15: release builds must be lock-first and fail closed."""

from __future__ import annotations

from app.bundle_paths import project_root

ROOT = project_root()


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _line_number(text: str, needle: str) -> int:
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(f"needle not found: {needle!r}")


def test_build_defaults_to_release_lock_and_requires_explicit_unlocked_flag() -> None:
    text = _read("scripts/build_exe.ps1")

    assert "[switch]$AllowUnlockedBuild" in text
    assert "$useReleaseLock = -not $AllowUnlockedBuild" in text
    assert "requirements-release-win-lock.txt" in text
    assert "Assert-ReleaseDependencyLock" in text
    assert "DANMU_BUILD_USE_RELEASE_LOCK" not in text


def test_release_python_preflight_checks_version_and_architecture() -> None:
    text = _read("scripts/resolve_build_python.ps1")

    assert "platform.python_version()" in text
    assert "struct.calcsize('P') * 8" in text
    assert "sys.version_info.major" in text
    assert "sys.version_info.minor" in text
    assert "Release builds require Python 3.12.x" in text
    assert "64-bit Python interpreter" in text


def test_release_lock_preflight_is_read_only_and_checks_pip_and_installed_versions() -> None:
    text = _read("scripts/verify_release_lock.ps1")

    assert "function Assert-ReleaseDependencyLock" in text
    assert "-m pip check" in text
    assert "importlib.metadata" in text
    assert "unexpected" in text
    assert "pip is the bootstrap tool" in text
    assert "pip install" not in text
    assert "Invoke-WebRequest" not in text
    assert "vpk download" not in text


def test_publish_dryrun_runs_lock_preflight_before_exiting() -> None:
    text = _read("scripts/publish_windows_release.ps1")

    assert "Assert-ReleaseLockFile" in text
    assert "Assert-ReleaseDependencyLock" in text
    assert "No build, pack, or network operation was run" in text
    assert _line_number(text, "Assert-ReleaseDependencyLock") < _line_number(
        text, "exit 0"
    )
    assert "-AllowUnlockedBuild" not in text


def test_pack_ci_installs_release_lock_and_runs_drift_checks() -> None:
    text = _read(".github/workflows/ci.yml")
    pack_job = text.split("  pack-windows:", 1)[1]

    assert "requirements-release-win-lock.txt" in pack_job
    assert "DANMU_BUILD_PYTHON=$pythonPath" in pack_job
    assert "python -m pip check" in pack_job
    assert "verify_release_lock.ps1" in pack_job
    assert "Publish script DryRun (release preflight smoke)" in pack_job
    assert "-AllowUnlockedBuild" not in pack_job
    assert "requirements.txt -r requirements-dev.txt" not in pack_job
