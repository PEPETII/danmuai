# DanmuAI

![Python](https://img.shields.io/badge/python-3.12%E6%8E%A8%E8%8D%90-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

DanmuAI is a Windows desktop danmu tool: it captures the **entire selected display**, calls a vision model to generate 5 danmu messages, and renders them as a scrolling Qt transparent always-on-top overlay. By default it uses the **Warm Web Console**[...] 

<img width="2487" height="1375" alt="Screenshot 2026-05-17 195301" src="https://github.com/user-attachments/assets/7a366c6c-1729-4852-b8df-c5755388fe60" />
<img width="2541" height="1408" alt="Screenshot 2026-05-17 195727" src="https://github.com/user-attachments/assets/655b778a-26c8-4c3b-8fd3-45eef7aac4a9" />
<img width="2526" height="1391" alt="Screenshot 2026-05-17 195659" src="https://github.com/user-attachments/assets/ab2aff3c-c1d0-44bc-b507-7a42921dbb48" />

Discord: https://discord.gg/xQyx24ttK

**Project focus**: a lightweight, privacy-friendly AI danmu assistant for streamers. Screenshots are compressed in memory before being sent to the model and are not written to disk by default; configuration and keys are stored locally in `%APPDATA%/DanmuAI/`.

## Project status

This project is in early active development, so APIs and config formats may change. The console UI is web-based; the legacy Qt main window (`--qt-ui`) has been removed.

**Current UI facts (based on `main.py`)**

- Default: `python main.py` → Web Console + pywebview + Qt Overlay / tray
- New feature entry points: `web/static/`, `app/web_api/` (registered in `routes.py`)
- Overlay: `app/overlay.py`, `app/danmu_engine/` always run

See [AGENTS.md](AGENTS.md) Appendix A.3.10 (Web API / console), [.local-ai/workorders/工单列表.md](.local-ai/workorders/工单列表.md) (feature backlog), and [docs/final-architecture-baseline.md](docs/final-architecture-baseline.md).[...]

## Tech stack

| Component | Purpose |
|------|------|
| **Python** 3.12 (recommended) | Primary language |
| **FastAPI** + **uvicorn** | Local Web API (`127.0.0.1:18765`) |
| **pywebview** | Desktop shell (Windows WebView2) |
| **PyQt6** | Danmu overlay, system tray |
| **httpx** | HTTP/2 client for AI API requests |
| **Pillow** | Image compression (JPEG quality defaults to 85, max_width is config-controlled, common values 1024 and legacy 768, Base64 data URI) |
| **SQLite** | Config storage (WAL mode) |
| **cryptography** | API key encryption (Fernet) |
| **keyboard** | Global hotkeys |
| **python-Levenshtein** | Similarity scoring for danmu deduplication |

## Features

- Danmu generation: **fixed recognition interval** (`normal_recognition_interval_sec`, default 5 seconds) + **messages per batch** (`normal_reply_count`, default 5); if the previous request is still in flight, the current round is skipped
- Screenshot on the main thread, compression and AI requests in a thread pool to avoid blocking the UI
- Backoff on consecutive failures, timeout control, log redaction
- **Multi-monitor**: `screen_index` selects the screenshot and overlay target display (invalid indices fall back to 0)
- Screenshots are compressed in memory before being sent to the AI and are **not written to disk by default**; only danmu text history is saved
- **Web Console**: runtime overview (session stats + persistent totals: generated danmu count, total runtime, total token usage), assistant settings, persona workshop, danmu diary; custom model CRUD, image[...]