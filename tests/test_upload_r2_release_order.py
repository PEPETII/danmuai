"""Regression for R2 upload-order BUG-011 (not reply_parser BUG-011).

Feed metadata (releases.win.json) must be uploaded after all binary assets so
clients never see a new feed pointing at not-yet-uploaded nupkg/setup files.
"""

from __future__ import annotations

import re

from app.bundle_paths import project_root

FEED_KEY = "releases/win/stable/releases.win.json"
FEED_ALIAS_KEY = "releases/win/stable"
SCRIPT_PATH = project_root() / "scripts" / "upload_r2_release.ps1"


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _initial_uploads_block(text: str) -> str:
    match = re.search(r"\$uploads\s*=\s*@\((.*?)\)", text, re.DOTALL)
    assert match, "$uploads = @( ... ) block not found in upload_r2_release.ps1"
    return match.group(1)


def _upload_append_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("$uploads +=")
    ]


def test_r2_upload_feed_not_in_initial_array() -> None:
    """BUG-011 (R2): feed must not be the first entry in the uploads array."""
    block = _initial_uploads_block(_script_text())
    assert FEED_KEY not in block, "releases.win.json must not appear in initial $uploads = @(...)"
    assert "releases.win.json" not in block
    assert "$feed" not in block


def test_r2_upload_feed_metadata_appended_last() -> None:
    """BUG-011 (R2): feed metadata must be appended after binary assets."""
    append_lines = _upload_append_lines(_script_text())
    assert append_lines, "expected at least one $uploads += line for feed"
    feed_lines = [line for line in append_lines if "releases.win.json" in line or "$feed" in line]
    assert len(feed_lines) == 2, f"feed metadata must be appended exactly twice, got: {feed_lines}"
    assert append_lines[-2:] == feed_lines, (
        "feed metadata append statements must be the final $uploads += statements"
    )


def test_r2_upload_feed_last_guard_present() -> None:
    """BUG-011 (R2): runtime guard must abort if feed is not last in $uploads."""
    text = _script_text()
    assert "feed metadata must be uploaded last" in text
    assert "$uploads[-2].Key -ne $feedKey" in text
    assert "$uploads[-1].Key -ne $feedAliasKey" in text
    assert FEED_ALIAS_KEY in text
