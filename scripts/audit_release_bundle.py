#!/usr/bin/env python3
"""Audit the runtime resource contract of a PyInstaller onedir bundle.

The audit intentionally checks a small, source-derived contract instead of
requiring every ordinary source file to appear in the distribution. Python
modules normally live in PyInstaller's PYZ archive; static files and native
runtime extensions must remain visible in ``dist/DanmuAI/_internal``.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

BASE_RUNTIME_FILES = (
    "web/static/index.html",
    "web/static/app.js",
    "web/static/utilities.css",
    "web/static/warm-tokens.css",
    "web/static/live-overlay.html",
    "web/static/live-overlay.js",
    "web/static/locales/manifest.json",
    "web/static/floating_panel/index.html",
    "web/static/floating_panel/app.js",
    "web/static/floating_panel/style.css",
    "data/personae_builtin.json",
    "resources/icon.png",
)
ALLOWED_SUPABASE_FILES = frozenset(
    {"supabase-config.example.js", "supabase-client.js"}
)
FORBIDDEN_BUILD_FILES = frozenset(
    {
        "build_index_html.py",
        "index.template.html",
        "tailwindcdn.js",
        "utilities.input.css",
    }
)
USER_DATA_NAMES = frozenset({"config.db", "knowledge.db", ".key"})
NATIVE_SUFFIXES = frozenset({".dll", ".pyd"})


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RuntimeContract:
    required_files: tuple[str, ...]
    required_directories: tuple[str, ...]


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _read_manifest(static_root: Path) -> tuple[str, ...]:
    manifest_path = static_root / "locales" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()

    languages = manifest.get("languages", [])
    shards = manifest.get("shards", [])
    if not isinstance(languages, list) or not isinstance(shards, list):
        return ()
    paths = []
    for language in languages:
        for shard in shards:
            if isinstance(language, str) and isinstance(shard, str):
                paths.append(f"web/static/locales/{language}/{shard}.json")
    return tuple(sorted(paths))


def build_runtime_contract(source_root: Path) -> RuntimeContract:
    """Build the required-file list from the current source tree."""

    source_root = source_root.resolve()
    static_root = source_root / "web" / "static"
    required = set(BASE_RUNTIME_FILES)
    required.update(_read_manifest(static_root))

    modules_root = static_root / "modules"
    if modules_root.is_dir():
        required.update(
            _relative_posix(path, source_root)
            for path in modules_root.rglob("*.js")
            if path.is_file()
        )

    image_root = static_root / "image"
    if image_root.is_dir():
        required.update(
            _relative_posix(path, source_root)
            for path in image_root.rglob("*")
            if path.is_file()
        )

    for suffix in (".woff", ".woff2", ".ttf", ".otf"):
        required.update(
            _relative_posix(path, source_root)
            for path in static_root.rglob(f"*{suffix}")
            if path.is_file()
        )

    directories = (
        "web/static",
        "web/static/locales",
        "web/static/modules",
        "web/static/floating_panel",
        "data",
        "resources",
        "live2d",
        "velopack",
    )
    return RuntimeContract(tuple(sorted(required)), directories)


def _check_required_files(internal_root: Path, contract: RuntimeContract) -> Check:
    missing = [
        path
        for path in contract.required_files
        if not (internal_root / path).is_file()
    ]
    detail = "all source-derived runtime files are present"
    if missing:
        detail = "missing: " + ", ".join(missing)
    return Check("source-derived runtime files", not missing, detail)


def _check_required_directories(
    internal_root: Path, contract: RuntimeContract
) -> Check:
    missing = [
        path
        for path in contract.required_directories
        if not (internal_root / path).is_dir()
    ]
    detail = "all runtime directories are present"
    if missing:
        detail = "missing: " + ", ".join(missing)
    return Check("runtime directory layout", not missing, detail)


def _check_native_runtime(internal_root: Path) -> tuple[Check, Check]:
    native_files = [
        path
        for path in internal_root.rglob("*")
        if path.is_file() and path.suffix.lower() in NATIVE_SUFFIXES
    ]
    native_detail = f"found {len(native_files)} DLL/PYD file(s)"
    native_check = Check("native DLL/PYD coverage", bool(native_files), native_detail)

    velopack = [
        path
        for path in native_files
        if path.name.lower() == "velopack.pyd"
        and "velopack" in {part.lower() for part in path.relative_to(internal_root).parts}
    ]
    live2d = [
        path
        for path in native_files
        if "live2d" in {part.lower() for part in path.relative_to(internal_root).parts}
    ]
    missing = []
    if not velopack:
        missing.append("velopack/velopack.pyd")
    if not live2d:
        missing.append("live2d native DLL/PYD")
    detail = "Velopack and Live2D native runtime files are present"
    if missing:
        detail = "missing: " + ", ".join(missing)
    return native_check, Check("Velopack/Live2D native runtime", not missing, detail)


def _check_forbidden_files(internal_root: Path) -> Check:
    violations = []
    for path in internal_root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        relative = _relative_posix(path, internal_root)
        if "supabase-config" in name and path.name not in ALLOWED_SUPABASE_FILES:
            violations.append(f"credential config: {relative}")
        if path.name in FORBIDDEN_BUILD_FILES:
            violations.append(f"build source: {relative}")
        if path.name.lower() in USER_DATA_NAMES:
            violations.append(f"user data: {relative}")
        if path.suffix.lower() == ".msi":
            violations.append(f"MSI: {relative}")
    detail = "no credential config, build source, user data, or MSI found"
    if violations:
        detail = "; ".join(violations)
    return Check("package safety exclusions", not violations, detail)


def audit_bundle(source_root: Path, dist_dir: Path) -> tuple[Check, ...]:
    """Return checks for a PyInstaller onedir bundle."""

    source_root = source_root.resolve()
    dist_dir = dist_dir.resolve()
    internal_root = dist_dir / "_internal"
    checks = [
        Check(
            "dist directory",
            dist_dir.is_dir(),
            str(dist_dir) if dist_dir.is_dir() else f"missing: {dist_dir}",
        ),
        Check(
            "PyInstaller _internal directory",
            internal_root.is_dir(),
            str(internal_root)
            if internal_root.is_dir()
            else f"missing: {internal_root}",
        ),
    ]
    if not source_root.is_dir() or not internal_root.is_dir():
        return tuple(checks)

    contract = build_runtime_contract(source_root)
    checks.extend(
        (
            _check_required_files(internal_root, contract),
            _check_required_directories(internal_root, contract),
            *_check_native_runtime(internal_root),
            _check_forbidden_files(internal_root),
        )
    )
    return tuple(checks)


def _print_checks(checks: tuple[Check, ...]) -> None:
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"[{status}] {check.name}: {check.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root used to derive the runtime contract",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=None,
        help="PyInstaller onedir directory; defaults to dist/<app name>",
    )
    args = parser.parse_args(argv)
    source_root = args.source_root.resolve()
    dist_dir = args.dist_dir or source_root / "dist" / "DanmuAI"
    checks = audit_bundle(source_root, dist_dir)
    _print_checks(checks)
    passed = all(check.passed for check in checks)
    print("Release bundle audit: " + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
