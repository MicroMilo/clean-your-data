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
- Exposing the GUI beyond loopback, accepting an unauthenticated API request, or returning internal absolute paths in a public API response.
- Storing provider API keys in the Clean Your Data AI configuration.

The scanner should remain read-only. GUI and TUI may mutate files only through an explicit move of measured, eligible, exactly confirmed paths into system Trash. They must never permanently delete or touch the active scan root, home/root, Trash, VCS metadata, credential stores, credential configuration, app-managed data, cloud-sync roots, unknown paths, or incomplete measurements.

The GUI must bind to `127.0.0.1`, validate the loopback Host, require a random per-run token on every API request, reject cross-origin browser requests, return no internal `_local_path`, apply a restrictive content security policy, and avoid exposing tracebacks to the browser. Custom AI commands must be parsed into direct arguments and must never be executed through a shell.
