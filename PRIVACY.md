# Privacy

Audit Local Files is designed for local, read-only metadata analysis.

## Default Redaction

By default:

- The home directory is rendered as `~`.
- Git origin URLs are omitted.
- Reports do not include file contents.
- Reports do not include chat, mail, browser, or document contents.

Avoid sharing reports created with:

```bash
--no-redact
--include-git-origins
```

## Data The Scanner May Collect

- Directory paths, usually home-relative.
- Allocated byte counts from `du` or a standard-library fallback.
- Modification times.
- Known category labels such as `workspace`, `app-state`, `cloud-sync`, `cache`, and `inbox`.
- Optional Git dirty-entry counts from `git status --porcelain`.

## Data The Scanner Should Not Collect

- Message text.
- Browser history.
- Email bodies.
- Document text.
- Secrets, tokens, keychains, or credentials.
- Source file contents.

## Sharing Reports

Before sharing a report publicly:

- Prefer Markdown over JSON.
- Review path names for sensitive project names.
- Do not include Git origin URLs.
- Do not include absolute home paths.
- Do not include full raw reports from work machines without review.
