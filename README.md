# Clean Your Data

[![CI](https://github.com/MicroMilo/clean-your-data/actions/workflows/test.yml/badge.svg)](https://github.com/MicroMilo/clean-your-data/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/MicroMilo/clean-your-data?display_name=tag)](https://github.com/MicroMilo/clean-your-data/releases)

<p align="center">
  <img src="https://raw.githubusercontent.com/MicroMilo/clean-your-data/main/assets/github-social-preview-v1.png" alt="Clean Your Data: a safe map before you clean" width="100%">
</p>

**A local-first disk explorer that helps humans and Agents understand a path before anything moves.**

**Clean Your Data** turns an opaque folder into an interactive space map. Open a directory, follow the largest branches, preview a file locally, ask your own Agent about one exact path, and move only reviewed items to system Trash with undo.

The browser GUI and keyboard-first TUI use the same scanner and safety gates. AI is optional and user-configured; the explorer works without an API key or network connection.

<p align="center">
  <img src="https://raw.githubusercontent.com/MicroMilo/clean-your-data/main/assets/clean-your-data-gui-v0.4.jpg" alt="Clean Your Data local browser GUI" width="100%">
</p>

## Install And Open

Install directly from GitHub, then open any directory:

```bash
uv tool install git+https://github.com/MicroMilo/clean-your-data.git

# Local browser GUI
cyd gui ~/Documents/project

# Terminal UI
cyd ~/Documents/project
```

From PyPI after the first package release:

```bash
uv tool install clean-your-data
```

`cyd gui` starts a random-port server on `127.0.0.1` and opens the browser. It is not exposed to the LAN. Stop it from the square button or with `Ctrl-C`. For a source checkout, run `python3 -m pip install .` first.

## Why This Exists

| Question | Product behavior |
| --- | --- |
| Where did the space go? | A relative-size tree makes large siblings visible and loads deeper folders on demand. |
| What is this path? | Local preview, metadata, inferred relationships, and a per-path Agent conversation stay together. |
| Can I move it? | The scanner separates rebuildable candidates, review items, and protected data. A suggestion is never permission. |
| What if the decision is wrong? | Cleanup stages an exact path, confirms it again, moves it to system Trash, rescans, and supports undo. |
| Can I stay in the terminal? | The TUI provides the same scan, preview, Agent context, cleanup gate, Trash, and undo model. |

This is not a generic file manager and it does not promise automatic deletion. It is the investigation and decision layer between an unfamiliar path and a file operation.

## Optional Agent

The explorer does not bundle an LLM account. It can use an already authenticated Codex CLI or any trusted stdin/stdout command:

```bash
cyd config ai --auto
cyd config ai --codex
cyd config ai --command 'ollama run qwen3:8b'
cyd config ai --off
cyd config ai --show
```

The GUI exposes the same setting. Commands are executed as direct arguments, never through a shell. Clean Your Data has no API-key field, but saved custom-command arguments are stored verbatim. Never put a credential in the command; keep provider credentials in that provider's own environment or credential store.

The prompt that Clean Your Data writes to the configured command contains only bounded metadata for the selected path: redacted path, name, kind, size, modified time, category, and measurement status. Clean Your Data does not put file previews or file contents in that prompt. The built-in Codex mode runs in a read-only, ephemeral sandbox; a custom command still has its own operating-system permissions, so configure only a command you trust. Agent answers are advice and cannot approve or execute cleanup through Clean Your Data.

## Optional Agent Trace

Run an Agent through `cyd trace` when you want to know which paths changed during that session:

```bash
# Trace the current directory while Codex works.
cyd trace -- codex

# Trace a specific project while Claude Code works there.
cyd trace --path ~/projects/demo -- claude

# Watch more than one local scope and keep a machine-readable report.
cyd trace \
  --path ~/projects/demo \
  --path ~/.codex \
  --format json \
  --output trace.json \
  -- codex
```

The command after `--` runs normally. The tracer takes bounded metadata snapshots while it runs and reports paths that were created, modified, deleted, or observed briefly. It records the session, command, process id, time, scope, and before/after stat fields, but never reads file contents or environment variables. Trace records stay in the local `~/.clean-your-data/provenance.sqlite3` database with user-only permissions where supported. Command arguments are stored verbatim, so never put credentials directly on a traced command line. The default scope is the command's working directory; use `--path` explicitly when an Agent writes elsewhere.

The report says that a change was **observed while the traced command was running**. It does not claim kernel-level proof of the exact child process that wrote a path. Historical files that were created before tracing may remain unattributed. This is intentional: evidence, inference, and unknowns stay separate.

## Privacy Boundary

- Read-only by default. The initial map reads metadata, not file contents.
- No uploads by the scanner or local GUI. A configured Agent command follows its own network policy.
- The GUI listens only on `127.0.0.1`; it validates the loopback Host, requires a random per-run API token, and rejects cross-origin browser requests.
- Cleanup is separate from scanning. GUI and TUI can move only an exact, user-confirmed, eligible path to system Trash.
- Exact duplicate matching is opt-in and hashes candidate files locally; raw hashes are not written to reports.
- Home paths are redacted to `~` by default. Review project and folder names before sharing a report.
- The active scope, home/root, Trash, VCS metadata, credential stores, credential config, app-managed data, cloud-sync roots, unknown paths, and incomplete measurements are blocked from cleanup.
- Agent tracing is opt-in, metadata-only, local, and bounded by the selected `--path` roots and `--max-entries` limit. The traced Agent may have its own network or authentication behavior; the tracer does not add network access.

## Give It To Your Agent

You can send this repository URL to Codex or another local agent:

<https://github.com/MicroMilo/clean-your-data>

Use a message like this:

> Read and use the Clean Your Data skill from this repository. Analyze my local home directory with a read-only, metadata-only audit. Start with the quick audit, keep paths anonymized, do not read chat, browser, mail, document, source, or credential contents, and do not move or delete anything. Give me a decision-ready report: what is accumulating, what owns it, what is durable versus rebuildable, the risks, and the safest next actions.

The agent can clone the repository, read `audit-local-files/SKILL.md`, and run the bundled scanner locally. The GitHub page itself never receives access to the user's computer.

## Why Use This Instead Of A Shell Or One-Off Prompt?

You can always ask an Agent to inspect a folder. `cyd` is useful when you want a persistent, human-controlled workspace for that inspection:

| A shell or one-off prompt | Clean Your Data |
| --- | --- |
| A list of paths or a one-off answer | A live, keyboard-first map you can keep exploring |
| You decide what to inspect from memory | Search, filters, sorting, bookmarks, tags, and tabs keep context visible |
| Deletion is easy to make irreversible | Exact-path staging, review, Trash moves, and undo keep actions reversible |
| An Agent sees an ad hoc prompt | The local metadata context is structured and safe to hand to an Agent |
| You repeat the same investigation manually | Save snapshots and compare what grew over time |

The optional Skill adds a repeatable audit protocol for Agents. The package is the main product: a local file-system interface that gives people control and gives Agents clean context.

## The Workflow

```text
map -> inspect -> ask -> assess risk -> stage -> confirm -> Trash -> undo
```

The useful question is not only “what is large?” It is:

> What is this data, who owns it, can it be rebuilt, and what can I safely do next?

## Detailed Terminal Usage

After installing the package, open the TUI:

```bash
cyd ~/Documents/project
```

From the repository root, the compatibility script still works:

```bash
python3 audit-local-files/scripts/audit_local_files.py --format markdown
```

Open the focused terminal explorer:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --tui \
  --path ~/Documents/project \
  --focus-depth 2
```

The first scan uses depth 2 and shows the root plus its first two levels. The explorer has no fixed depth limit: deeper folders load when opened, and folders always carry a trailing `/`.

Core navigation is `Up`/`Down` or `j`/`k`, `Left`/`Right` or `h`/`l`, `Enter` to open/close, `gg`/`G` for the endpoints, `Home`/`End` for the same endpoints, and `PageUp`/`PageDown` for a screen. Mouse clicks select an area, double-clicking a folder opens it, and the scroll wheel moves the selection. Press `?` for the complete key list and `q` to quit.

Advanced browsing is always available from the same tree:

- `/` fuzzy-searches loaded names, paths, areas, and tags;
- `f` filters to folders, files, large items, recent changes, likely rebuildable paths, bookmarks, cleanup candidates, or tagged paths;
- `s` sorts each sibling group by tree order, name, allocated size, modification time, or kind;
- `T` edits comma-separated local tags; `@` marks tagged rows;
- `N` opens the selected folder in a new tab; `gt`/`gT` switch tabs; `X` closes the current tab.

Search, filter, and sort are view controls over the current metadata map. They do not rescan or change files. While `/` or `T` is editing, `Enter` applies, `Esc` cancels, and `Ctrl-U` clears the input.

TUI startup is focused: it measures only the selected `--path` roots before opening and does not run the home-wide audit. Use the non-TUI commands when you want the full home report.

Explore one path as an interactive, metadata-only map:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --path ~/Documents/project \
  --focus-depth 2 \
  --tui
```

The terminal explorer shows an area's name, path, size, last-change time, and inferred area. Selecting a file also shows a small local text preview, limited to 4 KB and 14 lines; binary files and likely credential files are hidden. Press `a` to enter a question for Codex. When the `codex` CLI is available, it uses a read-only, ephemeral `codex exec` session; otherwise set `CLEAN_YOUR_DATA_AI_COMMAND` to a trusted local command that reads the prompt from stdin. The preview is never included in that prompt. The scanner never makes network requests; pressing `a` hands only metadata to the selected local AI command, whose own authentication and network rules apply.

The selected path is also the context for local actions: `t` opens Terminal, `v` opens VS Code, `c` opens Cursor, and `o` reveals the path in Finder. `a` opens the Codex question box beside the tree, `m` saves a bookmark, `M` browses bookmarks and recent paths, `w` saves the current workspace, and `W` restores it. `D` runs a bounded metadata-only relationship analysis that connects project markers, source files, dependencies, build folders, outputs, and possible repeated files. These local actions do not pass paths through a shell. Bookmarks, tags, recents, and the last workspace stay in the local `~/.clean-your-data/workspace-state.json` file and are never added to reports.

Tabs are session-local views. Opening a tab on a selected folder keeps that path's report, selection, search, filter, and sort state available while you inspect another area. Closing a tab does not touch its files.

Find exact duplicates only when you explicitly want content hashing:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --duplicates \
  --format markdown \
  --output duplicate-audit.md
```

The duplicate pass first groups files by size, then streams SHA-256 locally for candidate files. It does not upload content or expose raw hashes. By default it scans common workspace roots, skips app-managed/cloud-sync roots and rebuildable directories, and reports hard-link aliases and parent-scope overlap so “potential duplicate bytes” is not mistaken for guaranteed reclaimable space. Use `--duplicate-root PATH` only for an explicitly understood additional scope.

Write a local report:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --format markdown \
  --output local-file-audit.md
```

Run a deeper audit before reorganizing a machine:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --mode full \
  --children \
  --artifacts \
  --git-status \
  --format markdown \
  --output local-file-audit-full.md
```

The scanner never changes the scanned files. In the TUI, cleanup is a separate, approval-gated action: `dd` stages a candidate, the local coding agent gives a preliminary metadata-only recommendation, and an explicit confirmation moves the exact path to system Trash. Press `u` to undo the most recent move during the session. App-managed data, cloud-sync roots, unknown paths, and incomplete measurements are blocked.

### Safe Cleanup Loop

```text
select -> dd stage -> preliminary scan -> coding-agent advice -> review exact path -> y confirm -> system Trash -> refresh map -> u undo
```

The initial scan is evidence, not permission. The agent's recommendation is advisory and cannot execute a command. After a successful move or restore, the TUI re-scans only the focused path. It also records the original path locally so an approved Trash move can be restored without overwriting a newer path.

## Compare Audits Over Time

JSON output is a local snapshot. Save two snapshots and compare them:

```bash
mkdir -p snapshots

python3 audit-local-files/scripts/audit_local_files.py \
  --mode full --children --artifacts --git-status \
  --format json --output snapshots/before.json

# Use the machine normally, then run the same command again as after.json.

python3 audit-local-files/scripts/compare_reports.py \
  snapshots/before.json snapshots/after.json
```

The comparison highlights disk usage, target areas, Codex workspace counts, Git dirty changes, rebuildable artifacts, exact duplicate groups, and interactive-map coverage that changed. Keep snapshots local unless you review their paths first.

## Evidence, Not Guesswork

The JSON report now carries a small decision contract:

- `measurement_status` distinguishes measured, timeout, error, missing, and unknown;
- `coverage` records which target families were actually measured;
- `findings` links each recommendation to evidence, owner, risk, confidence, and rollback/rebuild guidance;
- `space_map` records a bounded, keyboard-navigable view of a selected path using names, sizes, dates, and measurement status only;
- `action_gate` keeps the result in `review_only` when evidence is incomplete or dirty Git work must be preserved.

Validate a saved snapshot before handing it to another Agent:

```bash
python3 audit-local-files/scripts/validate_report.py snapshots/before.json
```

Terminal output is intended for local review. It follows the report's redaction settings, but you should still review project and folder names before sharing a saved report. TUI bookmarks, recent paths, and the last workspace are stored locally in `~/.clean-your-data/workspace-state.json` and are never included in reports.

Artifact rows are candidate subsets. They may already be included in a parent workspace total, so the report does not present them as additive reclaimable space.

## How We Iterate The Skill

The project uses a maintainer-only evaluation loop: run a real local audit, aggregate and redact the evidence, ask independent roles to review it, synthesize the smallest change, then run contract and fixture tests before publishing. Raw local reports never enter the repository. See [the evaluation loop](audit-local-files/references/agentic-evaluation.md).

## What A Useful Result Looks Like

The report is designed to turn raw measurements into a next step:

```text
Main pattern: data is concentrated in AI workspaces, app-managed storage,
and project build artifacts.

Interpretation:
- AI workspace: inspect and promote durable outputs before archiving.
- App-managed storage: use the owning app's storage controls; do not delete
  its container directly.
- Build artifact: potentially rebuildable, but check the project and disk
  cost before removal.
- Dirty Git repository: preserve or commit/stash changes before moving it.

Next action: review exact paths, then approve one reversible category at a time.
```

See the [anonymized sample report](examples/sample-report.md) and the [agent handoff prompt](examples/agent-handoff.md).

## Privacy And Safety

The scanner collects local metadata only:

- path existence and home-relative paths;
- allocated directory size;
- modification time;
- optional Git repository and dirty-entry counts.

It does not read chat messages, browser history, email bodies, document text, source code, credentials, or keychains. The selected-file preview is a separate local exception: it reads at most 4 KB and 14 lines, skips binary and likely credential files, and is never sent to Codex. The scanner does not make network requests and does not upload reports.

Exact duplicate mode is an explicit exception to the metadata-only default: it reads candidate file bytes locally to calculate SHA-256 matches. It still makes no network requests, stores no raw hashes in the report, and never modifies files.

Reports redact the home directory to `~` by default. Git origin URLs are omitted by default. Review project and folder names before sharing any report publicly. Do not publish reports generated with `--no-redact` or `--include-git-origins`.

The scanner does not perform cleanup. App-managed data should be handled by the owning app; rebuildable artifacts should be removed only after their exact paths, rebuild cost, and rollback options are understood.

## Install As A Codex Skill (Optional)

An agent can install the `audit-local-files/` directory as a Codex skill. For a manual local install:

```bash
git clone https://github.com/MicroMilo/clean-your-data.git
mkdir -p ~/.codex/skills
cp -R clean-your-data/audit-local-files ~/.codex/skills/audit-local-files
```

Then ask Codex:

```text
Use $audit-local-files to audit my local file organization. Start read-only and anonymized. Do not delete anything.
```

## Dependencies

- Python 3.9+
- `du` on macOS/Linux for fast allocated-size measurement
- `git` only for Git discovery or status checks
- `curses` and an interactive terminal for `--tui` (standard library on macOS/Linux)

No third-party Python packages are required.

## 中文说明

**先看清，再动手。面向人和 Agent 的本地磁盘浏览器。**

**Clean Your Data** 把陌生目录变成可以继续探索的空间地图。你可以沿着大目录往下看，在本地预览文件，针对某个精确路径询问自己配置的 Agent，再把经过复核的项目移入系统废纸篓并撤销。

GUI 和 TUI 共用同一套扫描器与安全门禁。默认只读取元数据；选中文件时才在本地读取最多 4 KB、14 行预览，疑似凭据和二进制文件不会展示。AI 完全可选，不配置也能正常浏览、分析关系和进行可逆操作。

### 交给你的 Agent

把这个 GitHub 地址发给 Codex 或其他本地 Agent：

<https://github.com/MicroMilo/clean-your-data>

可以直接附上：

> 请读取并使用这个仓库里的 Clean Your Data skill。对我的本地 home 目录做一次只读、只读取元数据的审计。先运行快速模式，路径保持匿名化，不读取聊天、浏览器、邮件、文档、源码或凭据内容，也不要移动或删除任何文件。请输出一份可以做决定的报告：哪些数据正在沉积、由谁管理、哪些是长期资产或可重建产物、风险是什么，以及最安全的下一步。

Agent 可以下载仓库、读取 `audit-local-files/SKILL.md`，然后在用户电脑本地运行扫描器。GitHub 页面本身不会获得用户电脑的访问权限。

### 为什么不直接问 Codex

Codex 可以完成一次分析，但很难持续保留“当前选中了什么、它和空间分布的关系、预览边界、清理篮状态以及撤销记录”。这个产品把这些状态放进一个人可以直接操控的界面，并只给 Agent 一份结构化、受限的元信息。Agent 负责解释，人负责决定，程序负责执行安全门禁。

### 工作流

```text
空间地图 -> 检查 -> 询问 -> 判断风险 -> 加入清理篮 -> 精确确认 -> 废纸篓 -> 撤销
```

真正要回答的不是“哪里最大”，而是：

> 这些数据是什么、由谁管理、能否重建、我接下来怎样处理才不会误删？

### 快速运行

安装包后，从任意目录打开浏览器 GUI 或终端 TUI：

```bash
# 直接安装 GitHub 当前版本
uv tool install git+https://github.com/MicroMilo/clean-your-data.git

# 本地浏览器 GUI
cyd gui ~/Documents/project

# 终端 TUI
cyd ~/Documents/project
```

`cyd gui` 只监听 `127.0.0.1` 的随机端口，不会暴露到局域网；服务端还会校验本地 Host。每次运行都有随机 API 令牌，并拒绝跨站请求。方形停止按钮和 `Ctrl-C` 都可以关闭本地服务。

AI 不需要内置在产品里。你可以复用本机已经登录的 Codex CLI，接入 Ollama 等可信命令，或彻底关闭：

```bash
cyd config ai --auto
cyd config ai --codex
cyd config ai --command 'ollama run qwen3:8b'
cyd config ai --off
cyd config ai --show
```

配置没有 API-key 字段，也不会通过 shell 执行命令，但自定义命令及参数会原样保存在本地，因此绝不能把密钥写进命令参数。凭据应继续放在对应工具自己的环境变量或凭据存储中。Clean Your Data 写入该命令 stdin 的 Prompt 只包含所选路径的匿名路径、名称、类型、大小、修改时间、分类和测量状态，不包含右侧文件预览或文件正文。内置 Codex 模式使用只读、临时沙箱；自定义命令仍拥有它自己的操作系统权限，因此只能配置你信任的命令。

如果你想观察 Agent 在一个项目里留下了哪些文件，可以直接包住它运行：

```bash
cyd trace --path ~/Documents/project -- codex
```

`trace` 只记录运行期间观察到的创建、修改和删除路径，以及命令、时间和前后元信息；不会读取文件正文。默认把追踪记录保存在 `~/.clean-your-data/provenance.sqlite3`，并在系统支持时设为仅当前用户可读。命令及参数会原样保存在本地，因此不要把密钥直接写进被追踪的命令行。它能证明“在这次被追踪的 Agent 会话期间观察到了变化”，不能对历史文件或并发进程做超出证据的断言。

开发仓库时可以在仓库根目录执行 `python3 -m pip install .`。发布到 PyPI 后，也可以执行 `python3 -m pip install --user clean-your-data`。`cyd --version` 查看版本。

旧的脚本入口仍然保留，方便已有用户和 Agent 继续使用：

```bash
python3 audit-local-files/scripts/audit_local_files.py --format markdown
```

更适合人直接阅读的终端交互界面：

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --tui --path ~/Documents/project --focus-depth 2
```

终端界面第一次只扫描两层目录，显示根目录和下面两层。使用方向键浏览，`gg` 跳到顶部，`G` 跳到底部，`Home`/`End` 跳到两端，`PageUp`/`PageDown` 按屏幕翻页，`Enter` 按需加载下一层或收起当前文件夹，`a` 在树右侧打开问题框，`Enter` 发送问题，`Esc` 或 `Ctrl-C` 取消，`t` 在当前目录打开 Terminal，`v` 用 VS Code 打开，`c` 用 Cursor 打开，`o` 在 Finder 中定位，`m`/`M` 管理书签，`w`/`W` 保存或恢复工作区，`D` 深度分析当前路径，`dd` 把选中的精确路径加入清理篮，`Y` 打开废纸篓确认框，确认框中按 `y` 执行，`u` 撤销最近一次移动，`C` 复制只包含元信息的提问上下文，`r` 重新读取文件预览，`?` 查看帮助，`q` 退出。`dd` 不会立即移动文件；右侧会分别显示初步扫描结论和 coding agent 的建议。鼠标单击选择区域，双击文件夹展开，滚轮移动选择。问题框打开时，`q` 会作为问题文字输入；要离开问题框请按 `Esc` 或 `Ctrl-C`。文件夹会显示为 `venv/` 这种形式，深度没有固定上限，会在进入时继续加载。

TUI 启动时只测量你指定的 `--path`，不会先做整个 home 目录的审计；需要完整 home 报告时使用非 TUI 命令。

如果你想持续追问某个目录，而不是只看一次总表，可以指定路径生成可点击的空间地图：

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --path ~/Documents/project \
  --focus-depth 2 \
  --tui
```

终端界面会展示名称、路径、大小、最后修改时间和所属区域；选中文件后，右侧会显示最多 4 KB、14 行的本地文本预览，二进制文件和疑似凭据文件会隐藏。按 `a` 输入“这个文件夹是干什么的？”之类的问题；如果本机有 `codex` 命令，TUI 会在后台使用只读、临时的 Codex 会话回答，期间仍可移动光标。按 `D` 会在后台做一次只读取元信息的深度分析，尝试关联项目标记、源码、依赖、构建目录、输出目录和可能重复的文件。按 `dd` 后，TUI 会用另一条只包含元信息的清理顾问请求，让 coding agent 判断“保留、复核、归档、可重建候选、交给所属应用或不要触碰”；这只是初步建议，不是删除授权。没有 Codex CLI 时，可以设置可信的 `CLEAN_YOUR_DATA_AI_COMMAND`，让本地命令从 stdin 接收元信息上下文。文件预览不会发送给 Codex；按下 `a` 或 `dd` 后，是否联网由本地 Codex 或其他命令自己的配置决定。回答会保留在对应区域，移动回来仍然可见。

如果明确需要查找精确重复文件，可以显式开启本地哈希：

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --duplicates --format markdown --output duplicate-audit.md
```

该模式先按文件大小筛选候选，再在本机流式计算 SHA-256；不会上传文件，也不会把原始哈希写入报告。默认只扫描常见工作区，排除 App 私有数据、云同步目录和可重建产物，并标注硬链接、父目录和同步范围重叠。“潜在重复空间”是逻辑字节，不等于可以直接删除或一定能回收的空间。只有在明确理解范围后，才使用 `--duplicate-root PATH` 增加目录。

深度模式：

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --mode full --children --artifacts --git-status \
  --format markdown --output local-file-audit-full.md
```

保存 JSON 快照后，可以用 `audit-local-files/scripts/compare_reports.py` 比较两次审计，观察哪些区域在增长。

交给其他 Agent 之前，可以先运行 `python3 audit-local-files/scripts/validate_report.py snapshots/before.json` 校验报告契约。

JSON 报告还会区分 `measured`、`timeout`、`error`、`missing` 和 `unknown`，记录 coverage、证据关联的 findings，以及是否因为证据不足或 Git dirty 状态而只能停留在 `review_only`。artifact 可能已经包含在父工作区大小中，不会被当成可回收空间重复相加；重复组也会记录父目录、硬链接和云同步重叠。

交互地图由 `space_map` 保存。它只扫描指定路径的有限层级，使用名称、大小、修改时间、类别和测量状态；超过时间或节点预算时会明确标记为不完整，不把未知区域当成零空间。

### 隐私与安全

扫描器只读取路径、占用大小、修改时间和可选的 Git 状态计数；不会读取聊天、浏览器历史、邮件正文、文档正文、源码、凭据或 keychain。选中文件时，GUI/TUI 会额外提供一个本地预览例外，最多读取 4 KB、14 行，跳过二进制和疑似凭据文件，且不会发送给 Agent。默认把 home 目录显示为 `~`，默认不输出 Git origin URL。清理历史保存在本机 `~/.clean-your-data/cleanup-history.json`，书签、最近路径和最后工作区保存在 `~/.clean-your-data/workspace-state.json`；这些文件只在本地使用，不会写入报告或上传。任何公开分享前，都应检查项目名和文件夹名。

扫描根目录、home、系统根目录、废纸篓、`.git`/`.ssh` 等关键目录、`.env` 等凭据配置、App 私有数据、云同步目录、未知分类和未完整测量的路径都不能进入清理篮。Agent 的回答只是建议，不能绕过这些确定性规则。

项目维护时会使用真实本机审计的聚合匿名证据包，让不同 Agent 角色独立评审，再通过确定性 fixture 和 schema 测试后发布；原始本机报告不会进入仓库。

### 依赖

安装包没有第三方运行时依赖。需要 Python 3.9+；macOS/Linux 上的 `du`；只有在进行 Git 检查时才需要 `git`；TUI 需要支持 `curses` 的交互式终端；GUI 使用 Python 标准库启动本地 HTTP 服务并调用默认浏览器。需要 AI 解释时，还要有本机已登录的 `codex` CLI，或自行配置可信的 stdin/stdout 命令；其余浏览与清理功能不依赖 LLM。

## License

MIT. See [LICENSE](LICENSE).
