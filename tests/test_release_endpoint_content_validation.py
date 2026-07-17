"""BUG-V2-010: release aliases must validate bounded asset content, not only HTTP 2xx."""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.bundle_paths import project_root
from app.packaging_constants import WINDOWS_EXE_NAME

ROOT = project_root()
SCRIPT_PATH = ROOT / "scripts" / "check_release_endpoints.ps1"
MINIMUM_ASSET_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class _Asset:
    total_length: int
    prefix: bytes = b""
    suffix: bytes = b""
    data: bytes | None = None
    supports_range: bool = True
    stall_after_bytes: int | None = None
    stall_seconds: float = 0.0

    def read_range(self, start: int, end: int) -> bytes:
        if self.data is not None:
            return self.data[start : end + 1]
        length = end - start + 1
        result = bytearray(length)
        prefix_end = min(end + 1, len(self.prefix))
        if start < prefix_end:
            source_start = start
            source_end = prefix_end
            result[0 : source_end - source_start] = self.prefix[source_start:source_end]
        suffix_start = self.total_length - len(self.suffix)
        overlap_start = max(start, suffix_start)
        overlap_end = min(end + 1, self.total_length)
        if overlap_start < overlap_end:
            source_start = overlap_start - suffix_start
            source_end = overlap_end - suffix_start
            target_start = overlap_start - start
            result[target_start : target_start + source_end - source_start] = self.suffix[
                source_start:source_end
            ]
        return bytes(result)


def _virtual_asset(prefix: bytes, *, total_length: int = MINIMUM_ASSET_BYTES + 1024) -> _Asset:
    return _Asset(total_length=total_length, prefix=prefix)


@lru_cache(maxsize=2)
def _portable_zip(valid_layout: bool) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        if valid_layout:
            archive.writestr(WINDOWS_EXE_NAME, b"MZ" + b"\0" * 1024)
            archive.writestr("_internal/stub.txt", b"stub")
            padding_name = "_internal/padding.bin"
        else:
            archive.writestr(".portable", b"stub")
            archive.writestr("Update.exe", b"MZstub")
            archive.writestr(f"current/{WINDOWS_EXE_NAME}", b"MZstub")
            padding_name = "current/padding.bin"
        archive.writestr(padding_name, b"\0" * MINIMUM_ASSET_BYTES)
    return output.getvalue()


def _parse_range(value: str, total_length: int) -> tuple[int, int]:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match:
        raise ValueError(f"unsupported Range: {value}")
    start_text, end_text = match.groups()
    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else total_length - 1
    else:
        suffix_length = int(end_text)
        start = max(0, total_length - suffix_length)
        end = total_length - 1
    return start, min(end, total_length - 1)


def _run_monitor(
    setup: _Asset,
    portable: _Asset,
    *,
    timeout_sec: int = 5,
) -> subprocess.CompletedProcess[str]:
    feed_payload = json.dumps(
        {"Assets": [{"Type": "Full", "Version": "0.4.0"}]}
    ).encode("utf-8")
    github_payload = json.dumps({"tag_name": "v0.4.0"}).encode("utf-8")
    assets = {"/setup": setup, "/portable": portable}

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:  # noqa: N802
            asset = assets.get(self.path)
            if asset is not None:
                self.send_response(200)
                self.send_header("Content-Length", str(asset.total_length))
                if asset.supports_range:
                    self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return
            payload = b"stub"
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            asset = assets.get(self.path)
            if asset is not None:
                range_value = self.headers.get("Range")
                if range_value and asset.supports_range:
                    start, end = _parse_range(range_value, asset.total_length)
                    payload = asset.read_range(start, end)
                    self.send_response(206)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{asset.total_length}")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    split_at = asset.stall_after_bytes
                    if split_at is None:
                        self.wfile.write(payload)
                    else:
                        split_at = max(0, min(split_at, len(payload)))
                        self.wfile.write(payload[:split_at])
                        self.wfile.flush()
                        time.sleep(asset.stall_seconds)
                        try:
                            self.wfile.write(payload[split_at:])
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    return
                payload = asset.data or asset.read_range(0, asset.total_length - 1)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

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
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        started = time.monotonic()
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT_PATH),
                "-ExpectedVersion",
                "0.4.0",
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
                str(timeout_sec),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        completed.monitor_elapsed = time.monotonic() - started
        return completed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _output(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stdout or "") + (completed.stderr or "")


@pytest.mark.skipif(sys.platform != "win32", reason="release monitor is Windows-only")
@pytest.mark.parametrize("prefix", [b'{"Assets":[]}', b"<!doctype html>"])
def test_rejects_text_masquerading_as_setup_and_portable(prefix: bytes) -> None:
    completed = _run_monitor(_virtual_asset(prefix), _virtual_asset(prefix))
    output = _output(completed)
    assert completed.returncode != 0
    assert "Setup content invalid" in output
    assert "Portable content invalid" in output


@pytest.mark.skipif(sys.platform != "win32", reason="release monitor is Windows-only")
def test_accepts_valid_mz_and_portable_zip_structure() -> None:
    portable = _portable_zip(True)
    completed = _run_monitor(
        _virtual_asset(b"MZ"),
        _Asset(total_length=len(portable), data=portable),
    )
    output = _output(completed)
    assert completed.returncode == 0, output
    assert "MZ valid" in output
    assert "ZIP layout valid" in output


@pytest.mark.skipif(sys.platform != "win32", reason="release monitor is Windows-only")
def test_rejects_valid_magic_below_minimum_size() -> None:
    portable = _portable_zip(True)
    completed = _run_monitor(
        _virtual_asset(b"MZ", total_length=1024),
        _Asset(total_length=len(portable), data=portable),
    )
    output = _output(completed)
    assert completed.returncode != 0
    assert "Setup content invalid" in output
    assert "too small" in output


@pytest.mark.skipif(sys.platform != "win32", reason="release monitor is Windows-only")
def test_rejects_velopack_portable_stub_layout() -> None:
    portable = _portable_zip(False)
    completed = _run_monitor(
        _virtual_asset(b"MZ"),
        _Asset(total_length=len(portable), data=portable),
    )
    output = _output(completed)
    assert completed.returncode != 0
    assert "Portable content invalid" in output
    assert "layout" in output.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="release monitor is Windows-only")
def test_fails_closed_when_range_is_unsupported() -> None:
    setup_data = b"MZ" + b"\0" * MINIMUM_ASSET_BYTES
    portable = _portable_zip(True)
    completed = _run_monitor(
        _Asset(
            total_length=len(setup_data),
            data=setup_data,
            supports_range=False,
        ),
        _Asset(total_length=len(portable), data=portable),
    )
    output = _output(completed)
    assert completed.returncode != 0
    assert "Setup content invalid" in output
    assert "Range" in output


@pytest.mark.skipif(sys.platform != "win32", reason="release monitor is Windows-only")
def test_range_body_read_respects_timeout() -> None:
    portable = _portable_zip(True)
    completed = _run_monitor(
        _Asset(
            total_length=MINIMUM_ASSET_BYTES + 1024,
            prefix=b"MZ",
            stall_after_bytes=1,
            stall_seconds=15,
        ),
        _Asset(total_length=len(portable), data=portable),
        timeout_sec=1,
    )
    elapsed = completed.monitor_elapsed
    output = _output(completed)
    assert completed.returncode != 0
    assert "Setup content invalid" in output
    assert elapsed < 12, f"bounded read ignored TimeoutSec: elapsed={elapsed:.2f}s\n{output}"
