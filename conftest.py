"""Project-root pytest hooks (loaded before tests/conftest.py)."""

import os
from pathlib import Path

_workspace_tmp = (Path(__file__).resolve().parent / ".pytest_tmp").resolve()
_workspace_tmp.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = str(_workspace_tmp)
os.environ["TEMP"] = str(_workspace_tmp)
os.environ["TMPDIR"] = str(_workspace_tmp)
