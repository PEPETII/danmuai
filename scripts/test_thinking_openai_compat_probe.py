"""Probe OpenAI-compatible thinking parameters (enable_thinking vs thinking.type).

Usage:
  python scripts/test_thinking_openai_compat_probe.py --provider dashscope
  python scripts/test_thinking_openai_compat_probe.py --endpoint https://api.siliconflow.cn/v1 --model Qwen/Qwen3-VL-8B-Instruct
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.model_providers import normalize_endpoint
from app.providers import get_capabilities_for_endpoint
from app.providers.thinking import apply_thinking_mode

PRESETS = {
    "dashscope": {
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-vl-flash",
        "mode": "openai-compatible",
    },
    "siliconflow_instruct": {
        "endpoint": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen3-VL-32B-Instruct",
        "mode": "openai-compatible",
    },
    "mimo": {
        "endpoint": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5",
        "mode": "openai-compatible",
    },
}


def resolve_api_key(cli_key: str) -> str:
    key = (cli_key or os.getenv("DANMU_API_KEY") or "").strip()
    if key:
        return key
    try:
        from app.config_store import ConfigStore

        return (ConfigStore().get_api_key() or "").strip()
    except (OSError, RuntimeError, ImportError) as exc:
        print(f"[warn] could not read ConfigStore: {exc}")
        return ""


def run_case(
    endpoint: str,
    api_key: str,
    model: str,
    mode: str,
    *,
    enabled: bool,
    label: str,
) -> None:
    caps = get_capabilities_for_endpoint(endpoint, mode)
    data: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "用一句话说你好"}],
        "max_tokens": 32,
        "stream": False,
    }
    apply_thinking_mode(data, enabled=enabled, caps=caps)
    url = f"{normalize_endpoint(endpoint)}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    print(f"\n=== {label} ===")
    print(f"style={caps.thinking_param_style} enabled={enabled} keys={sorted(data.keys())}")
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            resp = client.post(url, headers=headers, json=data)
            if resp.status_code >= 400:
                print(f"HTTP {resp.status_code}: {resp.text[:400]}")
                return
            body = resp.json()
            choice = (body.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = (message.get("content") or "").strip()
            print(f"ok=True content={content[:120]!r}")
    except httpx.HTTPError as exc:
        print(f"ERROR: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe OpenAI-compat thinking parameters")
    parser.add_argument("--provider", choices=sorted(PRESETS), default="dashscope")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--mode", default="openai-compatible")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()

    preset = PRESETS[args.provider]
    endpoint = args.endpoint or preset["endpoint"]
    model = args.model or preset["model"]
    mode = args.mode or preset["mode"]
    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print("No API key. Pass --api-key or save key in DanmuAI settings.")
        return 2

    print(f"endpoint={endpoint} model={model}")
    run_case(endpoint, api_key, model, mode, enabled=False, label="thinking off")
    run_case(endpoint, api_key, model, mode, enabled=True, label="thinking on")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
