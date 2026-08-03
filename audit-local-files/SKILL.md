---
name: audit-local-files
description: Analyze local computer file organization, workspace sprawl, Codex/date outputs, downloads, cloud-drive folders, Git repo distribution, and chat/collaboration app sediment such as Feishu/Lark, WeChat, Slack, Teams, Discord, Telegram, QQ, DingTalk, and Zoom. Use when the user asks to audit local files, organize Desktop/Downloads/projects, inspect local app storage, identify reusable deliverables, or propose safe archive and cleanup plans.
---

# Clean Your Data

## Purpose

Use this skill to produce a privacy-preserving, read-only local file organization audit. The default job is to explain where files are accumulating, which areas are durable knowledge assets, which are temporary workspaces, which are app-managed state, and what can be promoted, archived, or reviewed for cleanup.

## Safety Boundary

- Start read-only. Do not move, delete, or rewrite files unless the user explicitly approves exact paths or cleanup categories.
- Do not read chat message databases, browser history, credentials, keychains, app profile databases, or private document contents unless the user explicitly asks for that exact content.
- For chat/collaboration apps, treat container and application-support directories as `app-state` by default. Prefer app-native storage managers for cleanup.
- For Git repositories, inspect status before any proposed move or cleanup. Dirty repositories and untracked source files are user data.
- For rebuildable artifacts such as `node_modules`, `.venv`, `build`, `dist`, `.next`, and `target`, explain rebuild cost and get approval before removal.
- Reports redact the home path by default and use `~` in paths. Git origin URLs are omitted unless the user explicitly passes `--include-git-origins`.

## Workflow

1. Establish scope. If the user does not specify a path, default to the current user's home directory.
2. Run the bundled scanner:

```bash
python3 scripts/audit_local_files.py --format markdown
```

Quick mode favors fast known-location inventory, limited size probes, and skips deep Git and child-directory discovery. Use it first when analyzing an unfamiliar machine.

For deeper project evidence, run:

```bash
python3 scripts/audit_local_files.py --mode full --children --artifacts --git-status --format markdown
```

For a private, non-shareable local report with absolute paths, pass `--no-redact`. For Git origin URLs, pass `--include-git-origins`; do not use that flag for public examples or issue attachments.

3. Interpret the report using these buckets:
   - `deliverable`: outputs worth promoting into a stable archive or knowledge base.
   - `workspace`: project folders, Git repos, Codex date workspaces, experiments.
   - `app-state`: chat, email, browser, and cloud-sync application data.
   - `cache`: rebuildable package, build, or tool cache.
   - `unknown`: needs human review before action.
4. Recommend a stable target structure before cleanup. A common shape is:

```text
~/work/
~/research/
~/papers/
~/personal/
~/src/github.com/<owner>/<repo>
~/archive/YYYY-MM/
```

5. If cleanup is requested, present an approval-gated plan with exact targets, size, risk, consequence, and rollback. Prefer moving user-visible folders to Trash over permanent deletion.

## Target Taxonomy

Read `references/target-taxonomy.md` when adding new app patterns, explaining why an app is similar to Feishu/WeChat, or classifying ambiguous findings.

## Report Expectations

Lead with the organization conclusion, not raw sizes. Include:

- largest workspace roots and app-state areas;
- scattered Git repo buckets and dirty repo risk when available;
- Codex date/output/work accumulation;
- chat/collaboration app sediment that should be managed in-app;
- deliverable promotion opportunities;
- cleanup candidates only as optional, approval-gated next steps.
