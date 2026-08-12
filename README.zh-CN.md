# Clean Your Data

<div align="center">

**你的文件系统不是为 AI Agent 设计的。**

看清空间去了哪里，询问一条路径可能由什么生成，理解移动后会影响什么，再通过可撤销的安全门禁采取行动。

[![CI](https://github.com/MicroMilo/clean-your-data/actions/workflows/test.yml/badge.svg)](https://github.com/MicroMilo/clean-your-data/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/MicroMilo/clean-your-data?display_name=tag)](https://github.com/MicroMilo/clean-your-data/releases)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) · [使用手册](docs/USAGE.md) · [隐私边界](PRIVACY.md) · [最新版本](https://github.com/MicroMilo/clean-your-data/releases/latest)

</div>

<p align="center">
  <img src="https://raw.githubusercontent.com/MicroMilo/clean-your-data/main/assets/clean-your-data-tui-v0.4.png" alt="Clean Your Data TUI：相对空间条与路径检查器" width="100%">
  <br><sub><b>终端工作区：</b>无需离开 TUI，即可浏览、检查、询问、复核和撤销。</sub>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/MicroMilo/clean-your-data/main/assets/clean-your-data-gui-v0.4.jpg" alt="Clean Your Data 浏览器 GUI：空间地图与路径级 Agent 对话" width="100%">
  <br><sub><b>浏览器工作区：</b>空间地图与每条路径的 Agent 对话始终在同一界面。</sub>
</p>

两张图都来自合成演示项目，不包含 home 目录、用户名或私人工作区。

## 立刻运行

安装 [`uv`](https://docs.astral.sh/uv/) 后，不用 clone，也不用永久安装：

```bash
# 终端工作区
uvx --from git+https://github.com/MicroMilo/clean-your-data.git cyd .

# 浏览器工作区
uvx --from git+https://github.com/MicroMilo/clean-your-data.git cyd gui .
```

希望随处使用 `cyd` 时再安装：

```bash
uv tool install git+https://github.com/MicroMilo/clean-your-data.git
cyd ~/Documents/project          # TUI
cyd gui ~/Documents/project      # GUI
```

支持 Python 3.9+ 与 macOS/Linux，安装包没有第三方 Python 运行时依赖。

## 为什么需要它

磁盘分析器知道**大小**，文件管理器知道**名字**，一次性的 Agent 提问能得到**回答**，却会丢失当前选区和周围状态。

Clean Your Data 把完整决定留在同一个地方：

```text
空间地图 -> 精确路径 -> 本地预览 -> Agent 证据 -> 安全复核 -> 废纸篓 -> 撤销
```

| 能力 | 这里有什么不同 |
| --- | --- |
| 空间地图 | 相对空间条直接说明哪个分支主导当前文件夹 |
| 路径上下文 | 预览、元信息、关系和 Agent 回答都跟随同一个选区 |
| Agent 控制 | 可复用已登录的 Codex CLI，也可接可信 stdin/stdout 命令；AI 完全可选 |
| 操作安全 | 确定性规则、精确路径确认、系统废纸篓、本地历史与撤销 |

## 接入自己的 Agent

```bash
cyd config ai --auto                         # 优先使用已登录的 Codex CLI
cyd config ai --codex
cyd config ai --command 'ollama run qwen3:8b'
cyd config ai --off
```

Agent 只收到受限元信息，不会收到选中文件的预览或正文。它只能提供建议，不能绕过清理门禁。自定义命令以直接参数执行，不经过 shell。

也可以把仓库地址直接交给 Agent，并告诉它：

> 安装 Clean Your Data，只读检查 `PATH`，解释最大的分支和可能归属；没有我的精确批准，不移动任何内容。

## 安全约束

- 初始扫描只在本地进行，以元信息为主，不发起网络请求。
- 疑似敏感名称和二进制文件不会预览；普通预览只留在本地，也不会进入 Agent Prompt。
- 清理从不永久删除：只有再次确认的精确路径才会进入系统废纸篓，并在恢复仍然安全时支持撤销。
- 报告默认把 home 路径匿名化为 `~`，公开分享前仍需检查项目名和文件夹名。

自行配置的 Agent 命令遵循它自己的联网与凭据策略。完整边界见 [Privacy](PRIVACY.md) 与 [Security](SECURITY.md)。

## 更多

[完整用法与快捷键](docs/USAGE.md) · [English README](README.md) · [匿名化报告样例](examples/sample-report.md) · [Agent 交接词](examples/agent-handoff.md) · [版本记录](CHANGELOG.md)

Clean Your Data 目前是 Beta。`v0.4.0` 已包含 GUI、键盘优先的 TUI、可选 Agent 接入、可逆清理、重复文件检测、报告比较和主动开启的 Agent Trace。

MIT 许可证，见 [LICENSE](LICENSE)。
