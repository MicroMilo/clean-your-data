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
import html
import json
import os
import platform
import re
import shutil
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
    }.get(category, "unknown")


def action_for_category(category: str) -> str:
    return {
        "app-state": "Use the owning app's storage controls; do not delete the container.",
        "cloud-sync": "Check sync status and retention before changing files.",
        "inbox": "Review and apply an age policy before archiving.",
        "workspace": "Review and promote durable outputs before archiving.",
        "cache": "Confirm the rebuild command before removal.",
        "deliverable": "Promote the selected output to a stable library or project root.",
    }.get(category, "Review shallow metadata before deciding.")


def rollback_for_category(category: str) -> str:
    return {
        "app-state": "Restore through the owning app or backup; direct deletion may lose local state.",
        "cloud-sync": "Restore through the sync provider and verify sync state.",
        "inbox": "Restore from Trash or the dated archive.",
        "workspace": "Restore from the archive, Git, or the original project location.",
        "cache": "Reinstall dependencies or rebuild the project.",
        "deliverable": "Restore from the stable library or backup.",
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


def build_findings(
    records: list[dict[str, Any]],
    git: dict[str, Any],
    artifacts: list[dict[str, Any]],
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
                "recommendation": "Confirm the rebuild command before removal.",
                "approval_required": True,
                "rollback_or_rebuild": row.get("rebuild_hint", "Rebuild the owning project."),
                "parent_target_id": parent.get("finding_id") if parent else None,
                "counted_in_total": bool(parent and parent.get("measurement_status") == "measured"),
                "nested_artifact": nested,
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
                "recommendation": "Commit, stash, or export dirty changes before moving repositories.",
                "approval_required": True,
                "rollback_or_rebuild": "Restore the original repository or recover from Git/stash/export.",
                "dirty_repo_count": dirty_repos,
                "dirty_change_count": dirty_changes,
            }
        )
    return findings


def action_gate(records: list[dict[str, Any]], git: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    if any(row.get("measurement_status") != "measured" for row in records):
        blockers.append("Some target size probes are incomplete; resolve timeout or error states before exact cleanup decisions.")
    if git.get("skipped") or not git.get("status_collected", False):
        blockers.append("Git status was not collected; repository moves require a status check first.")
    dirty_changes = sum(row.get("dirty_change_count", 0) for row in git.get("buckets", []))
    if dirty_changes:
        blockers.append(f"{dirty_changes} dirty Git changes require preservation before repository migration.")
    if any(row.get("measurement_status") != "measured" for row in artifacts):
        blockers.append("Some artifact measurements are incomplete; do not treat them as reclaimable totals.")
    return {
        "status": "review_only" if blockers else "approval_required",
        "scanner_mutates_files": False,
        "exact_cleanup_allowed": False,
        "requires_exact_approval": True,
        "blockers": blockers,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
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
    coverage = target_coverage(records)
    findings = build_findings(records, git, artifacts)
    return {
        "schema_version": "1.1",
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
        },
        "disk": disk_summary(home, redact),
        "target_areas": records,
        "coverage": coverage,
        "top_children": children,
        "codex": codex,
        "git": git,
        "artifacts": artifacts,
        "findings": findings,
        "action_gate": action_gate(records, git, artifacts),
        "recommendations": recommendations(records, git, artifacts, codex),
    }


def recommendations(records: list[dict[str, Any]], git: dict[str, Any], artifacts: list[dict[str, Any]], codex: Optional[dict[str, Any]]) -> list[str]:
    recs: list[str] = []
    by_label: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for row in records:
        size = row.get("allocated_bytes") or 0
        by_label[row["label"]] = by_label.get(row["label"], 0) + size
        by_category[row["category"]] = by_category.get(row["category"], 0) + size
    if by_label.get("Desktop", 0) > 10 * 1024**3:
        recs.append("Desktop is large enough to treat as an inbox. Move durable work into stable roots such as ~/work, ~/research, ~/papers, ~/personal, or ~/src.")
    elif any(row.get("label") == "Desktop" and row.get("timed_out") for row in records):
        recs.append("Desktop size measurement hit its timeout. Re-run with a larger --target-timeout or a narrower --home path before planning migration.")
    if codex and codex.get("outputs_dir_count", 0) > 20:
        recs.append("Codex has many output/work directories. Promote selected outputs to a durable library, then archive old date folders by month.")
    if by_category.get("app-state", 0) > 5 * 1024**3:
        recs.append("Chat, browser, email, and collaboration app storage is material. Use app-native storage cleanup before filesystem deletion.")
    if len(git.get("buckets", [])) > 3:
        recs.append("Git repositories are spread across multiple buckets. Standardize new clones under ~/src/<host>/<owner>/<repo> and migrate dirty repos only after commit/stash/export.")
    elif git.get("skipped"):
        recs.append("Git discovery was skipped for speed. Re-run with --git before planning repository moves.")
    if artifacts:
        total = sum(item.get("allocated_bytes") or 0 for item in artifacts)
        recs.append(f"Detected {len(artifacts)} large rebuildable/review artifacts totaling about {human_size(total)}. Treat them as cleanup candidates only after exact approval.")
    if not recs:
        recs.append("No major organization issue detected from shallow metadata. Use --mode full --artifacts --git-status for deeper evidence.")
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
        return "unknown (timeout)"
    if status in {"error", "unknown"}:
        return f"unknown ({status})"
    if status == "missing":
        return "not found"
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


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def html_token(value: Any) -> str:
    token = re.sub(r"[^a-z0-9_-]+", "-", str(value).lower()).strip("-")
    return token or "unknown"


def html_badge(value: Any) -> str:
    return f'<span class="badge {html_token(value)}">{html_escape(value)}</span>'


def html_table(headers: list[str], rows: list[list[str]], empty: str = "No data.") -> str:
    if not rows:
        return f'<p class="empty">{html_escape(empty)}</p>'
    header_html = "".join(f"<th scope=\"col\">{html_escape(header)}</th>" for header in headers)
    body_html = []
    for row in rows:
        body_html.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + header_html
        + "</tr></thead><tbody>"
        + "".join(body_html)
        + "</tbody></table></div>"
    )


def html_metric(label: str, value: Any, note: str = "") -> str:
    return (
        '<div class="metric">'
        f'<div class="metric-label">{html_escape(label)}</div>'
        f'<div class="metric-value">{html_escape(value)}</div>'
        f'<div class="metric-note">{html_escape(note)}</div>'
        "</div>"
    )


def html_meter(label: str, percentage: int, note: str, tone: str = "green") -> str:
    percentage = max(0, min(100, int(percentage)))
    return (
        '<div class="meter-block">'
        f'<div class="meter-label"><span>{html_escape(label)}</span><strong>{percentage}%</strong></div>'
        f'<div class="meter"><span class="meter-fill {html_token(tone)}" style="width: {percentage}%"></span></div>'
        f'<div class="meter-note">{html_escape(note)}</div>'
        '</div>'
    )


def render_html(report: dict[str, Any]) -> str:
    """Render a self-contained, offline report for human review."""

    disk = report.get("disk") or {}
    gate = report.get("action_gate") or {}
    settings = report.get("settings") or {}
    target_areas = report.get("target_areas") or []
    coverage = report.get("coverage") or []
    artifacts = report.get("artifacts") or []
    findings = report.get("findings") or []
    codex = report.get("codex") or {}
    git = report.get("git") or {}
    blockers = gate.get("blockers") or []
    decision_status = gate.get("status", "review_only")
    measured_targets = sum(row.get("measurement_status") == "measured" for row in target_areas)
    measured_artifacts = sum(row.get("measurement_status") == "measured" for row in artifacts)
    target_note = f"{measured_targets} measured of {len(target_areas)} rows"
    artifact_note = f"{measured_artifacts} measured; subsets may overlap"
    target_percentage = round(measured_targets * 100 / len(target_areas)) if target_areas else 0
    artifact_percentage = round(measured_artifacts * 100 / len(artifacts)) if artifacts else 100
    disk_used_percentage = 0
    if isinstance(disk.get("used_bytes"), int) and isinstance(disk.get("total_bytes"), int) and disk.get("total_bytes"):
        disk_used_percentage = round(disk["used_bytes"] * 100 / disk["total_bytes"])
    dirty_repo_count = sum(
        row.get("dirty_repo_count", 0)
        for row in git.get("buckets", [])
        if isinstance(row.get("dirty_repo_count", 0), int)
    )
    dirty_change_count = sum(
        row.get("dirty_change_count", 0)
        for row in git.get("buckets", [])
        if isinstance(row.get("dirty_change_count", 0), int)
    )
    git_value = "not scanned" if git.get("skipped") else len(git.get("repos", []))
    git_note = "Run full mode with --git-status for preservation checks" if git.get("skipped") else "repositories discovered"
    codex_value = codex.get("outputs_dir_count", "not detected") if codex else "not detected"
    codex_note = "outputs directories" if codex else "Codex workspace not found"
    if decision_status == "review_only":
        decision_label = "Review only"
        decision_heading = "Evidence is incomplete"
        decision_copy = "Resolve the blockers below before turning this report into a cleanup plan."
        decision_tone = "amber"
    else:
        decision_label = "Approval required"
        decision_heading = "Ready for exact review"
        decision_copy = "The measurements are complete enough to review exact paths one category at a time."
        decision_tone = "blue"

    warnings = []
    if settings.get("redact") is False:
        warnings.append("This report was generated with path redaction disabled. Keep it private.")
    if settings.get("include_git_origins"):
        warnings.append("Git origin collection was enabled. Keep this report private.")
    warning_html = "".join(f'<div class="warning">{html_escape(item)}</div>' for item in warnings)

    target_rows = []
    for row in target_areas[:25]:
        target_rows.append(
            [
                html_escape(display_measurement(row)),
                html_badge(row.get("measurement_status", "unknown")),
                html_escape(row.get("category", "unknown")),
                html_escape(row.get("risk", "review")),
                f'<code>{html_escape(row.get("path", ""))}</code>',
                html_escape(row.get("label", "")),
            ]
        )

    coverage_rows = []
    for row in coverage:
        coverage_rows.append(
            [
                html_badge(row.get("status", "unknown")),
                html_escape(row.get("matches", 0)),
                html_escape(row.get("unknown", 0)),
                html_escape(human_size(row.get("measured_bytes"))),
                html_escape(row.get("label", "")),
            ]
        )

    app_rows = []
    for row in [row for row in target_areas if row.get("category") in {"app-state", "cloud-sync"}][:20]:
        app_rows.append(
            [
                html_escape(display_measurement(row)),
                html_badge(row.get("measurement_status", "unknown")),
                html_escape(row.get("risk", "review")),
                f'<code>{html_escape(row.get("path", ""))}</code>',
                html_escape(row.get("label", "")),
            ]
        )

    codex_rows = []
    for row in (codex.get("top_date_dirs") or [])[:10]:
        codex_rows.append(
            [
                html_escape(display_measurement(row)),
                html_badge(row.get("measurement_status", "unknown")),
                f'<code>{html_escape(row.get("path", ""))}</code>',
                html_escape(row.get("modified_at") or ""),
            ]
        )

    child_sections = []
    for root, rows_data in (report.get("top_children") or {}).items():
        rows = []
        for row in rows_data[:15]:
            rows.append(
                [
                    html_escape(display_measurement(row)),
                    html_badge(row.get("measurement_status", "unknown")),
                    f'<code>{html_escape(row.get("path", ""))}</code>',
                    html_escape(row.get("modified_at") or ""),
                ]
            )
        if rows:
            child_sections.append(
                f'<h3>{html_escape(root)}</h3>'
                + html_table(["Size", "Status", "Path", "Modified"], rows)
            )
    children_html = "".join(child_sections) or '<p class="empty">No measured child directories above the configured threshold.</p>'

    git_rows = []
    for row in (git.get("buckets") or [])[:20]:
        git_rows.append(
            [
                html_escape(row.get("repo_count", 0)),
                html_escape(row.get("dirty_repo_count", 0)),
                html_escape(row.get("dirty_change_count", 0)),
                f'<code>{html_escape(row.get("bucket", ""))}</code>',
            ]
        )
    git_status_note = (
        "Git dirty counts were not collected. Do not move repositories yet."
        if not git.get("skipped") and not settings.get("git_status")
        else "Dirty changes are preservation blockers."
        if not git.get("skipped") and settings.get("git_status")
        else "Git discovery was skipped in quick mode."
    )

    finding_by_path = {item.get("path_redacted"): item for item in findings}
    artifact_rows = []
    for row in artifacts[:30]:
        finding = finding_by_path.get(row.get("path"), {})
        artifact_rows.append(
            [
                html_escape(display_measurement(row)),
                html_badge(row.get("measurement_status", "unknown")),
                html_escape(row.get("risk", "review")),
                html_escape(row.get("name", "")),
                f'<code>{html_escape(row.get("path", ""))}</code>',
                html_escape("yes" if finding.get("counted_in_total") else "unknown"),
                html_escape(row.get("rebuild_hint", "")),
            ]
        )

    finding_rows = []
    for finding in findings[:40]:
        finding_rows.append(
            [
                html_badge(finding.get("status", "unknown")),
                html_badge(finding.get("confidence", "low")),
                html_escape(finding.get("category", "unknown")),
                html_escape(finding.get("owner", "unknown")),
                f'<code>{html_escape(finding.get("path_redacted", ""))}</code>',
                html_escape(finding.get("recommendation", "Review")),
            ]
        )

    recommendation_items = "".join(
        f"<li>{html_escape(item)}</li>" for item in (report.get("recommendations") or [])
    ) or "<li>No additional heuristic recommendations.</li>"
    blocker_items = "".join(f"<li>{html_escape(item)}</li>" for item in blockers)
    blocker_content = (
        f"<ul>{blocker_items}</ul>"
        if blockers
        else '<p class="good">No evidence blockers. Any cleanup is still approval-gated.</p>'
    )
    app_content = html_table(
        ["Size", "Status", "Risk", "Path", "Target"],
        app_rows,
        "No app-managed or cloud-sync targets were found.",
    )
    codex_content = (
        f'<div class="inline-stats"><span><strong>{html_escape(codex.get("date_dir_count", 0))}</strong> date directories</span>'
        f'<span><strong>{html_escape(codex.get("work_dir_count", 0))}</strong> work directories</span>'
        f'<span><strong>{html_escape(codex.get("outputs_dir_count", 0))}</strong> outputs directories</span></div>'
        + html_table(["Size", "Status", "Date directory", "Modified"], codex_rows, "No dated Codex directories were measured.")
        if codex
        else '<p class="empty">No Codex workspace was found.</p>'
    )

    styles = """
    :root { color-scheme: light; --ink: #182b29; --muted: #687874; --line: #d8e1dd; --paper: #ffffff; --bg: #eef2ef; --deep: #123c37; --deep-2: #1f5a50; --green: #1f7658; --green-soft: #e5f2eb; --lime: #d4e96e; --amber: #916100; --amber-soft: #fff2d2; --red: #a74743; --red-soft: #fbe9e7; --blue: #285f87; --blue-soft: #e8f1f7; --coral: #df785c; }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    a { color: inherit; }
    .masthead { background: var(--deep); color: #f7f6ed; }
    .masthead-inner, main { max-width: 1240px; margin: 0 auto; }
    .masthead-inner { display: flex; justify-content: space-between; gap: 22px; align-items: center; padding: 15px 22px; }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 750; letter-spacing: .01em; }
    .brand-mark { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 7px; background: var(--lime); color: var(--deep); font-size: 10px; font-weight: 850; letter-spacing: -.02em; }
    .masthead-meta { color: #b6cbc2; font-size: 12px; text-align: right; }
    main { padding: 0 22px 62px; }
    .hero { display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 34px; align-items: stretch; margin: 0 -22px; padding: 48px 44px 42px; background: var(--deep); color: #f7f6ed; border-top: 1px solid #2a5a51; }
    .eyebrow, .section-kicker { margin: 0 0 8px; color: var(--lime); font-size: 11px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
    h1 { max-width: 720px; margin: 0; font-size: clamp(34px, 5vw, 60px); line-height: 1.02; letter-spacing: 0; }
    h2 { margin: 0; font-size: 21px; letter-spacing: 0; }
    h3 { margin: 20px 0 8px; font-size: 15px; }
    .lede { max-width: 700px; margin: 16px 0 0; color: #c6d5cf; font-size: 17px; }
    .hero-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 24px; }
    .tag { display: inline-flex; align-items: center; min-height: 25px; padding: 3px 9px; border: 1px solid #416b61; border-radius: 999px; color: #d5e2dc; font-size: 12px; }
    .status-card { display: flex; gap: 14px; align-items: flex-start; align-self: center; padding: 20px; border: 1px solid #54766e; border-radius: 8px; background: #f7f4e9; color: var(--ink); }
    .status-icon { display: grid; place-items: center; flex: 0 0 auto; width: 34px; height: 34px; border-radius: 50%; background: var(--amber-soft); color: var(--amber); font-size: 18px; font-weight: 850; }
    .status-icon.blue { background: var(--blue-soft); color: var(--blue); }
    .decision-label { color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; }
    .decision-value { margin-top: 4px; font-size: 19px; font-weight: 800; }
    .decision-value.amber { color: var(--amber); }
    .decision-value.blue { color: var(--blue); }
    .decision-copy { margin: 7px 0 0; color: var(--muted); font-size: 13px; }
    .report-nav { display: flex; gap: 18px; overflow-x: auto; margin: 0 -22px; padding: 12px 22px; border-bottom: 1px solid var(--line); background: var(--paper); color: var(--muted); font-size: 12px; white-space: nowrap; }
    .report-nav a { text-decoration: none; }
    .report-nav a:hover { color: var(--deep); }
    .notice, .warning, .panel { border: 1px solid var(--line); border-radius: 8px; background: var(--paper); }
    .notice { margin-top: 18px; padding: 11px 14px; color: var(--muted); font-size: 13px; }
    .warning { margin-top: 10px; padding: 11px 14px; background: var(--amber-soft); border-color: #efd38e; color: var(--amber); }
    .signals { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; margin-top: 18px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); background: var(--paper); }
    .signal { min-height: 150px; padding: 18px 20px; border-right: 1px solid var(--line); }
    .signal:last-child { border-right: 0; }
    .signal-label, .metric-label { color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; }
    .signal-value { margin-top: 5px; font-size: 28px; font-weight: 820; letter-spacing: 0; }
    .signal-note { min-height: 43px; margin-top: 3px; color: var(--muted); font-size: 12px; }
    .meter-block { margin-top: 10px; }
    .meter-label { display: flex; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 12px; }
    .meter-label strong { color: var(--ink); }
    .meter { height: 6px; margin-top: 6px; overflow: hidden; border-radius: 999px; background: #e3eae6; }
    .meter-fill { display: block; height: 100%; border-radius: inherit; background: var(--green); }
    .meter-fill.amber { background: var(--coral); }
    .meter-fill.blue { background: var(--blue); }
    .meter-note { margin-top: 5px; color: var(--muted); font-size: 11px; }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 10px; }
    .metric { min-height: 95px; padding: 14px; border: 1px solid var(--line); border-radius: 8px; background: #f8faf8; }
    .metric-value { margin-top: 5px; font-size: 21px; font-weight: 780; overflow-wrap: anywhere; }
    .metric-note { margin-top: 4px; color: var(--muted); font-size: 11px; }
    .panel { margin-top: 18px; padding: 22px; }
    .panel > p { margin: 8px 0 12px; color: var(--muted); }
    .callout { border-left: 4px solid var(--coral); }
    .section-head { display: flex; justify-content: space-between; gap: 20px; align-items: flex-end; margin-bottom: 12px; }
    .section-note { max-width: 460px; color: var(--muted); font-size: 12px; text-align: right; }
    .good { color: var(--green) !important; }
    ul { margin: 8px 0 0; padding-left: 22px; }
    li + li { margin-top: 5px; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; min-width: 670px; border-collapse: collapse; }
    th, td { padding: 10px 9px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; white-space: nowrap; }
    tbody tr:hover { background: #f5f8f5; }
    code { color: #34534d; font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
    .badge { display: inline-block; padding: 2px 7px; border: 1px solid var(--line); border-radius: 999px; background: #f4f6f4; color: var(--muted); font-size: 12px; line-height: 1.4; white-space: nowrap; }
    .badge.measured, .badge.confirmed, .badge.dirty { background: var(--green-soft); border-color: #b9dfcc; color: var(--green); }
    .badge.timeout, .badge.error, .badge.low { background: var(--red-soft); border-color: #efc4c4; color: var(--red); }
    .badge.unknown, .badge.review_only { background: var(--amber-soft); border-color: #efd38e; color: var(--amber); }
    .badge.strong_inference { background: var(--blue-soft); border-color: #c2d9e9; color: var(--blue); }
    .inline-stats { display: flex; flex-wrap: wrap; gap: 10px 22px; margin: 0 0 14px; color: var(--muted); }
    .inline-stats strong { color: var(--ink); font-size: 18px; }
    details summary { cursor: pointer; color: var(--ink); font-weight: 780; }
    details summary::marker { color: var(--green); }
    .empty { color: var(--muted); font-style: italic; }
    footer { margin-top: 22px; color: var(--muted); font-size: 12px; }
    @media (max-width: 860px) { .hero { grid-template-columns: 1fr; } .status-card { max-width: 440px; } .signals { grid-template-columns: 1fr; } .signal { border-right: 0; border-bottom: 1px solid var(--line); } .signal:last-child { border-bottom: 0; } .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 620px) { .masthead-inner, main { padding-left: 14px; padding-right: 14px; } .hero { margin-left: -14px; margin-right: -14px; padding: 34px 20px; } .report-nav { margin-left: -14px; margin-right: -14px; padding-left: 14px; padding-right: 14px; } .masthead-meta { display: none; } .section-head { display: block; } .section-note { margin-top: 6px; text-align: left; } .metrics { grid-template-columns: 1fr 1fr; } .panel { padding: 16px; } }
    @media print { body { background: #fff; } .masthead, .report-nav { display: none; } main { max-width: none; padding: 0; } .hero { margin: 0; } .panel, .metric, .notice, .signals { break-inside: avoid; } }
    """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Clean Your Data | Local Audit</title>
  <style>{styles}</style>
</head>
<body>
<div class="masthead">
  <div class="masthead-inner">
    <div class="brand"><span class="brand-mark">CYD</span><span>Clean Your Data</span></div>
    <div class="masthead-meta">METADATA ONLY &middot; OFFLINE REPORT</div>
  </div>
</div>

<main>
  <header class="hero">
    <div>
      <p class="eyebrow">LOCAL STORAGE / AUDIT BRIEF</p>
      <h1>Clean Your Data</h1>
      <p class="lede">A readable map of what is accumulating, who owns it, and what needs review before anything moves.</p>
      <div class="hero-meta">
        <span class="tag">READ-ONLY</span>
        <span class="tag">{("PATHS REDACTED" if settings.get("redact", True) else "PATHS NOT REDACTED")}</span>
        <span class="tag">SCHEMA {html_escape(report.get("schema_version", "unknown"))}</span>
      </div>
    </div>
    <div class="status-card">
      <span class="status-icon {html_token(decision_tone)}">{"!" if decision_status == "review_only" else "OK"}</span>
      <div>
        <div class="decision-label">Decision state</div>
        <div class="decision-value {html_token(decision_tone)}">{html_escape(decision_label)}</div>
        <div class="decision-copy"><strong>{html_escape(decision_heading)}</strong><br>{html_escape(decision_copy)}</div>
      </div>
    </div>
  </header>

  <nav class="report-nav" aria-label="Report sections">
    <a href="#decision">Decision</a>
    <a href="#signals">Signals</a>
    <a href="#coverage">Coverage</a>
    <a href="#targets">Largest areas</a>
    <a href="#codex">Codex</a>
    <a href="#git">Git</a>
    <a href="#artifacts">Artifacts</a>
    <a href="#ledger">Ledger</a>
  </nav>

  <div class="notice">Generated {html_escape(report.get("generated_at", "unknown"))} &middot; Scope {html_escape(settings.get("home", "~"))} &middot; No files were modified, moved, or deleted.</div>
  {warning_html}

  <section id="decision" class="panel callout">
    <div class="section-head">
      <div><p class="section-kicker">00 / DECISION</p><h2>What needs attention first</h2></div>
      <div class="section-note">The scanner reports evidence. It never turns evidence into permission to delete.</div>
    </div>
    {blocker_content}
  </section>

  <section id="signals" class="signals" aria-label="Audit signals">
    <div class="signal">
      <div class="signal-label">Evidence coverage</div>
      <div class="signal-value">{measured_targets} / {len(target_areas)}</div>
      <div class="signal-note">Target rows with a measured size</div>
      {html_meter("Measured", target_percentage, target_note, decision_tone)}
    </div>
    <div class="signal">
      <div class="signal-label">Disk allocation</div>
      <div class="signal-value">{html_escape(disk.get("used", "unknown"))}</div>
      <div class="signal-note">{html_escape(disk.get("free", "unknown"))} free of {html_escape(disk.get("total", "unknown"))}</div>
      {html_meter("Used", disk_used_percentage, "Filesystem allocation estimate", "blue")}
    </div>
    <div class="signal">
      <div class="signal-label">Artifact evidence</div>
      <div class="signal-value">{len(artifacts)}</div>
      <div class="signal-note">Rebuildable or review candidates; not additive totals</div>
      {html_meter("Measured", artifact_percentage, artifact_note, "green")}
    </div>
  </section>

  <section class="metrics" aria-label="Audit summary">
    {html_metric("Findings", len(findings), "evidence-linked review items")}
    {html_metric("Git repositories", git_value, f"{dirty_repo_count} dirty repositories")}
    {html_metric("Dirty changes", dirty_change_count, "preserve before migration")}
    {html_metric("Artifacts", len(artifacts), "candidate subsets")}
    {html_metric("Codex outputs", codex_value, codex_note)}
    {html_metric("Scope", settings.get("home", "~"), f"{target_note}; {html_escape(settings.get('mode', 'quick'))} mode")}
  </section>

  <section id="summary" class="panel">
    <div class="section-head">
      <div><p class="section-kicker">SUMMARY / PATTERNS</p><h2>What the evidence suggests</h2></div>
      <div class="section-note">Heuristics explain where to look. They do not authorize cleanup.</div>
    </div>
    <ul>{recommendation_items}</ul>
  </section>

  <section id="coverage" class="panel">
    <div class="section-head">
      <div><p class="section-kicker">01 / EVIDENCE</p><h2>Coverage</h2></div>
      <div class="section-note">Measured, timeout, error, and not-found states stay separate; unknown is never zero.</div>
    </div>
    {html_table(["Status", "Matches", "Unknown", "Measured", "Target"], coverage_rows)}
  </section>

  <section id="targets" class="panel">
    <div class="section-head">
      <div><p class="section-kicker">02 / WHERE</p><h2>Largest target areas</h2></div>
      <div class="section-note">Start here for review, not deletion. A large directory may still be user data.</div>
    </div>
    {html_table(["Size", "Status", "Category", "Risk", "Path", "Target"], target_rows)}
  </section>

  <section id="apps" class="panel">
    <details open>
      <summary>App-managed and cloud-sync data</summary>
      <p>Handle these through the owning app or sync provider. Do not bulk-delete their containers.</p>
      {app_content}
    </details>
  </section>

  <section id="codex" class="panel">
    <details open>
      <summary>Codex workspaces</summary>
      {codex_content}
    </details>
  </section>

  <section id="children" class="panel">
    <details>
      <summary>Workspace children</summary>
      <p>Immediate child directories above the configured size threshold. This remains metadata-only.</p>
      {children_html}
    </details>
  </section>

  <section id="git" class="panel">
    <details open>
      <summary>Git distribution</summary>
      <p>{html_escape(git_status_note)}</p>
      {html_table(["Repositories", "Dirty repos", "Dirty changes", "Bucket"], git_rows, "No Git buckets were reported.")}
    </details>
  </section>

  <section id="artifacts" class="panel">
    <details open>
      <summary>Rebuildable or review artifacts</summary>
      <p>Artifact rows can be subsets of parent workspace totals. Do not add them together as reclaimable space.</p>
      {html_table(["Size", "Status", "Risk", "Name", "Path", "In parent", "Rebuild hint"], artifact_rows, "No artifact candidates were reported.")}
    </details>
  </section>

  <section id="ledger" class="panel">
    <details>
      <summary>Decision ledger</summary>
      <p>Every finding links to evidence in the JSON report. This table is for review; the scanner does not execute the recommendation.</p>
      {html_table(["Status", "Confidence", "Category", "Owner", "Path", "Recommended review"], finding_rows, "No findings were reported.")}
    </details>
  </section>

  <footer>Clean Your Data &middot; schema {html_escape(report.get("schema_version", "unknown"))} &middot; Offline HTML; review exact paths before sharing.</footer>
</main>
</body>
</html>
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only local file organization audit.")
    parser.add_argument("--home", default=str(Path.home()), help="Home directory to analyze. Defaults to current user home.")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick", help="Quick scans known roots; full also scans artifacts.")
    parser.add_argument("--format", choices=["markdown", "json", "html"], default="markdown", help="Output format.")
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
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    start = time.time()
    report = build_report(args)
    report["duration_seconds"] = round(time.time() - start, 3)
    if args.format == "json":
        output = json.dumps(report, ensure_ascii=False, indent=2)
    elif args.format == "html":
        output = render_html(report)
    else:
        output = render_markdown(report)
    if args.output:
        Path(args.output).expanduser().write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
