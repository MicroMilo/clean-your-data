# Changelog

## 0.4.0 - 2026-08-12

- Added `cyd gui [PATH]`, a local browser interface backed by the same scanner and cleanup gates as the TUI.
- Added expandable relative-size browsing, bounded local previews, search, sorting, relationships, per-path Agent conversations, and responsive desktop/mobile layouts.
- Added secret-free AI configuration for Codex, custom stdin/stdout commands, or AI-off operation.
- Added exact-path cleanup baskets, system Trash moves, rescanning, and undo to the GUI.
- Protected active roots, VCS metadata, credential stores, and common credential files from cleanup.
- Bound the GUI to loopback with Host validation, per-run API tokens, cross-origin checks, path redaction, restrictive response headers, and no traceback disclosure.
- Added the opt-in `cyd trace -- <command>` wrapper for Agent sessions.
- Records metadata-only created, modified, and deleted paths while the traced command runs.
- Persists local session and event evidence in `~/.clean-your-data/provenance.sqlite3`.
- Reports attribution as an observed association, not as kernel-level proof of the exact writer process.

## 0.3.1 - 2026-08-10

- Added relative size bars to the space map so large siblings stand out immediately.
- Added a first-screen space summary with folder, file, rebuildable, and staged counts.
- Reworked the folder inspector into a plain-language space story with a next-best action.

## 0.3.0 - 2026-08-10

- Added the installable `clean-your-data` Python package.
- Added the `cyd` command for launching the terminal explorer from any directory.
- Kept the repository's Skill and legacy script paths working as compatibility entry points.
- Documented the package-first workflow, local-only data boundary, and release checks.
