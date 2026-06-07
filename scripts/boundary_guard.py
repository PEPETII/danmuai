"""Backward-compatible CLI entry: ``python scripts/boundary_guard.py``.

Thin shim that injects the repository root into ``sys.path`` and delegates to
``scripts.boundary_guard.cli.main``. The real CLI lives in
``scripts/boundary_guard/cli.py``; this file exists so that running
``python scripts/boundary_guard.py`` from the repo root still works after the
package was extracted to ``scripts/boundary_guard/``.

Exit codes: ``0`` = PASS, ``1`` = findings emitted.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.boundary_guard.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
