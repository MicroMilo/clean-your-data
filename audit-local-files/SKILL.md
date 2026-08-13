---
name: audit-local-files
description: Run the legacy machine-wide Clean Your Data audit, validate its report, or compare two local storage snapshots. Use only when explicitly asked for the compatibility audit scripts, a broad home-directory report, or historical report comparison. For one-path explanations and normal product use, prefer the clean-your-data skill and the cyd command.
license: MIT
metadata:
  author: MicroMilo
  status: compatibility
---

# Machine-Wide Audit Compatibility

This entry preserves the repository's original read-only audit workflow. Prefer the sibling `clean-your-data` Skill for individual paths, the TUI, the GUI, and Agent-facing explanations.

## Run An Audit

From this Skill directory:

```bash
# Fast, redacted Markdown report.
python3 scripts/audit_local_files.py --format markdown

# Deeper, redacted JSON report.
python3 scripts/audit_local_files.py \
  --mode full --children --artifacts --git-status \
  --format json --output report.json
python3 scripts/validate_report.py report.json
```

Compare two local snapshots with:

```bash
python3 scripts/compare_reports.py before.json after.json
```

Read only the reference needed for the request:

- `references/report-schema.md` for report fields and evidence states.
- `references/target-taxonomy.md` for ownership categories.
- `references/duplicate-detection.md` when duplicate hashing was explicitly requested.
- `references/action-playbook.md` before proposing any cleanup plan.
- `references/agentic-evaluation.md` for maintainer evaluation runs.

## Safety Contract

- Begin read-only and keep home redaction enabled.
- Never pass `--no-redact` or `--include-git-origins` for a report that may be shared.
- Duplicate detection is opt-in because it reads candidate bytes locally for SHA-256.
- Treat app state, cloud-sync roots, dirty repositories, incomplete measurements, and unknown ownership as blocked.
- A report is evidence, not permission to delete or move files.
- Use the owning application for app-managed data and system Trash for an exact user-approved reversible move.

For an individual path, use:

```bash
cyd why "PATH" --format json
```
