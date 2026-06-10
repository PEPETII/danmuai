# DanmuAI documentation

Entry point: [README.md](../README.md) (install, quick start).

## Start here

| Document | Audience | Description |
|----------|----------|-------------|
| [core/ARCHITECTURE.md](core/ARCHITECTURE.md) | Everyone | What DanmuAI is, modules, threading, pipeline summary |
| [features/WEB_CONSOLE.md](features/WEB_CONSOLE.md) | Users & contributors | Web API, pages, launch modes |
| [core/MAIN_PIPELINE.md](core/MAIN_PIPELINE.md) | Contributors | Screenshot → AI → queue → overlay (normal mode) |
| [core/RUNTIME_STATE.md](core/RUNTIME_STATE.md) | Contributors | Status, diagnostics, state ownership |
| [core/PRIVACY.md](core/PRIVACY.md) | Users | Screenshot, mic, keys, data boundaries |

## Contributing

| Document | Description |
|----------|-------------|
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Dev setup, batched tests (no local full suite), PR hygiene |
| [CONTRIBUTING_ARCHITECTURE.md](CONTRIBUTING_ARCHITECTURE.md) | Architecture boundaries and checklist |
| [core/BOUNDARY_GUARD.md](core/BOUNDARY_GUARD.md) | `scripts/boundary_guard.py` usage |
| [DANMAKU_FORMULA.md](DANMAKU_FORMULA.md) | AI output JSON contract |

## Changelog & roadmap

| Document | Description |
|----------|-------------|
| [operations/ROADMAP.md](operations/ROADMAP.md) | Planned and completed work |
| [operations/CHANGELOG.md](operations/CHANGELOG.md) | Release notes |
| [release/](release/) | GitHub Release notes (by version) |

## Release & compliance

| Document | Description |
|----------|-------------|
| [release/2026-05-27.md](release/2026-05-27.md) | Release notes example |
| [operations/PACKAGING_WINDOWS.md](operations/PACKAGING_WINDOWS.md) | PyInstaller / exe |
| [operations/RELEASE_CHECKLIST.md](operations/RELEASE_CHECKLIST.md) | Release steps |
| [core/OPEN_SOURCE_AUDIT.md](core/OPEN_SOURCE_AUDIT.md) | Licenses & dependencies |
| [core/THIRD_PARTY_NOTICES.md](core/THIRD_PARTY_NOTICES.md) | Third-party licenses |
| [operations/README.en.md](operations/README.en.md) | English project summary |
| [SECURITY.md](../SECURITY.md) | Security reporting |
| [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Community norms |
| [data/ATTRIBUTION.md](../data/ATTRIBUTION.md) | Corpus attribution |

## Engineering reference

| Document | Description |
|----------|-------------|
| [features/CAPTURE_AND_DANMAKU_REFERENCE.md](features/CAPTURE_AND_DANMAKU_REFERENCE.md) | External libs (mss, Danmaku.js) |
| [architecture/provider-adapter.md](architecture/provider-adapter.md) | Provider adapter layer |

## Maintainer registry (Boundary Guard)

These paths are **stable filenames**—do not rename without updating `scripts/boundary_guard.py` and tests.

| Document | Purpose |
|----------|---------|
| [runtime-state-map.md](runtime-state-map.md) | Register new `DanmuApp` fields |
| [main-pipeline-sequence.md](main-pipeline-sequence.md) | Pipeline sequence table (sync with [core/MAIN_PIPELINE.md](core/MAIN_PIPELINE.md)) |
| [final-architecture-baseline.md](final-architecture-baseline.md) | Short architecture baseline (required to exist) |

## UI prototype

| Document | Description |
|----------|-------------|
| [prototype/README.md](../prototype/README.md) | Prototype folder |
| [prototype/Qwen_html_20260524_481u8vlmv.html](../prototype/Qwen_html_20260524_481u8vlmv.html) | Web UI reference |
| [prototype/Qwen_markdown_20260525_4vyxmv819.md](../prototype/Qwen_markdown_20260525_4vyxmv819.md) | Design tokens |

## Local AI / IDE documents

Agent rules, work orders, completion reports, and IDE templates live in **`.local-ai/`** at the repository root. That directory is gitignored and not published on GitHub. Maintainers: see `.local-ai/prompts/AGENTS.md`.
