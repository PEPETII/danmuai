"""Exercise the spec's real static-data collection without building an EXE."""

from __future__ import annotations

import ast
from pathlib import Path

from app.bundle_paths import project_root

SPEC = project_root() / "DanmuAI.spec"


def collect_static_datas(root: Path) -> list[tuple[str, str]]:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    helpers = []
    collect_call = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_ALLOWED_SUPABASE_FILES"
            for target in node.targets
        ):
            helpers.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "_should_exclude_supabase_config", "_collect_dir_datas"
        }:
            helpers.append(node)
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_collect_dir_datas"
            and any(isinstance(arg, ast.Constant) and arg.value == "web/static" for arg in node.value.args)
        ):
            collect_call = node.value
    assert collect_call is not None
    namespace = {"Path": Path, "root": root}
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(SPEC), "exec"), namespace)
    return eval(compile(ast.Expression(collect_call), str(SPEC), "eval"), namespace)


def test_static_datas_keep_runtime_assets_and_reject_build_sources_and_credentials(tmp_path):
    keep = {
        "index.html", "app.js", "warm-tokens.css", "utilities.css", "live-overlay.html", "live-overlay.js",
        "locales/zh.json", "modules/settings.js", "previews/style.png",
        "vendor/live2d/cubismcore.js", "supabase-config.example.js", "supabase-client.js",
    }
    reject = {
        "partials/settings.html", "partials/nested/page.html", "index.template.html",
        "build_index_html.py", "utilities.input.css", "tailwindcdn.js", "__pycache__/build_index_html.cpython-312.pyc",
        "modules/__pycache__/unrelated.dat", "temporary.pyc", "temporary.pyo",
        "supabase-config.js", "supabase-config.js.backup", "SUPABASE-CONFIG-LOCAL.JS",
        "modules/my-supabase-config.js",
    }
    static = tmp_path / "web/static"
    for relative in keep | reject:
        path = static / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")

    entries = collect_static_datas(tmp_path)
    included = {Path(source).relative_to(static).as_posix() for source, _ in entries}
    assert included == keep
    for source, destination in entries:
        relative_parent = Path(source).relative_to(static).parent
        expected = "web/static" if relative_parent == Path(".") else f"web/static/{relative_parent.as_posix()}"
        assert destination == expected


def test_repository_static_datas_include_all_existing_runtime_files():
    root = project_root()
    static = root / "web/static"
    entries = collect_static_datas(root)
    included = {Path(source).relative_to(static).as_posix() for source, _ in entries}
    required = {"index.html", "app.js", "live-overlay.html", "live-overlay.js", "warm-tokens.css", "utilities.css"}
    required.update(path.relative_to(static).as_posix() for path in (static / "locales").rglob("*.json"))
    required.update(path.relative_to(static).as_posix() for path in (static / "vendor").rglob("*") if path.is_file())
    assert required <= included
    assert not any(path.startswith("partials/") or "__pycache__" in path for path in included)
    assert "index.template.html" not in included
    assert "build_index_html.py" not in included
    assert not any(Path(path).suffix.lower() in {".pyc", ".pyo"} for path in included)
