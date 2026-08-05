# Agentic Evaluation Loop

Use this loop when improving the skill. It is a maintainer workflow, not a user cleanup workflow.

```text
real local audit
  -> aggregate and redact evidence packet
  -> independent role reviews
  -> main-agent synthesis
  -> bounded code/doc change
  -> deterministic fixture and contract tests
  -> public release
```

## Evidence Packet

Create a temporary packet containing only aggregate counts, sizes, statuses, and scanner limitations. Remove project names, repository names, exact paths, Git origins, prompts, and file contents. Keep the raw report local and never commit it.

## Recommended Roles

- **Audit operator**: check coverage, timeouts, duplicate counting, and whether conclusions are supported.
- **Privacy guardian**: check redaction, content boundaries, origin URLs, command scope, and report sharing risk.
- **First-time user**: check whether the Agent can start quickly and produce a decision instead of a raw size list.
- **Loop architect**: check whether findings have evidence references, confidence, coverage state, and regression tests.

Require each role to return findings, evidence, severity, and the smallest concrete improvement. A role that times out is recorded as incomplete, not as approval.

## Acceptance Gates

Before publishing an iteration:

1. No cleanup or migration was executed during evaluation.
2. Non-measured sizes are represented as `null` with an explicit status.
3. Coverage and findings are linked to evidence.
4. Parent and artifact sizes are not summed as independent reclaimable space.
5. Privacy defaults and synthetic fixtures pass regression tests.
6. The README explains the user-facing outcome and the Agent handoff.
