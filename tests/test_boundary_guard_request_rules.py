from __future__ import annotations

from pathlib import Path

from tests.boundary_guard_helpers import _baseline_repo, _write, run_boundary_guard


def test_boundary_guard_detects_generation_pipeline_writeback_and_forbidden_tokens(
    tmp_path: Path,
) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/generation_pipeline_state.py",
        """
        from PyQt6.QtCore import QTimer

        class GenerationPipelineState:
            @classmethod
            def from_app(cls, app):
                app._latest_displayed_round = 3
                return {
                    "timer": QTimer(),
                    "ai_in_flight": app.ai_in_flight,
                }
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("read-only" in finding.message for finding in findings)
    assert any("QTimer" in finding.message for finding in findings)
    assert any("ai_in_flight" in finding.message for finding in findings)


def test_boundary_guard_detects_generation_pipeline_main_pipeline_call(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/generation_pipeline_state.py",
        """
        class GenerationPipelineState:
            @classmethod
            def from_app(cls, app):
                app._trigger_api_call()
                return cls()
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("main pipeline functions" in finding.message for finding in findings)


def test_boundary_guard_detects_runtime_state_projection_bypass(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/runtime_state.py",
        """
        class RuntimeState:
            @classmethod
            def from_app(cls, app):
                return {
                    "latest_displayed_round": getattr(app, "_latest_displayed_round", 0),
                }
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("GenerationPipelineState.from_app()" in finding.message for finding in findings)
    assert any("must not bypass GenerationPipelineState" in finding.message for finding in findings)


def test_boundary_guard_detects_application_layer_private_field_read(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/diagnostic_snapshot.py",
        """
        class DiagnosticSnapshotBuilder:
            def build(self):
                recorder = self._app.__dict__.get("_danmu_diagnostics")
                return {"recorder": recorder}
        """,
    )

    findings = run_boundary_guard(repo)

    assert any(
        "application/ must not read DanmuApp private fields" in finding.message
        for finding in findings
    )


def test_boundary_guard_detects_request_metadata_state_regression(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/request_metadata_state.py",
        """
        from PyQt6.QtCore import QTimer

        class RequestMetadataState:
            @classmethod
            def from_app(cls, app):
                app._api_schedule_block_reason()
                return {
                    "timer": QTimer(),
                    "last_api_trigger_at": app._last_api_trigger_at,
                    "request_started_at_by_id": app._request_started_at_by_id,
                    "reply_buffer": app.reply_buffer,
                }
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("RequestMetadataState" in finding.message for finding in findings)
    assert any("_last_api_trigger_at" in finding.message for finding in findings)
    assert any("_request_started_at_by_id" in finding.message for finding in findings)


def test_boundary_guard_detects_request_metadata_field_in_stats_state(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/stats_state.py",
        """
        class StatsState:
            def __init__(self, app):
                self.last_api_trigger_at = app._last_api_trigger_at
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("StatsState" in finding.message for finding in findings)
    assert any("_last_api_trigger_at" in finding.message for finding in findings)


def test_boundary_guard_detects_request_metadata_field_in_web_runtime_state(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/web_runtime_state.py",
        """
        class WebRuntimeState:
            def __init__(self, app):
                self.request_started_at_by_id = app._request_started_at_by_id
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("WebRuntimeState" in finding.message for finding in findings)
    assert any("_request_started_at_by_id" in finding.message for finding in findings)


def test_boundary_guard_detects_web_api_request_metadata_exposure(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/web_api/routes.py",
        """
        def register_web_routes(app, bridge, check_token):
            danmu_app = bridge.danmu_app
            return {
                "last_api_trigger_at": danmu_app._last_api_trigger_at,
            }
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("diagnostic snapshot" in finding.message for finding in findings)


def test_boundary_guard_detects_web_api_request_started_at_exposure(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/web_api/routes.py",
        """
        def register_web_routes(app, bridge, check_token):
            danmu_app = bridge.danmu_app
            return {
                "request_started_at_by_id": danmu_app._request_started_at_by_id,
            }
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("_request_started_at_by_id" in finding.message for finding in findings)
    assert any("diagnostic snapshot" in finding.message for finding in findings)


def test_boundary_guard_detects_rtt_history_field_in_stats_state(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/stats_state.py",
        """
        class StatsState:
            def __init__(self, app):
                self.rtt_history = app._rtt_history
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("StatsState" in finding.message for finding in findings)
    assert any("_rtt_history" in finding.message for finding in findings)


def test_boundary_guard_detects_rtt_history_field_in_web_runtime_state(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/web_runtime_state.py",
        """
        class WebRuntimeState:
            def __init__(self, app):
                self.rtt_history = app._rtt_history
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("WebRuntimeState" in finding.message for finding in findings)
    assert any("_rtt_history" in finding.message for finding in findings)


def test_boundary_guard_detects_web_api_rtt_history_exposure(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/web_api/routes.py",
        """
        def register_web_routes(app, bridge, check_token):
            danmu_app = bridge.danmu_app
            return {
                "rtt_history": danmu_app._rtt_history,
            }
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("_rtt_history" in finding.message for finding in findings)
    assert any("diagnostic snapshot" in finding.message for finding in findings)


def test_boundary_guard_detects_request_scheduler_regression(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/request_scheduler.py",
        """
        from app.overlay import DanmuOverlay
        from PyQt6.QtCore import QTimer

        class RequestScheduler:
            def __init__(self, app):
                self.app = app
                self.reply_buffer = app.reply_buffer
                self._scene_generation = app._scene_generation

            def should_fire(self, app):
                app._trigger_api_call()
                app._on_ai_reply()
                app._consume_reply_queue()
                return QTimer()
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("RequestScheduler" in finding.message for finding in findings)
    assert any("reply_buffer" in finding.message for finding in findings)
    assert any("QTimer" in finding.message for finding in findings)
    assert any("God Object" in finding.message for finding in findings)
    assert any("overlay" in finding.message for finding in findings)


def test_boundary_guard_detects_request_timing_service_regression(tmp_path: Path) -> None:
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/request_timing_service.py",
        """
        from app.danmu_engine import DanmuEngine
        from PyQt6.QtCore import QThreadPool

        class RequestTimingService:
            def __init__(self, app):
                self.danmu_app = app
                self.danmu_queue = app.danmu_queue
                self.overlay = app.overlay

            def consume(self, app):
                app._trigger_api_call()
                app._consume_reply_queue()
                return QThreadPool()
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("RequestTimingService" in finding.message for finding in findings)
    assert any("danmu_queue" in finding.message for finding in findings)
    assert any("Overlay" in finding.message for finding in findings)
    assert any("God Object" in finding.message for finding in findings)
    assert any("DanmuEngine" in finding.message for finding in findings)


def test_boundary_guard_allows_generation_pipeline_reply_timer_start(tmp_path: Path) -> None:
    """generation_pipeline.py 调用 reply_timer.start 不报错（允许的委托模式）。"""
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/generation_pipeline.py",
        """
        class GenerationPipeline:
            def __init__(self, app):
                self._app = app

            def consume_reply_queue(self):
                self._app.reply_timer.start(100)
        """,
    )

    findings = run_boundary_guard(repo)

    assert not any("generation-pipeline-service" in finding.rule for finding in findings)


def test_boundary_guard_detects_generation_pipeline_forbidden_qtimer_instantiation(
    tmp_path: Path,
) -> None:
    """generation_pipeline.py 实例化 QTimer() 报错（所有权属 DanmuApp）。"""
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/generation_pipeline.py",
        """
        from PyQt6.QtCore import QTimer

        class GenerationPipeline:
            def consume_reply_queue(self):
                self._timer = QTimer()
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("QTimer" in finding.message for finding in findings)
    assert any("generation-pipeline-service" in finding.rule for finding in findings)


def test_boundary_guard_detects_generation_pipeline_trigger_api_call(tmp_path: Path) -> None:
    """generation_pipeline.py 调用 _trigger_api_call 报错（主链路触发仍属 DanmuApp）。"""
    repo = _baseline_repo(tmp_path)
    _write(
        repo,
        "app/application/generation_pipeline.py",
        """
        class GenerationPipeline:
            def __init__(self, app):
                self._app = app

            def consume_reply_queue(self):
                self._app._trigger_api_call()
        """,
    )

    findings = run_boundary_guard(repo)

    assert any("main pipeline trigger functions" in finding.message for finding in findings)
    assert any("generation-pipeline-service" in finding.rule for finding in findings)
