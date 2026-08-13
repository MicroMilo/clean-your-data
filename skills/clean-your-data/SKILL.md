---
name: clean-your-data
description: Explain why a local file or directory exists, who or what likely created it, what evidence supports that conclusion, and what could break if it moves. Use for unfamiliar paths, disk-space questions, Agent-created files, build outputs, caches, app data, local file provenance, or requests to inspect a filesystem safely before changing it.
license: MIT
metadata:
  author: MicroMilo
  version: "0.5.0"
---

# Clean Your Data

Use `cyd` as the local evidence collector. Let the Agent interpret its bounded JSON instead of guessing from a filename or recursively reading files.

## Start With One Path

For questions such as “what created this?”, “why is this here?”, or “can I move this?”, first test the required capability:

```bash
command -v cyd >/dev/null 2>&1 && cyd why --help >/dev/null 2>&1
```

If that succeeds, run:

```bash
cyd why "PATH" --format json
```

If it fails, `cyd` is missing or older than v0.5.0. Tell the user that the next command downloads and caches the fixed public release from GitHub, then wait for approval before running:

```bash
uvx --from git+https://github.com/MicroMilo/clean-your-data.git@v0.5.0 cyd why "PATH" --format json
```

Do not use `sudo` or modify the system Python. Do not silently install a permanent tool or execute a mutable branch such as `main`. If `uv` is unavailable, ask before installing `uv`, `pipx`, or Clean Your Data. Stop when installation is not approved.

## Interpret The Evidence

Answer in the user's language. Lead with:

1. **Likely source** and confidence.
2. **Evidence**, keeping `observed`, `observed_association`, `bounded`, and `inference` distinct.
3. **Impact if moved** and its risk.
4. **Unknowns** that prevent a stronger conclusion.
5. **Safest next check**.

Treat these JSON fields as the contract:

- `likely_source`: a conclusion, confidence, and basis; it is not guaranteed authorship.
- `evidence`: facts and inferences with explicit strength labels.
- `impact_if_moved`: a consequence assessment, not cleanup permission.
- `unknowns`: facts the local metadata cannot establish.
- `safest_next_check`: the smallest useful follow-up.
- `action_gate`: always check `authorizes_move`; `cyd why` itself never authorizes or moves anything.
- `limits`: confirms whether contents, symlink targets, or trace evidence were used.

Do not claim an exact application, process, Agent, or conversation created a path unless the evidence proves it. A prospective trace only associates a change with a captured time window; it does not prove the exact child process that wrote the path.

## Escalate Only When Needed

- If the user wants to browse visually, invite them to run `cyd PATH` for the TUI or `cyd gui PATH` for the local browser GUI. Do not launch an interactive surface unattended.
- If the origin must be observed prospectively and the user supplies the command, use `cyd trace --path SCOPE -- COMMAND`. Warn that traced command arguments are stored locally and must not contain credentials.
- If the user requests file contents, inspect only the exact approved file and keep that content separate from the metadata-only `cyd why` result.
- If the user requests a move, use the product's exact-path TUI/GUI review and system Trash flow. Agent advice cannot bypass its deterministic gate.

## Safety Rules

- Begin read-only. Never delete or move a path merely because it is large or looks rebuildable.
- Do not follow a symbolic link as though it were the selected directory.
- Prefer the owning application's controls for app state and cloud-sync data.
- Treat credential paths, VCS internals, filesystem roots, home roots, incomplete measurements, and unknown ownership as blocked.
- Keep reports local unless the user explicitly asks to share them. Home prefixes are redacted, but project and folder names may still identify private work.
