# Report Contract

The JSON report is a local evidence artifact, not a cleanup authorization. `schema_version` is incremented when the contract changes.

## Core Fields

| Field | Meaning |
| --- | --- |
| `settings.scope_id` | Logical scan scope. The default home scan uses `home`. Do not combine reports with different scopes without saying so. |
| `settings.size_kind` | `allocated_bytes`; these are filesystem allocation estimates, not apparent file size. |
| `target_areas[]` | Discovered known roots. `allocated_bytes` may be `null`. |
| `target_areas[].measurement_status` | `measured`, `timeout`, `error`, `missing`, or `unknown`. Never treat a non-measured row as zero. |
| `coverage[]` | Coverage ledger for configured target families, including matches, unknown rows, measured bytes, and status. |
| `findings[]` | Evidence-linked decision records with owner, risk, confidence, recommendation, and rollback/rebuild guidance. |
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

## Action Gate

`review_only` is required when any target or artifact is not measured, Git status is missing, or dirty Git changes exist. Even without blockers, `approval_required` remains true. App-state and cloud-sync findings remain owner-managed.
