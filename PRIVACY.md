# Privacy

Clean Your Data is designed for local, metadata-first analysis. The bundled scanner does not make network requests and does not upload reports. An agent may download this public repository, but the scan itself runs on the user's machine. The optional TUI cleanup loop can move an exact user-confirmed path to the local system Trash; that action and its undo record stay on the machine.

## Default Redaction

By default:

- The home directory is rendered as `~`.
- Git origin URLs are omitted.
- Reports do not include file contents.
- Reports do not include chat, mail, browser, or document contents.

Avoid sharing reports created with:

```bash
--no-redact
--include-git-origins
```

## Data The Scanner May Collect

- Directory paths, usually home-relative.
- Allocated byte counts from `du` or a standard-library fallback.
- Modification times.
- Known category labels such as `workspace`, `app-state`, `cloud-sync`, `cache`, and `inbox`.
- Optional Git dirty-entry counts from `git status --porcelain`.

## Data The Scanner Should Not Collect

- Message text.
- Browser history.
- Email bodies.
- Document text.
- Secrets, tokens, keychains, or credentials.
- Source file contents.

## Sharing Reports

Before sharing a report publicly:

- Prefer Markdown over JSON.
- Review path names for sensitive project names.
- Do not include Git origin URLs.
- Do not include absolute home paths.
- Do not include full raw reports from work machines without review.

JSON snapshots are intended for local before/after comparison. They can still contain home-relative project and folder names, so treat them as private until reviewed.

## Cleanup History

The TUI stores the original and Trash paths needed for undo in `~/.clean-your-data/cleanup-history.json`. This file is local-only and is not included in JSON/Markdown reports or sent to the coding agent. Review or remove it according to your local retention needs.

Bookmarks, recent paths, local tags, and the last workspace selection are stored locally in `~/.clean-your-data/workspace-state.json`. Tabs exist only for the current TUI session. Deep path analysis uses names, extensions, sizes, project markers, and directory shape; it does not read file contents or calculate hashes. These state files and analysis results are not included in reports or uploaded.
