# Clean Your Data Usage Guide

This guide covers installation, the GUI and TUI controls, local Agent configuration, tracing, duplicate detection, reports, and snapshot comparison. See the [project README](../README.md) for the short product overview or [README.zh-CN.md](../README.zh-CN.md) for Chinese.

## Install

Run without a checkout or permanent install:

```bash
uvx --from git+https://github.com/MicroMilo/clean-your-data.git@v0.5.0 cyd gui .
uvx --from git+https://github.com/MicroMilo/clean-your-data.git@v0.5.0 cyd .
```

Install from GitHub:

```bash
uv tool install --force git+https://github.com/MicroMilo/clean-your-data.git@v0.5.0
cyd --version
```

`--force` also replaces an older `cyd` installation. A successful install should print `clean-your-data 0.5.0` from `cyd --version`.

Install a downloaded release wheel:

```bash
python3 -m pip install clean_your_data-0.5.0-py3-none-any.whl
```

Install a source checkout for development:

```bash
git clone https://github.com/MicroMilo/clean-your-data.git
cd clean-your-data
python3 -m pip install .
```

Run `cyd --help` for the product entry points. The original broad report flags remain under `cyd audit --help`.

Clean Your Data requires Python 3.9+ and currently targets macOS/Linux. It has no third-party Python runtime dependencies. It uses `du` for allocated-size measurement, `git` only for optional Git checks, `curses` for the TUI, and Python's standard HTTP server for the GUI.

## Explain One Path To An Agent

Use the non-interactive command when an Agent needs local evidence about one file or directory:

```bash
cyd why ~/Documents/project/build --format json
```

The result has stable sections for `likely_source`, `evidence`, `impact_if_moved`, `unknowns`, `safest_next_check`, and `action_gate`. Evidence is labeled as observed fact, bounded observation, prospective trace association, or inference. For a directory, relationship analysis stays inside that selected directory and reports its actual scope and file count in `analysis_scope`; a selected file does not trigger a parent-directory traversal. Up to ten ancestor levels may be checked for project-marker names, and the detected root is reported as `project_context_root`. The command reads directory-entry metadata, names, sizes, project markers, and the local optional trace database; it does not read selected file contents, follow a selected symbolic link, move files, or authorize cleanup.

Use text when a human will read the result directly:

```bash
cyd why ~/Documents/project/build
```

Install the repository's Agent Skill by giving an Agent this fixed release directory URL:

```text
https://github.com/MicroMilo/clean-your-data/tree/v0.5.0/skills/clean-your-data
```

In Codex, use two turns:

```text
Install the clean-your-data Skill from https://github.com/MicroMilo/clean-your-data/tree/v0.5.0/skills/clean-your-data

# After Codex confirms installation, send this in the next turn:
Use $clean-your-data to explain PATH read-only.
```

The Skill first probes `cyd why --help`. If the installed command is missing or too old, it asks before downloading the fixed `v0.5.0` package through `uvx`; it does not silently install a permanent tool or execute `main`. It then preserves uncertainty and escalates to the TUI, GUI, prospective trace, content inspection, or Trash review only when the user asks.

## Browser GUI

```bash
cyd gui ~/Documents/project
```

The GUI binds to a random port on `127.0.0.1`, prints its URL, and opens the default browser. Use `--no-open` when you want to open the printed URL yourself:

```bash
cyd gui ~/Documents/project --no-open
```

The initial scan loads two levels by default. Deeper folders load on demand. Main interactions:

- click a row to select it;
- click its triangle or double-click the row to open or close a folder;
- use search and relative-size sorting over paths already loaded;
- inspect a bounded local preview and deterministic cleanup reason;
- use **Ask Agent** to keep questions and answers attached to one path;
- open **Relations** for a bounded metadata-only project/dependency/output analysis;
- add eligible exact paths to the cleanup basket, review them again, then move them to system Trash;
- use **Undo** while the recorded Trash item still exists and its original location remains free.

Keyboard controls available in the GUI include `j`/`k`, arrow keys, `Enter`, `/`, `A`, `dd`, `gg`, `G`, `u`, `?`, and `Esc`.

Stop the server with its square button or `Ctrl-C` in the launching terminal.

## Terminal UI

```bash
cyd ~/Documents/project
```

The TUI starts with the root and two child levels. There is no fixed depth limit; opening a folder loads another level when needed.

### Navigation

| Key | Action |
| --- | --- |
| `j` / `k`, `Up` / `Down` | Move through visible paths |
| `h` / `l`, `Left` / `Right` | Collapse or enter folders |
| `Enter` | Open another level or close the selected folder |
| `gg` / `G` | Jump to top or bottom |
| `PageUp` / `PageDown` | Move by one screen |
| Mouse click / double-click / wheel | Select, open, or move selection |
| `?` | Open the full in-app help |
| `q` | Quit when no input box is active |

### Browse And Organize The View

| Key | Action |
| --- | --- |
| `/` | Fuzzy-search loaded names, paths, areas, and tags |
| `f` | Filter folders, files, large/recent/rebuildable/bookmarked/staged/tagged paths |
| `s` | Sort siblings by tree order, name, size, modified time, or kind |
| `T` | Edit local tags |
| `m` / `M` | Save or browse bookmarks and recent paths |
| `N` | Open the selected folder in a new tab |
| `gt` / `gT` / `X` | Next tab, previous tab, or close tab |
| `w` / `W` | Save or restore the last workspace |

Search, filter, and sort only operate on paths already loaded into the current metadata map. They do not imply that unopened directories were scanned.

### Inspect, Ask, And Act

| Key | Action |
| --- | --- |
| `a` | Open the Agent question box beside the selected path |
| `Esc` / `Ctrl-C` | Cancel an input or pending Agent request |
| `C` | Copy the metadata-only Agent context |
| `r` | Reload a selected file preview |
| `D` | Run bounded metadata-only relationship analysis |
| `t` / `v` / `c` / `o` | Open Terminal, VS Code, Cursor, or Finder for the path |
| `dd` | Stage the exact eligible path for cleanup review |
| `Y`, then `y` | Review and confirm moving the exact path to system Trash |
| `u` | Undo the most recent recorded Trash move |

Selected text files receive a local preview limited to 4 KB and 14 lines. Binary files and likely credential paths are hidden. Preview content never enters the Agent prompt.

Paths tracked by Git, including directories containing tracked files, are blocked from executable Trash review. Clean Your Data checks the Git index for the selected path but does not inspect working-tree content differences; use Git status and history before deciding what to do.

Path launch actions use direct arguments, not shell interpolation. Bookmarks, tags, recent paths, and the last workspace stay in `~/.clean-your-data/workspace-state.json` and are not added to reports.

## Configure An Agent

The explorer works with AI disabled. Choose one local provider mode:

```bash
cyd config ai --auto
cyd config ai --codex
cyd config ai --command 'ollama run qwen3:8b'
cyd config ai --off
cyd config ai --show
```

`auto` uses an authenticated `codex` CLI when available. Built-in Codex calls use an ephemeral, read-only sandbox. A custom command reads the prompt from stdin and writes its answer to stdout. It is parsed into direct arguments and never invoked through a shell.

The saved custom command is stored verbatim in `~/.clean-your-data/ai-config.json` with user-only permissions where supported. Never put credentials in its arguments. Keep them in the provider's environment or credential store.

The prompt contains the redacted path, name, kind, size, modified time, category, measurement status, project-marker names, bounded relationship summaries, and any matching prospective trace association. It excludes the selected preview, file contents, credentials, full traced command arguments, and cleanup authority. A custom provider still has its own operating-system permissions and network policy; configure only a command you trust.

`CLEAN_YOUR_DATA_AI_COMMAND` can provide a session-only environment override.

## Trace One Agent Run

Wrap a command when you need prospective evidence about paths changed while it runs:

```bash
cyd trace -- codex
cyd trace --path ~/Documents/project -- claude
cyd trace \
  --path ~/Documents/project \
  --path ~/.codex \
  --format json \
  --output trace.json \
  -- codex
```

The tracer takes bounded metadata snapshots and reports created, modified, deleted, and briefly observed paths. It never reads file contents or environment variables. It stores the session, command arguments, timestamps, scope, process id, and before/after stat fields in `~/.clean-your-data/provenance.sqlite3` with user-only permissions where supported.

Command arguments are stored verbatim, so do not place credentials on the traced command line. A trace means “this changed while the command was running,” not kernel-level proof that a particular child process wrote it. Concurrent writers and very short-lived paths remain limitations.

## Read-Only Reports

The compatibility scanner remains available from a source checkout:

```bash
# Quick Markdown audit
python3 audit-local-files/scripts/audit_local_files.py \
  --format markdown \
  --output local-file-audit.md

# Deeper audit
python3 audit-local-files/scripts/audit_local_files.py \
  --mode full \
  --children \
  --artifacts \
  --git-status \
  --format markdown \
  --output local-file-audit-full.md
```

Reports separate `measured`, `timeout`, `error`, `missing`, and `unknown` states. Their decision contract records coverage, evidence-linked findings, risks, confidence, rebuild or rollback guidance, and whether incomplete evidence or dirty Git work keeps the result at `review_only`.

Validate a JSON report before handing it to another Agent:

```bash
python3 audit-local-files/scripts/validate_report.py report.json
```

Home paths are redacted to `~` and Git origin URLs are omitted by default. Project and folder names can still identify private work, so inspect every saved report before sharing it. Do not publish output created with `--no-redact` or `--include-git-origins`.

## Exact Duplicate Detection

Duplicate matching is opt-in because it reads candidate file bytes locally:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --duplicates \
  --format markdown \
  --output duplicate-audit.md
```

The pass groups files by size, then streams SHA-256 only for candidates. It makes no network request, does not expose raw hashes in reports, and does not change files. It distinguishes independent copies from hard-link aliases and parent/cloud scope overlap. “Potential duplicate bytes” is review evidence, not guaranteed reclaimable space.

Use `--duplicate-root PATH` only for an additional scope you explicitly understand.

## Compare Snapshots

```bash
mkdir -p snapshots

python3 audit-local-files/scripts/audit_local_files.py \
  --mode full --children --artifacts --git-status \
  --format json --output snapshots/before.json

# Use the machine, then create snapshots/after.json with the same options.

python3 audit-local-files/scripts/compare_reports.py \
  snapshots/before.json snapshots/after.json
```

The comparison reports changes in measured disk usage, target areas, Codex workspace counts, dirty Git entries, rebuildable artifacts, exact duplicate groups, and interactive-map coverage. Keep snapshots local unless you have reviewed their paths.

## Legacy Machine-Wide Audit Skill

```bash
git clone https://github.com/MicroMilo/clean-your-data.git
mkdir -p ~/.codex/skills
cp -R clean-your-data/audit-local-files ~/.codex/skills/audit-local-files
```

Then ask:

```text
Use $audit-local-files to audit my local file organization. Start read-only and anonymized. Do not delete anything.
```

This compatibility Skill covers broad home-directory reports and snapshot comparison. Use `skills/clean-your-data` for the main product workflow.
