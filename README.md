# Clean Your Data

**Clean Your Data** is a privacy-preserving local file organization auditor for Codex and standalone command-line use.

It helps people understand where local data accumulates: Desktop sprawl, Downloads, Codex workspaces, Git repository distribution, chat/collaboration app storage, cloud-sync folders, AI tool state, and rebuildable project artifacts.

The scanner is read-only by default. It does **not** read chat messages, browser history, mail bodies, document contents, credentials, or source files.

中文版本见下方：[中文说明](#中文说明)。

## Why

Modern local machines accumulate data across many places:

- chat and collaboration apps such as Feishu/Lark, WeChat, Slack, Teams, Discord, Telegram, QQ, DingTalk, and Zoom;
- browsers, mail clients, cloud drives, and AI coding tools;
- Codex date workspaces, generated outputs, Git clones, experiments, and dependency folders.

Clean Your Data gives users a safe first pass: what exists, how large it is, what category it belongs to, and what should be promoted, archived, reviewed, or cleaned through the owning app.

## Quick Start

Run a fast local audit:

```bash
python3 audit-local-files/scripts/audit_local_files.py --format markdown
```

Write a report:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --format markdown \
  --output local-file-audit.md
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
- App-managed storage for Feishu/Lark, WeChat, Slack, Teams, Discord, Telegram, QQ, DingTalk, Zoom, mail clients, browsers, and cloud-sync folders.
- Codex date workspace counts, including `work` and `outputs` directories.
- Optional Git repository distribution and dirty-entry counts.
- Optional rebuildable or review-needed artifacts such as `node_modules`, `.venv`, `build`, `dist`, `.next`, and `target`.

## Privacy Defaults

Reports redact the home directory to `~` by default.

Git origin URLs are omitted by default, even in JSON. Include them only for private local debugging:

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --git \
  --include-git-origins \
  --format json
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

The Codex skill lives in:

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

- path existence;
- allocated size;
- modification time;
- optional Git repository status counts.

It does not read:

- chat databases or message content;
- browser history;
- mail content;
- document content;
- credentials or keychains;
- source code content.

Any cleanup should be done separately and only after reviewing exact paths.

## Test

Run the no-dependency smoke test:

```bash
python3 tests/smoke_test.py
```

## License

MIT. See [LICENSE](LICENSE).

---

# 中文说明

**Clean Your Data** 是一个面向 Codex 和命令行的本地文件组织审计工具，默认只读、默认匿名化。

它帮助用户理解电脑里的数据沉积在哪里：桌面、下载目录、Codex 工作区、Git 仓库、微信/飞书/Slack/Teams 等协作工具、本地云盘、浏览器、AI 工具状态，以及 `node_modules`、`.venv`、`build` 这类可重建产物。

默认情况下，扫描器不会读取聊天内容、浏览器历史、邮件正文、文档正文、凭据或源码内容。

## 为什么做这个

现代电脑的数据不再只在一个“文档”目录里。它会沉积在：

- 飞书/Lark、微信、Slack、Teams、Discord、Telegram、QQ、钉钉、Zoom 等聊天和协作工具；
- 浏览器、邮箱、云盘同步目录和 AI 编程工具；
- Codex 日期工作区、生成输出、Git 克隆、实验目录和依赖目录。

Clean Your Data 提供一个安全的第一步：先看有哪些目录、占多少空间、属于什么类别，以及哪些应该晋升、归档、复核，哪些应该通过所属 App 自带能力清理。

## 快速开始

运行快速审计：

```bash
python3 audit-local-files/scripts/audit_local_files.py --format markdown
```

把报告写入文件：

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --format markdown \
  --output local-file-audit.md
```

在迁移或清理前运行深度审计：

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --mode full \
  --children \
  --artifacts \
  --git-status \
  --format markdown \
  --output local-file-audit-full.md
```

## 报告内容

- Desktop、Downloads、Documents、Codex、源码根目录和 AI 工具目录等常见本地区域。
- 飞书/Lark、微信、Slack、Teams、Discord、Telegram、QQ、钉钉、Zoom、邮箱、浏览器和云盘同步目录等 App 管理数据。
- Codex 日期工作区数量，包括 `work` 和 `outputs` 目录。
- 可选的 Git 仓库分布和 dirty entry 计数。
- 可选的可重建或需复核产物，例如 `node_modules`、`.venv`、`build`、`dist`、`.next`、`target`。

## 默认隐私保护

报告默认会把用户主目录匿名化为 `~`。

Git origin URL 默认不会输出，即使是 JSON 报告也不会输出。只有在本机私有调试时才建议开启：

```bash
python3 audit-local-files/scripts/audit_local_files.py \
  --git \
  --include-git-origins \
  --format json
```

绝对主目录路径默认不会输出。只有在本机私有调试时才建议开启：

```bash
python3 audit-local-files/scripts/audit_local_files.py --no-redact --format json
```

不要公开发布使用 `--no-redact` 或 `--include-git-origins` 生成的报告。

## 依赖

必需：

- Python 3.9+
- macOS/Linux 上的 `du` 命令，用于快速测量目录占用

可选：

- `git`，仅在使用 `--git`、`--git-status` 或 `--mode full` 时需要

不需要任何第三方 Python 包。

## Codex Skill 用法

Codex skill 位于：

```text
audit-local-files/
```

安装为 Codex skill 后，可以处理这类请求：

- “分析我的本地文件组织。”
- “审计我的 Desktop、Downloads、Codex、微信和飞书存储。”
- “找出哪些本地工作区和 App 缓存正在沉积。”
- “在不删除文件的前提下，给我一个安全清理或归档计划。”

## 安全模型

扫描器只读取元数据：

- 路径是否存在；
- 目录占用大小；
- 修改时间；
- 可选的 Git 仓库状态计数。

它不会读取：

- 聊天数据库或消息正文；
- 浏览器历史；
- 邮件正文；
- 文档正文；
- 凭据或 keychain；
- 源码内容。

任何清理动作都应该单独执行，并且必须先复核精确路径。

## 测试

运行无第三方依赖的 smoke test：

```bash
python3 tests/smoke_test.py
```

## 许可证

MIT，见 [LICENSE](LICENSE)。
