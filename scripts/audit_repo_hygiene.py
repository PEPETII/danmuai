"""Fail-closed checks for files and credentials that must stay out of Git.

The audit intentionally scans the Git index rather than the whole checkout so
CI checks the public change set and does not read developers' local databases or
virtual environments.  Findings never include matched secret values.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 1024 * 1024

LOCAL_SEGMENTS = {
    ".agents",
    ".ai-notes",
    ".claude",
    ".codex",
    ".cursor",
    ".idea",
    ".local-ai",
    ".local-ide",
    ".trae",
    ".vscode",
    "ai-workspace",
    "experiments",
    "prototype",
    "references",
}

FORBIDDEN_SUFFIXES = {
    ".cer",
    ".crt",
    ".dump",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".session",
    ".sqlite",
    ".sqlite3",
    ".trace",
}

TOKEN_PATTERNS = (
    (
        "openai/deepseek-style key",
        re.compile(
            rb"(?<![A-Za-z0-9])sk-(?!(?:ant-|test(?:[-_]|$)|fake(?:[-_]|$)|"
            rb"mock(?:[-_]|$)|example(?:[-_]|$)|placeholder(?:[-_]|$)|"
            rb"dummy(?:[-_]|$)|redacted(?:[-_]|$)))[A-Za-z0-9_-]{16,}"
        ),
    ),
    (
        "anthropic-style key",
        re.compile(rb"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{16,}"),
    ),
    ("google API key", re.compile(rb"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{20,}")),
    ("AWS access key", re.compile(rb"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])")),
    (
        "GitHub token",
        re.compile(rb"(?<![A-Za-z0-9])(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    ),
    ("Slack token", re.compile(rb"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{16,}")),
    (
        "JWT",
        re.compile(
            rb"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
            rb"\.[A-Za-z0-9_-]{8,}"
        ),
    ),
    (
        "Bearer token",
        re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    ),
)

SENSITIVE_ASSIGNMENT = re.compile(
    rb"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|"
    rb"webhook[_-]?secret|private[_-]?key|password)\b\s*[:=]\s*"
    rb"(['\"])([^'\"\r\n]{16,})\1"
)
PRIVATE_KEY_MARKER = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
PLACEHOLDER_WORDS = (
    "change-me",
    "changeme",
    "dummy",
    "example",
    "fake",
    "masked",
    "mock",
    "none",
    "null",
    "placeholder",
    "redacted",
    "replace",
    "secret",
    "test",
    "token",
    "your-",
    "your_",
    "xxxx",
)


def git_bytes(*args: str) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def git_paths(*args: str) -> list[str]:
    return [
        item.decode("utf-8", "surrogateescape").replace("\\", "/")
        for item in git_bytes(*args, "-z").split(b"\0")
        if item
    ]


def is_test_path(path: str) -> bool:
    parts = path.lower().split("/")
    return "tests" in parts or "fixtures" in parts or Path(path).name.lower().startswith("test_")


def is_local_path(path: str) -> bool:
    normalized = path.lower()
    parts = normalized.split("/")
    name = parts[-1]
    if name == "agents.md":
        return True
    if any(part in LOCAL_SEGMENTS for part in parts):
        return True
    if normalized.startswith("workorders/local/") or normalized.startswith("reports/local/"):
        return True
    if normalized.startswith("reports/"):
        return True
    if name.endswith(("-completion-report.md", "-completion.md", "-workorder.md", ".prompt.md")):
        return True
    return False


def forbidden_path_reason(path: str) -> str | None:
    name = Path(path).name.lower()
    suffix = Path(name).suffix
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return ".env file"
    if suffix in FORBIDDEN_SUFFIXES:
        return f"forbidden extension {suffix}"
    if re.search(r"(?:\.db(?:[-.]|$)|\.sqlite(?:[-.]|$))", name):
        return "database file"
    if re.fullmatch(r"credentials[^/]*\.(?:json|ini|toml|txt|yaml|yml)", name):
        return "credential data file"
    if re.fullmatch(r"secrets?[^/]*\.(?:json|ini|toml|txt|yaml|yml)", name):
        return "secret data file"
    if re.fullmatch(r".*_(?:secret|credentials)\.(?:json|ini|toml|txt|yaml|yml)", name):
        return "credential data file"
    return None


def entropy(value: bytes) -> float:
    counts = {byte: value.count(bytes([byte])) for byte in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def is_placeholder(value: bytes, path: str) -> bool:
    if is_test_path(path):
        return True
    text = value.decode("utf-8", "ignore").lower()
    return any(word in text for word in PLACEHOLDER_WORDS)


def fingerprint(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()[:12]


def scan_content(path: str, findings: set[tuple[str, str, str]], allowed_tests: list[int]) -> None:
    full_path = ROOT / path
    carry = b""
    try:
        with full_path.open("rb") as stream:
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                window = carry + chunk
                for label, pattern in TOKEN_PATTERNS:
                    for match in pattern.finditer(window):
                        value = match.group(0)
                        if is_test_path(path) or is_placeholder(value, path):
                            allowed_tests[0] += 1
                            continue
                        findings.add((path, label, fingerprint(value)))
                for match in SENSITIVE_ASSIGNMENT.finditer(window):
                    value = match.group(2)
                    if is_placeholder(value, path) or entropy(value) < 3.2:
                        continue
                    findings.add((path, "high-entropy sensitive assignment", fingerprint(value)))
                if PRIVATE_KEY_MARKER.search(window):
                    findings.add((path, "private key marker", "content-marker"))
                carry = window[-1024:]
    except OSError as exc:
        findings.add((path, "unreadable tracked file", type(exc).__name__))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-size-mib",
        type=float,
        default=5.0,
        help="fail for tracked files larger than this size (default: 5 MiB)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_size_mib <= 0:
        print("--max-size-mib must be positive", file=sys.stderr)
        return 2

    try:
        tracked = sorted(set(git_paths("ls-files", "--cached")))
        tracked_ignored = sorted(set(git_paths("ls-files", "-c", "-i", "--exclude-standard")))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    findings: set[tuple[str, str, str]] = set()
    allowed_tests = [0]
    max_bytes = int(args.max_size_mib * 1024 * 1024)

    for path in tracked:
        full_path = ROOT / path
        try:
            size = full_path.stat().st_size
        except OSError as exc:
            findings.add((path, "unreadable tracked file", type(exc).__name__))
            continue
        if size > max_bytes:
            findings.add((path, "large tracked file", f"{size} bytes"))
        reason = forbidden_path_reason(path)
        if reason:
            findings.add((path, "forbidden tracked path", reason))
        if is_local_path(path):
            findings.add((path, "local/AI artifact path", "must remain untracked"))
        scan_content(path, findings, allowed_tests)

    for path in tracked_ignored:
        findings.add((path, "tracked-but-ignored", "review index and .gitignore"))

    print(f"Repository hygiene audit: tracked_files={len(tracked)}")
    print(f"Allowed test/mock credential literals: {allowed_tests[0]}")
    if findings:
        print(f"FAIL: {len(findings)} finding(s)")
        for path, category, detail in sorted(findings):
            print(f"- {category}: {path} ({detail})")
        return 1
    print("PASS: no forbidden tracked files or high-confidence credentials found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
