#!/usr/bin/env python3
"""Probe MiMo + DashScope Qwen3 TTS for danmu-read integration.

Keys are read from environment variables only (never hardcode):
  MIMO_TTS_API_KEY             - Xiaomi MiMo Bearer token
  MIMO_TTS_ENDPOINT            - optional override (default https://api.xiaomimimo.com/v1)
  DASHSCOPE_API_KEY            - Bailian / DashScope API key

Usage:
  python scripts/probe_tts_providers.py --out .pytest_tmp/tts_probe
  python scripts/probe_tts_providers.py --quick --mimo-only
"""

from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import os
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

PROBE_TEXT = "你好，这是一条读弹幕试听。"

MIMO_TTS_ENDPOINT = "https://api.xiaomimimo.com/v1"
MIMO_TTS_MODEL = "mimo-v2.5-tts"

MIMO_VOICES: tuple[tuple[str, str], ...] = (
    ("MiMo-默认", "mimo_default"),
    ("冰糖", "冰糖"),
    ("茉莉", "茉莉"),
    ("苏打", "苏打"),
    ("白桦", "白桦"),
    ("Mia", "Mia"),
    ("Chloe", "Chloe"),
    ("Milo", "Milo"),
    ("Dean", "Dean"),
)

DASHSCOPE_MODELS = (
    "qwen3-tts-flash-2025-11-27",
    "qwen3-tts-flash-realtime",
    "qwen3-tts-instruct-flash-realtime",
)

DASHSCOPE_VOICES: tuple[tuple[str, str], ...] = (
    ("芊悦", "Cherry"),
    ("苏瑶", "Serena"),
    ("晨煦", "Ethan"),
    ("千雪", "Chelsie"),
    ("茉兔", "Momo"),
    ("十三", "Vivian"),
    ("凯", "Kai"),
    ("萌宝", "Bella"),
    ("龙安洋", "longanyang"),
    ("龙安欢 V3", "longanhuan_v3"),
)


def pcm_to_wav(pcm: bytes, *, sample_rate: int = 24000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def validate_wav(data: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            return wf.getnframes() > 0 and wf.getsampwidth() == 2
    except (wave.Error, OSError, EOFError):
        return False


@dataclass
class ProbeResult:
    provider: str
    model: str
    voice: str
    voice_label: str = ""
    auth_mode: str = ""
    ok: bool = False
    latency_ms: int = 0
    audio_bytes: int = 0
    error: str = ""
    logid: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    wav_bytes: bytes = field(default_factory=lambda: b"", repr=False)

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("wav_bytes", None)
        return d


def probe_mimo_voice(
    *,
    api_key: str,
    endpoint: str,
    voice: str,
    text: str = PROBE_TEXT,
    timeout: float = 60.0,
) -> tuple[bytes | None, str]:
    """Returns (wav_bytes, error)."""
    payload = {
        "model": MIMO_TTS_MODEL,
        "messages": [{"role": "assistant", "content": text}],
        "audio": {"format": "wav", "voice": voice},
    }
    url = f"{endpoint.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
            response = client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                return None, f"HTTP {response.status_code}: {response.text[:500]!r}"
            body = response.json()
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.HTTPError as exc:
        return None, f"http error: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"json decode: {exc}"

    choices = body.get("choices") or []
    if not choices:
        return None, "no choices in response"
    message = choices[0].get("message") or {}
    audio = message.get("audio") or {}
    data_b64 = audio.get("data") or ""
    if not data_b64:
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return None, "text-only response (not a TTS model)"
        return None, "no audio.data in response"
    try:
        wav = base64.b64decode(data_b64)
    except (ValueError, TypeError) as exc:
        return None, f"base64 decode: {exc}"
    if not validate_wav(wav):
        return None, "invalid wav"
    return wav, ""


def probe_mimo(*, api_key: str, endpoint: str, quick: bool) -> list[ProbeResult]:
    if not api_key:
        return [
            ProbeResult(
                provider="mimo",
                model="*",
                voice="*",
                ok=False,
                error="no MIMO_TTS_API_KEY",
            )
        ]

    results: list[ProbeResult] = []
    voices = MIMO_VOICES[:1] if quick else MIMO_VOICES
    for label, voice in voices:
        t0 = time.perf_counter()
        wav, err = probe_mimo_voice(api_key=api_key, endpoint=endpoint, voice=voice)
        ms = int((time.perf_counter() - t0) * 1000)
        results.append(
            ProbeResult(
                provider="mimo",
                model=MIMO_TTS_MODEL,
                voice=voice,
                voice_label=label,
                auth_mode="bearer",
                ok=wav is not None,
                latency_ms=ms,
                audio_bytes=len(wav) if wav else 0,
                error=err,
                extra={"endpoint": endpoint},
                wav_bytes=wav or b"",
            )
        )
    return results


def probe_dashscope_http(
    *,
    api_key: str,
    model: str,
    voice: str,
    stream: bool,
    instructions: str = "",
) -> tuple[bytes | None, str]:
    try:
        import dashscope
        from dashscope import MultiModalConversation
    except ImportError:
        return None, "dashscope not installed (pip install dashscope>=1.24.6)"

    dashscope.api_key = api_key
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "text": PROBE_TEXT,
        "voice": voice,
        "language_type": "Chinese",
        "stream": stream,
    }
    if instructions:
        kwargs["instructions"] = instructions
        kwargs["optimize_instructions"] = True

    try:
        response = MultiModalConversation.call(**kwargs)
    except (ImportError, AttributeError, TypeError, ValueError, OSError) as exc:
        return None, str(exc)

    if getattr(response, "status_code", None) != 200:
        code = getattr(response, "code", "?")
        msg = getattr(response, "message", "?")
        return None, f"status={getattr(response, 'status_code', '?')} code={code} msg={msg}"

    output = getattr(response, "output", None) or {}
    audio = output.get("audio") if isinstance(output, dict) else getattr(output, "audio", None)
    if not audio:
        return None, "no audio in output"

    if stream:
        pcm_chunks: list[bytes] = []
        for chunk in response:
            out = getattr(chunk, "output", None) or {}
            aud = out.get("audio") if isinstance(out, dict) else getattr(out, "audio", None)
            if not aud:
                continue
            data_b64 = aud.get("data") if isinstance(aud, dict) else getattr(aud, "data", "")
            if data_b64:
                pcm_chunks.append(base64.b64decode(data_b64))
        if not pcm_chunks:
            return None, "stream: no pcm chunks"
        wav = pcm_to_wav(b"".join(pcm_chunks))
        return (wav, "") if validate_wav(wav) else (None, "stream: invalid wav")

    url = audio.get("url") if isinstance(audio, dict) else getattr(audio, "url", "")
    if not url:
        data_b64 = audio.get("data") if isinstance(audio, dict) else getattr(audio, "data", "")
        if data_b64:
            raw = base64.b64decode(data_b64)
            if raw[:4] == b"RIFF":
                return (raw, "") if validate_wav(raw) else (None, "invalid wav from data")
            wav = pcm_to_wav(raw)
            return (wav, "") if validate_wav(wav) else (None, "invalid pcm wav")
        return None, "no url or data in audio"

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.content
    except httpx.HTTPError as exc:
        return None, f"download url failed: {exc}"

    if data[:4] == b"RIFF" and validate_wav(data):
        return data, ""
    if len(data) > 100:
        wav = pcm_to_wav(data) if data[:4] != b"RIFF" else data
        return (wav, "") if validate_wav(wav) else (None, "downloaded audio not valid wav")
    return None, "downloaded audio too short"


def probe_dashscope_realtime(
    *,
    api_key: str,
    model: str,
    voice: str,
    instructions: str = "",
    timeout: float = 45.0,
) -> tuple[bytes | None, str]:
    try:
        import dashscope
        from dashscope.audio.qwen_tts_realtime import (
            AudioFormat,
            QwenTtsRealtime,
            QwenTtsRealtimeCallback,
        )
    except ImportError:
        return None, "dashscope realtime not available (pip install dashscope>=1.24.6)"

    dashscope.api_key = api_key
    pcm_chunks: list[bytes] = []
    done = {"finished": False, "error": ""}

    class _Cb(QwenTtsRealtimeCallback):
        def on_open(self) -> None:
            pass

        def on_close(self, close_status_code, close_msg) -> None:
            done["finished"] = True

        def on_event(self, response: dict) -> None:
            try:
                typ = response.get("type", "")
                if typ == "response.audio.delta":
                    delta = response.get("delta", "")
                    if delta:
                        pcm_chunks.append(base64.b64decode(delta))
                elif typ == "error":
                    done["error"] = str(response.get("error", response))
            except (ValueError, TypeError, binascii.Error) as exc:
                done["error"] = str(exc)

    callback = _Cb()
    url = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    try:
        client = QwenTtsRealtime(model=model, callback=callback, url=url)
        client.connect()
        session_kwargs: dict[str, Any] = {
            "voice": voice,
            "response_format": AudioFormat.PCM_24000HZ_MONO_16BIT,
            "mode": "server_commit",
        }
        if instructions:
            session_kwargs["instructions"] = instructions
            session_kwargs["optimize_instructions"] = True
        client.update_session(**session_kwargs)
        client.append_text(PROBE_TEXT)
        client.finish()
        t0 = time.perf_counter()
        while not done["finished"] and (time.perf_counter() - t0) < timeout:
            time.sleep(0.05)
        if done["error"]:
            return None, done["error"]
        if not pcm_chunks:
            return None, "realtime: no pcm received"
        wav = pcm_to_wav(b"".join(pcm_chunks))
        return (wav, "") if validate_wav(wav) else (None, "realtime: invalid wav")
    except (ImportError, AttributeError, TypeError, ValueError, OSError) as exc:
        return None, str(exc)


def probe_dashscope(*, api_key: str, quick: bool) -> list[ProbeResult]:
    if not api_key:
        return [
            ProbeResult(
                provider="dashscope_qwen",
                model="*",
                voice="*",
                ok=False,
                error="no DASHSCOPE_API_KEY",
            )
        ]

    results: list[ProbeResult] = []
    models = DASHSCOPE_MODELS[:1] if quick else DASHSCOPE_MODELS
    voices = DASHSCOPE_VOICES[:1] if quick else DASHSCOPE_VOICES

    for model in models:
        for label, voice in voices:
            t0 = time.perf_counter()
            instructions = ""
            if model == "qwen3-tts-instruct-flash-realtime":
                instructions = "语速适中，语气自然。"
            if model == "qwen3-tts-flash-2025-11-27":
                wav, err = probe_dashscope_http(
                    api_key=api_key,
                    model=model,
                    voice=voice,
                    stream=False,
                )
                extra: dict[str, Any] = {"mode": "http_url"}
            elif model.endswith("-realtime"):
                wav, err = probe_dashscope_realtime(
                    api_key=api_key,
                    model=model,
                    voice=voice,
                    instructions=instructions,
                )
                extra = {"mode": "websocket", "instructions": bool(instructions)}
            else:
                wav, err = probe_dashscope_http(
                    api_key=api_key,
                    model=model,
                    voice=voice,
                    stream=True,
                )
                extra = {"mode": "http_stream"}

            ms = int((time.perf_counter() - t0) * 1000)
            results.append(
                ProbeResult(
                    provider="dashscope_qwen",
                    model=model,
                    voice=voice,
                    voice_label=label,
                    auth_mode="api_key",
                    ok=wav is not None,
                    latency_ms=ms,
                    audio_bytes=len(wav) if wav else 0,
                    error=err,
                    extra=extra,
                    wav_bytes=wav or b"",
                )
            )
    return results


def _safe_filename(*parts: str) -> str:
    raw = "_".join(parts)
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in raw)[:120]


def write_reports(results: list[ProbeResult], out_dir: Path, wav_by_key: dict[str, bytes]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = out_dir / "samples"
    samples_dir.mkdir(exist_ok=True)

    for key, wav in wav_by_key.items():
        (samples_dir / f"{key}.wav").write_bytes(wav)

    serializable = [r.to_json_dict() for r in results]
    (out_dir / "probe_report.json").write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ok_count = sum(1 for r in results if r.ok)
    lines = [
        "# TTS Provider Probe Report",
        "",
        f"Total: {len(results)} probes, **{ok_count} passed**",
        "",
        "## Passed",
        "",
        "| Provider | Model | Voice | Auth | Latency | Size |",
        "|----------|-------|-------|------|---------|------|",
    ]
    for r in results:
        if not r.ok:
            continue
        lines.append(
            f"| {r.provider} | {r.model} | {r.voice} | {r.auth_mode} | {r.latency_ms}ms | {r.audio_bytes} |"
        )
    lines.extend(["", "## Failed", "", "| Provider | Model | Voice | Auth | Error |", "|----------|-------|-------|------|-------|"])
    for r in results:
        if r.ok:
            continue
        err = (r.error or "?").replace("|", "/")[:80]
        lines.append(f"| {r.provider} | {r.model} | {r.voice} | {r.auth_mode} | {err} |")

    (out_dir / "probe_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe TTS providers for danmu-read")
    parser.add_argument("--out", type=Path, default=Path(".pytest_tmp/tts_probe"))
    parser.add_argument("--quick", action="store_true", help="one voice per provider/model")
    parser.add_argument("--mimo-only", action="store_true")
    parser.add_argument("--dashscope-only", action="store_true")
    args = parser.parse_args()

    if args.mimo_only and args.dashscope_only:
        parser.error("cannot use --mimo-only and --dashscope-only together")

    mimo_key = os.environ.get("MIMO_TTS_API_KEY", "").strip()
    mimo_endpoint = os.environ.get("MIMO_TTS_ENDPOINT", MIMO_TTS_ENDPOINT).strip() or MIMO_TTS_ENDPOINT
    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()

    all_results: list[ProbeResult] = []
    wav_by_key: dict[str, bytes] = {}

    if not args.dashscope_only:
        print("=== Probing Xiaomi MiMo TTS ===")
        all_results.extend(
            probe_mimo(api_key=mimo_key, endpoint=mimo_endpoint, quick=args.quick)
        )

    if not args.mimo_only:
        print("=== Probing DashScope Qwen3 TTS ===")
        all_results.extend(probe_dashscope(api_key=dashscope_key, quick=args.quick))

    for r in all_results:
        if r.ok and r.wav_bytes:
            key = _safe_filename(r.provider, r.model, r.voice)
            wav_by_key[key] = r.wav_bytes
            print(f"  OK   {r.provider}/{r.model}/{r.voice} ({r.latency_ms}ms, {r.audio_bytes} bytes)")
        elif not r.ok:
            print(f"  FAIL {r.provider}/{r.model}/{r.voice}: {r.error}")

    write_reports(all_results, args.out, wav_by_key)
    print(f"\nReport written to {args.out / 'probe_report.md'}")

    any_ok = any(r.ok for r in all_results)
    return 0 if any_ok else 1


if __name__ == "__main__":
    sys.exit(main())
