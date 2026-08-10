# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.9] - 2026-07-07

### Changed
- Windows release package built from the current release-readiness branch state.

---

## [0.3.7] - Unreleased

### Added
- AI platform reference data system with custom models schema and web UI model selector.
- Per-model thinking level selector in advanced model configuration (off/low/medium/high).
- Pet barrage system (`app/pet/pet_barrage.py`) for desktop companion overlay comments.
- Live overlay setup assistant for streamers.
- Diagnostics hub and SSE-based diagnostics snapshot API (`/api/diagnostics`).
- Feedback context image handling for user reports.
- Full persona prompt preview in web console.
- Track layout exposure in `/api/status` with font settings visualization.

### Changed
- Updated core modules: pet system, meme barrage, AI client, danmu pool, tests and build scripts.
- Improved startup trace and stream performance.
- Restructured web settings UI for mic, TTS, and persona panels.
- Refined builtin persona prompts and reply contract wording.

### Fixed
- Removed `_Y_OFFSET` ghost offset so top danmu aligns to track origin.
- Batch fixes for tray restore, bililive-dm plugin bridge, and engine bugs.
- Security, threading safety, and test coverage improvements.
- PyInstaller spec updated for PyInstaller 6.16 compatibility.
- Restored supabase/migrations/ to fix CI test failures.

### Removed
- Deprecated scene brief memory support and related configuration keys.

---

## [0.3.6]

> Early release; not recorded under this changelog format.

---

## [0.3.5]

> Version number was not used; skipped.

---

## [0.3.4]

> Early release; not recorded under this changelog format.

---

## [0.3.3] and earlier

> Early releases; not recorded under this changelog format.
