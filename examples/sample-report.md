# Example Decision-Ready Report

This is synthetic data. It is not a report from a real machine.

## Outcome

- Read-only: no files were changed.
- Main pattern: the largest areas are an AI workspace, app-managed collaboration data, and rebuildable project artifacts.
- Highest-risk area: a Git repository with uncommitted changes.
- Decision state: `review_only`; exact cleanup decisions are blocked until incomplete measurements and dirty work are reviewed.
- First action: preserve project changes and promote durable outputs before considering cleanup.

## Findings

| Size | Status | Confidence | Classification | Owner | Recommended action |
| ---: | --- | --- | --- | --- | --- |
| 8.4 GB | `measured` | `strong_inference` | `workspace` | AI workflow | Review outputs; promote durable results; archive old dates |
| 6.1 GB | `measured` | `strong_inference` | `app-state` | Collaboration app | Use the app's storage controls; do not delete the container |
| 3.7 GB | `measured` | `strong_inference` | `cache` | Project toolchain | Confirm the rebuild command, then request approval |
| unknown | `timeout` | `low` | `workspace` | Git project | Preserve or inspect before moving anything |

## Safe Next Actions

1. Inspect the exact Git status before any migration.
2. Move only selected durable outputs into a stable project or library root.
3. Use the collaboration app's own storage controls for app-managed data.
4. Remove rebuildable artifacts only after confirming their rebuild cost.

## After A Week

A later snapshot can turn the same audit into a trend report:

```text
Disk used: +4.2 GB
AI workspace outputs: +18
Build artifacts: +2.6 GB
Git dirty changes: +37
```

That tells the user where the accumulation is coming from, instead of asking them to repeat an unstructured prompt and compare two unrelated answers.

## What This Report Does Not Mean

A large path is not automatically disposable. A small path can still contain important work. The scanner provides evidence and a review order; the user approves any change.
