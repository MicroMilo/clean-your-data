#!/usr/bin/env python3
"""Read-only local file organization audit.

The scanner collects path metadata, sizes, mtimes, shallow Git metadata, and
known app-storage locations. It never reads chat databases, browser history, or
document contents.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import stat as stat_module
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


QUICK_TARGET_TIMEOUT_SECONDS = 3
FULL_TARGET_TIMEOUT_SECONDS = 20
QUICK_CHILD_TIMEOUT_SECONDS = 8
FULL_CHILD_TIMEOUT_SECONDS = 30
GIT_TIMEOUT_SECONDS = 4
DUPLICATE_HASH_CHUNK_BYTES = 1024 * 1024
DUPLICATE_DEFAULT_TIME_BUDGET_SECONDS = 60
DUPLICATE_DEFAULT_MAX_BYTES = 10 * 1024**3
DUPLICATE_DEFAULT_FILE_LIMIT = 10000
DUPLICATE_DEFAULT_MIN_BYTES = 1 * 1024**2

ARTIFACT_NAMES = {
    "node_modules": ("cache", "rebuildable", "reinstall dependencies"),
    ".venv": ("cache", "review", "recreate Python environment"),
    "venv": ("cache", "review", "recreate Python environment"),
    "build": ("cache", "review", "rebuild project outputs"),
    "dist": ("cache", "review", "rebuild project outputs"),
    ".next": ("cache", "rebuildable", "rebuild Next.js output"),
    "target": ("cache", "rebuildable", "rebuild Rust/Java output"),
    ".turbo": ("cache", "rebuildable", "rebuild Turborepo cache"),
    ".pnpm-store": ("cache", "rebuildable", "reinstall pnpm store"),
}

SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "build",
    "dist",
    ".next",
    "target",
    ".turbo",
    ".pnpm-store",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


@dataclass(frozen=True)
class TargetDef:
    label: str
    category: str
    risk: str
    patterns: tuple[str, ...]


TARGETS = [
    TargetDef(
        "Desktop",
        "workspace",
        "user-data",
        ("~/Desktop",),
    ),
    TargetDef(
        "Downloads",
        "inbox",
        "user-data",
        ("~/Downloads",),
    ),
    TargetDef(
        "Documents",
        "workspace",
        "user-data",
        ("~/Documents",),
    ),
    TargetDef(
        "Codex date workspaces",
        "workspace",
        "user-data",
        ("~/Documents/Codex", "~/.codex"),
    ),
    TargetDef(
        "Source roots",
        "workspace",
        "user-data",
        (
            "~/src",
            "~/work",
            "~/research",
            "~/projects",
            "~/github",
            "~/code",
            "~/dev",
            "~/AndroidStudioProjects",
        ),
    ),
    TargetDef(
        "WeChat",
        "app-state",
        "user-data",
        (
            "~/Library/Containers/com.tencent.xinWeChat",
            "~/Library/Containers/com.tencent.WeChat",
            "~/Library/Application Support/com.tencent.xinWeChat",
            "~/Library/Application Support/WeChat",
            "~/Documents/WeChat Files",
            "~/Documents/Tencent Files",
        ),
    ),
    TargetDef(
        "Feishu/Lark",
        "app-state",
        "user-data",
        (
            "~/Library/Containers/com.bytedance.macos.feishu",
            "~/Library/Containers/com.larksuite.Lark",
            "~/Library/Containers/com.bytedance.ee.lark",
            "~/Library/Application Support/LarkShell",
            "~/Library/Application Support/Lark",
            "~/Library/Application Support/Feishu",
            "~/Library/Application Support/com.bytedance.feishu",
        ),
    ),
    TargetDef(
        "Slack",
        "app-state",
        "user-data",
        (
            "~/Library/Application Support/Slack",
            "~/Library/Containers/com.tinyspeck.slackmacgap",
        ),
    ),
    TargetDef(
        "Microsoft Teams",
        "app-state",
        "user-data",
        (
            "~/Library/Application Support/Microsoft/Teams",
            "~/Library/Containers/com.microsoft.teams",
            "~/Library/Containers/com.microsoft.teams2",
            "~/Library/Group Containers/UBF8T346G9.com.microsoft.teams",
        ),
    ),
    TargetDef(
        "Discord",
        "app-state",
        "user-data",
        (
            "~/Library/Application Support/discord",
            "~/Library/Application Support/discordcanary",
            "~/Library/Application Support/discordptb",
        ),
    ),
    TargetDef(
        "Telegram",
        "app-state",
        "user-data",
        (
            "~/Library/Application Support/Telegram Desktop",
            "~/Library/Containers/ru.keepcoder.Telegram",
            "~/Library/Group Containers/*ru.keepcoder.Telegram",
        ),
    ),
    TargetDef(
        "QQ",
        "app-state",
        "user-data",
        (
            "~/Library/Containers/com.tencent.qq*",
            "~/Library/Application Support/QQ",
            "~/Documents/Tencent Files",
        ),
    ),
    TargetDef(
        "DingTalk",
        "app-state",
        "user-data",
        (
            "~/Library/Containers/com.alibaba.DingTalkMac",
            "~/Library/Application Support/DingTalk",
        ),
    ),
    TargetDef(
        "Zoom",
        "app-state",
        "user-data",
        (
            "~/Library/Application Support/zoom.us",
            "~/Documents/Zoom",
        ),
    ),
    TargetDef(
        "Email clients",
        "app-state",
        "user-data",
        (
            "~/Library/Mail",
            "~/Library/Application Support/Thunderbird",
            "~/Library/Group Containers/UBF8T346G9.Office/Outlook",
        ),
    ),
    TargetDef(
        "Browsers",
        "app-state",
        "review",
        (
            "~/Library/Application Support/Google/Chrome",
            "~/Library/Application Support/Microsoft Edge",
            "~/Library/Application Support/Firefox",
            "~/Library/Safari",
        ),
    ),
    TargetDef(
        "Cloud sync",
        "cloud-sync",
        "user-data",
        (
            "~/Library/CloudStorage",
            "~/Library/Mobile Documents/com~apple~CloudDocs",
            "~/Dropbox",
            "~/Google Drive",
            "~/OneDrive",
        ),
    ),
    TargetDef(
        "AI and coding agents",
        "workspace",
        "user-data",
        (
            "~/.codex",
            "~/.claude",
            "~/.agents",
            "~/.gemini",
            "~/.cursor",
            "~/.vscode",
            "~/.agent-browser",
            "~/.cherrystudio",
            "~/.cua-driver",
            "~/.continue",
            "~/.ollama",
        ),
    ),
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def human_size(num: Optional[int]) -> str:
    if num is None:
        return "unknown"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def rel_home(path: Path, home: Path) -> str:
    try:
        return "~/" + str(path.resolve().relative_to(home.resolve()))
    except Exception:
        return str(path)


def display_home(home: Path, redact: bool) -> str:
    return "~" if redact else str(home)


def sanitize_text(text: str, home: Path, redact: bool) -> str:
    if not text or not redact:
        return text
    return text.replace(str(home), "~")


def measurement_status(size: Optional[int], error: str, timed_out: bool) -> str:
    if timed_out:
        return "timeout"
    if size is not None:
        return "measured"
    if error == "missing":
        return "missing"
    if error:
        return "error"
    return "unknown"


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def owner_for_category(category: str) -> str:
    return {
        "app-state": "owning app",
        "cloud-sync": "sync provider",
        "inbox": "user workflow",
        "workspace": "project or agent workflow",
        "cache": "project toolchain",
        "deliverable": "user or project library",
        "duplicate": "user or project workflow",
    }.get(category, "unknown")


def action_for_category(category: str) -> str:
    return {
        "app-state": "Open the app's own storage settings. Avoid deleting this folder directly.",
        "cloud-sync": "Check that syncing is finished and that another device does not rely on this copy.",
        "inbox": "Keep what you still need, then move older items to an archive.",
        "workspace": "Keep finished work in a stable folder. Archive active work only after checking it.",
        "cache": "Check how the project recreates this folder before removing it.",
        "deliverable": "Move the finished result to a stable library or project folder.",
        "duplicate": "Compare the copies, choose the one you recognize, and review the others before archiving.",
    }.get(category, "Review shallow metadata before deciding.")


def rollback_for_category(category: str) -> str:
    return {
        "app-state": "Restore through the owning app or backup; direct deletion may lose local state.",
        "cloud-sync": "Restore through the sync provider and verify sync state.",
        "inbox": "Restore from Trash or the dated archive.",
        "workspace": "Restore from the archive, Git, or the original project location.",
        "cache": "Reinstall dependencies or rebuild the project.",
        "deliverable": "Restore from the stable library or backup.",
        "duplicate": "Restore an archived copy or Trash item; keep the verified canonical copy.",
    }.get(category, "No rollback is defined until the owner is identified.")


def expand_pattern(pattern: str, home: Path) -> list[Path]:
    expanded = os.path.expandvars(pattern.replace("~", str(home), 1))
    if any(ch in expanded for ch in "*?["):
        return [Path(p) for p in glob.glob(expanded)]
    return [Path(expanded)]


def du_size(path: Path, timeout: int) -> tuple[Optional[int], str, bool]:
    if not path.exists():
        return None, "missing", False
    if os.name != "nt" and shutil.which("du"):
        try:
            proc = subprocess.run(
                ["du", "-sk", str(path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                kb = int(proc.stdout.split()[0])
                return kb * 1024, "", False
            return None, (proc.stderr or proc.stdout).strip(), False
        except subprocess.TimeoutExpired:
            return None, f"timed out after {timeout}s", True
        except Exception as exc:  # pragma: no cover - defensive fallback
            return None, str(exc), False
    return fallback_size(path)


def path_cache_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path)


def stat_size(path: Path) -> tuple[Optional[int], str, bool]:
    """Measure one non-directory entry without starting a subprocess."""
    try:
        info = path.lstat()
        if stat_module.S_ISLNK(info.st_mode):
            return None, "symlink", False
        return int(getattr(info, "st_blocks", 0) * 512 or info.st_size), "", False
    except OSError as exc:
        return None, str(exc), False


def bulk_du_sizes(root: Path, max_depth: int, timeout: int) -> dict[str, tuple[Optional[int], str, bool]]:
    """Measure directory sizes in one bounded du traversal for the TUI map."""
    if os.name == "nt" or not shutil.which("du") or not root.is_dir():
        return {}
    command_timeout = timeout if timeout > 0 else None
    try:
        proc = subprocess.run(
            ["du", "-k", "-d", str(max(0, max_depth)), str(root)],
            capture_output=True,
            text=True,
            timeout=command_timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0:
        return {}
    sizes: dict[str, tuple[Optional[int], str, bool]] = {}
    for line in proc.stdout.splitlines():
        size_text, separator, raw_path = line.partition("\t")
        if not separator:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            size_text, raw_path = parts
        try:
            size = int(size_text) * 1024
        except ValueError:
            continue
        sizes[path_cache_key(Path(raw_path))] = (size, "", False)
    return sizes


def fallback_size(path: Path) -> tuple[Optional[int], str, bool]:
    total = 0
    errors: list[str] = []
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            stat = current.lstat()
            total += getattr(stat, "st_blocks", 0) * 512 or stat.st_size
            if current.is_dir() and not current.is_symlink():
                for child in current.iterdir():
                    stack.append(child)
        except Exception as exc:
            if len(errors) < 5:
                errors.append(f"{current}: {exc}")
    return total, "; ".join(errors), False


def mtime_iso(path: Path) -> Optional[str]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except Exception:
        return None


def budget_exhausted(deadline: Optional[float]) -> bool:
    return deadline is not None and time.time() >= deadline


def scan_targets(home: Path, timeout: int, deadline: Optional[float], redact: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in TARGETS:
        for pattern in target.patterns:
            for path in expand_pattern(pattern, home):
                try:
                    key = str(path.resolve())
                except Exception:
                    key = str(path)
                if key in seen or not path.exists():
                    continue
                seen.add(key)
                if budget_exhausted(deadline):
                    size, error, timed_out = None, "skipped due time budget", True
                else:
                    size, error, timed_out = du_size(path, timeout)
                records.append(
                    {
                        "label": target.label,
                        "path": rel_home(path, home),
                        "category": target.category,
                        "risk": target.risk,
                        "allocated_bytes": size,
                        "human_size": human_size(size),
                        "modified_at": mtime_iso(path),
                        "measurement_error": sanitize_text(error, home, redact),
                        "timed_out": timed_out,
                        "measurement_status": measurement_status(size, error, timed_out),
                    }
                )
    records.sort(key=lambda item: item.get("allocated_bytes") or -1, reverse=True)
    return records


def top_children(root: Path, home: Path, min_bytes: int, limit: int, timeout: int, redact: bool) -> list[dict[str, Any]]:
    if not root.exists() or not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    try:
        children = list(root.iterdir())
    except Exception:
        return rows
    for child in children:
        size, error, timed_out = du_size(child, timeout)
        if size is None:
            if error or timed_out:
                rows.append(
                    {
                        "path": rel_home(child, home),
                        "allocated_bytes": None,
                        "human_size": "unknown",
                        "modified_at": mtime_iso(child),
                        "measurement_error": sanitize_text(error, home, redact),
                        "timed_out": timed_out,
                        "measurement_status": measurement_status(None, error, timed_out),
                    }
                )
            continue
        if size < min_bytes:
            continue
        rows.append(
            {
                "path": rel_home(child, home),
                "allocated_bytes": size,
                "human_size": human_size(size),
                "modified_at": mtime_iso(child),
                "measurement_error": sanitize_text(error, home, redact),
                "timed_out": timed_out,
                "measurement_status": measurement_status(size, error, timed_out),
            }
        )
    rows.sort(key=lambda item: item["allocated_bytes"] if item["allocated_bytes"] is not None else -1, reverse=True)
    return rows[:limit]


def depth_of(path: Path, root: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except Exception:
        return 999


def should_skip_dir(path: Path) -> bool:
    name = path.name
    if name in SKIP_DIR_NAMES:
        return True
    if name in {"Library", "Movies", "Music", "Pictures"}:
        return True
    return False


def read_git_origin(repo: Path) -> str:
    git = repo / ".git"
    config = git / "config"
    if git.is_file():
        try:
            text = git.read_text(errors="ignore").strip()
            match = re.search(r"gitdir:\s*(.+)", text)
            if match:
                gitdir = Path(match.group(1))
                if not gitdir.is_absolute():
                    gitdir = (repo / gitdir).resolve()
                config = gitdir / "config"
        except Exception:
            return ""
    if not config.exists():
        return ""
    try:
        in_origin = False
        for line in config.read_text(errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                in_origin = stripped == '[remote "origin"]'
            elif in_origin and stripped.startswith("url"):
                _, value = stripped.split("=", 1)
                return value.strip()
    except Exception:
        return ""
    return ""


def git_status_count(repo: Path) -> tuple[Optional[int], str]:
    if not shutil.which("git"):
        return None, "git not found"
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if proc.returncode != 0:
            return None, proc.stderr.strip()
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        return len(lines), ""
    except subprocess.TimeoutExpired:
        return None, f"git status timed out after {GIT_TIMEOUT_SECONDS}s"


def git_bucket(path: Path, home: Path) -> str:
    rel = rel_home(path, home)
    parts = rel.replace("~/", "", 1).split("/")
    if len(parts) >= 3 and parts[0] == "Desktop" and parts[1] == "work":
        return "/".join(parts[:3])
    if len(parts) >= 2 and parts[0] in {"Desktop", "Documents"}:
        return "/".join(parts[:2])
    if parts:
        return parts[0]
    return rel


def find_git_repos(roots: list[Path], home: Path, max_depth: int, limit: int, include_status: bool, include_origins: bool, redact: bool) -> dict[str, Any]:
    repos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for current, dirs, _files in os.walk(root):
            current_path = Path(current)
            if depth_of(current_path, root) > max_depth:
                dirs[:] = []
                continue
            has_git = (current_path / ".git").exists()
            dirs[:] = [d for d in dirs if not should_skip_dir(current_path / d)]
            if not has_git:
                continue
            try:
                key = str(current_path.resolve())
            except Exception:
                key = str(current_path)
            if key in seen:
                continue
            seen.add(key)
            origin = read_git_origin(current_path) if include_origins else ""
            dirty_count = None
            status_error = ""
            if include_status:
                dirty_count, status_error = git_status_count(current_path)
            repo_record = {
                "path": rel_home(current_path, home),
                "bucket": git_bucket(current_path, home),
                "dirty_count": dirty_count,
                "status_error": sanitize_text(status_error, home, redact),
            }
            if include_origins:
                repo_record["origin"] = origin
            repos.append(repo_record)
            if len(repos) >= limit:
                break
        if len(repos) >= limit:
            break
    buckets: dict[str, dict[str, Any]] = {}
    for repo in repos:
        bucket = repo["bucket"]
        item = buckets.setdefault(bucket, {"bucket": bucket, "repo_count": 0, "dirty_repo_count": 0, "dirty_change_count": 0})
        item["repo_count"] += 1
        if isinstance(repo["dirty_count"], int) and repo["dirty_count"] > 0:
            item["dirty_repo_count"] += 1
            item["dirty_change_count"] += repo["dirty_count"]
    bucket_rows = sorted(buckets.values(), key=lambda item: item["repo_count"], reverse=True)
    return {
        "repos": repos,
        "buckets": bucket_rows,
        "truncated": len(repos) >= limit,
        "status_collected": include_status,
    }


def scan_artifacts(roots: list[Path], home: Path, max_depth: int, min_bytes: int, limit: int, timeout: int, redact: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for current, dirs, _files in os.walk(root):
            current_path = Path(current)
            if depth_of(current_path, root) > max_depth:
                dirs[:] = []
                continue
            kept_dirs = []
            for dirname in dirs:
                child = current_path / dirname
                if dirname in ARTIFACT_NAMES:
                    size, error, timed_out = du_size(child, timeout)
                    if (size is not None and size >= min_bytes) or (size is None and (error or timed_out)):
                        category, risk, rebuild = ARTIFACT_NAMES[dirname]
                        rows.append(
                            {
                                "path": rel_home(child, home),
                                "name": dirname,
                                "category": category,
                                "risk": risk,
                                "allocated_bytes": size,
                                "human_size": human_size(size),
                                "modified_at": mtime_iso(child),
                                "rebuild_hint": rebuild,
                                "measurement_error": sanitize_text(error, home, redact),
                                "timed_out": timed_out,
                                "measurement_status": measurement_status(size, error, timed_out),
                            }
                        )
                    continue
                if not should_skip_dir(child):
                    kept_dirs.append(dirname)
            dirs[:] = kept_dirs
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    rows.sort(
        key=lambda item: item["allocated_bytes"] if item["allocated_bytes"] is not None else -1,
        reverse=True,
    )
    return rows[:limit]


def codex_summary(home: Path, measure_sizes: bool, timeout: int, deadline: Optional[float], redact: bool) -> Optional[dict[str, Any]]:
    root = home / "Documents" / "Codex"
    if not root.exists() or not root.is_dir():
        return None
    date_re = re.compile(r"^20\d\d-\d\d-\d\d")
    date_dirs = [p for p in root.iterdir() if p.is_dir() and date_re.match(p.name)]
    work_count = 0
    output_count = 0
    for current, dirs, _files in os.walk(root):
        current_path = Path(current)
        if depth_of(current_path, root) > 3:
            dirs[:] = []
            continue
        for dirname in dirs:
            if dirname == "work":
                work_count += 1
            elif dirname == "outputs":
                output_count += 1
    top_dates = []
    if measure_sizes:
        for date_dir in date_dirs:
            if budget_exhausted(deadline):
                break
            size, error, timed_out = du_size(date_dir, timeout)
            top_dates.append(
                {
                    "path": rel_home(date_dir, home),
                    "allocated_bytes": size,
                    "human_size": human_size(size),
                    "modified_at": mtime_iso(date_dir),
                    "measurement_error": sanitize_text(error, home, redact),
                    "timed_out": timed_out,
                    "measurement_status": measurement_status(size, error, timed_out),
                }
            )
        top_dates.sort(key=lambda item: item["allocated_bytes"] if item["allocated_bytes"] is not None else -1, reverse=True)
    return {
        "path": rel_home(root, home),
        "date_dir_count": len(date_dirs),
        "work_dir_count": work_count,
        "outputs_dir_count": output_count,
        "top_date_dirs": top_dates[:15],
    }


def workspace_roots(home: Path) -> list[Path]:
    candidates = [
        home / "Desktop",
        home / "Downloads",
        home / "Documents" / "Codex",
        home / "github",
        home / "src",
        home / "work",
        home / "research",
        home / "projects",
        home / "code",
        home / "dev",
        home / "AndroidStudioProjects",
    ]
    return [p for p in candidates if p.exists() and p.is_dir()]


def disk_summary(home: Path, redact: bool) -> dict[str, Any]:
    usage = shutil.disk_usage(home)
    return {
        "path": display_home(home, redact),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "total": human_size(usage.total),
        "used": human_size(usage.used),
        "free": human_size(usage.free),
        "measurement_status": "measured",
    }


def target_coverage(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for target in TARGETS:
        item = definitions.setdefault(
            target.label,
            {
                "label": target.label,
                "category": target.category,
                "risk": target.risk,
                "patterns_checked": 0,
            },
        )
        item["patterns_checked"] += len(target.patterns)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["label"], []).append(record)

    coverage: list[dict[str, Any]] = []
    for label, definition in definitions.items():
        rows = grouped.get(label, [])
        statuses = {row.get("measurement_status", "unknown") for row in rows}
        measured_bytes = sum(
            row["allocated_bytes"]
            for row in rows
            if isinstance(row.get("allocated_bytes"), int)
        )
        if "timeout" in statuses:
            status = "timeout"
        elif "error" in statuses:
            status = "error"
        elif not rows:
            status = "not_found"
        elif "unknown" in statuses:
            status = "unknown"
        else:
            status = "measured"
        coverage.append(
            {
                **definition,
                "scope_id": "home",
                "matches": len(rows),
                "measured": sum(row.get("measurement_status") == "measured" for row in rows),
                "unknown": sum(row.get("measurement_status") != "measured" for row in rows),
                "measured_bytes": measured_bytes,
                "status": status,
            }
        )
    return coverage


def path_is_within(child: str, parent: str) -> bool:
    normalized_parent = parent.rstrip("/")
    return child == normalized_parent or child.startswith(normalized_parent + "/")


def safe_report_path(path: Path, home: Path, redact: bool) -> str:
    """Keep explicitly selected paths private even when they are outside home."""
    if not redact:
        return str(path)
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(home.resolve())
        return "~" if not relative.parts else "~/" + str(relative)
    except ValueError:
        return f"<external>/{path.name or 'root'}"
    except Exception:
        return "<unavailable>"


def duplicate_excluded_scopes() -> list[dict[str, str]]:
    return [
        {
            "category": "app-state",
            "label": "App-managed storage",
            "reason": "Excluded by default; select a specific root with --duplicate-root only when its owner is understood.",
        },
        {
            "category": "cloud-sync",
            "label": "Cloud-sync roots",
            "reason": "Excluded by default; local copies and sync-provider retention are not the same cleanup decision.",
        },
        {
            "category": "cache",
            "label": "Rebuildable directories",
            "reason": "Known dependency and build directories are skipped during duplicate traversal.",
        },
        {
            "category": "symlink",
            "label": "Symlink targets",
            "reason": "Symlinks are not followed, preventing the same tree from being scanned through an alias.",
        },
    ]


def duplicate_scope_index(home: Path) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for target in TARGETS:
        for pattern in target.patterns:
            for candidate in expand_pattern(pattern, home):
                if not candidate.exists() or not candidate.is_dir():
                    continue
                try:
                    resolved = candidate.resolve()
                except Exception:
                    continue
                key = (str(resolved), target.label)
                if key in seen:
                    continue
                seen.add(key)
                index.append(
                    {
                        "root": resolved,
                        "label": target.label,
                        "category": target.category,
                    }
                )
    return index


def duplicate_context(path: Path, scope_index: list[dict[str, Any]]) -> dict[str, str]:
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    matches = [
        item
        for item in scope_index
        if path_is_within(str(resolved), str(item["root"]))
    ]
    if not matches:
        return {"category": "unknown", "label": "Unknown scope"}
    specificity = {"Codex date workspaces": 3, "AI and coding agents": 2}
    selected = max(
        matches,
        key=lambda item: (len(Path(item["root"]).parts), specificity.get(item["label"], 1)),
    )
    return {"category": selected["category"], "label": selected["label"]}


def duplicate_scan_roots(home: Path, extra_roots: list[str]) -> tuple[list[Path], list[Path], list[Path]]:
    requested = workspace_roots(home)
    for raw_root in extra_roots:
        requested.append(Path(raw_root).expanduser())

    existing: list[Path] = []
    missing: list[Path] = []
    seen: set[str] = set()
    for candidate in requested:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_dir():
            existing.append(resolved)
        else:
            missing.append(resolved)

    # Prefer a selected parent root over a nested default root so files are not
    # visited twice when a user explicitly widens the scope.
    normalized: list[Path] = []
    for candidate in sorted(existing, key=lambda item: (len(item.parts), str(item))):
        if any(path_is_within(str(candidate), str(parent)) for parent in normalized):
            continue
        normalized.append(candidate)
    return normalized, missing, requested


def hash_duplicate_file(
    path: Path,
    deadline: Optional[float],
    max_bytes: int,
    bytes_hashed: int,
) -> tuple[str, Optional[str], int, str]:
    """Hash one stable regular file without reading beyond the duplicate budget."""
    try:
        before = path.lstat()
        if not stat_module.S_ISREG(before.st_mode) or path.is_symlink():
            return "error", None, 0, "not a regular file"
        size = int(before.st_size)
        if max_bytes > 0 and bytes_hashed + size > max_bytes:
            return "limit", None, 0, "duplicate byte budget reached"
        digest = hashlib.sha256()
        consumed = 0
        with path.open("rb") as handle:
            while True:
                if budget_exhausted(deadline):
                    return "timeout", None, consumed, "duplicate hash time budget reached"
                chunk = handle.read(DUPLICATE_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                consumed += len(chunk)
        after = path.lstat()
        if (
            before.st_size != after.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
        ):
            return "error", None, consumed, "file changed while hashing"
        if consumed != size:
            return "error", None, consumed, "file size changed while hashing"
        return "ok", digest.hexdigest(), consumed, ""
    except Exception as exc:
        return "error", None, 0, str(exc)


def scan_duplicates(
    roots: list[Path],
    missing_roots: list[Path],
    requested_roots: list[Path],
    home: Path,
    min_bytes: int,
    time_budget: int,
    max_bytes: int,
    file_limit: int,
    redact: bool,
) -> dict[str, Any]:
    """Find exact duplicate files using size buckets followed by local SHA-256."""
    deadline = time.time() + time_budget if time_budget > 0 else None
    scope_index = duplicate_scope_index(home)
    size_groups: dict[int, list[dict[str, Any]]] = {}
    errors: list[str] = []
    files_seen = 0
    status = "complete"

    def record_error(path: Optional[Path], message: str) -> None:
        if len(errors) >= 20:
            return
        rendered = f"{safe_report_path(path, home, redact)}: {message}" if path else message
        errors.append(rendered)

    def walk_error(exc: OSError) -> None:
        record_error(Path(exc.filename) if exc.filename else None, str(exc))

    for root in roots:
        if budget_exhausted(deadline):
            status = "timeout"
            break
        try:
            walker = os.walk(root, topdown=True, followlinks=False, onerror=walk_error)
            for current, dirs, filenames in walker:
                if budget_exhausted(deadline):
                    status = "timeout"
                    break
                current_path = Path(current)
                dirs[:] = sorted(
                    dirname
                    for dirname in dirs
                    if not should_skip_dir(current_path / dirname)
                    and not (current_path / dirname).is_symlink()
                )
                for filename in sorted(filenames):
                    if budget_exhausted(deadline):
                        status = "timeout"
                        break
                    path = current_path / filename
                    try:
                        file_stat = path.lstat()
                    except OSError as exc:
                        record_error(path, str(exc))
                        status = "error"
                        continue
                    if path.is_symlink() or not stat_module.S_ISREG(file_stat.st_mode):
                        continue
                    files_seen += 1
                    size = int(file_stat.st_size)
                    if size < min_bytes:
                        continue
                    size_groups.setdefault(size, []).append(
                        {
                            "path": path,
                            "size_bytes": size,
                            "st_dev": file_stat.st_dev,
                            "st_ino": file_stat.st_ino,
                        }
                    )
                if status in {"timeout"}:
                    break
            if status == "timeout":
                break
        except Exception as exc:  # pragma: no cover - defensive filesystem guard
            status = "error"
            record_error(root, str(exc))

    candidate_groups = [
        entries
        for _size, entries in size_groups.items()
        if len(entries) > 1
    ]
    candidate_groups.sort(key=lambda entries: (-entries[0]["size_bytes"], str(entries[0]["path"])))
    candidate_files = sum(len(entries) for entries in candidate_groups)
    hashed_files = 0
    bytes_hashed = 0
    hashed_groups: dict[tuple[int, str], list[dict[str, Any]]] = {}

    for entries in candidate_groups:
        for entry in sorted(entries, key=lambda item: str(item["path"])):
            if budget_exhausted(deadline):
                status = "timeout"
                break
            if file_limit > 0 and hashed_files >= file_limit:
                status = "limit"
                break
            hash_status, digest, consumed, error = hash_duplicate_file(
                entry["path"], deadline, max_bytes, bytes_hashed
            )
            if hash_status == "ok" and digest:
                entry = {**entry, "digest": digest}
                hashed_groups.setdefault((entry["size_bytes"], digest), []).append(entry)
                hashed_files += 1
                bytes_hashed += consumed
                continue
            if consumed:
                bytes_hashed += consumed
            if hash_status == "timeout":
                status = "timeout"
                break
            if hash_status == "limit":
                status = "limit"
                break
            status = "error"
            record_error(entry["path"], error or "unable to hash file")
        if status in {"timeout", "limit"}:
            break

    groups: list[dict[str, Any]] = []
    for (size_bytes, digest), entries in hashed_groups.items():
        if len(entries) < 2:
            continue
        path_rows: list[dict[str, Any]] = []
        inode_counts: dict[tuple[int, int], int] = {}
        for entry in entries:
            inode_key = (entry["st_dev"], entry["st_ino"])
            inode_counts[inode_key] = inode_counts.get(inode_key, 0) + 1
        for entry in sorted(entries, key=lambda item: str(item["path"])):
            context = duplicate_context(entry["path"], scope_index)
            inode_key = (entry["st_dev"], entry["st_ino"])
            path_rows.append(
                {
                    "path": safe_report_path(entry["path"], home, redact),
                    "context": context["category"],
                    "scope": context["label"],
                    "size_bytes": size_bytes,
                    "human_size": human_size(size_bytes),
                    "modified_at": mtime_iso(entry["path"]),
                    "hardlink_alias": inode_counts[inode_key] > 1,
                }
            )
        independent_copy_count = len(inode_counts)
        potential_bytes = size_bytes * max(independent_copy_count - 1, 0)
        priority = {"workspace": 4, "cloud-sync": 3, "inbox": 2, "unknown": 1, "app-state": 0}
        canonical = min(
            path_rows,
            key=lambda row: (-priority.get(row["context"], 1), row["path"]),
        )
        groups.append(
            {
                "duplicate_group_id": stable_id("duplicate", f"{size_bytes}:{digest}"),
                "status": "exact",
                "hash_algorithm": "sha256",
                "byte_kind": "logical_bytes",
                "size_bytes": size_bytes,
                "human_size": human_size(size_bytes),
                "file_count": len(path_rows),
                "independent_copy_count": independent_copy_count,
                "hardlink_alias_count": len(path_rows) - independent_copy_count,
                "potential_duplicate_bytes": potential_bytes,
                "potential_duplicate_size": human_size(potential_bytes),
                "canonical_candidate_path": canonical["path"],
                "canonical_candidate_context": canonical["context"],
                "canonical_reason": "Prefer the workspace-context copy as a review candidate; verify references before archiving anything.",
                "paths": path_rows,
            }
        )
    groups.sort(key=lambda group: (-group["potential_duplicate_bytes"], group["duplicate_group_id"]))
    if not roots:
        status = "not_found"
    elif missing_roots and status == "complete":
        status = "error"
        for missing in missing_roots:
            record_error(missing, "requested duplicate root was not found")

    return {
        "enabled": True,
        "status": status,
        "hash_algorithm": "sha256",
        "byte_kind": "logical_bytes",
        "roots": [safe_report_path(root, home, redact) for root in roots],
        "requested_roots": [safe_report_path(root, home, redact) for root in requested_roots],
        "missing_roots": [safe_report_path(root, home, redact) for root in missing_roots],
        "excluded_scopes": duplicate_excluded_scopes(),
        "min_bytes": min_bytes,
        "time_budget": time_budget,
        "max_bytes": max_bytes,
        "file_limit": file_limit,
        "files_seen": files_seen,
        "candidate_files": candidate_files,
        "hashed_files": hashed_files,
        "bytes_hashed": bytes_hashed,
        "errors": errors,
        "groups": groups,
        "group_count": len(groups),
        "potential_duplicate_bytes": sum(group["potential_duplicate_bytes"] for group in groups),
        "potential_duplicate_size": human_size(sum(group["potential_duplicate_bytes"] for group in groups)),
    }


def annotate_duplicate_overlaps(
    duplicates: dict[str, Any],
    records: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Add parent-container context without counting parent and child bytes together."""
    target_labels = [(row.get("path", ""), row.get("label", "")) for row in records]
    artifact_paths = [row.get("path", "") for row in artifacts]
    for group in duplicates.get("groups", []):
        contexts: dict[str, int] = {}
        parent_labels: set[str] = set()
        artifact_parents: set[str] = set()
        contains_cloud_sync = False
        hardlink_alias = False
        for row in group.get("paths", []):
            context = row.get("context", "unknown")
            contexts[context] = contexts.get(context, 0) + 1
            contains_cloud_sync = contains_cloud_sync or context == "cloud-sync"
            hardlink_alias = hardlink_alias or bool(row.get("hardlink_alias"))
            path = row.get("path", "")
            for target_path, label in target_labels:
                if target_path and path_is_within(path, target_path) and label:
                    parent_labels.add(label)
            for artifact_path in artifact_paths:
                if artifact_path and path_is_within(path, artifact_path):
                    artifact_parents.add(artifact_path)
        warnings: list[str] = []
        if parent_labels:
            warnings.append("These files sit inside a larger folder total. Do not add the numbers together.")
        if artifact_parents:
            warnings.append("One file is inside a rebuildable folder. Its space may already be counted above.")
        if contains_cloud_sync:
            warnings.append("One copy is in a cloud folder. Removing it may affect sync or another device.")
        if hardlink_alias:
            warnings.append("Some paths point to the same underlying file. They do not use extra space in the same way.")
        group["contexts"] = contexts
        group["parent_targets"] = sorted(parent_labels)
        group["artifact_parents"] = sorted(artifact_parents)
        group["contains_cloud_sync"] = contains_cloud_sync
        group["overlap_warnings"] = warnings
    return duplicates


def focus_scan_roots(home: Path, extra_roots: list[str]) -> tuple[list[Path], list[Path], list[Path]]:
    requested = [Path(raw).expanduser() for raw in extra_roots] if extra_roots else workspace_roots(home)
    existing: list[Path] = []
    missing: list[Path] = []
    seen: set[str] = set()
    for candidate in requested:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists():
            existing.append(resolved)
        else:
            missing.append(resolved)

    normalized: list[Path] = []
    for candidate in sorted(existing, key=lambda item: (len(item.parts), str(item))):
        if any(path_is_within(str(candidate), str(parent)) for parent in normalized):
            continue
        normalized.append(candidate)
    return normalized, missing, requested


def scan_space_map(
    roots: list[Path],
    missing_roots: list[Path],
    requested_roots: list[Path],
    home: Path,
    max_depth: int,
    node_limit: int,
    timeout: int,
    time_budget: int,
    redact: bool,
    include_local_paths: bool = False,
    allow_skipped_root: bool = False,
) -> dict[str, Any]:
    """Collect a bounded, metadata-only tree for an interactive report."""
    deadline = time.time() + time_budget if time_budget > 0 else None
    scope_index = duplicate_scope_index(home)
    size_cache: dict[str, tuple[Optional[int], str, bool]] = {}
    for root in roots:
        if budget_exhausted(deadline):
            break
        size_cache.update(bulk_du_sizes(root, max_depth, timeout))

    def size_for(path: Path) -> tuple[Optional[int], str, bool]:
        cached = size_cache.get(path_cache_key(path))
        if cached is not None:
            return cached
        try:
            info = path.lstat()
        except OSError as exc:
            return None, str(exc), False
        if not stat_module.S_ISDIR(info.st_mode):
            return stat_size(path)
        return du_size(path, timeout)

    nodes: list[dict[str, Any]] = []
    errors: list[str] = []
    status = "complete"

    def report_error(path: Optional[Path], message: str) -> None:
        if len(errors) >= 20:
            return
        rendered = f"{safe_report_path(path, home, redact)}: {message}" if path else message
        errors.append(rendered)

    def context_for(path: Path, root: Path) -> dict[str, str]:
        context = duplicate_context(path, scope_index)
        if context["category"] == "unknown" and path_is_within(str(path), str(root)):
            return {"category": "workspace", "label": "Selected area"}
        return context

    def add_node(
        path: Path,
        parent_id: Optional[str],
        depth: int,
        root: Path,
        root_id: str,
        measured: Optional[tuple[Optional[int], str, bool]] = None,
    ) -> None:
        nonlocal status
        if len(nodes) >= node_limit:
            status = "limit"
            return
        if budget_exhausted(deadline):
            status = "partial"
            return
        try:
            path_stat = path.lstat()
        except OSError as exc:
            status = "partial"
            report_error(path, str(exc))
            return
        if path.is_symlink():
            return
        size, error, timed_out = measured if measured is not None else size_for(path)
        measurement = measurement_status(size, error, timed_out)
        if measurement != "measured":
            status = "partial"
        is_directory = stat_module.S_ISDIR(path_stat.st_mode)
        context = context_for(path, root)
        try:
            child_count = len(list(path.iterdir())) if is_directory else 0
        except OSError:
            child_count = 0
        node_id = stable_id("space", str(path.resolve()))
        node = {
            "node_id": node_id,
            "parent_id": parent_id,
            "root_id": root_id,
            "depth": depth,
            "name": path.name or safe_report_path(path, home, redact),
            "path": safe_report_path(path, home, redact),
            "kind": "folder" if is_directory else "file",
            "category": context["category"],
            "area": context["label"],
            "allocated_bytes": size,
            "human_size": human_size(size),
            "modified_at": mtime_iso(path),
            "measurement_status": measurement,
            "measurement_error": sanitize_text(error, home, redact),
            "timed_out": timed_out,
            "child_count": child_count,
            # This remains true at the scan boundary so the TUI can load the
            # next level on demand instead of treating the boundary as a leaf.
            "can_expand": is_directory and child_count > 0,
        }
        if include_local_paths:
            # Private in-memory context for the local TUI. It is never emitted
            # by JSON/Markdown output and is needed for lazy expansion/preview.
            node["_local_path"] = str(path)
        nodes.append(node)
        may_descend = not should_skip_dir(path) or (allow_skipped_root and depth == 0)
        if depth >= max_depth or not node["can_expand"] or not may_descend:
            return
        try:
            children = [child for child in path.iterdir() if not child.is_symlink()]
        except OSError as exc:
            status = "partial"
            report_error(path, str(exc))
            return
        child_rows: list[tuple[Path, Optional[int], str, bool]] = []
        for child in children:
            if len(nodes) + len(child_rows) >= node_limit or budget_exhausted(deadline):
                status = "limit" if len(nodes) + len(child_rows) >= node_limit else "partial"
                break
            child_size, child_error, child_timed_out = size_for(child)
            child_rows.append((child, child_size, child_error, child_timed_out))
        child_rows.sort(key=lambda item: (item[1] if item[1] is not None else -1, str(item[0])), reverse=True)
        for child, child_size, child_error, child_timed_out in child_rows:
            if len(nodes) >= node_limit or budget_exhausted(deadline):
                status = "limit" if len(nodes) >= node_limit else "partial"
                break
            add_node(child, node_id, depth + 1, root, root_id, (child_size, child_error, child_timed_out))

    for root in roots:
        if len(nodes) >= node_limit or budget_exhausted(deadline):
            status = "limit" if len(nodes) >= node_limit else "partial"
            break
        root_id = stable_id("space", str(root.resolve()))
        add_node(root, None, 0, root, root_id)
    if not roots:
        status = "not_found"
    elif missing_roots and status == "complete":
        status = "partial"
    for missing in missing_roots:
        report_error(missing, "selected path was not found")

    return {
        "enabled": True,
        "status": status,
        "selection_mode": "selected paths" if missing_roots or requested_roots != workspace_roots(home) else "workspace roots",
        "roots": [safe_report_path(root, home, redact) for root in roots],
        "requested_roots": [safe_report_path(root, home, redact) for root in requested_roots],
        "missing_roots": [safe_report_path(root, home, redact) for root in missing_roots],
        "max_depth": max_depth,
        "node_limit": node_limit,
        "timeout": timeout,
        "time_budget": time_budget,
        "node_count": len(nodes),
        "nodes": nodes,
        "errors": errors,
    }


def expand_space_map_node(
    node: dict[str, Any],
    home: Path,
    redact: bool,
    timeout: int,
    node_limit: int,
    time_budget: int,
) -> tuple[list[dict[str, Any]], str]:
    """Load only the immediate children of a TUI folder on demand."""
    local_path = node.get("_local_path")
    if node.get("kind") != "folder" or not local_path:
        return [], "unavailable"
    path = Path(str(local_path))
    if not path.is_dir():
        return [], "not_found"
    root_id = stable_id("space", str(path.resolve()))
    mapped = scan_space_map(
        [path],
        [],
        [path],
        home,
        1,
        node_limit,
        timeout,
        time_budget,
        redact,
        include_local_paths=True,
        allow_skipped_root=True,
    )
    children = [item for item in mapped.get("nodes", []) if item.get("parent_id") == root_id]
    parent_depth = int(node.get("depth") or 0)
    for child in children:
        child["root_id"] = node.get("root_id") or root_id
        child["depth"] = parent_depth + 1
    return children, str(mapped.get("status") or "unknown")


def build_findings(
    records: list[dict[str, Any]],
    git: dict[str, Any],
    artifacts: list[dict[str, Any]],
    duplicates: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    target_records: list[dict[str, Any]] = []
    for index, row in enumerate(records):
        finding_id = stable_id("target", row["path"])
        row["finding_id"] = finding_id
        status = row.get("measurement_status", "unknown")
        target_records.append(row)
        findings.append(
            {
                "finding_id": finding_id,
                "scope_id": "home",
                "path_redacted": row["path"],
                "category": row["category"],
                "owner": owner_for_category(row["category"]),
                "size_bytes": row.get("allocated_bytes"),
                "status": status,
                "evidence_refs": [f"target_areas[{index}]"],
                "confidence": "strong_inference" if status == "measured" else "low",
                "risk": row["risk"],
                "recommendation": action_for_category(row["category"]),
                "approval_required": True,
                "rollback_or_rebuild": rollback_for_category(row["category"]),
            }
        )

    artifact_paths = [row.get("path", "") for row in artifacts]
    for index, row in enumerate(artifacts):
        path = row.get("path", "")
        parents = [
            target
            for target in target_records
            if path and path_is_within(path, target["path"])
        ]
        parent = max(parents, key=lambda target: len(target["path"])) if parents else None
        nested = any(
            other_path != path and path_is_within(path, other_path)
            for other_path in artifact_paths
            if other_path
        )
        status = row.get("measurement_status", "unknown")
        findings.append(
            {
                "finding_id": stable_id("artifact", path),
                "scope_id": "home",
                "path_redacted": path,
                "category": row.get("category", "cache"),
                "owner": "project toolchain",
                "size_bytes": row.get("allocated_bytes"),
                "status": status,
                "evidence_refs": ["artifacts[" + str(index) + "]"]
                + (["target_areas[" + str(records.index(parent)) + "]"] if parent else []),
                "confidence": "strong_inference" if status == "measured" else "low",
                "risk": row.get("risk", "review"),
                "recommendation": "Check how this project recreates the folder before removing it.",
                "approval_required": True,
                "rollback_or_rebuild": row.get("rebuild_hint", "Rebuild the owning project."),
                "parent_target_id": parent.get("finding_id") if parent else None,
                "counted_in_total": bool(parent and parent.get("measurement_status") == "measured"),
                "nested_artifact": nested,
            }
        )

    if duplicates and duplicates.get("enabled"):
        for index, group in enumerate(duplicates.get("groups", [])):
            potential_bytes = group.get("potential_duplicate_bytes", 0)
            status = group.get("status", "unknown")
            findings.append(
                {
                    "finding_id": group.get("duplicate_group_id") or stable_id("duplicate", str(index)),
                    "scope_id": "home",
                    "path_redacted": group.get("canonical_candidate_path", "unknown"),
                    "category": "duplicate",
                    "owner": owner_for_category("duplicate"),
                    "size_bytes": potential_bytes,
                    "status": status,
                    "evidence_refs": [f"duplicates.groups[{index}]"],
                    "confidence": "confirmed" if status == "exact" else "low",
                    "risk": "review",
                    "recommendation": action_for_category("duplicate"),
                    "approval_required": True,
                    "rollback_or_rebuild": rollback_for_category("duplicate"),
                    "duplicate_group_id": group.get("duplicate_group_id"),
                    "file_count": group.get("file_count", 0),
                    "independent_copy_count": group.get("independent_copy_count", 0),
                    "potential_duplicate_bytes": potential_bytes,
                    "canonical_candidate_path": group.get("canonical_candidate_path"),
                    "overlap_warnings": group.get("overlap_warnings", []),
                }
            )

    for index, bucket in enumerate(git.get("buckets", [])):
        dirty_repos = bucket.get("dirty_repo_count", 0)
        dirty_changes = bucket.get("dirty_change_count", 0)
        if not dirty_repos and not dirty_changes:
            continue
        status = "dirty" if isinstance(dirty_repos, int) and isinstance(dirty_changes, int) else "unknown"
        findings.append(
            {
                "finding_id": stable_id("git", str(bucket.get("bucket", index))),
                "scope_id": "home",
                "path_redacted": bucket.get("bucket", "unknown"),
                "category": "workspace",
                "owner": "project owner",
                "size_bytes": None,
                "status": status,
                "evidence_refs": [f"git.buckets[{index}]"],
                "confidence": "confirmed" if status == "dirty" else "low",
                "risk": "user-data",
                "recommendation": "Save or export the changes before moving this project.",
                "approval_required": True,
                "rollback_or_rebuild": "Restore the original repository or recover from Git/stash/export.",
                "dirty_repo_count": dirty_repos,
                "dirty_change_count": dirty_changes,
            }
        )
    return findings


def action_gate(
    records: list[dict[str, Any]],
    git: dict[str, Any],
    artifacts: list[dict[str, Any]],
    duplicates: Optional[dict[str, Any]] = None,
    space_map: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if any(row.get("measurement_status") != "measured" for row in records):
        blockers.append("Some folder sizes could not be checked completely. Review those areas before deciding what to move or remove.")
    if git.get("skipped") or not git.get("status_collected", False):
        blockers.append("We did not check projects for unsaved work. Check project status before moving any project folder.")
    dirty_changes = sum(row.get("dirty_change_count", 0) for row in git.get("buckets", []))
    if dirty_changes:
        blockers.append(f"{dirty_changes} unsaved project changes need to be preserved before any project is moved.")
    if any(row.get("measurement_status") != "measured" for row in artifacts):
        blockers.append("Some rebuildable folders could not be checked completely. Do not treat their sizes as reliable savings yet.")
    if duplicates and duplicates.get("enabled") and duplicates.get("status") != "complete":
        blockers.append("The repeated-file check stopped early. Do not decide what to remove from a partial result.")
    if space_map and space_map.get("enabled") and space_map.get("status") not in {"complete", "disabled"}:
        blockers.append("The selected space map is incomplete. Check the path again before relying on its distribution.")
    gate = {
        "status": "review_only" if blockers else "approval_required",
        "scanner_mutates_files": False,
        "exact_cleanup_allowed": False,
        "requires_exact_approval": True,
        "blockers": blockers,
    }
    if duplicates and duplicates.get("enabled") and duplicates.get("groups"):
        gate["approval_notes"] = [
            "Exact matches are review items, not deletion instructions.",
            "Approve each group only after checking references, sync state, and the canonical candidate.",
        ]
    return gate


def build_tui_report(args: argparse.Namespace) -> dict[str, Any]:
    """Build only the focused map needed by the terminal explorer."""
    home = Path(args.home).expanduser().resolve()
    redact = not args.no_redact
    focus_roots, focus_missing, focus_requested = focus_scan_roots(home, args.focus_root)
    space_map = scan_space_map(
        focus_roots,
        focus_missing,
        focus_requested,
        home,
        args.focus_depth,
        args.focus_limit,
        args.focus_timeout,
        args.focus_time_budget,
        redact,
        include_local_paths=True,
    )
    return {
        "schema_version": "1.3",
        "generated_at": now_iso(),
        "read_only": True,
        "settings": {
            "home": display_home(home, redact),
            "scope_id": "focused-path",
            "size_kind": "allocated_bytes",
            "mode": "interactive",
            "redact": redact,
            "interactive": True,
            "tui": True,
            "interactive_only": True,
            "focus_roots": space_map.get("requested_roots", []),
            "focus_depth": space_map.get("max_depth", args.focus_depth),
            "requested_focus_depth": args.focus_depth,
            "focus_limit": args.focus_limit,
            "focus_timeout": args.focus_timeout,
            "focus_time_budget": args.focus_time_budget,
        },
        "space_map": space_map,
        "action_gate": {
            "status": "review_only",
            "scanner_mutates_files": False,
            "exact_cleanup_allowed": False,
            "requires_exact_approval": True,
        },
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.tui:
        return build_tui_report(args)
    home = Path(args.home).expanduser().resolve()
    redact = not args.no_redact
    min_bytes = int(args.min_mb * 1024 * 1024)
    target_timeout = args.target_timeout
    if target_timeout is None:
        target_timeout = FULL_TARGET_TIMEOUT_SECONDS if args.mode == "full" else QUICK_TARGET_TIMEOUT_SECONDS
    child_timeout = args.child_timeout
    if child_timeout is None:
        child_timeout = FULL_CHILD_TIMEOUT_SECONDS if args.mode == "full" else QUICK_CHILD_TIMEOUT_SECONDS
    time_budget = args.time_budget
    if time_budget is None:
        time_budget = 0 if args.mode == "full" else 30
    deadline = time.time() + time_budget if time_budget and time_budget > 0 else None
    roots = workspace_roots(home)
    records = scan_targets(home, target_timeout, deadline, redact)
    include_children = args.children or args.mode == "full"
    codex = codex_summary(home, include_children, target_timeout, deadline, redact)
    child_roots = [home / "Desktop", home / "Downloads", home / "Documents" / "Codex", home / "github", home / "src", home / "work", home / "research", home / "projects"]
    if include_children:
        children = {
            rel_home(root, home): top_children(root, home, min_bytes, args.top_children, child_timeout, redact)
            for root in child_roots
            if root.exists()
        }
    else:
        children = {}
    include_git = args.git or args.git_status or args.mode == "full"
    if include_git:
        git = find_git_repos(roots, home, args.git_depth, args.git_limit, args.git_status, args.include_git_origins, redact)
    else:
        git = {"repos": [], "buckets": [], "truncated": False, "skipped": True, "status_collected": False}
    artifacts = []
    if args.mode == "full" or args.artifacts:
        artifacts = scan_artifacts(roots, home, args.artifact_depth, min_bytes, args.artifact_limit, child_timeout, redact)
    duplicates = {
        "enabled": False,
        "status": "disabled",
        "hash_algorithm": "sha256",
        "byte_kind": "logical_bytes",
        "roots": [],
        "requested_roots": [],
        "missing_roots": [],
        "excluded_scopes": duplicate_excluded_scopes(),
        "groups": [],
        "group_count": 0,
        "potential_duplicate_bytes": 0,
        "potential_duplicate_size": human_size(0),
    }
    if args.duplicates:
        duplicate_roots, missing_roots, requested_roots = duplicate_scan_roots(home, args.duplicate_root)
        duplicates = scan_duplicates(
            duplicate_roots,
            missing_roots,
            requested_roots,
            home,
            int(args.duplicate_min_mb * 1024 * 1024),
            args.duplicate_time_budget,
            int(args.duplicate_max_mb * 1024 * 1024),
            args.duplicate_file_limit,
            redact,
        )
        duplicates = annotate_duplicate_overlaps(duplicates, records, artifacts)
    space_map = {
        "enabled": False,
        "status": "disabled",
        "selection_mode": "not selected",
        "roots": [],
        "requested_roots": [],
        "missing_roots": [],
        "nodes": [],
        "node_count": 0,
        "errors": [],
    }
    if args.tui or args.interactive or args.focus_root:
        focus_roots, focus_missing, focus_requested = focus_scan_roots(home, args.focus_root)
        space_map = scan_space_map(
            focus_roots,
            focus_missing,
            focus_requested,
            home,
            args.focus_depth,
            args.focus_limit,
            args.focus_timeout,
            args.focus_time_budget,
            redact,
            include_local_paths=args.tui,
        )
    coverage = target_coverage(records)
    findings = build_findings(records, git, artifacts, duplicates)
    return {
        "schema_version": "1.3",
        "generated_at": now_iso(),
        "read_only": True,
        "host": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "settings": {
            "home": display_home(home, redact),
            "scope_id": "home",
            "size_kind": "allocated_bytes",
            "mode": args.mode,
            "redact": redact,
            "min_mb": args.min_mb,
            "target_timeout": target_timeout,
            "child_timeout": child_timeout,
            "time_budget": time_budget,
            "children": include_children,
            "git": include_git,
            "git_status": args.git_status,
            "include_git_origins": args.include_git_origins,
            "artifacts": bool(artifacts),
            "duplicates": args.duplicates,
            "duplicate_roots": duplicates.get("requested_roots", []),
            "duplicate_min_mb": args.duplicate_min_mb,
            "duplicate_time_budget": args.duplicate_time_budget,
            "duplicate_max_mb": args.duplicate_max_mb,
            "duplicate_file_limit": args.duplicate_file_limit,
            "interactive": space_map.get("enabled", False),
            "tui": args.tui,
            "focus_roots": space_map.get("requested_roots", []),
            "focus_depth": space_map.get("max_depth", args.focus_depth),
            "requested_focus_depth": args.focus_depth,
            "focus_limit": args.focus_limit,
            "focus_timeout": args.focus_timeout,
            "focus_time_budget": args.focus_time_budget,
        },
        "disk": disk_summary(home, redact),
        "target_areas": records,
        "coverage": coverage,
        "top_children": children,
        "codex": codex,
        "git": git,
        "artifacts": artifacts,
        "duplicates": duplicates,
        "space_map": space_map,
        "findings": findings,
        "action_gate": action_gate(records, git, artifacts, duplicates, space_map),
        "recommendations": recommendations(records, git, artifacts, codex, duplicates),
    }


def recommendations(
    records: list[dict[str, Any]],
    git: dict[str, Any],
    artifacts: list[dict[str, Any]],
    codex: Optional[dict[str, Any]],
    duplicates: Optional[dict[str, Any]] = None,
) -> list[str]:
    recs: list[str] = []
    by_label: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for row in records:
        size = row.get("allocated_bytes") or 0
        by_label[row["label"]] = by_label.get(row["label"], 0) + size
        by_category[row["category"]] = by_category.get(row["category"], 0) + size
    if by_label.get("Desktop", 0) > 10 * 1024**3:
        recs.append("Your Desktop is carrying a lot of working material. Move finished work to a stable folder before archiving older items.")
    elif any(row.get("label") == "Desktop" and row.get("timed_out") for row in records):
        recs.append("We could not finish checking the Desktop. Look at it again with a little more time before planning any move.")
    if codex and codex.get("outputs_dir_count", 0) > 20:
        recs.append("Your Codex work area has accumulated many dated folders. Keep the useful outputs in a stable library, then archive older work by month.")
    if by_category.get("app-state", 0) > 5 * 1024**3:
        recs.append("Chat, browser, mail, and collaboration apps are using meaningful space. Review them from inside each app instead of deleting their folders directly.")
    if len(git.get("buckets", [])) > 3:
        recs.append("Your projects are spread across several folders. Before moving any project, check for unsaved work and choose one home for future projects.")
    elif git.get("skipped"):
        recs.append("The quick check did not look for project folders. Run a deeper check before moving development work.")
    if artifacts:
        total = sum(item.get("allocated_bytes") or 0 for item in artifacts)
        recs.append(f"We found {len(artifacts)} folders that may be rebuilt, using about {human_size(total)}. Check each project before removing one; the folder may already be counted inside a larger total.")
    if duplicates and duplicates.get("enabled"):
        if duplicates.get("status") == "complete" and duplicates.get("groups"):
            group_word = "set" if len(duplicates["groups"]) == 1 else "sets"
            recs.append(
                f"We found {len(duplicates['groups'])} {group_word} of identical files, with about {duplicates.get('potential_duplicate_size', '0 B')} in possible extra copies. Start with one set at a time; matching files are not automatically safe to remove."
            )
        elif duplicates.get("status") == "complete":
            recs.append("We did not find identical files in the work folders we checked.")
        else:
            recs.append("The repeated-file check stopped before it finished. Run it again with more time before relying on the result.")
    if not recs:
        recs.append("Nothing stands out in this first pass. A deeper check can look inside project folders and confirm project status.")
    return recs


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(cell.replace("\n", " ").replace("|", "\\|") for cell in row) + " |")
    return "\n".join(out)


def display_measurement(row: dict[str, Any]) -> str:
    status = row.get("measurement_status", "unknown")
    if status == "timeout":
        return "Could not measure (time limit)"
    if status in {"error", "unknown"}:
        return "Could not measure"
    if status == "missing":
        return "Not found"
    return row.get("human_size", "unknown")


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Local File Audit")
    lines.append("")
    lines.append(f"Generated: `{report['generated_at']}`")
    lines.append("")
    lines.append("Read-only: no files were modified, moved, or deleted.")
    lines.append("")
    disk = report["disk"]
    lines.append("## Outcome")
    lines.append("")
    lines.append(f"- Home: `{disk['path']}`")
    lines.append(f"- Disk: {disk['used']} used, {disk['free']} free, {disk['total']} total")
    gate = report.get("action_gate", {})
    lines.append(f"- Decision state: `{gate.get('status', 'review_only')}`")
    if gate.get("blockers"):
        lines.append("- Exact cleanup decisions are blocked until the following evidence gaps are reviewed:")
        for blocker in gate["blockers"]:
            lines.append(f"  - {blocker}")
    for rec in report["recommendations"]:
        lines.append(f"- {rec}")
    lines.append("")
    if report.get("coverage"):
        lines.append("## Coverage")
        lines.append("")
        lines.append("Coverage statuses distinguish measured data from timeout, error, and not-found states. Missing variants are not treated as zero bytes.")
        rows = []
        for row in report["coverage"]:
            rows.append([
                row["status"],
                str(row["matches"]),
                str(row["unknown"]),
                human_size(row["measured_bytes"]),
                row["label"],
            ])
        lines.append(markdown_table(["Status", "Matches", "Unknown", "Measured", "Target"], rows))
        lines.append("")
    lines.append("## Largest Target Areas")
    rows = []
    for row in report["target_areas"][:25]:
        rows.append([display_measurement(row), row.get("measurement_status", "unknown"), row["category"], row["risk"], f"`{row['path']}`", row["label"]])
    lines.append(markdown_table(["Size", "Status", "Category", "Risk", "Path", "Label"], rows))
    lines.append("")
    app_rows = [
        row for row in report["target_areas"]
        if row["category"] in {"app-state", "cloud-sync"}
    ][:20]
    if app_rows:
        lines.append("## App And Cloud Sediment")
        lines.append("")
        lines.append("Treat these as app-managed or sync-managed data. Prefer in-app cleanup and do not bulk-delete containers.")
        rows = [[display_measurement(row), row.get("measurement_status", "unknown"), row["risk"], f"`{row['path']}`", row["label"]] for row in app_rows]
        lines.append(markdown_table(["Size", "Status", "Risk", "Path", "Label"], rows))
        lines.append("")
    if report.get("codex"):
        codex = report["codex"]
        lines.append("## Codex Workspaces")
        lines.append("")
        lines.append(f"- Path: `{codex['path']}`")
        lines.append(f"- Date directories: {codex['date_dir_count']}")
        lines.append(f"- `work` directories: {codex['work_dir_count']}")
        lines.append(f"- `outputs` directories: {codex['outputs_dir_count']}")
        rows = [[display_measurement(row), row.get("measurement_status", "unknown"), f"`{row['path']}`", row.get("modified_at") or ""] for row in codex["top_date_dirs"][:10]]
        if rows:
            lines.append("")
            lines.append(markdown_table(["Size", "Status", "Date Dir", "Modified"], rows))
        lines.append("")
    lines.append("## Workspace Children")
    lines.append("")
    if not report["settings"].get("children"):
        lines.append("Child-directory ranking skipped in quick mode. Re-run with `--children` or `--mode full` for this view.")
        lines.append("")
    else:
        any_children = False
        for root, rows_data in report["top_children"].items():
            if not rows_data:
                continue
            any_children = True
            lines.append(f"### `{root}`")
            rows = [[display_measurement(row), row.get("measurement_status", "unknown"), f"`{row['path']}`", row.get("modified_at") or ""] for row in rows_data[:15]]
            lines.append(markdown_table(["Size", "Status", "Path", "Modified"], rows))
            lines.append("")
        if not any_children:
            lines.append("No workspace children above the configured size threshold.")
            lines.append("")
    git = report["git"]
    lines.append("## Git Distribution")
    lines.append("")
    if git.get("skipped"):
        lines.append("- Git discovery skipped in quick mode. Re-run with `--git` or `--mode full` before moving repositories.")
    else:
        lines.append(f"- Repositories found: {len(git['repos'])}" + (" (truncated)" if git.get("truncated") else ""))
    if not git.get("skipped") and not report["settings"]["git_status"]:
        lines.append("- Dirty counts were not collected. Re-run with `--git-status` before moving repositories.")
    rows = []
    for row in git["buckets"][:20]:
        rows.append([
            str(row["repo_count"]),
            str(row["dirty_repo_count"]),
            str(row["dirty_change_count"]),
            f"`{row['bucket']}`",
        ])
    if rows:
        lines.append("")
        lines.append(markdown_table(["Repos", "Dirty Repos", "Dirty Changes", "Bucket"], rows))
    lines.append("")
    if report["artifacts"]:
        lines.append("## Large Rebuildable Or Review Artifacts")
        lines.append("")
        lines.append("Artifact sizes may already be included in their parent workspace totals. Treat them as candidate subsets, not additive reclaimable space.")
        lines.append("")
        rows = []
        for row in report["artifacts"][:30]:
            finding = next((item for item in report.get("findings", []) if item.get("path_redacted") == row.get("path")), {})
            rows.append([display_measurement(row), row.get("measurement_status", "unknown"), row["risk"], row["name"], f"`{row['path']}`", "yes" if finding.get("counted_in_total") else "unknown", row["rebuild_hint"]])
        lines.append(markdown_table(["Size", "Status", "Risk", "Name", "Path", "In Parent", "Rebuild"], rows))
        lines.append("")
    duplicates = report.get("duplicates") or {}
    lines.append("## Exact Duplicate Groups")
    lines.append("")
    if not duplicates.get("enabled"):
        lines.append("Exact duplicate detection is disabled. The default audit does not read file contents; opt in with `--duplicates`.")
        lines.append("")
    else:
        lines.append(
            f"Status: `{duplicates.get('status', 'unknown')}`. Hashing is local and uses {duplicates.get('hash_algorithm', 'sha256').upper()}; no file contents or hashes are uploaded."
        )
        if duplicates.get("excluded_scopes"):
            excluded = ", ".join(item.get("label", "unknown") for item in duplicates["excluded_scopes"])
            lines.append(f"Excluded by default: {excluded}.")
        lines.append("")
        duplicate_groups = duplicates.get("groups") or []
        if duplicate_groups:
            rows = []
            for group in duplicate_groups[:50]:
                contexts = ", ".join(f"{key}: {value}" for key, value in sorted((group.get("contexts") or {}).items()))
                overlap = "; ".join(group.get("overlap_warnings") or []) or "none reported"
                rows.append(
                    [
                        f"`{group.get('duplicate_group_id', 'unknown')}`",
                        str(group.get("file_count", 0)),
                        str(group.get("independent_copy_count", 0)),
                        group.get("potential_duplicate_size", "unknown"),
                        f"`{group.get('canonical_candidate_path', 'unknown')}`",
                        contexts or "unknown",
                        overlap,
                    ]
                )
            lines.append(markdown_table(["Group", "Copies", "Independent", "Potential logical bytes", "Review candidate", "Contexts", "Overlap"], rows))
            lines.append("")
            for group in duplicate_groups[:20]:
                lines.append(f"### `{group.get('duplicate_group_id', 'unknown')}`")
                lines.append("")
                for path_row in group.get("paths", []):
                    alias = "; hard-link alias" if path_row.get("hardlink_alias") else ""
                    lines.append(f"- `{path_row.get('path', 'unknown')}` ({path_row.get('scope', 'unknown')}; {path_row.get('context', 'unknown')}{alias})")
                if group.get("overlap_warnings"):
                    lines.append("")
                    lines.append("Review notes:")
                    for warning in group["overlap_warnings"]:
                        lines.append(f"- {warning}")
                lines.append("")
        else:
            lines.append("No exact duplicate groups were found in the selected roots.")
            lines.append("")
    if report.get("findings"):
        lines.append("## Decision Ledger")
        lines.append("")
        lines.append("Each finding links back to evidence in the JSON report. This ledger is for review; the scanner never executes the recommended action.")
        lines.append("")
        rows = []
        for finding in report["findings"][:40]:
            rows.append([
                finding["status"],
                finding["confidence"],
                finding["category"],
                finding["owner"],
                f"`{finding['path_redacted']}`",
                finding["recommendation"],
            ])
        lines.append(markdown_table(["Status", "Confidence", "Category", "Owner", "Path", "Recommended review"], rows))
        lines.append("")
    lines.append("## Suggested Next Step")
    lines.append("")
    if gate.get("blockers"):
        lines.append("Resolve the coverage and preservation blockers first. Do not turn this report into a cleanup plan until every exact target is measured and dirty work is preserved.")
    else:
        lines.append("Create a promotion map before deleting anything: choose which outputs belong in stable folders, which workspaces should be archived, and which app-managed data should be cleaned inside the owning app.")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only local file organization audit.")
    parser.add_argument("--home", default=str(Path.home()), help="Home directory to analyze. Defaults to current user home.")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick", help="Quick scans known roots; full also scans artifacts.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format for non-interactive runs.")
    parser.add_argument("--output", help="Write report to this path instead of stdout.")
    parser.add_argument("--no-redact", action="store_true", help="Include absolute home path in report metadata and errors. Redaction is enabled by default.")
    parser.add_argument("--min-mb", type=float, default=100.0, help="Minimum child/artifact size to report.")
    parser.add_argument("--target-timeout", type=int, help="Per-target size timeout in seconds. Defaults to 3 in quick mode and 20 in full mode.")
    parser.add_argument("--time-budget", type=int, help="Overall target measurement budget in seconds. Defaults to 30 in quick mode and disabled in full mode. Use 0 to disable.")
    parser.add_argument("--children", action="store_true", help="Rank large immediate children of workspace roots. Enabled automatically in full mode.")
    parser.add_argument("--child-timeout", type=int, help="Per-child size timeout in seconds. Defaults to 8 in quick mode and 30 in full mode.")
    parser.add_argument("--top-children", type=int, default=20, help="Top child entries per workspace root.")
    parser.add_argument("--git", action="store_true", help="Discover Git repositories. Enabled automatically in full mode.")
    parser.add_argument("--git-depth", type=int, default=7, help="Max depth for Git repository discovery.")
    parser.add_argument("--git-limit", type=int, default=500, help="Max Git repositories to report.")
    parser.add_argument("--include-git-origins", action="store_true", help="Include Git origin URLs in JSON reports. Off by default to reduce accidental disclosure.")
    parser.add_argument("--git-status", action="store_true", help="Run git status in discovered repos to count dirty entries.")
    parser.add_argument("--artifacts", action="store_true", help="Scan for node_modules, .venv, build, dist, and similar artifacts.")
    parser.add_argument("--artifact-depth", type=int, default=8, help="Max depth for artifact discovery.")
    parser.add_argument("--artifact-limit", type=int, default=100, help="Max artifacts to report.")
    parser.add_argument("--duplicates", action="store_true", help="Opt in to local SHA-256 hashing for exact duplicate detection.")
    parser.add_argument("--duplicate-root", action="append", default=[], help="Additional directory to include in duplicate detection. May be repeated.")
    parser.add_argument("--duplicate-min-mb", type=float, default=DUPLICATE_DEFAULT_MIN_BYTES / 1024**2, help="Minimum logical file size for duplicate candidates. Defaults to 1 MB; use 0 to include all files.")
    parser.add_argument("--duplicate-time-budget", type=int, default=DUPLICATE_DEFAULT_TIME_BUDGET_SECONDS, help="Duplicate hashing budget in seconds. Use 0 to disable the time limit.")
    parser.add_argument("--duplicate-max-mb", type=int, default=DUPLICATE_DEFAULT_MAX_BYTES // 1024**2, help="Maximum logical bytes to hash. Use 0 to disable the byte limit.")
    parser.add_argument("--duplicate-file-limit", type=int, default=DUPLICATE_DEFAULT_FILE_LIMIT, help="Maximum candidate files to hash. Use 0 to disable the file limit.")
    parser.add_argument("--interactive", action="store_true", help="Build a bounded metadata-only space map for JSON or the terminal explorer.")
    parser.add_argument("--tui", action="store_true", help="Open the dependency-free terminal explorer after the read-only scan.")
    parser.add_argument("--focus-root", "--path", dest="focus_root", action="append", default=[], help="Directory to map interactively. May be repeated; implies --interactive.")
    parser.add_argument("--focus-depth", type=int, default=2, help="Initial folder depth to scan below each focused path; TUI loads deeper folders when opened.")
    parser.add_argument("--focus-limit", type=int, default=100, help="Maximum space-map nodes to collect.")
    parser.add_argument("--focus-timeout", type=int, default=5, help="Per-folder size timeout for the interactive map.")
    parser.add_argument("--focus-time-budget", type=int, default=30, help="Overall interactive map budget in seconds. Use 0 to disable the time limit.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.tui and args.output:
        print("error: --tui is interactive and cannot write --output", file=sys.stderr)
        return 2
    start = time.time()
    report = build_report(args)
    report["duration_seconds"] = round(time.time() - start, 3)
    if args.tui:
        from audit_tui import run_tui

        home = Path(args.home).expanduser().resolve()
        redact = not args.no_redact

        def expand_node(node: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
            return expand_space_map_node(
                node,
                home,
                redact,
                args.focus_timeout,
                args.focus_limit,
                args.focus_time_budget,
            )

        return run_tui(report, expand_node)
    if args.format == "json":
        output = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        output = render_markdown(report)
    if args.output:
        Path(args.output).expanduser().write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
