from __future__ import annotations

from pathlib import Path

from tests.boundary_guard_helpers import _baseline_repo, _write, run_boundary_guard


def test_boundary_guard_detects_virtual_host_qt_import_in_scheduler(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/virtual_host/response_scheduler.py",
        "from PyQt6.QtCore import QObject\n",
    )
    findings = run_boundary_guard(repo)
    assert any(
        item.rule == "virtual-host-module-boundary"
        and "response_scheduler.py" in item.path
        for item in findings
    )


def test_boundary_guard_detects_direct_start_turn_in_batch_handler(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/virtual_host/runtime_service.py",
        "    def on_danmu_batch_created(self, batch):\n        self._session.start_turn('x')\n",
    )
    findings = run_boundary_guard(repo)
    assert any(
        item.rule == "virtual-host-response-scheduler"
        and "runtime_service.py" in item.path
        for item in findings
    )
