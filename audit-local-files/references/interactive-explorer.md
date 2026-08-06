# Terminal Explorer Contract

The terminal explorer is the product layer on top of the local audit. It gives a user a bounded view of one path and a way to continue the conversation about a selected area without turning the scanner into a cleanup tool.

## User Loop

```text
select a path
  -> scan bounded metadata
  -> move through the tree
  -> ask a plain-language question
  -> inspect the answer, evidence, and unknowns
  -> ask a follow-up or run a later comparison
```

Start it with:

```bash
python3 scripts/audit_local_files.py \
  --tui \
  --path /path/to/review \
  --focus-depth 2
```

Controls:

- `Up` / `Down`: select visible areas; `gg` jumps to the top, `G` jumps to the bottom, `Home`/`End` jump to the endpoints, and `PageUp`/`PageDown` move by a screen;
- `Left` / `Right`: collapse, expand, or move into a folder;
- `Enter`: load and open one more level, then close the selected folder when pressed again;
- `a`: open the question box beside the tree; `Enter` sends, `Esc` or `Ctrl-C` cancels. While it is open, `q` is question text;
- `c`: copy the current metadata-only context;
- `r`: reload the selected file preview;
- `?`: show help;
- `q`: quit without changing files.

Mouse clicks select an area, double-clicking a folder opens it, and the scroll wheel moves the selection. TUI startup measures only the selected roots rather than running the full home audit first.

`--path` may be repeated. `--focus-depth` sets the initial scan depth (2 by default). A folder at the scan boundary remains expandable; pressing `Enter` loads only that folder's immediate children. The TUI has no fixed depth limit, while `--focus-limit`, `--focus-timeout`, and `--focus-time-budget` still bound each scan step. The scanner never follows symlinks.

## Node Metadata

Each `space_map.nodes[]` item is a presentation-safe evidence unit:

- `node_id`, `parent_id`, and `root_id` are opaque stable identifiers for the report;
- `path` and `name` are redacted by default;
- `kind` distinguishes `folder` and `file`;
- `allocated_bytes` and `human_size` describe measured filesystem allocation;
- `modified_at` is the last-change timestamp when available;
- `category` and `area` are path-based classifications, not claims about private content;
- `measurement_status` and `measurement_error` preserve incomplete evidence;
- `child_count` and `can_expand` describe the bounded view.

The map is not a full disk visualizer. It is a focused explanation surface. A node that is large may still be active work, app state, synchronized data, or an important deliverable. `can_expand` can remain true when the initial scan stopped at its depth boundary; the TUI uses that signal to load the next level on demand.

## File Preview

When a file is selected, the TUI reads at most 4 KB and 14 lines locally and shows the text on the right. Binary files and names that look like credentials or private configuration are hidden. Press `r` to reload the preview. The preview is not stored in the JSON report and is never included in the metadata-only Codex prompt.

## AI Handoff Boundary

The generated prompt includes only:

- selected path and name;
- folder/file kind;
- measured size;
- last-change time;
- path-based area label;
- measurement status;
- the user's question.

The prompt asks an Agent to explain likely purpose, supporting evidence, unknowns, and the safest next check. It must not ask the Agent to delete anything merely because the node is large.

When the `codex` CLI is available, `a` starts this read-only ephemeral command automatically:

```bash
codex exec --sandbox read-only --ephemeral --skip-git-repo-check -C /tmp -
```

The TUI sends only the metadata prompt on stdin. The file preview is not sent. To use another local command, set it explicitly:

```bash
export CLEAN_YOUR_DATA_AI_COMMAND='my-local-agent --answer'
python3 scripts/audit_local_files.py --tui --path /path/to/review
```

The command receives the prompt on stdin and its stdout is shown as the answer. The request runs in a background worker, so navigation remains available while the spinner runs. Codex authentication, network access, and response handling stay with the host CLI. If no command is available, the report continues to work and `c` remains available for copying the prompt.

## Evidence Rules

- `complete` means the bounded request finished; it does not mean the entire computer was scanned.
- `partial`, `limit`, and `not_found` are orientation results, not complete distribution evidence.
- A failed size probe is unknown, never zero.
- Redaction applies to selected paths outside the home directory as well: they appear as `<external>/name` by default.
- The explorer never authorizes or performs cleanup.
