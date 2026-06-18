#!/usr/bin/env python3
"""Audit DanmuAI.spec hiddenimports against deferred/lazy runtime imports.

Scans app/**/*.py and main.py for imports inside functions (and known lazy
third-party imports), then compares against string literals in DanmuAI.spec.

Exit 0 when CRITICAL_DEFERRED_IMPORTS are all covered; exit 1 otherwise.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "DanmuAI.spec"
SCAN_PATHS = [ROOT / "main.py", ROOT / "app"]

# Deferred app modules that must stay in DanmuAI.spec (frozen smoke failures without them).
CRITICAL_DEFERRED_IMPORTS: frozenset[str] = frozenset(
    {
        "app.web_api.live_overlay",
        "app.uninstall_service",
        "app.font_registry",
        "app.pet.pet_window",
        "app.pet.pet_barrage",
        "app.pet.pet_command_service",
        "app.pet.pet_facade",
        "app.pet.pet_assets",
    }
)

# Lazy third-party packages used on optional runtime paths.
CRITICAL_LAZY_THIRD_PARTY: frozenset[str] = frozenset(
    {
        "keyboard",
        "dashscope",
        "dashscope.audio.qwen_tts_realtime",
    }
)

_LAZY_THIRD_PARTY_RE = re.compile(
    r"^\s*(?:import\s+(\w+)|from\s+([\w.]+)\s+import)",
    re.MULTILINE,
)


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for base in SCAN_PATHS:
        if base.is_file():
            files.append(base)
        else:
            files.extend(sorted(base.rglob("*.py")))
    return files


def _function_depth(node: ast.AST, ancestors: tuple[type, ...]) -> int:
    return sum(1 for t in ancestors if t in (ast.FunctionDef, ast.AsyncFunctionDef))


class _DeferredImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.app_modules: set[str] = set()
        self._ancestors: list[type] = []

    def visit(self, node: ast.AST) -> None:
        self._ancestors.append(type(node))
        super().visit(node)
        self._ancestors.pop()

    def visit_Import(self, node: ast.Import) -> None:
        if _function_depth(node, tuple(self._ancestors)) == 0:
            return
        for alias in node.names:
            name = alias.name
            if name == "app" or name.startswith("app."):
                self.app_modules.add(name)
            elif name in {"dashscope", "keyboard", "velopack"}:
                self.app_modules.add(name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if _function_depth(node, tuple(self._ancestors)) == 0:
            return
        if not node.module:
            return
        module = node.module
        if module == "app" or module.startswith("app."):
            self.app_modules.add(module)
        elif module.startswith("dashscope"):
            self.app_modules.add(module)
        elif module in {"keyboard", "velopack"}:
            self.app_modules.add(module)


def scan_deferred_imports() -> set[str]:
    found: set[str] = set()
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        visitor = _DeferredImportVisitor()
        visitor.visit(tree)
        found.update(visitor.app_modules)
    return found


def parse_spec_hiddenimports(spec_text: str) -> set[str]:
    """Extract string literal entries from hiddenimports list (ignores collect_submodules)."""
    entries: set[str] = set()
    in_block = False
    for line in spec_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("hiddenimports:"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("]"):
                break
            if stripped.startswith('"') or stripped.startswith("'"):
                match = re.match(r'^["\']([^"\']+)["\']', stripped)
                if match:
                    entries.add(match.group(1))
    return entries


def missing_critical(spec_entries: set[str]) -> tuple[set[str], set[str]]:
    missing_app = {m for m in CRITICAL_DEFERRED_IMPORTS if m not in spec_entries}
    missing_3p = {m for m in CRITICAL_LAZY_THIRD_PARTY if m not in spec_entries}
    return missing_app, missing_3p


def main() -> int:
    if not SPEC_PATH.is_file():
        print(f"ERROR: missing {SPEC_PATH}", file=sys.stderr)
        return 2

    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    spec_entries = parse_spec_hiddenimports(spec_text)
    deferred = scan_deferred_imports()

    missing_app, missing_3p = missing_critical(spec_entries)
    uncovered_deferred = sorted(
        m for m in deferred if m.startswith("app.") and m not in spec_entries
    )

    print("=== DanmuAI.spec hiddenimports audit ===")
    print(f"Spec entries (literals): {len(spec_entries)}")
    print(f"Deferred app imports found: {len([m for m in deferred if m.startswith('app.')])}")
    print()

    if missing_app or missing_3p:
        print("CRITICAL gaps (must be in DanmuAI.spec):")
        for name in sorted(missing_app | missing_3p):
            print(f"  - {name}")
        print()
    else:
        print("CRITICAL gaps: none")

    if uncovered_deferred:
        print("Other deferred app.* not in spec (informational):")
        for name in uncovered_deferred[:40]:
            print(f"  - {name}")
        if len(uncovered_deferred) > 40:
            print(f"  ... and {len(uncovered_deferred) - 40} more")
        print()

    return 1 if (missing_app or missing_3p) else 0


if __name__ == "__main__":
    raise SystemExit(main())
