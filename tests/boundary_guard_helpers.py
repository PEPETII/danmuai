from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from scripts.boundary_guard import run_boundary_guard


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _baseline_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    _write(
        repo,
        "main.py",
        """
        from app.application.config_service import apply_web_config_patch
        from app.application.status_snapshot import StatusSnapshotBuilder

        class DanmuApp:
            def __init__(self):
                self.web_server = None
                self._web_error_message = ""

            def build_status_snapshot(self):
                return StatusSnapshotBuilder(self).build()

            def apply_web_config_payload(self, payload):
                apply_web_config_patch(self, payload)
        """,
    )
    _write(
        repo,
        "app/application/status_snapshot.py",
        """
        class StatusSnapshotBuilder:
            def __init__(self, app):
                self.app = app

            def build(self):
                return {"running": False}
        """,
    )
    _write(
        repo,
        "app/application/config_service.py",
        """
        def apply_web_config_patch(app, payload):
            return None

        def set_default_model_selection(config, model_id):
            return model_id
        """,
    )
    _write(
        repo,
        "app/web_console.py",
        """
        from app.application.config_service import apply_web_config_patch

        def apply_config_patch(danmu_app, payload):
            apply_web_config_patch(danmu_app, payload)

        class WebConsoleBridge:
            def __init__(self, danmu_app):
                self.danmu_app = danmu_app

            def refresh_status(self):
                snapshot = self.danmu_app.build_status_snapshot()
                return snapshot
        """,
    )
    _write(
        repo,
        "app/web_api/routes.py",
        """
        def register_web_routes(app, bridge, check_token):
            def _danmu():
                return bridge.danmu_app

            def mic_test():
                return _danmu().run_mic_test(3.0, send_to_ai=False)
        """,
    )
    _write(
        repo,
        "app/web_api/custom_models.py",
        """
        from app.application.config_service import set_default_model_selection

        def delete_custom_model(app, index):
            set_default_model_selection(app.config, "fallback")

        def set_default_custom_model(app, index):
            set_default_model_selection(app.config, "default")
            return {"default_model_id": "default"}
        """,
    )
    _write(
        repo,
        "docs/runtime-state-map.md",
        """
        # Runtime State Map

        - `web_server`
        - `_web_error_message`
        """,
    )
    _write(
        repo,
        "docs/main-pipeline-sequence.md",
        """
        # Main Pipeline Sequence

        baseline
        """,
    )
    _write(
        repo,
        "docs/phase1-boundary-rules.md",
        """
        # Phase 1 Boundary Rules
        """,
    )
    _write(
        repo,
        "docs/final-architecture-baseline.md",
        """
        # Final Architecture Baseline
        """,
    )
    _write(
        repo,
        "app/application/generation_pipeline.py",
        """
        class GenerationPipeline:
            pass
        """,
    )

    _git(repo, "init")
    _git(repo, "config", "user.name", "Codex")
    _git(repo, "config", "user.email", "codex@example.com")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    return repo


__all__ = ["_baseline_repo", "_write", "run_boundary_guard"]
