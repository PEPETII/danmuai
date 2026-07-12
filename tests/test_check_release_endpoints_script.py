"""W-REL-READINESS-011: check_release_endpoints.ps1 read-only monitor structure."""

from __future__ import annotations

import json
import re
import sys
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.bundle_paths import project_root

ROOT = project_root()
SCRIPT_PATH = ROOT / "scripts" / "check_release_endpoints.ps1"
DOC_PATH = ROOT / "docs" / "operations" / "RELEASE_MONITORING.md"


def _read_script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _run_with_local_endpoints(
    full_versions: list[str],
    expected_version: str,
) -> subprocess.CompletedProcess[str]:
    feed_payload = json.dumps(
        {
            "Assets": [
                {"Type": "Full", "Version": version}
                for version in full_versions
            ]
        }
    ).encode("utf-8")
    github_payload = json.dumps({"tag_name": f"v{expected_version}"}).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", "4")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/feed":
                payload = feed_payload
                content_type = "application/json"
            elif self.path == "/api":
                payload = github_payload
                content_type = "application/json"
            else:
                payload = b"stub"
                content_type = "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        return subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT_PATH),
                "-ExpectedVersion",
                expected_version,
                "-FeedUrl",
                f"{base_url}/feed",
                "-SetupUrl",
                f"{base_url}/setup",
                "-PortableUrl",
                f"{base_url}/portable",
                "-GitHubReleasesUrl",
                f"{base_url}/github",
                "-GitHubApiLatestUrl",
                f"{base_url}/api",
                "-TimeoutSec",
                "5",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_release_monitoring_doc_exists_and_covers_endpoints():
    text = _read_doc()
    assert "本地产物就绪" in text and "线上" in text
    for url in (
        "https://updates.qiaoqiao.buzz/releases/win/stable",
        "https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe",
        "https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip",
        "https://github.com/PEPETII/danmuai/releases",
    ):
        assert url in text
    assert "app_updates" in text
    assert "release_url" in text
    assert "anon key" in text.lower() or "anon key" in text


def test_check_release_endpoints_script_exists():
    assert SCRIPT_PATH.is_file()
    text = _read_script()
    assert "Invoke-WebRequest" in text or "Invoke-RestMethod" in text
    assert "AbortController" not in text  # not applicable; ensure read-only HTTP only
    assert "aws s3 cp" not in text
    assert "R2_SECRET" not in text
    assert "anonKey" not in text
    assert "DANMU_SUPABASE_ANON_KEY" not in text


def test_check_release_endpoints_script_read_only_methods():
    text = _read_script()
    assert re.search(r"ValidateSet\('Head',\s*'Get'\)", text)
    assert "Method Get" in text or "-Method Get" in text
    assert "Method Head" in text or "-Method Head" in text
    assert "FeedLatestFull" in text
    assert "ContentLength" in text
    assert "ExpectedVersion" in text


def test_check_release_endpoints_validates_setup_and_portable_content():
    text = _read_script()
    assert "$MinimumSetupBytes = 8MB" in text
    assert "$MinimumPortableBytes = 8MB" in text
    assert "$ZipTailProbeBytes = 1MB" in text
    assert "function Invoke-BoundedRangeGet" in text
    assert "function Test-SetupEndpoint" in text
    assert "function Test-PortableEndpoint" in text
    assert "Test-ZipPortableLayout" in text


def test_check_release_endpoints_uses_shared_semver_helper():
    text = _read_script()
    assert "version_parse.ps1" in text
    assert "Get-LatestAppSemVersion" in text
    assert "[version]" not in text


def test_check_release_endpoints_script_default_urls():
    text = _read_script()
    assert "https://updates.qiaoqiao.buzz/releases/win/stable" in text
    assert "https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe" in text
    assert "https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip" in text
    assert "https://github.com/PEPETII/danmuai/releases" in text


def test_check_release_endpoints_script_exits_nonzero_on_failure():
    text = _read_script()
    assert "exit 1" in text
    assert "exit 0" in text


@pytest.mark.skipif(sys.platform != "win32", reason="release monitor is Windows-only")
@pytest.mark.parametrize(
    ("full_versions", "expected_version"),
    [
        (["0.4.0-beta.1", "0.4.0-rc.1"], "0.4.0-rc.1"),
        (["0.4.0-beta.1", "0.4.0-rc.1", "0.4.0"], "0.4.0"),
    ],
)
def test_check_release_endpoints_selects_latest_semver(
    full_versions: list[str],
    expected_version: str,
) -> None:
    completed = _run_with_local_endpoints(full_versions, expected_version)
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0, output
    assert f"FeedLatestFull={expected_version}" in output


@pytest.mark.skipif(sys.platform != "win32", reason="release monitor is Windows-only")
def test_check_release_endpoints_rejects_invalid_expected_version() -> None:
    completed = _run_with_local_endpoints(["0.4.0"], "0.4.0+build")
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode != 0
    assert "Invalid version" in output


@pytest.mark.skip(reason="optional live probe; set DANMU_RELEASE_MONITOR_LIVE=1 to enable")
def test_check_release_endpoints_live_smoke_optional():
    """Optional live check; skip unless DANMU_RELEASE_MONITOR_LIVE=1."""
    import os

    if os.environ.get("DANMU_RELEASE_MONITOR_LIVE") != "1":
        pytest.skip("set DANMU_RELEASE_MONITOR_LIVE=1 to run live endpoint probe")

    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT_PATH),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert proc.returncode in (0, 1)
    assert "Feed" in proc.stdout
