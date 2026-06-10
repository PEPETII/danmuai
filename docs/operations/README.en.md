# DanmuAI (English summary)

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

Windows desktop overlay danmaku (scrolling comments) powered by vision models. Captures the **selected display**, sends compressed in-memory screenshots to your configured API, and renders transparent Qt overlays. Default UI is a **local Web console** (`127.0.0.1:18765`) in a pywebview shell.

Full documentation is in [README.md](README.md) (Chinese). Contributor architecture: [docs/CONTRIBUTING_ARCHITECTURE.md](docs/CONTRIBUTING_ARCHITECTURE.md).

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

## Platform

- **Windows** with WebView2 (pywebview)
- Python ≥ 3.12
- Config and secrets: `%APPDATA%/DanmuAI/` (see [SECURITY.md](SECURITY.md))

## API providers (Assistant settings)

Built-in presets (see `app/model_providers.py`) include Volcengine Ark (Doubao), Alibaba DashScope, Zhipu, Moonshot, SiliconFlow, **Xiaomi MiMo**, plus custom OpenAI-compatible and Doubao Responses entries.

| Preset | Default endpoint | Protocol | Vision danmu example |
|--------|------------------|----------|----------------------|
| Volcengine Ark | `https://ark.cn-beijing.volces.com/api/v3` | Doubao `/responses` | `doubao-seed-1-6-flash-250828` |
| Xiaomi MiMo | `https://api.xiaomimimo.com/v1` | OpenAI-compatible | `mimo-v2.5` (MiMo-V2.5) |

Platforms with a model picker catalog: Doubao, DashScope, SiliconFlow, MiMo (`GET /api/model-catalog`).

**Thinking mode** is always sent as `disabled` on outbound requests (`app/ai_client.py`). Streaming parsers use `content` only, not `reasoning_content`.

**Microphone mode** attaches audio on Doubao Responses (`input_audio` + `audio_url`) or on Xiaomi MiMo Chat Completions (`input_audio` + `input_audio.data`, **model `mimo-v2.5` only**). Other OpenAI-compatible presets remain screenshot + text only; for mic on Doubao use a multimodal model such as `doubao-seed-2-0-mini-260428`.

## Contributing

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Tests: install dev deps, then run **related** test files in batches (`-q -x`); avoid full `pytest tests/` locally (high memory). CI runs the full suite.

## License

SPDX-License-Identifier: `GPL-3.0-or-later` — see [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
