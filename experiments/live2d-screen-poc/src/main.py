"""CLI entry for isolated Live2D desktop display POC."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .model_validate import validate_model3
from .window import run_app

LOG = logging.getLogger("live2d_poc")


def _default_artifacts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "artifacts"


def _setup_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _load_config(path: Path | None) -> dict:
    if path is None:
        return {}
    if not path.is_file():
        raise SystemExit(f"config file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"failed to parse config: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("config root must be a JSON object")
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="live2d-screen-poc",
        description="Isolated native Live2D transparent desktop window POC (not DanmuAI).",
    )
    p.add_argument(
        "--model",
        "-m",
        dest="model_path",
        default=None,
        help="Path to .model3.json (required unless set in --config)",
    )
    p.add_argument(
        "--config",
        "-c",
        default=None,
        help="Optional JSON config (see config.example.json)",
    )
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--opacity", type=float, default=None, help="0.05–1.0 window opacity")
    p.add_argument("--scale", type=float, default=None, help="model scale multiplier")
    p.add_argument("--fps", type=int, default=None)
    p.add_argument(
        "--click-through",
        action="store_true",
        default=None,
        help="Start with mouse click-through (recover: Ctrl+Shift+F8)",
    )
    p.add_argument("--no-topmost", action="store_true", help="Disable always-on-top")
    p.add_argument(
        "--no-auto-motion",
        action="store_true",
        help="Do not auto-trigger a motion on start",
    )
    p.add_argument(
        "--no-auto-expression",
        action="store_true",
        help="Do not auto-trigger an expression on start",
    )
    p.add_argument("--motion-group", default=None)
    p.add_argument("--motion-index", type=int, default=None)
    p.add_argument("--expression-id", default=None)
    p.add_argument(
        "--demo-seconds",
        type=float,
        default=0.0,
        help="Auto-close after N seconds (0 = run until user closes)",
    )
    p.add_argument(
        "--cycle-expressions",
        type=float,
        default=0.0,
        help="Auto-cycle expressions every N seconds (0=off)",
    )
    p.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate model paths; do not open a window",
    )
    p.add_argument(
        "--log-file",
        default=None,
        help="Optional log path (default: artifacts/poc.log when artifacts dir exists)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = _load_config(Path(args.config)) if args.config else {}

    model_path = args.model_path or cfg.get("model_path")
    if not model_path:
        print(
            "ERROR: --model is required (or set model_path in --config).\n"
            "Example:\n"
            '  python -m src.main --model "E:\\path\\to\\Model.model3.json" --demo-seconds 8',
            file=sys.stderr,
        )
        return 2

    artifacts = _default_artifacts_dir()
    log_file = (
        Path(args.log_file)
        if args.log_file
        else (artifacts / "poc.log" if artifacts.exists() else None)
    )
    _setup_logging(log_file)

    model = Path(str(model_path)).expanduser()
    LOG.info("validating model: %s", model)
    validation = validate_model3(model)
    print(validation.summary())
    if not validation.ok:
        LOG.error("model validation failed; exiting")
        return 3

    if args.validate_only:
        LOG.info("validate-only: OK")
        return 0

    width = args.width if args.width is not None else int(cfg.get("width", 480))
    height = args.height if args.height is not None else int(cfg.get("height", 720))
    opacity = (
        args.opacity if args.opacity is not None else float(cfg.get("opacity", 1.0))
    )
    scale = args.scale if args.scale is not None else float(cfg.get("scale", 1.0))
    fps = args.fps if args.fps is not None else int(cfg.get("fps", 60))
    click_through = (
        True
        if args.click_through
        else bool(cfg.get("click_through", False))
    )
    topmost = not args.no_topmost and bool(cfg.get("topmost", True))
    auto_motion = not args.no_auto_motion and bool(cfg.get("auto_play_motion", True))
    auto_expr = not args.no_auto_expression and bool(
        cfg.get("auto_play_expression", True)
    )
    motion_group = args.motion_group or cfg.get("motion_group")
    motion_index = (
        args.motion_index
        if args.motion_index is not None
        else int(cfg.get("motion_index", 0))
    )
    expression_id = args.expression_id or cfg.get("expression_id")
    cycle_expressions = float(
        args.cycle_expressions or cfg.get("cycle_expressions", 0) or 0
    )
    demo_seconds = float(args.demo_seconds or cfg.get("demo_seconds", 0) or 0)

    LOG.info(
        "starting window model=%s size=%sx%s opacity=%s scale=%s fps=%s "
        "click_through=%s topmost=%s demo_seconds=%s",
        validation.model_path,
        width,
        height,
        opacity,
        scale,
        fps,
        click_through,
        topmost,
        demo_seconds,
    )
    try:
        code = run_app(
            model_path=validation.model_path,
            width=width,
            height=height,
            opacity=opacity,
            scale=scale,
            fps=fps,
            click_through=click_through,
            topmost=topmost,
            auto_play_motion=auto_motion,
            auto_play_expression=auto_expr,
            cycle_expressions=cycle_expressions,
            motion_group=motion_group,
            motion_index=motion_index,
            expression_id=expression_id,
            demo_seconds=demo_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.exception("run_app failed: %s", exc)
        return 4
    LOG.info("exited with code %s", code)
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
