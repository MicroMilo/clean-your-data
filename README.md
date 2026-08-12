# Clean Your Data

<div align="center">

**Your filesystem wasn't built for AI Agents.**

See where space went. Ask what likely created a path. Understand what could break. Move it only through reversible safety gates.

[![CI](https://github.com/MicroMilo/clean-your-data/actions/workflows/test.yml/badge.svg)](https://github.com/MicroMilo/clean-your-data/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/MicroMilo/clean-your-data?display_name=tag)](https://github.com/MicroMilo/clean-your-data/releases)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[简体中文](README.zh-CN.md) · [Usage](docs/USAGE.md) · [Privacy](PRIVACY.md) · [Latest release](https://github.com/MicroMilo/clean-your-data/releases/latest)

</div>

<p align="center">
  <img src="https://raw.githubusercontent.com/MicroMilo/clean-your-data/main/assets/clean-your-data-tui-v0.4.png" alt="Clean Your Data terminal space map with relative size bars and a path inspector" width="100%">
  <br><sub><b>Terminal workspace:</b> navigate, inspect, ask, review, and undo without leaving the TUI.</sub>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/MicroMilo/clean-your-data/main/assets/clean-your-data-gui-v0.4.jpg" alt="Clean Your Data browser GUI showing a disk map and per-path Agent conversation" width="100%">
  <br><sub><b>Browser workspace:</b> keep the space map and each path's Agent conversation visible together.</sub>
</p>

Both screenshots use a synthetic project. No home directory, username, or private workspace is shown.

## Run It

With [`uv`](https://docs.astral.sh/uv/) installed, no checkout or permanent install is required:

```bash
# Terminal workspace
uvx --from git+https://github.com/MicroMilo/clean-your-data.git cyd .

# Browser workspace
uvx --from git+https://github.com/MicroMilo/clean-your-data.git cyd gui .
```

Install `cyd` once when you want it everywhere:

```bash
uv tool install git+https://github.com/MicroMilo/clean-your-data.git
cyd ~/Documents/project          # TUI
cyd gui ~/Documents/project      # GUI
```

Python 3.9+ and macOS/Linux are supported. The package has no third-party Python runtime dependencies.

## Why This Exists

Disk analyzers know **size**. File managers know **names**. A one-off Agent prompt gives an **answer** but loses the selected path and surrounding state.

Clean Your Data keeps the whole decision in one place:

```text
space map -> exact path -> local preview -> Agent evidence -> safety review -> Trash -> undo
```

| Capability | What is different here |
| --- | --- |
| Space map | Relative bars explain which branch dominates the current folder |
| Path context | Preview, metadata, relationships, and Agent answers stay attached to one selection |
| Agent control | Bring an authenticated Codex CLI or any trusted stdin/stdout command; AI remains optional |
| Action safety | Deterministic rules, exact-path confirmation, system Trash, local history, and undo |

## Bring Your Own Agent

```bash
cyd config ai --auto                         # use an authenticated Codex CLI when available
cyd config ai --codex
cyd config ai --command 'ollama run qwen3:8b'
cyd config ai --off
```

The Agent receives bounded metadata, not the selected file preview or file body. Its answer is advice and cannot bypass cleanup gates. Custom providers are executed as direct arguments, never through a shell.

You can also give this repository URL to an Agent and say:

> Install Clean Your Data, inspect `PATH` read-only, explain the largest branches and likely owners, and do not move anything without my exact approval.

## Safety Contract

- Initial scans are local, metadata-first, and make no network request.
- Sensitive names and binary files are excluded from preview; ordinary previews remain local and never enter the Agent prompt.
- Cleanup never permanently deletes: only an exact confirmed path moves to system Trash, with undo when restoration remains safe.
- Reports redact the home directory to `~` by default, but you should still review project and folder names before sharing.

Configured Agent commands follow their own network and credential policies. Read [Privacy](PRIVACY.md) and [Security](SECURITY.md) for the complete boundary.

## More

[Usage and controls](docs/USAGE.md) · [Chinese README](README.zh-CN.md) · [Sample report](examples/sample-report.md) · [Agent handoff](examples/agent-handoff.md) · [Changelog](CHANGELOG.md)

Clean Your Data is beta software. `v0.4.0` includes the GUI, keyboard-first TUI, optional Agent integration, reversible cleanup, duplicate detection, report comparison, and opt-in Agent tracing.

MIT licensed. See [LICENSE](LICENSE).
