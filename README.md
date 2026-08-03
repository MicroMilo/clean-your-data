# Audit Local Files

Privacy-preserving local file organization audit for Codex.

This repository contains a Codex skill and a standalone Python scanner that helps users understand local file sediment: Desktop sprawl, Downloads, Codex workspaces, Git repository distribution, chat/collaboration app storage, cloud-sync folders, and rebuildable project artifacts.

The scanner is read-only by default. It does not read chat messages, browser history, mail bodies, document contents, credentials, or source files.

## Quick Start

Run a fast local audit:

```bash
python3 audit-local-files/scripts/audit_local_files.py --format markdown
```

Write a report:

```bash
python3 audit-local-files/scripts/audit_local_files.py --format markdown --output local-file-audit.md
```

Run a deeper audit before migration or cleanup planning:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --mode full \
  --children \
  --artifacts \
  --git-status \
  --format markdown \
  --output local-file-audit-full.md
```

## What It Reports

- Large known local areas such as Desktop, Downloads, Documents, Codex, source roots, and AI tool directories.
- App-managed storage for tools like Feishu/Lark, WeChat, Slack, Teams, Discord, Telegram, QQ, DingTalk, Zoom, mail clients, browsers, and cloud-sync folders.
- Codex date workspace counts, including `work` and `outputs` directories.
- Optional Git repository distribution and dirty-entry counts.
- Optional rebuildable or review-needed artifacts such as `node_modules`, `.venv`, `build`, `dist`, `.next`, and `target`.

## Privacy Defaults

Reports redact the home directory to `~` by default.

Git origin URLs are omitted by default, even in JSON. Include them only for private local debugging:

```bash
python3 audit-local-files/scripts/audit_local_files.py --git --include-git-origins --format json
```

Absolute home paths are omitted by default. Include them only for private local debugging:

```bash
python3 audit-local-files/scripts/audit_local_files.py --no-redact --format json
```

Do not publish reports generated with `--no-redact` or `--include-git-origins`.

## Dependencies

Required:

- Python 3.9+
- `du` on macOS/Linux for fast allocated-size measurement

Optional:

- `git`, only when using `--git`, `--git-status`, or `--mode full`

No third-party Python packages are required.

## Codex Skill Usage

The skill lives in:

```text
audit-local-files/
```

When installed as a Codex skill, it triggers for requests such as:

- "Analyze my local file organization."
- "Audit my Desktop, Downloads, Codex, WeChat, and Feishu storage."
- "Find which local workspaces and app caches are accumulating."
- "Create a safe cleanup or archive plan without deleting anything."

## Safety Model

The scanner reads metadata only:

- Path existence
- Allocated size
- Modification time
- Optional Git repository status counts

It does not read:

- Chat databases or message content
- Browser history
- Mail content
- Document content
- Credentials or keychains
- Source code content

Any cleanup should be done separately and only after reviewing exact paths.

## Test

Run the no-dependency smoke test:

```bash
python3 tests/smoke_test.py
```

## License

MIT. See [LICENSE](LICENSE).
