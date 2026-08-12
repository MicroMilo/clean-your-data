---
name: audit-local-files
description: Explain local file provenance and turn local file sprawl into a privacy-preserving, decision-ready audit. Use when someone asks what an Agent created, which paths changed during a local Agent session, what owns a file, or how to analyze Desktop, Downloads, Documents, Codex or other AI workspaces, Git repositories, cloud-sync folders, or local storage from Feishu/Lark, WeChat, Slack, Teams, Discord, Telegram, QQ, DingTalk, Zoom, mail, or browsers. Also use when proposing a safe archive, migration, cleanup, or before/after storage comparison.
---

# Clean Your Data

Use this skill as a local data audit protocol around the `cyd` terminal file-system interface. The package is the primary user experience; the skill is the optional Agent bridge. The goal is not to produce a large directory listing. The goal is to explain what is accumulating, who owns it, what is durable or rebuildable, what is risky, and what the user can safely do next.

## Safety Contract

- Start read-only. The scanner never moves, deletes, rewrites, or cleans files. The TUI may move only an exact path after the user confirms it in the Trash dialog.
- Inspect metadata by default: path existence, allocated size, modification time, and optional Git status counts. In the TUI, a selected file may show a local preview capped at 4 KB and 14 lines; binary and likely credential files are skipped, and the preview is never included in the Codex prompt.
- Do not read chat databases, browser history, email bodies, document text, source code, credentials, keychains, or other private contents.
- Treat Feishu/Lark, WeChat, Slack, Teams, Discord, Telegram, QQ, DingTalk, Zoom, mail, browser, and cloud-sync containers as app-managed or sync-managed state. Recommend the owning app for cleanup.
- Treat dirty Git repositories and untracked files as user data. Check status before proposing a move.
- Treat `node_modules`, `.venv`, `build`, `dist`, `.next`, `target`, and similar directories as candidates, not automatic deletions. Explain rebuild cost first. A coding agent may advise on the candidate, but its answer is not permission and cannot execute cleanup.
- Keep home paths redacted and Git origins omitted. Never use `--no-redact` or `--include-git-origins` for a public report.
- When the user names a path for closer inspection, keep that path redacted too. The interactive map may expose only home-relative paths by default.
- Exact duplicate detection is opt-in. Only run `--duplicates` after the user explicitly asks for duplicate matching; it reads candidate file bytes locally for SHA-256, never uploads them, and never changes files.
- Duplicate groups are review evidence, not cleanup authorization. Preserve the distinction between independent copies and hard-link aliases, and do not add duplicate bytes to parent target or artifact totals.
- Agent tracing is opt-in and bounded. It records metadata-only changes under explicit `--path` roots while a user-selected command runs; it does not read contents or environment variables, and it does not claim kernel-level proof of the exact child process.

## Workflow

### 1. Establish scope

If the user does not name a path, use the current user's home directory. State that the first pass is local, read-only, metadata-only, and anonymized.

### 2. Run the first audit

Prefer the installed package when it is available:

```bash
cyd --format markdown
```

For a human-controlled interactive session:

```bash
cyd /path/to/review
```

Use the repository script below only when the package is not installed or when working from a checkout.

From the skill directory, run:

```bash
python3 scripts/audit_local_files.py --format markdown
```

For a human-friendly terminal explorer that stays open while the user asks follow-up questions:

```bash
python3 scripts/audit_local_files.py \
  --tui \
  --path /path/to/review \
  --focus-depth 2
```

Use `Up`/`Down` to select an area, `gg` to jump to the top, `G` to jump to the bottom, `Home`/`End` for the endpoints, `PageUp`/`PageDown` to move by a screen, `Left`/`Right` to navigate, `Enter` to load and open one more level or close the selected folder, `a` to open the question box beside the tree, `Enter` to send, `Esc` or `Ctrl-C` to cancel, `dd` to stage the selected exact path in the cleanup basket, `Y` to review a Trash move, `y` inside the confirmation dialog to move it, `u` to undo the most recent move, `t` to open Terminal, `v` to open VS Code, `c` to open Cursor, `o` to reveal the path in Finder, `m` to bookmark, `M` to browse bookmarks, `w`/`W` to save or restore the last workspace, `D` to run deep path analysis, `C` to copy the metadata-only context, `r` to reload a selected file preview, `?` for help, and `q` to quit. Mouse clicks select an area, double-clicking a folder opens it, and the scroll wheel moves the selection. While the question box is open, `q` is question text; use `Esc` or `Ctrl-C` to leave it. Folders are shown with `/`. The initial depth is 2; deeper folders load on demand without a fixed TUI depth limit. TUI startup measures only the selected roots; use a non-TUI command for the full home audit. Use JSON for Agent handoff or snapshot comparison, and Markdown when plain text is more convenient.

When the user wants to explore a particular path and keep asking questions, generate the bounded interactive map:

```bash
python3 scripts/audit_local_files.py \
  --path /path/to/review \
  --focus-depth 2 \
  --tui
```

The map is metadata-first. It lets the user select a folder or file, inspect its name, path, size, last-change time, category, and measurement state, see a bounded local text preview for files, search loaded nodes fuzzily, filter and sort the tree, edit local tags, switch session-local tabs, edit a question, ask Codex, launch local tools, save a bookmark, and stage a cleanup candidate. The Codex call runs in a background worker so navigation remains responsive; the answer stays attached to the selected node. When the `codex` CLI is available, `a` uses a read-only ephemeral session, while `dd` sends a separate metadata-only cleanup-advisor prompt; neither prompt authorizes or executes a file operation. Otherwise set `CLEAN_YOUR_DATA_AI_COMMAND` to a trusted local command that reads the prompt from stdin. Press `C` to copy the metadata-only context. `D` performs a bounded metadata-only relationship analysis that can connect project markers, source files, dependencies, build directories, outputs, and possible repeated files. Read `references/interactive-explorer.md` for the contract and follow-up loop.

The advanced browsing controls are `/` fuzzy search, `f` filter, `s` sort, `T` local tags, `N` new tab, `gt`/`gT` next or previous tab, and `X` close tab. Search and filters operate only on nodes already loaded into the map; they do not imply that an unopened directory was scanned. Tags are stored locally with the existing workspace state and are not included in reports or Agent prompts.

### Agent Session Trace

When the user wants to know what an Agent changed during a session, run the Agent through the package tracer instead of trying to reconstruct causality from old timestamps:

```bash
cyd trace --path /path/to/project -- codex
cyd trace --path /path/to/project -- claude
```

The command after `--` runs normally. The tracer takes bounded metadata snapshots while it runs and reports `created`, `modified`, `deleted`, and transient `created + deleted` paths. It stores the local session and event evidence in `~/.clean-your-data/provenance.sqlite3`. Use repeated `--path` options when the Agent writes to more than one known scope, and `--format json --output trace.json` for a structured handoff.

Interpret the result as: "this path changed while the traced command was running." Do not rewrite that as proof that a particular child process created it. If the file predates the trace session, report its origin as unknown or inferred from separate evidence. A snapshot can miss a very short-lived change, hit the `--max-entries` limit, or be unable to read a protected path; preserve those limitations in the conclusion.

### TUI Cleanup Loop

`dd` is a Vim-style operator: it stages the exact selected path and does not move anything. The right pane shows two separate layers:

1. **Preliminary scan**: a deterministic local heuristic based on category, size, measurement state, and visible shape.
2. **Coding agent advice**: a metadata-only, read-only recommendation that explains evidence, unknowns, risks, preconditions, and rollback.

The agent is an advisor, not the authority. `Y` opens a dialog with the exact path; pressing `y` there moves only that path to the platform Trash. The TUI then re-scans only the focused path. The action writes a local undo record to `~/.clean-your-data/cleanup-history.json`; `u` restores the most recent item without overwriting a newer path and refreshes the focused map again. Incomplete measurements, app-managed data, cloud-sync data, unknown paths, the home directory, and the filesystem root are blocked by deterministic local checks.

Use quick mode for the first pass. It inventories known roots and skips expensive Git and child-directory discovery.

For a deeper decision about migration or cleanup, run:

```bash
python3 scripts/audit_local_files.py \
  --mode full --children --artifacts --git-status \
  --format markdown
```

When the user explicitly asks to find exact duplicate files, run the opt-in pass:

```bash
python3 scripts/audit_local_files.py \
  --duplicates --format markdown --output duplicate-audit.md
```

The default duplicate scope is common workspace roots. App-managed storage, cloud-sync roots, known rebuildable directories, and symlink targets are excluded. Add a specific additional root only when the user understands its ownership:

```bash
python3 scripts/audit_local_files.py \
  --duplicates --duplicate-root /path/to/review \
  --format markdown --output duplicate-audit.md
```

The duplicate report uses a size bucket followed by streaming SHA-256. It exposes an opaque group ID, redacted paths, contexts, hard-link information, and overlap warnings, but not raw hashes. `potential_duplicate_bytes` is logical file size after accounting for hard links; it is not a promise of reclaimable disk space.

Use `--output` to save a report. Use JSON when saving a snapshot for comparison. Read `references/target-taxonomy.md` when adding or interpreting app patterns. Read `references/report-schema.md` when consuming JSON or building an evidence-linked decision. Read `references/action-playbook.md` when turning findings into an action plan.
Read `references/duplicate-detection.md` when interpreting exact-match groups, budgets, hard links, or cloud-sync overlap.
Read `references/interactive-explorer.md` when using a selected path, interpreting `space_map`, or handing metadata to an AI.

Before comparing or sharing a JSON snapshot with another Agent, run:

```bash
python3 scripts/validate_report.py report.json
```

### 3. Interpret the evidence

Organize the explanation in this order:

1. **Discover**: identify the largest target areas and meaningful child directories.
2. **Classify**: label each finding as `deliverable`, `workspace`, `app-state`, `cloud-sync`, `cache`, `inbox`, or `unknown`.
3. **Explain**: say what normally creates the data and which app or workflow owns it.
4. **Assess risk**: distinguish user data, rebuildable data, synchronized data, dirty repositories, and unknown data.
5. **Plan action**: recommend promotion, archive, app-native cleanup, review, or no action. Include the exact path, size, consequence, and rollback or rebuild note.
6. **Compare**: when two JSON reports are available, run `scripts/compare_reports.py` and explain what grew or shrank.

Do not equate “large” with “safe to delete.” A large app container may contain user data; a small untracked file may be important.

Treat `measurement_status: timeout|error|unknown` as unknown, never as zero. Treat artifact rows as candidate subsets that may already be included in a parent workspace total. Use `coverage`, `findings`, and `action_gate` to preserve what was measured, why a conclusion was made, and whether exact cleanup review is blocked.

For an interactive map, require `space_map.status == complete` before treating its distribution as complete evidence. A partial, limited, or not-found map is useful for orientation only. Use the selected node's metadata to ask what it is likely for, what evidence supports that guess, what remains unknown, and what the safest next check is. Do not infer file purpose from size alone.

For duplicate findings, require `duplicates.status == complete` before treating the group list as complete evidence. Even then, verify references, sync state, ownership, and the canonical candidate one group at a time. A cloud-sync copy is not equivalent to a safely removable local copy, and multiple paths may be hard links to one inode.

### 4. Produce a decision-ready report

Lead with a short organization conclusion. Then include:

- disk usage and largest target areas;
- the main accumulation pattern, not just raw numbers;
- app-managed and cloud-sync data that should be handled by its owner;
- Codex/AI workspace counts and deliverable-promotion opportunities;
- Git distribution and dirty-entry risk when available;
- rebuildable artifacts with rebuild hints;
- an approval-gated next-action list.

Use this action language:

- **Promote**: a durable output belongs in a stable library or project root.
- **Archive**: old workspace data can be moved after checking status and references.
- **Use the owning app**: app state or sync data should be managed in-app.
- **Review**: ambiguity remains; inspect only the minimum metadata needed.
- **Rebuildable candidate**: removal may be reasonable after approval and a rebuild check.
- **Keep**: size is not enough evidence for removal.

### 5. Gate cleanup

If the user requests cleanup, present an approval table before changing anything:

| Exact path | Size | Classification | Action | Risk/consequence | Rollback or rebuild |
| --- | ---: | --- | --- | --- | --- |

Prefer reversible moves to Trash for user-visible folders when the user approves them. Never bulk-delete app containers, cloud-sync roots, dirty repositories, or unknown paths.

If the report's `action_gate.status` is `review_only`, do not produce an executable non-TUI cleanup plan. Resolve the listed evidence blockers first. The scanner itself never performs cleanup. The TUI has a separate exact-path gate: `dd` only stages, the coding agent only advises, and the user must confirm the Trash move.

## Snapshot Comparison

The JSON report is intentionally suitable for local snapshots:

```bash
python3 scripts/audit_local_files.py \
  --mode full --children --artifacts --git-status \
  --format json --output before.json

python3 scripts/compare_reports.py before.json after.json
```

The comparison script reports changes in disk usage, target areas, Codex counts, Git buckets, artifacts, and interactive-map coverage. It preserves whatever redaction was present in the input reports and never reads file contents.

The terminal explorer is a local review and reversible Trash surface. Review paths and project names before sharing saved JSON or Markdown; cleanup history stays local and is never part of a report.

## Maintainer Evaluation Loop

For a repeatable skill iteration using local evidence and independent roles, read `references/agentic-evaluation.md`. Keep raw reports in a temporary local directory, pass only an aggregated redacted packet to reviewers, record timed-out roles as incomplete, then require contract and fixture tests before publishing.

## Failure Handling

- If a size probe times out, report it as unknown or timed out. Do not silently treat it as zero.
- If Git discovery is skipped, say so and do not recommend moving repositories until status is checked.
- If a path is ambiguous, classify it as `unknown` and ask for targeted review instead of guessing.
- If no interactive terminal is available, use `--format json` or `--format markdown` and continue with a non-interactive handoff.
- If the user asks for content inspection, restate the metadata-only boundary and ask for the smallest explicit scope needed.
