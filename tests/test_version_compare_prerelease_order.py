"""Tests for semver prerelease identifier ordering in version comparison."""

from app.version_compare import compare_versions, is_version_newer


class TestPrereleaseOrder:
    def test_alpha_lt_beta(self):
        assert compare_versions("1.0.0-alpha", "1.0.0-beta") == -1

    def test_beta_lt_rc(self):
        assert compare_versions("0.9.0-beta.2", "0.9.0-rc.1") == -1

    def test_dev_lt_alpha(self):
        assert compare_versions("1.0.0-dev.1", "1.0.0-alpha.1") == -1

    def test_rc_same_prefix_lexicographic(self):
        assert compare_versions("1.0.0-rc.1", "1.0.0-rc.2") == -1

    def test_unknown_lower_than_rc(self):
        assert compare_versions("1.0.0-unknown.1", "1.0.0-rc.1") == -1

    def test_unknown_lower_than_beta(self):
        assert compare_versions("1.0.0-unknown.1", "1.0.0-beta.1") == -1

    def test_unknown_vs_unknown_lexicographic(self):
        assert compare_versions("1.0.0-unknown.1", "1.0.0-zeta.1") == -1

    def test_is_version_newer_rc_over_beta(self):
        assert is_version_newer("0.9.0-rc.1", "0.9.0-beta.2") is True

    def test_is_version_newer_beta_over_alpha(self):
        assert is_version_newer("1.0.0-beta.1", "1.0.0-alpha.1") is True

    def test_release_gt_prerelease(self):
        assert compare_versions("1.0.0", "1.0.0-rc.1") == 1
        assert compare_versions("1.0.0-rc.1", "1.0.0") == -1

    def test_equivalent_prerelease(self):
        assert compare_versions("1.0.0-alpha.1", "1.0.0-alpha.1") == 0
        assert compare_versions("1.0.0-beta.2", "1.0.0-beta.2") == 0

    def test_a_alias_for_alpha(self):
        assert compare_versions("1.0.0-a.1", "1.0.0-alpha.2") == -1

    def test_b_alias_for_beta(self):
        assert compare_versions("1.0.0-b.1", "1.0.0-beta.2") == -1

    def test_c_alias_for_rc(self):
        assert compare_versions("1.0.0-c.1", "1.0.0-rc.2") == -1
