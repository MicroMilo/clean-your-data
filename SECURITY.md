# Security

## Reporting Issues

Please report security or privacy issues privately to the repository maintainer.

Do not attach raw reports from your machine unless you have reviewed them for sensitive path names, project names, and Git metadata.

## Scope

Security-sensitive issues include:

- Reading private contents instead of metadata.
- Leaking absolute home paths despite default redaction.
- Emitting Git origin URLs without `--include-git-origins`.
- Following symlinks or paths in a way that unexpectedly scans outside the requested scope.
- Moving a path without the exact-path confirmation flow, or bypassing the system Trash and undo record.
- Overwriting an existing path during undo.
- Passing a selected path through shell interpolation instead of a direct argument when opening Terminal, VS Code, Cursor, or Finder.

The scanner should remain read-only. The TUI's only mutating operation is an explicit move of one measured, eligible path into system Trash after `dd`, `Y`, and `y`; it must never permanently delete, bulk-delete, or touch app-managed, cloud-sync, unknown, home, or root paths.
