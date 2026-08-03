# Target Taxonomy

Use this reference to classify local storage without reading private content.

## Categories

| Category | Meaning | Default risk | Action |
|---|---|---|---|
| `workspace` | Projects, experiments, Git clones, Codex work dirs | User data | Organize, archive, inspect Git status |
| `deliverable` | Reports, decks, PDFs, exported packages, final outputs | User data | Promote to stable library |
| `app-state` | App containers, profiles, chat stores, browser profiles | User data | Prefer app-native cleanup |
| `cache` | Package caches, build outputs, generated dependencies | Rebuildable | Cleanup only after approval |
| `cloud-sync` | iCloud Drive, OneDrive, Dropbox, Google Drive | User data | Do not bulk-delete; check sync state |
| `unknown` | Ambiguous local data | Review | Ask or inspect shallow metadata |

## Apps Similar To Feishu/Lark

These apps tend to accumulate chat attachments, previews, offline files, logs, embedded browser data, and local databases. Treat their application data as `app-state` unless a specific export/download folder is identified.

| Family | Examples | Why it is similar |
|---|---|---|
| Enterprise chat | Feishu/Lark, Slack, Microsoft Teams, DingTalk | channels, DMs, file previews, local cache, offline documents |
| Personal chat | WeChat, QQ, Telegram, Discord | messages, media, downloaded files, local stores |
| Meetings | Zoom, Tencent Meeting, Google Meet desktop wrappers | recordings, chat logs, caches |
| Email clients | Apple Mail, Outlook, Thunderbird | mail databases, attachments, offline sync |
| Browsers | Chrome, Edge, Firefox, Safari | profiles, downloads, service-worker caches, site storage |
| Cloud drives | iCloud Drive, OneDrive, Dropbox, Google Drive | synced user data and placeholders |
| AI/agent tools | Codex, Claude, Gemini, Cursor, VS Code, Cherry Studio | sessions, worktrees, generated files, model/tool caches |

## macOS App-State Path Patterns

Do not delete these folders directly in an automated workflow. They are scanned only for size and timestamp.

- `~/Library/Containers/com.tencent.xinWeChat`
- `~/Library/Containers/com.bytedance.macos.feishu`
- `~/Library/Application Support/Slack`
- `~/Library/Application Support/Microsoft/Teams`
- `~/Library/Application Support/discord`
- `~/Library/Application Support/Telegram Desktop`
- `~/Library/Containers/com.alibaba.DingTalkMac`
- `~/Library/Mail`
- `~/Library/Application Support/Google/Chrome`
- `~/Library/Application Support/Firefox`
- `~/Library/CloudStorage`

## Organization Heuristics

- Desktop should be an inbox, not the durable project root.
- Downloads should be a staging area with an age policy.
- Codex date folders are scratch/history; promote only selected `outputs`.
- Git clones should live under stable source roots such as `~/src/github.com/<owner>/<repo>`.
- Repeated experiment folders should live under one project root with `experiments/`, `results/`, and `archive/`.
- Dirty repositories should be committed, stashed, or exported before migration.

## Public Sharing Rules

- Prefer Markdown reports for sharing; they omit Git origin URLs by default.
- Do not publish JSON reports created with `--include-git-origins`.
- Do not publish reports created with `--no-redact`.
- Review dirty repository paths before sharing a report because repo and folder names may reveal project names.
