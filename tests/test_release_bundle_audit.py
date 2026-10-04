"""Regression tests for the source-to-dist runtime resource contract."""

from __future__ import annotations

from pathlib import Path

from scripts.audit_release_bundle import audit_bundle, build_runtime_contract


def _write_source_tree(root: Path) -> None:
    static = root / "web" / "static"
    (static / "modules").mkdir(parents=True)
    (static / "locales" / "zh").mkdir(parents=True)
    (static / "locales" / "en").mkdir(parents=True)
    (static / "floating_panel").mkdir(parents=True)
    (static / "image").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "resources").mkdir()

    (static / "locales" / "manifest.json").write_text(
        '{"languages":["zh","en"],"shards":["common"]}', encoding="utf-8"
    )
    (static / "index.html").write_text("<script src='app.js'></script>", encoding="utf-8")
    (static / "app.js").write_text("import './modules/settings.js';", encoding="utf-8")
    (static / "modules" / "settings.js").write_text("export const ok = true;", encoding="utf-8")
    (static / "floating_panel" / "index.html").write_text("fixture", encoding="utf-8")
    (static / "floating_panel" / "app.js").write_text("fixture", encoding="utf-8")
    (static / "floating_panel" / "style.css").write_text("fixture", encoding="utf-8")
    (static / "utilities.css").write_text("fixture", encoding="utf-8")
    (static / "warm-tokens.css").write_text("fixture", encoding="utf-8")
    (static / "live-overlay.html").write_text("fixture", encoding="utf-8")
    (static / "live-overlay.js").write_text("fixture", encoding="utf-8")
    for language in ("zh", "en"):
        (static / "locales" / language / "common.json").write_text("{}", encoding="utf-8")
    (static / "image" / "fixture.png").write_bytes(b"png")
    (root / "data" / "personae_builtin.json").write_text("{}", encoding="utf-8")
    (root / "resources" / "icon.png").write_bytes(b"png")


def _write_valid_bundle(source_root: Path, dist_root: Path) -> None:
    internal = dist_root / "_internal"
    contract = build_runtime_contract(source_root)
    for relative in contract.required_files:
        path = internal / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    (internal / "live2d" / "v3").mkdir(parents=True, exist_ok=True)
    (internal / "live2d" / "v3" / "_v3cpp.pyd").write_bytes(b"native")
    (internal / "velopack").mkdir(parents=True, exist_ok=True)
    (internal / "velopack" / "velopack.pyd").write_bytes(b"native")


def test_audit_accepts_source_derived_runtime_contract(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dist_root = tmp_path / "dist" / "DanmuAI"
    _write_source_tree(source_root)
    _write_valid_bundle(source_root, dist_root)

    checks = audit_bundle(source_root, dist_root)

    assert all(check.passed for check in checks), checks


def test_audit_rejects_missing_static_file_and_credential_config(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dist_root = tmp_path / "dist" / "DanmuAI"
    _write_source_tree(source_root)
    _write_valid_bundle(source_root, dist_root)
    (dist_root / "_internal" / "web" / "static" / "modules" / "settings.js").unlink()
    credential = dist_root / "_internal" / "web" / "static" / "supabase-config.js"
    credential.write_text("secret", encoding="utf-8")

    checks = audit_bundle(source_root, dist_root)

    failed = {check.name: check.detail for check in checks if not check.passed}
    assert "source-derived runtime files" in failed
    assert "package safety exclusions" in failed
    assert "supabase-config.js" in failed["package safety exclusions"]


def test_audit_rejects_missing_native_runtime(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dist_root = tmp_path / "dist" / "DanmuAI"
    _write_source_tree(source_root)
    _write_valid_bundle(source_root, dist_root)
    (dist_root / "_internal" / "live2d" / "v3" / "_v3cpp.pyd").unlink()
    (dist_root / "_internal" / "velopack" / "velopack.pyd").unlink()

    checks = audit_bundle(source_root, dist_root)

    failed = {check.name: check.detail for check in checks if not check.passed}
    assert "native DLL/PYD coverage" in failed
    assert "Velopack/Live2D native runtime" in failed
