"""One-off probe: send synthetic WAV audio to Doubao Responses API."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from app.ai_client import AiWorker, resolve_danmu_max_output_tokens
from app.config_store import ConfigStore
from app.doubao_responses_stream import consume_doubao_sse_lines, parse_doubao_json_body
from app.mic_encode import pcm_to_wav_data_uri
from app.mic_test_send import placeholder_image_data_uri
from app.model_providers import model_likely_supports_mic_audio, normalize_endpoint


def make_tone_pcm(seconds: float = 2.0, sample_rate: int = 16_000, freq: float = 440.0) -> bytes:
    samples = int(seconds * sample_rate)
    amp = 8000
    return struct.pack(f"<{samples}h", *(
        int(amp * math.sin(2 * math.pi * freq * i / sample_rate)) for i in range(samples)
    ))


def dump_result(label: str, result) -> None:
    print(f"\n=== {label} ===")
    print(f"text={result.text[:200]!r}")
    print(f"input_tokens={result.input_tokens} output_tokens={result.output_tokens}")
    print(f"error={result.error!r}")
    print(f"events={result.stream_events}")


def _join_body(raw_lines: list[str], limit: int = 20) -> str:
    return "\n".join(raw_lines[:limit])


def _hint_for_400(body: str) -> str | None:
    lowered = body.lower()
    if "content type is not supported" in lowered or "input_audio" in lowered:
        return (
            "当前 model/endpoint 不接受 Responses API 的 input_audio。"
            "doubao-seed-1-6-flash 多为图+文低延迟，麦克风请换全模态模型"
            "（如 doubao-seed-2-0-mini-260428、doubao-seed-2-0-lite-*、doubao-seed-1-6-vision-*）。"
        )
    return None


def _audio_parts(audio_uri: str, *, nested: bool) -> list[dict]:
    if nested:
        return [{"type": "input_audio", "input_audio": {"url": audio_uri}}]
    return [{"type": "input_audio", "audio_url": audio_uri}]


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Doubao Responses input_audio support.")
    parser.add_argument(
        "--model",
        default=os.environ.get("DANMU_PROBE_MODEL", "").strip(),
        help="Override model id (or set DANMU_PROBE_MODEL)",
    )
    args = parser.parse_args()

    config = ConfigStore()
    worker = AiWorker(config)
    resolved = worker._resolve_request_credentials()
    if not resolved:
        print("ERROR: incomplete credentials")
        return 1
    endpoint, api_key, model_id, api_mode = resolved
    if args.model:
        model_id = args.model
    print(f"endpoint={endpoint}")
    print(f"model={model_id} mode={api_mode}")
    if not model_likely_supports_mic_audio(model_id):
        print("warn: heuristic says this model may reject input_audio")
    else:
        print("ok: heuristic says this model likely accepts input_audio")

    pcm = make_tone_pcm()
    audio_uri = pcm_to_wav_data_uri(pcm)
    assert audio_uri
    print(f"pcm_bytes={len(pcm)} wav_uri_len={len(audio_uri)}")

    image_uri = placeholder_image_data_uri()
    user_pt = "这是一次麦克风发送测试。请用一句话说明你收到了用户音频。"
    max_out = resolve_danmu_max_output_tokens(config.get_int("max_tokens", 512))

    payloads: list[tuple[str, list[dict]]] = []
    for nested in (False, True):
        tag = "nested-input_audio" if nested else "audio_url"
        audio = _audio_parts(audio_uri, nested=nested)
        payloads.extend([
            (
                f"image+text+audio ({tag})",
                [
                    {"type": "input_image", "image_url": image_uri},
                    {"type": "input_text", "text": user_pt},
                    *audio,
                ],
            ),
            (
                f"text+audio ({tag})",
                [{"type": "input_text", "text": user_pt}, *audio],
            ),
            (
                f"audio+text ({tag})",
                [*audio, {"type": "input_text", "text": user_pt}],
            ),
        ])

    url = f"{normalize_endpoint(endpoint)}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(60.0, connect=10.0)

    with httpx.Client(timeout=timeout) as client:
        for name, content in payloads:
            data = {
                "model": model_id,
                "input": [{"type": "message", "role": "user", "content": content}],
                "stream": True,
                "thinking": {"type": "disabled"},
                "max_output_tokens": max_out,
            }
            print(f"\n--- trying {name} (stream) ---")
            try:
                with client.stream("POST", url, headers=headers, json=data) as resp:
                    print(f"HTTP {resp.status_code} content-type={resp.headers.get('content-type')}")
                    raw_lines = list(resp.iter_lines())
                    if resp.status_code >= 400:
                        body = _join_body(raw_lines)
                        print("body:", body)
                        hint = _hint_for_400(body)
                        if hint:
                            print("hint:", hint)
                        continue
                    result = consume_doubao_sse_lines(raw_lines)
                    dump_result(name, result)
            except httpx.HTTPStatusError as exc:
                print(f"HTTP error {exc.response.status_code}")

            sync = dict(data)
            sync["stream"] = False
            print(f"\n--- trying {name} (sync) ---")
            try:
                resp = client.post(url, headers=headers, json=sync)
                print(f"HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    body = resp.text
                    print("body:", body[:1200])
                    hint = _hint_for_400(body)
                    if hint:
                        print("hint:", hint)
                    continue
                body = resp.json()
                print(json.dumps(body, ensure_ascii=False)[:1200])
                parsed = parse_doubao_json_body(body if isinstance(body, dict) else {})
                dump_result(f"{name}-sync", parsed)
            except httpx.HTTPStatusError as exc:
                print(f"HTTP error {exc.response.status_code}: {exc.response.text[:800]}")

    worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
