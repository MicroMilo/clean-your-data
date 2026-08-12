# Privacy

Clean Your Data is designed for local, metadata-first analysis. The bundled scanner and GUI server do not make network requests and do not upload reports. An agent may download this public repository, but the scan itself runs on the user's machine. The optional GUI/TUI cleanup loop can move an exact user-confirmed path to the local system Trash; that action and its undo record stay on the machine.

## Local Browser GUI

- The GUI binds only to `127.0.0.1` on a random port by default.
- It validates the loopback Host; its JSON API requires a random per-run token and rejects cross-origin browser requests.
- Public API responses omit absolute local paths and internal `_local_path` fields.
- The browser receives redacted paths, bounded metadata, and only the preview the user explicitly selects.
- Closing the server ends the session. Agent conversations in the browser are not persisted by Clean Your Data.

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

## Optional AI Commands

AI is disabled or configured by the user. Clean Your Data can call an already authenticated Codex CLI or a trusted custom stdin/stdout command. It stores the selected mode and custom-command arguments verbatim in `~/.clean-your-data/ai-config.json`, with user-only file permissions where supported. The GUI reports that a command is configured but does not echo its arguments through the local browser API; `cyd config ai --show` is the explicit terminal view. There is no API-key field: never put credentials in command arguments, and keep them in the provider's environment or credential store.

The opt-in tracer also stores the traced command and its arguments verbatim in the local `~/.clean-your-data/provenance.sqlite3` database. Do not put credentials directly in a traced command line. The state directory and database use user-only permissions where the operating system supports them.

The stdin prompt constructed by Clean Your Data contains a redacted path, name, kind, size, modified time, category, and measurement status. Clean Your Data does not place the selected file preview or file contents in that prompt. The built-in Codex mode uses a read-only, ephemeral sandbox. A custom command still has its own operating-system permissions and may use its own network connection or credential store; configure only a trusted command and review that provider's privacy behavior separately.

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
