# Report Contract

The JSON report is a local evidence artifact, not a cleanup authorization. The current generator emits schema `1.3`; validators continue to accept `1.1`, `1.2`, and `1.3` snapshots.

## Core Fields

| Field | Meaning |
| --- | --- |
| `settings.scope_id` | Logical scan scope. The default home scan uses `home`. Do not combine reports with different scopes without saying so. |
| `settings.size_kind` | `allocated_bytes`; these are filesystem allocation estimates, not apparent file size. |
| `target_areas[]` | Discovered known roots. `allocated_bytes` may be `null`. |
| `target_areas[].measurement_status` | `measured`, `timeout`, `error`, `missing`, or `unknown`. Never treat a non-measured row as zero. |
| `coverage[]` | Coverage ledger for configured target families, including matches, unknown rows, measured bytes, and status. |
| `findings[]` | Evidence-linked decision records with owner, risk, confidence, recommendation, and rollback/rebuild guidance. |
| `duplicates` | Optional exact-match evidence. Disabled by default; enabled reports describe local hashing scope, completion status, duplicate groups, and overlap warnings. |
| `space_map` | Optional bounded tree for a selected path. It is disabled by default and contains metadata for a keyboard-navigable terminal explorer, not file contents. |
| `action_gate` | Whether the report is `review_only` or only `approval_required`. The scanner never authorizes or executes cleanup. |

## Finding Contract

Every finding should preserve these fields:

```json
{
  "finding_id": "target-opaque-id",
  "scope_id": "home",
  "path_redacted": "~/example",
  "category": "workspace",
  "owner": "project or agent workflow",
  "size_bytes": 123,
  "status": "measured",
  "evidence_refs": ["target_areas[0]"],
  "confidence": "strong_inference",
  "risk": "user-data",
  "recommendation": "Review and promote durable outputs before archiving.",
  "approval_required": true,
  "rollback_or_rebuild": "Restore from the archive or original project location."
}
```

Confidence is deliberately qualitative:

- `confirmed`: direct local metadata supports the claim, such as a Git status count;
- `strong_inference`: a known path pattern and metadata support the classification;
- `low`: timeout, error, or incomplete evidence prevents a reliable conclusion.

## Overlap Rules

Target areas are containers. Artifacts are candidate subsets and may already be included in a parent target's size. Use `parent_target_id`, `counted_in_total`, and `nested_artifact` to avoid adding parent and child bytes together as reclaimable space.

Duplicate detection is a separate, explicit content-reading pass. The default report uses:

```json
{
  "duplicates": {
    "enabled": false,
    "status": "disabled",
    "groups": []
  }
}
```

With `--duplicates`, the scanner reads candidate file bytes locally after grouping by logical size. It streams SHA-256, never uploads content, and does not expose raw digests. A group contains redacted paths, a stable opaque group ID, `file_count`, `independent_copy_count`, `hardlink_alias_count`, `potential_duplicate_bytes`, and a contextual review candidate.

`potential_duplicate_bytes` uses logical file size and subtracts hard-link aliases from the independent-copy count. It is not allocated disk usage and is not guaranteed reclaimable space. Duplicate paths may already be inside a measured target or artifact, so `parent_targets`, `artifact_parents`, `contains_cloud_sync`, and `overlap_warnings` must be read before comparing totals. App-managed and cloud-sync roots are excluded unless the user explicitly adds a root with `--duplicate-root`.

## Interactive Space Map

The map is opt-in. The default schema `1.3` report carries the disabled shape:

```json
{
  "space_map": {
    "enabled": false,
    "status": "disabled",
    "nodes": [],
    "node_count": 0
  }
}
```

Run the scanner with `--path PATH` or `--interactive` to populate it. A node contains a redacted `path`, `name`, `kind`, `category`, `area`, `allocated_bytes`, `human_size`, `modified_at`, `measurement_status`, `child_count`, and `can_expand`, plus opaque local `node_id` and `parent_id` values. The scanner follows no symlinks and reads no file contents during the initial map. `can_expand` may remain true at the `--focus-depth` boundary; the TUI then loads that folder's immediate children on demand. `--focus-limit`, `--focus-timeout`, and `--focus-time-budget` still bound each scan step.

Valid map statuses are `complete`, `partial`, `limit`, `not_found`, and `disabled`. Only `complete` means the bounded requested view finished within its evidence limits. Other statuses must remain visible to the Agent and user.

The terminal explorer turns the selected node into a metadata-only prompt containing path, name, kind, size, last-change time, area, measurement state, and the user's question. Press `a` to ask the local Codex CLI when available, or `c` to copy that prompt. A trusted local command configured through `CLEAN_YOUR_DATA_AI_COMMAND` may replace Codex and read the prompt from stdin. For a selected file, the TUI may show a local preview capped at 4 KB and 14 lines; it is never included in the prompt or saved report. The expected loop is: select a node, ask what it is likely used for, inspect evidence and unknowns, ask a follow-up, then run a later snapshot to compare change.

## Action Gate

`review_only` is required when any target or artifact is not measured, Git status is missing, dirty Git changes exist, an enabled duplicate scan is incomplete, or an enabled space map is not complete. Even without blockers, `approval_required` remains true. App-state and cloud-sync findings remain owner-managed, and exact duplicate groups always require per-group approval.
