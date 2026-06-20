"""Tests for app.version_compare — numeric segment ordering, not string compare."""

import pytest
from app.version_compare import (
    compare_versions,
    is_version_newer,
    normalize_version,
    parse_version,
)


def test_normalize_strips_v_prefix():
    assert normalize_version("v2026.05.29") == "2026.05.29"
    assert normalize_version("V1.0.0") == "1.0.0"


def test_semver_ordering():
    assert compare_versions("0.3.0", "0.2.2") > 0
    assert compare_versions("v0.3.0", "v0.2.2") > 0
    assert is_version_newer("0.3.0", "0.2.2")
    assert not is_version_newer("0.2.2", "0.3.0")
    assert parse_version("0.2.2") == ((0, 2, 2), None)


def test_calver_ordering():
    assert compare_versions("2026.05.27", "2026.05.29") < 0
    assert compare_versions("2026.05.29", "2026.05.27") > 0
    assert compare_versions("2026.05.29", "2026.05.29") == 0
    assert is_version_newer("2026.05.29", "2026.05.27")
    assert not is_version_newer("2026.05.27", "2026.05.29")


def test_semver_prerelease_lower_than_release():
    assert compare_versions("1.0.1", "1.0.1-beta") > 0
    assert compare_versions("1.0.1-beta", "1.0.1") < 0


def test_parse_version_segments():
    assert parse_version("2026.05.29") == ((2026, 5, 29), None)


def test_invalid_version_raises():
    with pytest.raises(ValueError):
        parse_version("")
    with pytest.raises(ValueError):
        parse_version("not-a-version")


# ── BUG-A07: +build metadata handling ──────────────────────────────


def test_build_metadata_ignored_in_comparison():
    """BUG-A07: +build metadata must be ignored per semver spec."""
    assert compare_versions("0.3.4", "0.3.4+build.1") == 0
    assert compare_versions("0.3.4+build.1", "0.3.4") == 0


def test_build_metadata_different_builds_equal():
    """BUG-A07: Different +build metadata still compares as equal."""
    assert compare_versions("0.3.4+build.1", "0.3.4+build.2") == 0


def test_build_metadata_newer_version_with_build():
    """BUG-A07: Version comparison ignores +build when determining newer."""
    assert is_version_newer("0.3.5", "0.3.4+build.1")
    assert not is_version_newer("0.3.4+build.1", "0.3.5")


def test_build_metadata_prerelease_with_build():
    """BUG-A07: +build is stripped before prerelease comparison."""
    assert compare_versions("0.3.4-alpha+build.1", "0.3.4-alpha") == 0
    assert compare_versions("0.3.4-alpha", "0.3.4-alpha+build.2") == 0
