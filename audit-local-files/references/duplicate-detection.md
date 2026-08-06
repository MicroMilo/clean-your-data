# Exact Duplicate Detection

Duplicate detection is a deliberately separate phase from the default metadata audit.

## Boundary

The default scanner does not read file contents. `--duplicates` is an explicit opt-in because it reads candidate bytes locally to calculate SHA-256. The scanner makes no network requests, does not store raw digests in the report, and never moves or deletes files.

The default scope is the common workspace roots already used by the audit: Desktop, Downloads, Codex workspaces, and conventional source roots. App-managed storage, cloud-sync roots, known rebuildable directories, and symlink targets are excluded. A user can add an understood directory with repeated `--duplicate-root PATH`.

## Algorithm

1. Walk selected roots without following symlinks.
2. Skip known dependency/build/cache directories.
3. Group regular files by logical `st_size`.
4. Stream SHA-256 only for size buckets containing at least two files.
5. Re-stat each file after hashing. A file that changed, disappeared, or exceeded a budget is not treated as an exact match.
6. Group identical `(size, digest)` pairs and report the digest-derived group ID without exposing the digest.

The scanner has independent time, logical-byte, and candidate-file budgets. An incomplete scan may still show groups found before the limit, but `duplicates.status` will not be `complete` and the action gate remains review-only.

## Reading A Group

- `file_count` counts reported paths.
- `independent_copy_count` counts distinct device/inode pairs.
- `hardlink_alias_count` counts additional paths to an existing inode. These aliases do not represent additional stored content.
- `potential_duplicate_bytes` is `size_bytes * max(independent_copy_count - 1, 0)`. It uses logical bytes, not allocated filesystem blocks.
- `canonical_candidate_path` is a deterministic review candidate. It is not an authorization to delete the other paths.
- `parent_targets`, `artifact_parents`, and `overlap_warnings` prevent duplicate evidence from being added to parent directory or artifact totals.

Cloud-sync copies require special care: a local duplicate may be represented on another device, held by provider retention, or still be referenced by an app. Review sync state and ownership before archiving anything.
