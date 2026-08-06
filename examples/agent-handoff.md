# Agent Handoff

Send the repository URL and the prompt below to a local agent.

Repository: <https://github.com/MicroMilo/clean-your-data>

```text
Read and use the Clean Your Data skill from this repository.

Audit my local home directory with these constraints:

- local only;
- read-only;
- metadata only;
- redact my home path;
- do not read chat, browser, mail, document, source, credential, or keychain contents;
- do not move, rewrite, or delete anything.

Start with the quick audit. Then explain:

1. where data is accumulating;
2. whether each important area is a durable asset, active workspace, app-managed state, cloud-sync data, cache, inbox, or unknown;
3. who owns its lifecycle;
4. what the risk is;
5. the safest next action, including what must be reviewed first.

Do not give me a raw size list only. Give me a decision-ready report.
```

For a deeper pass, ask the agent to run:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --mode full --children --artifacts --git-status \
  --format markdown
```

For a recurring check, save JSON output before and after a period of normal use and run `audit-local-files/scripts/compare_reports.py`.

For a closer, conversational review of one directory, ask the agent to run:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --path /path/to/review \
  --tui --focus-depth 2
```

Then select an area in the terminal, press `a` to ask Codex, and press `c` to copy its metadata-only context. The selected file's small local preview is not sent to Codex. Set `CLEAN_YOUR_DATA_AI_COMMAND` only when a different trusted local command should answer inside the TUI.
