"""Keep catalog-only CI independent from desktop/runtime dependencies."""

from __future__ import annotations

from app.bundle_paths import project_root
from packaging.requirements import Requirement


def requirements(path):
    return [
        Requirement(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_audit_uses_only_httpx_with_the_runtime_version_constraint():
    root = project_root()
    audit = requirements(root / "requirements-model-audit.txt")
    runtime = requirements(root / "requirements.txt")
    assert len(audit) == 1
    assert audit[0].name == "httpx"
    assert not audit[0].extras
    assert audit[0].specifier == next(req.specifier for req in runtime if req.name == "httpx")


def test_scheduled_audit_installs_only_its_requirements_file():
    workflow = (project_root() / ".github/workflows/model-catalog-audit.yml").read_text(encoding="utf-8")
    assert "pip install -r requirements-model-audit.txt" in workflow
    assert "pip install -r requirements.txt" not in workflow
    assert "cache-dependency-path: requirements-model-audit.txt" in workflow
