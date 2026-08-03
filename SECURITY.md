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
- Performing destructive file operations.

The scanner should remain read-only.
