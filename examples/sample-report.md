# Local File Audit

Generated: `2026-01-01T12:00:00+00:00`

Read-only: no files were modified, moved, or deleted.

## Outcome

- Home: `~`
- Disk: 120.0 GB used, 380.0 GB free, 500.0 GB total
- Desktop is large enough to treat as an inbox. Move durable work into stable roots such as `~/work`, `~/research`, `~/papers`, `~/personal`, or `~/src`.
- Chat, browser, email, and collaboration app storage is material. Use app-native storage cleanup before filesystem deletion.
- Git discovery was skipped for speed. Re-run with `--git` before planning repository moves.

## Largest Target Areas

| Size | Category | Risk | Path | Label |
| --- | --- | --- | --- | --- |
| 12.0 GB | workspace | user-data | `~/Desktop` | Desktop |
| 8.5 GB | app-state | user-data | `~/Library/Containers/com.example.chat` | Example Chat |
| 6.0 GB | workspace | user-data | `~/Documents/Codex` | Codex date workspaces |
| 950.0 MB | inbox | user-data | `~/Downloads` | Downloads |

## Suggested Next Step

Create a promotion map before deleting anything: choose which outputs belong in stable folders, which workspaces should be archived, and which app-managed data should be cleaned inside the owning app.
