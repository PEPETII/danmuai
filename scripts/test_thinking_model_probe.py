"""Probe doubao-seed-1-6-thinking-250715 on Volcengine Ark Responses API.

Compares DanmuAI default (thinking disabled) vs thinking model without that flag.
Reads API key from: --api-key, ARK_API_KEY, DANMU_API_KEY, or %APPDATA%/DanmuAI config.db.

Usage:
  python scripts/test_thinking_model_probe.py
  python scripts/test_thinking_model_probe.py --model doubao-seed-1-6-flash-250828
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.doubao_responses_stream import parse_doubao_json_body, stream_doubao_responses
from app.providers.constants import THINKING_DISABLED

DEFAULT_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seed-1-6-thinking-250715"

# 1x1 red JPEG
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAb/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/"
    "8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX/9k="
)
TINY_IMAGE_URI = f"data:image/jpeg;base64,{TINY_JPEG_B64}"


def resolve_api_key(cli_key: str) -> str:
    key = (cli_key or os.getenv("ARK_API_KEY") or os.getenv("DANMU_API_KEY") or "").strip()
    if key:
        return key
    try:
        from app.config_store import ConfigStore

        store = ConfigStore()
        return (store.get_api_key() or "").strip()
    except (OSError, RuntimeError, ImportError) as exc:
        print(f"[warn] could not read ConfigStore: {exc}")
        return ""


def build_payload(
    model: str,
    *,
    with_image: bool,
    thinking_mode: str,
) -> dict:
    content: list[dict] = []
    if with_image:
        content.append({"type": "input_image", "image_url": TINY_IMAGE_URI})
    content.append({"type": "input_text", "text": "用一句话描述你看到了什么，只输出一句中文。"})

    data: dict = {
        "model": model,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": content,
            }
        ],
        "stream": True,
        "max_output_tokens": 256,
        "temperature": 0.8,
    }
    if thinking_mode == "disabled":
        data["thinking"] = dict(THINKING_DISABLED)
    elif thinking_mode == "enabled":
        data["thinking"] = {"type": "enabled"}
    # thinking_mode == "omit": do not send thinking field
    return data


def call_responses(
    endpoint: str,
    api_key: str,
    data: dict,
    *,
    timeout_sec: float,
) -> dict:
    url = f"{endpoint.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    client = httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=10.0))
    try:
        result = stream_doubao_responses(client, url, headers, data)
    finally:
        client.close()

    return {
        "text": (result.text or "").strip(),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "error": (result.error or "").strip(),
        "reasoning_only": result.reasoning_only,
        "stream_events": result.stream_events[:12],
    }


def run_case(
    endpoint: str,
    api_key: str,
    model: str,
    label: str,
    *,
    with_image: bool,
    thinking_mode: str,
    timeout_sec: float,
) -> None:
    data = build_payload(model, with_image=with_image, thinking_mode=thinking_mode)
    print(f"\n=== {label} ===")
    print(f"model={model} image={with_image} thinking={thinking_mode}")
    try:
        out = call_responses(endpoint, api_key, data, timeout_sec=timeout_sec)
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.text[:500]
        except (OSError, RuntimeError, UnicodeDecodeError):
            pass
        print(f"HTTP {exc.response.status_code}: {body or exc}")
        return
    except httpx.HTTPError as exc:
        print(f"ERROR: {exc}")
        return
    except Exception as exc:  # boundary: CLI probe unexpected failure

    ok = bool(out["text"])
    print(f"ok={ok}")
    print(f"text={out['text'][:200]!r}")
    print(f"tokens in/out={out['input_tokens']}/{out['output_tokens']}")
    if out["error"]:
        print(f"stream_error={out['error']}")
    if out["reasoning_only"]:
        print("reasoning_only=True (only thinking content, no output_text)")
    if out["stream_events"]:
        print(f"events={out['stream_events']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Ark thinking model Responses API")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print("No API key. Pass --api-key or set ARK_API_KEY, or save key in DanmuAI settings.")
        return 2

    print(f"endpoint={args.endpoint}")
    print(f"key={'*' * 8} (len={len(api_key)})")

    cases = [
        ("text + thinking:disabled (DanmuAI default)", False, "disabled"),
        ("text + thinking omitted", False, "omit"),
        ("text + thinking:enabled", False, "enabled"),
        ("vision + thinking:disabled (DanmuAI default)", True, "disabled"),
        ("vision + thinking omitted", True, "omit"),
        ("vision + thinking:enabled", True, "enabled"),
    ]
    for label, with_image, thinking_mode in cases:
        run_case(
            args.endpoint,
            api_key,
            args.model,
            label,
            with_image=with_image,
            thinking_mode=thinking_mode,
            timeout_sec=args.timeout,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
