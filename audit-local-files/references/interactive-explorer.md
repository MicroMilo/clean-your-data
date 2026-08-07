# Terminal Explorer Contract

The terminal explorer is the product layer on top of the local audit. It gives a user a bounded view of one path, a way to continue the conversation about a selected area, and an explicit reversible Trash loop without turning the scanner itself into a mutating tool.

## User Loop

```text
select a path
  -> scan bounded metadata
  -> move through the tree
  -> ask a plain-language question
  -> inspect the answer, evidence, and unknowns
  -> dd stage an exact cleanup candidate
  -> inspect preliminary scan and coding-agent advice
  -> confirm a reversible Trash move
  -> refresh the focused map
  -> undo or run a later comparison
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
- `dd`: stage the selected exact path in the cleanup basket; the first `d` only arms the Vim-style operator;
- `Y`: open the exact-path Trash confirmation dialog; `y` confirms inside the dialog and `Esc` cancels;
- `u`: restore the most recent recorded Trash move without overwriting an existing path;
- `t`: open Terminal at the selected folder (a selected file uses its parent folder);
- `v`: open VS Code, `c`: open Cursor, and `o`: reveal the selected path in Finder;
- `m`: bookmark or unbookmark the selected path; `M`: browse bookmarks and recent paths;
- `w` / `W`: save or restore the last workspace selection;
- `D`: run a bounded metadata-only relationship analysis for the selected path;
- `/`: start fuzzy search across loaded names, paths, area labels, categories, and local tags; `Enter` applies and `Esc` cancels;
- `f`: choose a single view filter for folders, files, large items, recent changes, likely rebuildable paths, bookmarks, cleanup candidates, or tagged paths;
- `s`: choose sibling sorting by original tree order, name, allocated size, modification time, or kind;
- `T`: edit comma-separated local tags for the selected path; tagged rows show `@` and the `tagged` filter can find them;
- `N`: open the selected folder in a new session-local tab; `gt` and `gT` switch tabs; `X` closes the current tab;
- `C`: copy the current metadata-only context;
- `r`: reload the selected file preview;
- `?`: show help;
- `q`: quit without changing files unless a confirmed Trash move was already completed.

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

The prompt asks an Agent to explain likely purpose, supporting evidence, unknowns, and the safest next check. The cleanup-advisor prompt additionally asks for a recommendation among keep, review, archive, rebuildable candidate, use the owning app, or do not touch. It labels the scan as preliminary and must not ask the Agent to delete anything or treat its answer as authorization.

When the `codex` CLI is available, `a` starts this read-only ephemeral command automatically:

```bash
codex exec --sandbox read-only --ephemeral --skip-git-repo-check -C /tmp -
```

The TUI sends only the metadata prompt on stdin. The file preview is not sent. To use another local command, set it explicitly:

```bash
export CLEAN_YOUR_DATA_AI_COMMAND='my-local-agent --answer'
python3 scripts/audit_local_files.py --tui --path /path/to/review
```

The command receives the prompt on stdin and its stdout is shown as the answer. The request runs in a background worker, so navigation remains available while the spinner runs. Codex authentication, network access, and response handling stay with the host CLI. If no command is available, the report continues to work and `C` remains available for copying the prompt.

## Cleanup Boundary

`dd` never moves a file. It records a candidate in the current TUI session and shows a deterministic preliminary scan explanation. The TUI then asks the configured local coding agent for a separate read-only recommendation using the node's redacted metadata. That recommendation is advisory: it may say keep, review, archive, rebuildable candidate, use the owning app, or do not touch, but it cannot authorize an action or execute a command.

Before `Y` can open, deterministic local checks require an existing, completely measured path that is not the home directory, filesystem root, system Trash, app-managed data, cloud-sync data, or an unknown category. `Y` shows the exact path and size. Only `y` inside that dialog moves the one staged path to the platform Trash. The scanner report remains read-only.

Successful moves are written to the local-only `~/.clean-your-data/cleanup-history.json` file, then the focused map is re-scanned. `u` restores the most recent item if its Trash entry still exists and the original path is not occupied, then refreshes the map again. No report contains cleanup history, and no cleanup operation is sent to the coding agent.

## Path Context, Launchers, and Deep Analysis

The selected node is the shared context for local actions. `t` opens a terminal at the selected folder, while `v`, `c`, and `o` open VS Code, Cursor, or Finder without passing the path through a shell. Moving the cursor does not inject `cd` commands into an existing terminal.

Bookmarks, recent paths, local tags, and the last workspace selection are stored locally in `~/.clean-your-data/workspace-state.json`. They are not added to reports or sent to an Agent. Tabs live only for the current TUI session. Search, filters, and sorting operate over the currently loaded bounded map; a filtered result does not prove that unopened descendants were inspected. `D` scans a selected path in a background worker using names, sizes, extensions, project markers, and directory shape only. It can relate source files to build directories, dependencies, outputs, and possible same-name/same-size matches; those matches are candidates, not confirmed duplicates.

## Evidence Rules

- `complete` means the bounded request finished; it does not mean the entire computer was scanned.
- `partial`, `limit`, and `not_found` are orientation results, not complete distribution evidence.
- A failed size probe is unknown, never zero.
- Redaction applies to selected paths outside the home directory as well: they appear as `<external>/name` by default.
- The scanner never authorizes or performs cleanup. The TUI performs only the explicit, exact-path Trash move described above.
