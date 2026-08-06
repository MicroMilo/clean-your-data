---
name: audit-local-files
description: Turn local file sprawl into a privacy-preserving, decision-ready audit. Use when someone asks to analyze or organize Desktop, Downloads, Documents, Codex or other AI workspaces, Git repositories, cloud-sync folders, or local storage from Feishu/Lark, WeChat, Slack, Teams, Discord, Telegram, QQ, DingTalk, Zoom, mail, or browsers. Also use when proposing a safe archive, migration, cleanup, or before/after storage comparison.
---

# Clean Your Data

Use this skill as a local data audit protocol. The goal is not to produce a large directory listing. The goal is to explain what is accumulating, who owns it, what is durable or rebuildable, what is risky, and what the user can safely do next.

## Safety Contract

- Start read-only. Never move, delete, rewrite, or clean files unless the user approves exact paths or an explicit category.
- Inspect metadata only: path existence, allocated size, modification time, and optional Git status counts.
- Do not read chat databases, browser history, email bodies, document text, source code, credentials, keychains, or other private contents.
- Treat Feishu/Lark, WeChat, Slack, Teams, Discord, Telegram, QQ, DingTalk, Zoom, mail, browser, and cloud-sync containers as app-managed or sync-managed state. Recommend the owning app for cleanup.
- Treat dirty Git repositories and untracked files as user data. Check status before proposing a move.
- Treat `node_modules`, `.venv`, `build`, `dist`, `.next`, `target`, and similar directories as candidates, not automatic deletions. Explain rebuild cost first.
- Keep home paths redacted and Git origins omitted. Never use `--no-redact` or `--include-git-origins` for a public report.

## Workflow

### 1. Establish scope

If the user does not name a path, use the current user's home directory. State that the first pass is local, read-only, metadata-only, and anonymized.

### 2. Run the first audit

From the skill directory, run:

```bash
python3 scripts/audit_local_files.py --format markdown
```

For a human-friendly offline report that can be opened or printed in a browser:

```bash
python3 scripts/audit_local_files.py \
  --format html \
  --output local-file-audit.html
```

Prefer HTML for a person reviewing one audit, JSON for Agent handoff or snapshot comparison, and Markdown when plain text is more convenient. The HTML file is self-contained and makes no network requests.

Use quick mode for the first pass. It inventories known roots and skips expensive Git and child-directory discovery.

For a deeper decision about migration or cleanup, run:

```bash
python3 scripts/audit_local_files.py \
  --mode full --children --artifacts --git-status \
  --format markdown
```

Use `--output` to save a report. Use JSON when saving a snapshot for comparison. Read `references/target-taxonomy.md` when adding or interpreting app patterns. Read `references/report-schema.md` when consuming JSON or building an evidence-linked decision. Read `references/action-playbook.md` when turning findings into an action plan.

Before comparing or sharing a JSON snapshot with another Agent, run:

```bash
python3 scripts/validate_report.py report.json
```

### 3. Interpret the evidence

Organize the explanation in this order:

1. **Discover**: identify the largest target areas and meaningful child directories.
2. **Classify**: label each finding as `deliverable`, `workspace`, `app-state`, `cloud-sync`, `cache`, `inbox`, or `unknown`.
3. **Explain**: say what normally creates the data and which app or workflow owns it.
4. **Assess risk**: distinguish user data, rebuildable data, synchronized data, dirty repositories, and unknown data.
5. **Plan action**: recommend promotion, archive, app-native cleanup, review, or no action. Include the exact path, size, consequence, and rollback or rebuild note.
6. **Compare**: when two JSON reports are available, run `scripts/compare_reports.py` and explain what grew or shrank.

Do not equate “large” with “safe to delete.” A large app container may contain user data; a small untracked file may be important.

Treat `measurement_status: timeout|error|unknown` as unknown, never as zero. Treat artifact rows as candidate subsets that may already be included in a parent workspace total. Use `coverage`, `findings`, and `action_gate` to preserve what was measured, why a conclusion was made, and whether exact cleanup review is blocked.

### 4. Produce a decision-ready report

Lead with a short organization conclusion. Then include:

- disk usage and largest target areas;
- the main accumulation pattern, not just raw numbers;
- app-managed and cloud-sync data that should be handled by its owner;
- Codex/AI workspace counts and deliverable-promotion opportunities;
- Git distribution and dirty-entry risk when available;
- rebuildable artifacts with rebuild hints;
- an approval-gated next-action list.

Use this action language:

- **Promote**: a durable output belongs in a stable library or project root.
- **Archive**: old workspace data can be moved after checking status and references.
- **Use the owning app**: app state or sync data should be managed in-app.
- **Review**: ambiguity remains; inspect only the minimum metadata needed.
- **Rebuildable candidate**: removal may be reasonable after approval and a rebuild check.
- **Keep**: size is not enough evidence for removal.

### 5. Gate cleanup

If the user requests cleanup, present an approval table before changing anything:

| Exact path | Size | Classification | Action | Risk/consequence | Rollback or rebuild |
| --- | ---: | --- | --- | --- | --- |

Prefer reversible moves to Trash for user-visible folders when the user approves them. Never bulk-delete app containers, cloud-sync roots, dirty repositories, or unknown paths.

If the report's `action_gate.status` is `review_only`, do not produce an executable cleanup plan. Resolve the listed evidence blockers first. The scanner itself never performs cleanup, even when the gate is `approval_required`.

## Snapshot Comparison

The JSON report is intentionally suitable for local snapshots:

```bash
python3 scripts/audit_local_files.py \
  --mode full --children --artifacts --git-status \
  --format json --output before.json

python3 scripts/compare_reports.py before.json after.json
```

The comparison script reports changes in disk usage, target areas, Codex counts, Git buckets, and artifacts. It preserves whatever redaction was present in the input reports and never reads file contents.

HTML is a presentation of one local report, not a public data export. Review paths and project names before sharing it.

## Maintainer Evaluation Loop

For a repeatable skill iteration using local evidence and independent roles, read `references/agentic-evaluation.md`. Keep raw reports in a temporary local directory, pass only an aggregated redacted packet to reviewers, record timed-out roles as incomplete, then require contract and fixture tests before publishing.

## Failure Handling

- If a size probe times out, report it as unknown or timed out. Do not silently treat it as zero.
- If Git discovery is skipped, say so and do not recommend moving repositories until status is checked.
- If a path is ambiguous, classify it as `unknown` and ask for targeted review instead of guessing.
- If the user asks for content inspection, restate the metadata-only boundary and ask for the smallest explicit scope needed.
