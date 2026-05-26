# DanmuAI (English summary)

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

Windows / macOS desktop overlay danmaku (scrolling comments) powered by vision models. Captures the **selected display**, sends compressed in-memory screenshots to your configured API, and renders transparent Qt overlays. Default UI is a **local Web console** (`127.0.0.1:18765`) in a pywebview shell.

Full documentation is in [README.md](README.md) (Chinese).

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

## Platform

- **Windows** with WebView2 or **macOS** with Cocoa/WebKit (pywebview)
- Python ≥ 3.12
- Config and secrets: `%APPDATA%/DanmuAI/` on Windows, `~/Library/Application Support/DanmuAI/` on macOS (see [SECURITY.md](SECURITY.md))

## Contributing

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Tests: `pip install -r requirements-dev.txt && python -m pytest tests/ -q`

## License

SPDX-License-Identifier: `GPL-3.0-or-later` — see [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
