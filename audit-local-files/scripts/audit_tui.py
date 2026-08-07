#!/usr/bin/env python3
"""Dependency-free terminal UI for exploring and safely reviewing a local audit."""

from __future__ import annotations

import curses
import json
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
import textwrap
import time
from pathlib import Path
from typing import Any, Callable, Optional


DEFAULT_QUESTION = "What is this area likely used for, and what should I check before changing it?"
INITIAL_TREE_LEVELS = 3
SPINNER_FRAMES = ("|", "/", "-", "\\")
PREVIEW_MAX_BYTES = 4096
PREVIEW_MAX_LINES = 14
CLEANUP_STATE_ENV = "CLEAN_YOUR_DATA_STATE_DIR"
CLEANUP_TRASH_ENV = "CLEAN_YOUR_DATA_TRASH_DIR"
CLEANUP_HISTORY_FILE = "cleanup-history.json"
WORKSPACE_STATE_FILE = "workspace-state.json"
LARGE_FILTER_BYTES = 100 * 1024 * 1024
RECENT_FILTER_SECONDS = 7 * 24 * 60 * 60
FILTER_OPTIONS = (
    ("all", "All visible areas"),
    ("folders", "Folders only"),
    ("files", "Files only"),
    ("large", "Large items (100 MB+)"),
    ("recent", "Changed in the last 7 days"),
    ("rebuildable", "Likely rebuildable"),
    ("bookmarked", "Bookmarked"),
    ("queued", "In cleanup basket"),
    ("tagged", "Tagged paths"),
)
SORT_OPTIONS = (
    ("tree", "Original tree order"),
    ("name", "Name A-Z"),
    ("size", "Largest first"),
    ("modified", "Newest first"),
    ("kind", "Folders first"),
)
RELATION_MAX_FILES = 2000
RELATION_MAX_SECONDS = 5
RELATION_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".next",
    "build",
    "dist",
    "target",
}

PALETTE: dict[str, int] = {}

DISPLAY_LABELS = {
    "measured": "Checked",
    "timeout": "Timed out",
    "error": "Could not check",
    "missing": "Not found",
    "not_found": "Not found",
    "unknown": "Needs review",
    "complete": "Complete",
    "disabled": "Not run",
    "partial": "Partial",
    "limit": "Stopped early",
    "exact": "Identical files",
    "dirty": "Uncommitted work",
    "strong_inference": "Likely",
    "confirmed": "Confirmed",
    "low": "Uncertain",
    "review_only": "Review first",
    "approval_required": "Needs approval",
    "queued": "In cleanup basket",
    "awaiting_agent": "Waiting for agent",
    "waiting": "Waiting for agent",
    "ready": "Ready to review",
    "unavailable": "Agent unavailable",
    "cancelled": "Advice cancelled",
    "not_requested": "Not requested",
    "blocked": "Blocked",
    "trashed": "In Trash",
    "restored": "Restored",
    "bookmark": "Bookmarked",
    "unbookmarked": "Bookmark removed",
    "workspace": "Work files",
    "inbox": "Inbox / Downloads",
    "app-state": "App data",
    "cloud-sync": "Cloud files",
    "cache": "Rebuildable",
    "deliverable": "Finished work",
    "duplicate": "Repeated files",
    "user-data": "Your files",
    "review": "Check first",
    "unknown scope": "Unknown area",
    "Codex date workspaces": "Codex dated folders",
    "Source roots": "Code folders",
    "Cloud sync": "Cloud folders",
    "AI and coding agents": "AI tools and agents",
    "Feishu/Lark": "Feishu / Lark",
}


def display_label(value: Any) -> str:
    raw = "" if value is None else str(value)
    return DISPLAY_LABELS.get(raw, raw.replace("_", " ").replace("-", " ").strip().capitalize())


def display_date(value: Any) -> str:
    if not value:
        return "Not available"
    return str(value).replace("T", " ").replace("+08:00", "").replace("Z", "")


def display_size(node: dict[str, Any]) -> str:
    return str(node.get("human_size") or "Not available")


def display_node_name(node: dict[str, Any]) -> str:
    name = str(node.get("name") or node.get("path") or "unnamed")
    return f"{name}/" if node.get("kind") == "folder" and not name.endswith("/") else name


def display_node_path(node: dict[str, Any]) -> str:
    path = str(node.get("path") or "Path unavailable")
    return f"{path}/" if node.get("kind") == "folder" and not path.endswith("/") else path


def sensitive_preview_path(path: Path) -> bool:
    name = path.name.lower()
    sensitive_names = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "credentials",
        "credentials.json",
        "secrets.json",
        "id_rsa",
        "id_ed25519",
        "known_hosts",
    }
    sensitive_suffixes = (".pem", ".key", ".p12", ".pfx", ".kdbx")
    return name in sensitive_names or name.endswith(sensitive_suffixes)


def read_file_preview(node: dict[str, Any]) -> list[str]:
    """Read a small, local text preview without making it part of AI context."""
    local_path = node.get("_local_path")
    if not local_path:
        return ["Preview unavailable for this path."]
    path = Path(str(local_path))
    if sensitive_preview_path(path):
        return ["Preview hidden because this filename may contain credentials or private configuration."]
    try:
        with path.open("rb") as handle:
            data = handle.read(PREVIEW_MAX_BYTES + 1)
    except OSError as exc:
        return [f"Preview unavailable: {exc}"]
    if b"\x00" in data[:PREVIEW_MAX_BYTES]:
        return ["Binary file; text preview is unavailable."]
    truncated = len(data) > PREVIEW_MAX_BYTES
    text = data[:PREVIEW_MAX_BYTES].decode("utf-8", errors="replace")
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        safe_line = "".join(char if char == "\t" or ord(char) >= 32 else "?" for char in line)
        lines.append(safe_line)
    if not lines:
        lines = ["(empty file)"]
    if len(lines) > PREVIEW_MAX_LINES:
        lines = lines[:PREVIEW_MAX_LINES]
        truncated = True
    if truncated:
        lines.append("... preview limited to the first 4 KB / 14 lines ...")
    return lines


def palette(name: str) -> int:
    return PALETTE.get(name, 0)


def key_matches(key: Any, *candidates: Any) -> bool:
    """Match both get_wch() characters and curses integer key codes."""
    for candidate in candidates:
        if key == candidate:
            return True
        if isinstance(key, str) and isinstance(candidate, int) and len(key) == 1 and ord(key) == candidate:
            return True
    return False


def local_node_path(node: dict[str, Any]) -> Optional[Path]:
    local_path = node.get("_local_path")
    if not local_path:
        return None
    return Path(str(local_path)).expanduser()


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def preliminary_cleanup_advice(node: dict[str, Any]) -> str:
    """Describe what the bounded scan suggests without treating it as permission."""
    category = str(node.get("category") or "unknown")
    kind = "folder" if node.get("kind") == "folder" else "file"
    if category == "cache":
        return f"Preliminary scan: this {kind} may be rebuildable. Confirm the owning project and rebuild cost first."
    if category == "workspace":
        return f"Preliminary scan: this {kind} may contain active work. Check project status and durable outputs before moving it."
    if category == "inbox":
        return f"Preliminary scan: this {kind} is in an inbox-like area. Confirm it is no longer needed before moving it."
    if category == "duplicate":
        return f"Preliminary scan: this {kind} may be one copy of repeated data. Choose the canonical copy before moving it."
    if category == "app-state":
        return "Preliminary scan: this looks app-managed. Use the owning app's storage controls instead of moving its container."
    if category == "cloud-sync":
        return "Preliminary scan: this looks synchronized. Check sync and retention state before touching it."
    if category == "deliverable":
        return "Preliminary scan: this looks like finished work. Keep it or move it intentionally; do not treat size as permission."
    return f"Preliminary scan: the purpose of this {kind} is not confirmed. Review more evidence before moving it."


def cleanup_gate(node: dict[str, Any]) -> tuple[bool, str]:
    """Apply deterministic local guardrails before any user-approved Trash move."""
    path = local_node_path(node)
    if path is None:
        return False, "the local path is unavailable in this TUI session"
    try:
        resolved = path.resolve()
    except OSError as exc:
        return False, f"the path could not be resolved ({exc})"
    if not resolved.exists():
        return False, "the path no longer exists"
    if resolved == Path("/") or resolved == Path.home().resolve():
        return False, "the filesystem root and home directory are protected"
    if resolved == (Path.home() / ".Trash").resolve() or path_is_within(resolved, Path.home() / ".Trash"):
        return False, "the system Trash is protected"
    if str(node.get("measurement_status") or "unknown") != "measured":
        return False, "the initial scan did not measure this path completely"
    category = str(node.get("category") or "unknown")
    if category in {"app-state", "cloud-sync", "unknown"}:
        return False, f"{display_label(category)} is owner-managed or not understood"
    return True, "exact path measured and eligible for explicit review"


def cleanup_review_path_available(node: dict[str, Any]) -> bool:
    """Allow a blocked node to receive advice without making it Trash-eligible."""
    path = local_node_path(node)
    if path is None:
        return False
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if not resolved.exists() or resolved in {Path("/"), Path.home().resolve()}:
        return False
    if resolved == (Path.home() / ".Trash").resolve() or path_is_within(resolved, Path.home() / ".Trash"):
        return False
    return True


def cleanup_prompt(node: dict[str, Any]) -> str:
    """Ask the local coding agent for advice, never for authorization or execution."""
    return "\n".join(
        [
            "Act as a cautious cleanup advisor for a local computer.",
            "This is preliminary, bounded scan evidence, not proof of purpose or permission to remove anything.",
            "Use only the metadata below. Do not read file contents, run cleanup commands, or move/delete files.",
            "Give a short plain-language recommendation with these headings:",
            "Recommendation, Evidence, Unknowns, Risks, Preconditions, Rollback.",
            "Choose among keep, review, archive, rebuildable candidate, use the owning app, or do not touch.",
            "Never call something safe to delete merely because it is large. The user must approve the exact path separately.",
            "",
            f"Path: {node.get('path', 'unknown')}",
            f"Name: {node.get('name', 'unknown')}",
            f"Kind: {'folder' if node.get('kind') == 'folder' else 'file'}",
            f"Size: {node.get('human_size') or 'unknown'}",
            f"Last changed: {display_date(node.get('modified_at'))}",
            f"Area: {node.get('area') or 'unknown'}",
            f"Category: {node.get('category') or 'unknown'}",
            f"Measurement: {node.get('measurement_status') or 'unknown'}",
            f"Visible child count: {node.get('child_count', 'unknown')}",
            "",
            "Remember: your answer is advice attached to a cleanup candidate. It is not an approval and must not trigger an action.",
        ]
    )


def cleanup_state_dir() -> Path:
    configured = os.environ.get(CLEANUP_STATE_ENV, "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".clean-your-data"


def cleanup_history_path() -> Path:
    return cleanup_state_dir() / CLEANUP_HISTORY_FILE


def load_cleanup_history(history_path: Optional[Path] = None) -> list[dict[str, Any]]:
    path = history_path or cleanup_history_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_cleanup_history(history: list[dict[str, Any]], history_path: Optional[Path] = None) -> None:
    path = history_path or cleanup_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def trash_directory() -> Path:
    configured = os.environ.get(CLEANUP_TRASH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    if sys.platform.startswith("linux"):
        return Path.home() / ".local" / "share" / "Trash" / "files"
    return Path.home() / ".Trash"


def unique_trash_destination(trash_root: Path, source: Path) -> Path:
    candidate = trash_root / source.name
    if not candidate.exists():
        return candidate
    stamp = time.strftime("%Y%m%d-%H%M%S")
    index = 1
    while True:
        candidate = trash_root / f"{source.name} (Clean Your Data {stamp}-{index})"
        if not candidate.exists():
            return candidate
        index += 1


def move_to_trash(
    path: Path,
    node: Optional[dict[str, Any]] = None,
    trash_root: Optional[Path] = None,
    history_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Move one exact path to the platform Trash and persist a local undo record."""
    source = path.expanduser()
    if not source.exists():
        raise FileNotFoundError(f"path no longer exists: {source}")
    resolved = source.resolve()
    if resolved == Path("/") or resolved == Path.home().resolve():
        raise ValueError("the filesystem root and home directory cannot be moved to Trash")
    root = (trash_root or trash_directory()).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if path_is_within(resolved, root):
        raise ValueError("a path already inside Trash cannot be moved again")
    destination = unique_trash_destination(root, source)
    shutil.move(str(source), str(destination))
    record = {
        "record_id": f"cleanup-{int(time.time() * 1000)}",
        "original_path": str(resolved),
        "trash_path": str(destination.resolve()),
        "name": source.name,
        "kind": (node or {}).get("kind") or ("folder" if destination.is_dir() else "file"),
        "size_bytes": (node or {}).get("allocated_bytes"),
        "human_size": (node or {}).get("human_size"),
        "category": (node or {}).get("category"),
        "moved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "trashed",
    }
    history = load_cleanup_history(history_path)
    history.append(record)
    try:
        save_cleanup_history(history, history_path)
    except OSError as exc:
        try:
            shutil.move(str(destination), str(source))
        except OSError as restore_exc:
            raise RuntimeError(f"moved to Trash but could not save undo record ({exc}); restore failed ({restore_exc})") from exc
        raise RuntimeError(f"could not save undo record; the move was rolled back ({exc})") from exc
    return record


def restore_trash_record(record: dict[str, Any], history_path: Optional[Path] = None) -> dict[str, Any]:
    """Restore one recorded Trash move without overwriting a new path."""
    destination = Path(str(record.get("trash_path") or ""))
    original = Path(str(record.get("original_path") or ""))
    if not destination.exists():
        raise FileNotFoundError("the Trash item is no longer available")
    if original.exists():
        raise FileExistsError(f"the original path already exists: {original}")
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(destination), str(original))
    record = dict(record)
    record["status"] = "restored"
    record["restored_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    history = load_cleanup_history(history_path)
    for index, item in enumerate(history):
        if item.get("record_id") == record.get("record_id"):
            history[index] = record
            break
    else:
        history.append(record)
    save_cleanup_history(history, history_path)
    return record


def workspace_state_path() -> Path:
    return cleanup_state_dir() / WORKSPACE_STATE_FILE


def load_workspace_state(state_path: Optional[Path] = None) -> dict[str, Any]:
    path = state_path or workspace_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    bookmarks = data.get("bookmarks")
    if not isinstance(bookmarks, list):
        bookmarks = []
    recent = data.get("recent")
    if not isinstance(recent, list):
        recent = []
    workspace = data.get("last_workspace")
    if not isinstance(workspace, dict):
        workspace = {}
    raw_tags = data.get("tags")
    tags: dict[str, list[str]] = {}
    if isinstance(raw_tags, dict):
        for path_text, values in raw_tags.items():
            if not isinstance(path_text, str) or not isinstance(values, list):
                continue
            clean_values = [str(value).strip()[:40] for value in values if str(value).strip()]
            if clean_values:
                tags[path_text] = list(dict.fromkeys(clean_values))[:12]
    return {"version": 1, "bookmarks": bookmarks, "recent": recent, "tags": tags, "last_workspace": workspace}


def save_workspace_state(state: dict[str, Any], state_path: Optional[Path] = None) -> None:
    path = state_path or workspace_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def action_target_path(node: dict[str, Any], action: str) -> Optional[Path]:
    path = local_node_path(node)
    if path is None:
        return None
    if action == "terminal" and path.is_file():
        return path.parent
    return path


def build_launch_command(node: dict[str, Any], action: str) -> list[str]:
    """Build a no-shell command for a selected path."""
    path = local_node_path(node)
    target = action_target_path(node, action)
    if path is None or target is None:
        raise ValueError("the selected path is unavailable in this TUI session")
    if not path.exists():
        raise FileNotFoundError(f"the selected path no longer exists: {path}")
    target_text = str(target.resolve())
    if action == "terminal":
        if sys.platform == "darwin":
            return ["open", "-a", "Terminal", target_text]
        if shutil.which("x-terminal-emulator"):
            return ["x-terminal-emulator", "--working-directory", target_text]
        if shutil.which("gnome-terminal"):
            return ["gnome-terminal", "--working-directory", target_text]
        return [
            "xterm",
            "-e",
            "sh",
            "-c",
            'cd -- "$1" && exec "${SHELL:-sh}"',
            "clean-your-data-terminal",
            target_text,
        ]
    if action == "vscode":
        if shutil.which("code"):
            return ["code", "--reuse-window", target_text]
        if sys.platform == "darwin":
            return ["open", "-a", "Visual Studio Code", target_text]
        return ["code", target_text]
    if action == "cursor":
        if shutil.which("cursor"):
            return ["cursor", target_text]
        if sys.platform == "darwin":
            return ["open", "-a", "Cursor", target_text]
        return ["cursor", target_text]
    if action == "finder":
        if sys.platform == "darwin":
            return ["open", "-R", str(path.resolve())] if path.is_file() else ["open", target_text]
        return ["xdg-open", target_text]
    raise ValueError(f"unknown path action: {action}")


def launch_path_action(node: dict[str, Any], action: str) -> str:
    try:
        command = build_launch_command(node, action)
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError) as exc:
        return f"Could not open {display_node_name(node)}: {exc}"
    labels = {"terminal": "Terminal", "vscode": "VS Code", "cursor": "Cursor", "finder": "Finder"}
    return f"Opened {labels.get(action, action)} for {display_node_path(node)}"


def human_relation_size(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def relation_file_bucket(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name in {"readme", "readme.md", "changelog.md", "license", "copying"} or suffix in {".md", ".rst", ".txt", ".pdf", ".docx", ".pptx", ".xlsx"}:
        return "documentation"
    if any(token in name for token in ("test", "spec")) or "/test/" in str(path).lower():
        return "tests"
    if suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".rb", ".php", ".css", ".html", ".vue", ".sql"}:
        return "source"
    if suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".cfg", ".conf"}:
        return "configuration"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".wav", ".mp3"}:
        return "media"
    return "other"


def analyze_path_relationships(
    node: dict[str, Any],
    max_files: int = RELATION_MAX_FILES,
    time_budget: int = RELATION_MAX_SECONDS,
) -> dict[str, Any]:
    """Build a bounded, metadata-only relationship summary for one selected path."""
    path = local_node_path(node)
    if path is None:
        return {"status": "error", "root": node.get("path", "unknown"), "error": "local path unavailable"}
    if not path.exists():
        return {"status": "error", "root": node.get("path", "unknown"), "error": "path no longer exists"}
    root = path if path.is_dir() else path.parent
    started = time.monotonic()
    counts = {"source": 0, "tests": 0, "documentation": 0, "configuration": 0, "media": 0, "other": 0}
    special_dirs: dict[str, list[str]] = {}
    project_markers: list[str] = []
    same_name_size: dict[tuple[str, int], list[str]] = {}
    largest: list[tuple[int, str]] = []
    files_scanned = 0
    directories_seen = 0
    bytes_scanned = 0
    status = "complete"
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories_seen += 1
        dirs[:] = [name for name in dirs if not (current_path / name).is_symlink()]
        for directory in list(dirs):
            lower = directory.lower()
            if lower in RELATION_SKIP_DIRS or lower in {"output", "outputs", "reports", "artifacts", "coverage", "logs", "vendor"}:
                special_dirs.setdefault(lower, []).append(str((current_path / directory).relative_to(root)))
            if lower == ".git" or lower in {".hg", ".svn"}:
                project_markers.append(str((current_path / directory).relative_to(root)))
        dirs[:] = [name for name in dirs if name.lower() not in RELATION_SKIP_DIRS]
        for filename in files:
            if files_scanned >= max_files or time.monotonic() - started >= time_budget:
                status = "partial"
                break
            file_path = current_path / filename
            try:
                stat_result = file_path.stat()
            except OSError:
                continue
            if not file_path.is_file():
                continue
            relative = str(file_path.relative_to(root))
            size = int(stat_result.st_size)
            bucket = relation_file_bucket(file_path)
            counts[bucket] += 1
            bytes_scanned += size
            files_scanned += 1
            largest.append((size, relative))
            same_name_size.setdefault((filename.lower(), size), []).append(relative)
            if filename.lower() in {"package.json", "pyproject.toml", "cargo.toml", "go.mod", "requirements.txt", "pom.xml", "gemfile", "composer.json"}:
                project_markers.append(relative)
        if status == "partial":
            break
    largest.sort(reverse=True)
    relations: list[dict[str, Any]] = []
    marker_names = sorted(set(project_markers))
    if marker_names:
        relations.append({"kind": "project", "title": "Project structure", "detail": f"Found project markers: {', '.join(marker_names[:5])}."})
    build_dirs = [name for name in ("build", "dist", "target", ".next", "out") if name in special_dirs]
    dependency_dirs = [name for name in ("node_modules", ".venv", "venv", "vendor") if name in special_dirs]
    output_dirs = [name for name in ("output", "outputs", "reports", "artifacts", "coverage") if name in special_dirs]
    if counts["source"] and build_dirs:
        relations.append({"kind": "generated", "title": "Source -> build output", "detail": f"{counts['source']} source files sit alongside {', '.join(build_dirs)}; those directories may be generated from project code."})
    if counts["source"] and dependency_dirs:
        relations.append({"kind": "dependency", "title": "Source -> dependencies", "detail": f"Source files are associated with {', '.join(dependency_dirs)}; check the project's package or environment configuration before moving them."})
    if output_dirs:
        relations.append({"kind": "deliverable", "title": "Possible outputs", "detail": f"Found {', '.join(output_dirs)}; inspect whether they contain final deliverables or temporary exports."})
    duplicate_candidates = [paths for paths in same_name_size.values() if len(paths) > 1]
    if duplicate_candidates:
        relations.append({"kind": "similar", "title": "Possible repeated files", "detail": f"Found {len(duplicate_candidates)} same-name, same-size groups. These are candidates for comparison, not confirmed duplicates."})
    if not relations:
        relations.append({"kind": "unknown", "title": "No strong relationship found", "detail": "The bounded metadata scan did not find enough structure to explain how these files relate."})
    return {
        "status": status,
        "root": node.get("path", "unknown"),
        "kind": node.get("kind"),
        "files_scanned": files_scanned,
        "directories_seen": directories_seen,
        "bytes_scanned": bytes_scanned,
        "counts": counts,
        "special_dirs": {key: value[:8] for key, value in special_dirs.items()},
        "relations": relations,
        "duplicate_candidates": [paths[:5] for paths in duplicate_candidates[:8]],
        "largest": [{"path": relative, "size": human_relation_size(size)} for size, relative in largest[:8]],
        "limits": {"max_files": max_files, "time_budget": time_budget},
    }


def resolve_ai_command() -> tuple[Optional[list[str]], str]:
    """Prefer an explicit command, otherwise use a read-only ephemeral Codex CLI."""
    configured = os.environ.get("CLEAN_YOUR_DATA_AI_COMMAND", "").strip()
    if configured:
        try:
            command = shlex.split(configured)
        except ValueError:
            return None, "Configured local AI command is invalid."
        return (command or None), "Configured local AI"
    codex = shutil.which("codex")
    if codex:
        return (
            [
                codex,
                "exec",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color",
                "never",
                "-C",
                "/tmp",
                "-",
            ],
            "Codex",
        )
    return None, "No local AI command"


def build_prompt(node: dict[str, Any], question: str = DEFAULT_QUESTION) -> str:
    """Build the exact metadata-only context used by the optional AI command."""
    return "\n".join(
        [
            "Please help me understand this area of my local computer using only the metadata below.",
            "Do not ask me to upload or open file contents unless I explicitly approve it.",
            "",
            f"Path: {node.get('path', 'unknown')}",
            f"Name: {node.get('name', 'unknown')}",
            f"Kind: {'folder' if node.get('kind') == 'folder' else 'file'}",
            f"Size: {node.get('human_size') or 'unknown'}",
            f"Last changed: {display_date(node.get('modified_at'))}",
            f"Area: {node.get('area') or 'unknown'}",
            f"Measurement: {node.get('measurement_status') or 'unknown'}",
            "",
            f"My question: {question.strip() or DEFAULT_QUESTION}",
            "",
            "Please answer in the same language as my question and use plain language: what this area is likely used for, what evidence supports that, what remains unknown, and the safest next check. Do not recommend deleting anything merely because it is large.",
        ]
    )


def children_by_parent(nodes: list[dict[str, Any]]) -> dict[Optional[str], list[dict[str, Any]]]:
    result: dict[Optional[str], list[dict[str, Any]]] = {}
    for node in nodes:
        result.setdefault(node.get("parent_id"), []).append(node)
    return result


def node_search_text(node: dict[str, Any], tags: Optional[list[str]] = None) -> str:
    """Build the small, local search index for one node."""
    values = (
        node.get("name"),
        node.get("path"),
        node.get("area"),
        node.get("category"),
        node.get("kind"),
        " ".join(tags or []),
    )
    return " ".join(str(value) for value in values if value is not None).casefold()


def fuzzy_match(query: str, text: str) -> bool:
    """Match each query word as an in-order subsequence of the indexed text."""
    def subsequence(needle: str, haystack: str) -> bool:
        position = 0
        for character in needle:
            position = haystack.find(character, position)
            if position < 0:
                return False
            position += 1
        return True

    return all(subsequence(token, text) for token in query.casefold().split())


def node_sort_key(node: dict[str, Any], sort_mode: str) -> tuple[Any, ...]:
    name = str(node.get("name") or node.get("path") or "").casefold()
    if sort_mode == "size":
        return (-int(node.get("allocated_bytes") or 0), name)
    if sort_mode == "modified":
        local_path = local_node_path(node)
        modified = 0.0
        if local_path is not None:
            try:
                modified = local_path.stat().st_mtime
            except OSError:
                pass
        return (-modified, name)
    if sort_mode == "kind":
        return (0 if node.get("kind") == "folder" else 1, name)
    return (name,)


def visible_nodes(
    nodes: list[dict[str, Any]],
    expanded: set[str],
    query: str = "",
    predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
    sort_mode: str = "tree",
    tag_lookup: Optional[Callable[[dict[str, Any]], list[str]]] = None,
) -> list[dict[str, Any]]:
    """Return the display tree with optional fuzzy search, filtering, and sibling sorting."""
    by_parent = children_by_parent(nodes)
    visible: list[dict[str, Any]] = []
    active_view = bool(query.strip()) or predicate is not None
    included_ids: set[str] = set()
    by_id = {str(node.get("node_id")): node for node in nodes}

    if active_view:
        for node in nodes:
            tags = tag_lookup(node) if tag_lookup else None
            matches_query = not query.strip() or fuzzy_match(query, node_search_text(node, tags))
            matches_filter = predicate is None or predicate(node)
            if not (matches_query and matches_filter):
                continue
            current: Optional[dict[str, Any]] = node
            while current is not None:
                current_id = str(current.get("node_id"))
                if current_id in included_ids:
                    break
                included_ids.add(current_id)
                parent_id = current.get("parent_id")
                current = by_id.get(str(parent_id)) if parent_id is not None else None

    def visit(parent_id: Optional[str]) -> None:
        children = by_parent.get(parent_id, [])
        if active_view:
            children = [node for node in children if str(node.get("node_id")) in included_ids]
        if sort_mode != "tree":
            children = sorted(children, key=lambda node: node_sort_key(node, sort_mode))
        for node in children:
            visible.append(node)
            node_id = str(node.get("node_id"))
            has_included_child = any(
                str(child.get("node_id")) in included_ids
                for child in by_parent.get(node.get("node_id"), [])
            )
            if node.get("kind") == "folder" and (
                node_id in expanded or (active_view and has_included_child)
            ):
                visit(node_id)

    visit(None)
    return visible


def initial_expanded_nodes(nodes: list[dict[str, Any]]) -> set[str]:
    loaded_children = children_by_parent(nodes)
    return {
        str(node.get("node_id"))
        for node in nodes
        if node.get("kind") == "folder"
        and node.get("can_expand")
        and loaded_children.get(node.get("node_id"))
        and int(node.get("depth") or 0) < INITIAL_TREE_LEVELS - 1
    }


def wrap_lines(value: Any, width: int) -> list[str]:
    text = "" if value is None else str(value)
    if width <= 1:
        return [""]
    lines: list[str] = []
    for source in text.splitlines() or [""]:
        lines.extend(textwrap.wrap(source, width=width, break_long_words=True, break_on_hyphens=False) or [""])
    return lines


def copy_to_clipboard(value: str) -> str:
    """Use an installed native clipboard command without adding a dependency."""
    candidates = []
    if shutil.which("pbcopy"):
        candidates.append(["pbcopy"])
    if shutil.which("wl-copy"):
        candidates.append(["wl-copy"])
    if shutil.which("xclip"):
        candidates.append(["xclip", "-selection", "clipboard"])
    if not candidates:
        return "No clipboard command found. Press A to ask Codex or copy the context manually."
    for command in candidates:
        try:
            result = subprocess.run(
                command,
                input=value,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return "Metadata-only AI context copied to the clipboard."
    return "Clipboard access failed. Press A to ask Codex or copy the context manually."


def ask_local_ai(prompt: str, cancel_event: Optional[threading.Event] = None) -> tuple[Optional[str], str]:
    """Call the configured local AI, or a read-only ephemeral Codex CLI when available."""
    command, provider = resolve_ai_command()
    if not command:
        return None, f"{provider} Press C to copy the metadata-only context."
    process: Optional[subprocess.Popen[str]] = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started = time.monotonic()
        sent_input = False
        while True:
            if cancel_event and cancel_event.is_set():
                process.kill()
                process.communicate()
                return None, f"{provider} request cancelled."
            if time.monotonic() - started >= 60:
                process.kill()
                process.communicate()
                return None, f"{provider} timed out. Press C to copy the context."
            try:
                stdout, stderr = process.communicate(input=prompt if not sent_input else None, timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                sent_input = True
                continue
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return None, f"{provider} did not answer: {exc}. Press C to copy the context."
    if process.returncode != 0:
        detail = stderr.strip() or f"exit code {process.returncode}"
        return None, f"{provider} failed: {detail}. Press C to copy the context."
    answer = stdout.strip()
    if not answer:
        return None, f"{provider} returned no answer. Press C to copy the context."
    return answer, f"{provider} answer ready. Press A to ask a follow-up."


class TuiState:
    def __init__(
        self,
        report: dict[str, Any],
        expand_callback: Optional[Callable[[dict[str, Any]], tuple[list[dict[str, Any]], str]]] = None,
        rescan_callback: Optional[Callable[[Optional[Path]], dict[str, Any]]] = None,
        cleanup_history_file: Optional[Path] = None,
        cleanup_trash_root: Optional[Path] = None,
        workspace_file: Optional[Path] = None,
    ):
        self.report = report
        self.space_map = report.get("space_map") or {}
        self.nodes = list(self.space_map.get("nodes") or [])
        self.expand_callback = expand_callback
        self.rescan_callback = rescan_callback
        # Show the root plus two child levels first. Enter reveals one more level;
        # pressing Enter again on that folder collapses it.
        self.expanded = initial_expanded_nodes(self.nodes)
        self.selected_id = self.nodes[0].get("node_id") if self.nodes else None
        self.scroll = 0
        self.search_query = ""
        self.search_editing = False
        self.search_buffer = ""
        self.filter_mode = "all"
        self.filter_open = False
        self.filter_index = 0
        self.sort_mode = "tree"
        self.sort_open = False
        self.sort_index = 0
        self.tag_editing = False
        self.tag_buffer = ""
        self.tag_node_id: Optional[str] = None
        initial_path = next((local_node_path(node) for node in self.nodes if node.get("parent_id") is None and local_node_path(node)), None)
        self.tabs: list[dict[str, Any]] = [
            {
                "name": display_saved_path(initial_path) if initial_path else "current",
                "path": str(initial_path.resolve()) if initial_path else None,
                "report": report,
                "selected_path": None,
                "search_query": "",
                "filter_mode": "all",
                "sort_mode": "tree",
            }
        ]
        self.tab_index = 0
        self.message = "Select an area. The scan is read-only and metadata-only; press dd to stage an exact path for cleanup review."
        self.question = DEFAULT_QUESTION
        self.prompt = ""
        self.answer = ""
        self.question_editing = False
        self.question_buffer = ""
        self.questions_by_node: dict[str, str] = {}
        self.prompts_by_node: dict[str, str] = {}
        self.answers_by_node: dict[str, str] = {}
        self.ai_messages_by_node: dict[str, str] = {}
        self.preview_cache: dict[str, list[str]] = {}
        self.ai_results: queue.Queue[tuple[int, str, Optional[str], str, str]] = queue.Queue()
        self.ai_busy = False
        self.ai_busy_node_id: Optional[str] = None
        self.ai_spinner_index = 0
        self.ai_request_id = 0
        self.ai_current_request_id: Optional[int] = None
        self.ai_cancel_event: Optional[threading.Event] = None
        self.ai_cancelled_requests: set[int] = set()
        self.ai_kind_by_request: dict[int, str] = {}
        self.cleanup_queue: dict[str, dict[str, Any]] = {}
        self.cleanup_advice_by_node: dict[str, str] = {}
        self.cleanup_advice_status_by_node: dict[str, str] = {}
        self.cleanup_advice_message_by_node: dict[str, str] = {}
        self.cleanup_history_file = cleanup_history_file or cleanup_history_path()
        self.cleanup_trash_root = cleanup_trash_root
        self.cleanup_history = load_cleanup_history(self.cleanup_history_file)
        self.removed_nodes_by_record: dict[str, list[dict[str, Any]]] = {}
        self.workspace_file = workspace_file or workspace_state_path()
        self.workspace_state = load_workspace_state(self.workspace_file)
        saved_selected = (self.workspace_state.get("last_workspace") or {}).get("selected_path")
        if saved_selected:
            saved_text = str(Path(str(saved_selected)).expanduser().resolve())
            saved_node = next((node for node in self.nodes if str(node.get("_local_path")) == saved_text), None)
            if saved_node:
                self.selected_id = saved_node.get("node_id")
        self.bookmark_open = False
        self.bookmark_index = 0
        self.deep_analysis_by_node: dict[str, dict[str, Any]] = {}
        self.deep_analysis_results: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self.deep_analysis_busy = False
        self.deep_analysis_busy_node_id: Optional[str] = None
        self.deep_analysis_spinner_index = 0
        self.deep_analysis_open = False
        self.deep_analysis_scroll = 0
        self.help_open = False
        self.vim_pending_g = False
        self.vim_pending_d = False
        self.trash_confirmation = False
        self.trash_confirmation_node_id: Optional[str] = None

    def visible(self) -> list[dict[str, Any]]:
        return visible_nodes(
            self.nodes,
            self.expanded,
            query=self.search_query,
            predicate=self.filter_predicate(),
            sort_mode=self.sort_mode,
            tag_lookup=self.node_tags,
        )

    def node_tags(self, node: dict[str, Any]) -> list[str]:
        path = local_node_path(node)
        if path is not None:
            key = str(path.expanduser().resolve())
        else:
            key = f"node:{node.get('node_id')}"
        values = (self.workspace_state.get("tags") or {}).get(key, [])
        return [str(value) for value in values if str(value).strip()]

    def filter_label(self) -> str:
        return next((label for key, label in FILTER_OPTIONS if key == self.filter_mode), self.filter_mode)

    def sort_label(self) -> str:
        return next((label for key, label in SORT_OPTIONS if key == self.sort_mode), self.sort_mode)

    def filter_predicate(self) -> Optional[Callable[[dict[str, Any]], bool]]:
        mode = self.filter_mode
        if mode == "all":
            return None

        def predicate(node: dict[str, Any]) -> bool:
            if mode == "folders":
                return node.get("kind") == "folder"
            if mode == "files":
                return node.get("kind") == "file"
            if mode == "large":
                return int(node.get("allocated_bytes") or 0) >= LARGE_FILTER_BYTES
            if mode == "recent":
                local_path = local_node_path(node)
                if local_path is None:
                    return False
                try:
                    return time.time() - local_path.stat().st_mtime <= RECENT_FILTER_SECONDS
                except OSError:
                    return False
            if mode == "rebuildable":
                rebuildable_names = {"node_modules", ".venv", "venv", "build", "dist", ".next", "target", "__pycache__"}
                return node.get("category") == "cache" or str(node.get("name") or "") in rebuildable_names
            if mode == "bookmarked":
                return self.is_bookmarked(node)
            if mode == "queued":
                return self.cleanup_item(str(node.get("node_id"))) is not None
            if mode == "tagged":
                return bool(self.node_tags(node))
            return True

        return predicate

    def _reset_selection_for_view(self) -> None:
        visible = self.visible()
        if not visible:
            self.selected_id = None
            self.sync_selection_context()
            self.scroll = 0
            return
        if not any(str(node.get("node_id")) == str(self.selected_id) for node in visible):
            self.selected_id = visible[0].get("node_id")
            self.sync_selection_context()
        self.scroll = 0

    def tab_status(self) -> str:
        tab = self.tabs[self.tab_index] if self.tabs else {"name": "current"}
        name = str(tab.get("name") or "current").rstrip("/")
        short_name = name.rsplit("/", 1)[-1] or "root"
        return f"{self.tab_index + 1}/{len(self.tabs)} {short_name}"

    def _current_root_path(self) -> Optional[Path]:
        return next((local_node_path(node) for node in self.nodes if node.get("parent_id") is None and local_node_path(node)), None)

    def _snapshot_tab(self) -> None:
        if not self.tabs:
            return
        root_path = self._current_root_path()
        selected_path = self.selected_local_path()
        self.tabs[self.tab_index].update(
            {
                "name": display_saved_path(root_path or selected_path) if (root_path or selected_path) else "current",
                "path": str((root_path or selected_path).resolve()) if (root_path or selected_path) else None,
                "report": self.report,
                "selected_path": str(selected_path.resolve()) if selected_path else None,
                "search_query": self.search_query,
                "filter_mode": self.filter_mode,
                "sort_mode": self.sort_mode,
            }
        )

    def _restore_tab(self, index: int) -> None:
        if not self.tabs:
            return
        tab = self.tabs[index]
        self.tab_index = index
        preferred = Path(str(tab["selected_path"])).expanduser() if tab.get("selected_path") else None
        self._apply_report(tab.get("report") or {"space_map": {"nodes": []}}, preferred)
        self.search_query = str(tab.get("search_query") or "")
        self.filter_mode = str(tab.get("filter_mode") or "all")
        self.sort_mode = str(tab.get("sort_mode") or "tree")
        self.filter_index = next((i for i, (key, _) in enumerate(FILTER_OPTIONS) if key == self.filter_mode), 0)
        self.sort_index = next((i for i, (key, _) in enumerate(SORT_OPTIONS) if key == self.sort_mode), 0)
        self._reset_selection_for_view()

    def open_new_tab(self) -> None:
        selected = self.selected_local_path()
        if selected is None:
            self.message = "Select a local path before opening a new tab."
            return
        target = selected if selected.is_dir() else selected.parent
        try:
            report = self.rescan_callback(target) if self.rescan_callback else self.report
        except Exception as exc:
            self.message = f"Could not open a new tab: {exc}"
            return
        self._snapshot_tab()
        self.tabs.append(
            {
                "name": display_saved_path(target),
                "path": str(target.resolve()),
                "report": report,
                "selected_path": str(selected.resolve()),
                "search_query": "",
                "filter_mode": "all",
                "sort_mode": "tree",
            }
        )
        self._restore_tab(len(self.tabs) - 1)
        self.message = f"Opened tab {display_saved_path(target)}. Use gt/gT to switch tabs."

    def switch_tab(self, delta: int) -> None:
        if len(self.tabs) < 2:
            self.message = "There is only one tab. Press N on a selected folder to open another."
            return
        self._snapshot_tab()
        self._restore_tab((self.tab_index + delta) % len(self.tabs))
        self.message = f"Switched to tab {self.tab_status()}."

    def close_tab(self) -> None:
        if len(self.tabs) < 2:
            self.message = "The last tab stays open. Press q to quit the explorer."
            return
        self._snapshot_tab()
        closed = self.tabs.pop(self.tab_index)
        self.tab_index = min(self.tab_index, len(self.tabs) - 1)
        self._restore_tab(self.tab_index)
        self.message = f"Closed tab {closed.get('name', 'current')}."

    def begin_search(self) -> None:
        self.search_editing = True
        self.search_buffer = self.search_query
        self.message = "Type a fuzzy search. Enter applies it; Esc cancels; Ctrl-U clears."
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def apply_search(self) -> None:
        self.search_query = self.search_buffer.strip()
        self.search_buffer = ""
        self.search_editing = False
        self._reset_selection_for_view()
        self.message = f"Search: {self.search_query or 'cleared'}"
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def cancel_search(self) -> None:
        self.search_editing = False
        self.search_buffer = ""
        self.message = "Search cancelled."
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def choose_filter(self, index: int) -> None:
        index = max(0, min(index, len(FILTER_OPTIONS) - 1))
        self.filter_index = index
        self.filter_mode = FILTER_OPTIONS[index][0]
        self.filter_open = False
        self._reset_selection_for_view()
        self.message = f"Filter: {self.filter_label()}"

    def begin_filter(self) -> None:
        self.filter_index = next((index for index, (key, _) in enumerate(FILTER_OPTIONS) if key == self.filter_mode), 0)
        self.filter_open = True
        self.message = "Choose a filter. j/k move, Enter applies, Esc closes."

    def choose_sort(self, index: int) -> None:
        index = max(0, min(index, len(SORT_OPTIONS) - 1))
        self.sort_index = index
        self.sort_mode = SORT_OPTIONS[index][0]
        self.sort_open = False
        self._reset_selection_for_view()
        self.message = f"Sort: {self.sort_label()}"

    def begin_sort(self) -> None:
        self.sort_index = next((index for index, (key, _) in enumerate(SORT_OPTIONS) if key == self.sort_mode), 0)
        self.sort_open = True
        self.message = "Choose a sort order. j/k move, Enter applies, Esc closes."

    def begin_tag_edit(self) -> None:
        node = self.selected()
        if not node or local_node_path(node) is None:
            self.message = "Tags need a local path in this session."
            return
        self.tag_node_id = str(node.get("node_id"))
        self.tag_buffer = ", ".join(self.node_tags(node))
        self.tag_editing = True
        self.message = "Edit comma-separated tags. Enter saves; Esc cancels."
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def save_tags(self) -> None:
        node = self.node_by_id(self.tag_node_id)
        if not node:
            self.tag_editing = False
            self.tag_buffer = ""
            self.tag_node_id = None
            return
        path = local_node_path(node)
        if path is None:
            self.message = "The selected path is unavailable; tags were not saved."
            return
        tags = list(dict.fromkeys(value.strip()[:40] for value in self.tag_buffer.split(",") if value.strip()))[:12]
        tag_map = self.workspace_state.setdefault("tags", {})
        key = str(path.expanduser().resolve())
        if tags:
            tag_map[key] = tags
        else:
            tag_map.pop(key, None)
        try:
            save_workspace_state(self.workspace_state, self.workspace_file)
            self.message = f"Saved {len(tags)} tag(s) for {display_node_name(node)}."
        except OSError as exc:
            self.message = f"Tags changed in memory, but could not be saved locally: {exc}"
        self.tag_editing = False
        self.tag_buffer = ""
        self.tag_node_id = None
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def selected(self) -> Optional[dict[str, Any]]:
        for node in self.visible():
            if node.get("node_id") == self.selected_id:
                return node
        visible = self.visible()
        return visible[0] if visible else None

    def node_by_id(self, node_id: Optional[str]) -> Optional[dict[str, Any]]:
        if node_id is None:
            return None
        return next((node for node in self.nodes if str(node.get("node_id")) == str(node_id)), None)

    def sync_selection_context(self) -> None:
        node_id = str(self.selected_id) if self.selected_id is not None else ""
        self.question = self.questions_by_node.get(node_id, DEFAULT_QUESTION)
        self.prompt = self.prompts_by_node.get(node_id, "")
        self.answer = self.answers_by_node.get(node_id, "")

    def preview_for(self, node: dict[str, Any]) -> list[str]:
        if node.get("kind") != "file":
            return []
        node_id = str(node.get("node_id"))
        if node_id not in self.preview_cache:
            self.preview_cache[node_id] = read_file_preview(node)
        return self.preview_cache[node_id]

    def select_index(self, index: int) -> None:
        visible = self.visible()
        if not visible:
            self.selected_id = None
            return
        index = max(0, min(index, len(visible) - 1))
        self.selected_id = visible[index].get("node_id")
        self.sync_selection_context()
        selected_node = self.selected()
        if self.ai_busy:
            self.message = "You can keep moving. Codex is thinking " + SPINNER_FRAMES[self.ai_spinner_index] + "."
        elif selected_node and self.ai_messages_by_node.get(str(selected_node.get("node_id"))):
            self.message = self.ai_messages_by_node[str(selected_node.get("node_id"))]
        else:
            self.message = "Selected area changed. Press A to ask Codex about it."

    def load_children(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        node_id = str(node.get("node_id"))
        existing = children_by_parent(self.nodes).get(node.get("node_id"), [])
        if existing:
            return existing
        if not node.get("can_expand") or self.expand_callback is None:
            return []
        try:
            new_nodes, status = self.expand_callback(node)
        except Exception as exc:
            self.message = f"Could not open this folder: {exc}"
            return []
        if new_nodes:
            self.nodes.extend(new_nodes)
            self.message = f"Loaded {len(new_nodes)} entries from {display_node_name(node)}"
        elif status in {"partial", "limit"}:
            self.message = f"This folder could not be fully opened ({display_label(status)})."
        else:
            self.message = "This folder has no readable entries."
        return children_by_parent(self.nodes).get(node.get("node_id"), [])

    def open_or_close(self, node: dict[str, Any]) -> None:
        if node.get("kind") != "folder":
            return
        node_id = str(node.get("node_id"))
        children = children_by_parent(self.nodes).get(node.get("node_id"), [])
        if not children:
            children = self.load_children(node)
        if not children:
            return
        if node_id in self.expanded:
            self.expanded.remove(node_id)
            self.message = f"Closed {display_node_name(node)}"
        else:
            self.expanded.add(node_id)
            self.message = f"Opened {display_node_name(node)}"

    def start_ai(self, node: dict[str, Any], prompt: str, kind: str = "question") -> bool:
        if self.ai_busy:
            self.message = "Codex is already thinking. You can still move through the tree."
            return False
        node_id = str(node.get("node_id"))
        if kind == "question":
            self.prompts_by_node[node_id] = prompt
            self.questions_by_node[node_id] = self.question
        self.ai_busy = True
        self.ai_busy_node_id = node_id
        self.ai_spinner_index = 0
        self.ai_request_id += 1
        request_id = self.ai_request_id
        self.ai_current_request_id = request_id
        self.ai_kind_by_request[request_id] = kind
        cancel_event = threading.Event()
        self.ai_cancel_event = cancel_event
        if kind == "question":
            self.ai_messages_by_node[node_id] = "Codex is thinking..."

        def worker() -> None:
            answer, message = ask_local_ai(prompt, cancel_event)
            self.ai_results.put((request_id, node_id, answer, message, kind))

        threading.Thread(target=worker, name="clean-your-data-codex", daemon=True).start()
        self.message = "Codex is thinking " + SPINNER_FRAMES[self.ai_spinner_index] + ". You can keep moving."
        return True

    def cancel_ai(self) -> None:
        if not self.ai_busy or self.ai_current_request_id is None:
            return
        request_id = self.ai_current_request_id
        self.ai_cancelled_requests.add(request_id)
        kind = self.ai_kind_by_request.get(request_id, "question")
        busy_node_id = self.ai_busy_node_id
        if self.ai_cancel_event:
            self.ai_cancel_event.set()
        self.ai_busy = False
        self.ai_busy_node_id = None
        self.ai_current_request_id = None
        self.ai_cancel_event = None
        if kind == "cleanup" and busy_node_id:
            self.cleanup_advice_status_by_node[busy_node_id] = "cancelled"
            self.cleanup_advice_message_by_node[busy_node_id] = "The cleanup advice request was cancelled."
        self.message = "Codex request cancelled. You can keep browsing."

    def poll_ai(self) -> None:
        if self.ai_busy:
            self.ai_spinner_index = (self.ai_spinner_index + 1) % len(SPINNER_FRAMES)
        try:
            request_id, node_id, answer, message, kind = self.ai_results.get_nowait()
        except queue.Empty:
            return
        if request_id in self.ai_cancelled_requests:
            self.ai_cancelled_requests.remove(request_id)
            self.ai_kind_by_request.pop(request_id, None)
            return
        if request_id != self.ai_current_request_id:
            self.ai_kind_by_request.pop(request_id, None)
            return
        self.ai_busy = False
        self.ai_busy_node_id = None
        self.ai_current_request_id = None
        self.ai_cancel_event = None
        self.ai_kind_by_request.pop(request_id, None)
        if kind == "cleanup":
            if answer:
                self.cleanup_advice_by_node[node_id] = answer
                self.cleanup_advice_status_by_node[node_id] = "ready"
            else:
                self.cleanup_advice_status_by_node[node_id] = "unavailable"
            self.cleanup_advice_message_by_node[node_id] = message
        else:
            if answer:
                self.answers_by_node[node_id] = answer
            self.ai_messages_by_node[node_id] = message
        if str(self.selected_id) == node_id:
            if kind == "question":
                self.sync_selection_context()
            self.message = message
        else:
            node = self.node_by_id(node_id)
            self.message = f"{display_node_name(node) if node else 'Selected area'}: {message}"

    def spinner(self) -> str:
        return SPINNER_FRAMES[self.ai_spinner_index]

    def deep_spinner(self) -> str:
        return SPINNER_FRAMES[self.deep_analysis_spinner_index]

    def selected_local_path(self) -> Optional[Path]:
        node = self.selected()
        return local_node_path(node) if node else None

    def launch_selected(self, action: str) -> None:
        node = self.selected()
        if not node:
            self.message = "Nothing is selected."
            return
        self.message = launch_path_action(node, action)
        if not self.message.startswith("Could not"):
            self.record_recent(node)

    def record_recent(self, node: dict[str, Any]) -> None:
        path = local_node_path(node)
        if path is None or not path.exists():
            return
        path_text = str(path.resolve())
        recent = [item for item in self.workspace_state.get("recent", []) if item.get("path") != path_text]
        recent.insert(
            0,
            {
                "name": display_node_name(node),
                "path": path_text,
                "kind": node.get("kind"),
                "visited_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
        )
        self.workspace_state["recent"] = recent[:12]
        try:
            save_workspace_state(self.workspace_state, self.workspace_file)
        except OSError:
            self.message = "Action completed, but the local recent-path history could not be saved."

    def toggle_bookmark(self) -> None:
        node = self.selected()
        if not node:
            self.message = "Nothing is selected."
            return
        path = local_node_path(node)
        if path is None or not path.exists():
            self.message = "The selected path is unavailable, so it cannot be bookmarked."
            return
        path_text = str(path.resolve())
        bookmarks = self.workspace_state.get("bookmarks", [])
        existing = next((item for item in bookmarks if item.get("path") == path_text), None)
        if existing:
            bookmarks[:] = [item for item in bookmarks if item.get("path") != path_text]
            self.message = f"Removed bookmark for {display_node_name(node)}."
        else:
            bookmarks.append(
                {
                    "name": display_node_name(node),
                    "path": path_text,
                    "kind": node.get("kind"),
                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
            )
            self.message = f"Bookmarked {display_node_name(node)}. Press M to browse bookmarks."
        self.workspace_state["bookmarks"] = bookmarks[-50:]
        try:
            save_workspace_state(self.workspace_state, self.workspace_file)
        except OSError as exc:
            self.message = f"Bookmark changed in memory, but could not be saved locally: {exc}"

    def is_bookmarked(self, node: dict[str, Any]) -> bool:
        path = local_node_path(node)
        if path is None:
            return False
        path_text = str(path.resolve())
        return any(item.get("path") == path_text for item in self.workspace_state.get("bookmarks", []))

    def open_bookmarks(self) -> None:
        bookmarks = self.workspace_state.get("bookmarks", [])
        recent = self.workspace_state.get("recent", [])
        if not bookmarks and not recent:
            self.message = "No bookmarks or recent paths yet. Press m on a path to save one."
            return
        self.bookmark_open = True
        self.bookmark_index = 0
        self.message = "Bookmarks and recent paths: j/k move, Enter open, Esc close."

    def bookmark_entries(self) -> list[dict[str, Any]]:
        bookmarks = [{**item, "entry_kind": "bookmark"} for item in self.workspace_state.get("bookmarks", [])]
        recent = [{**item, "entry_kind": "recent"} for item in self.workspace_state.get("recent", [])]
        return bookmarks + recent

    def jump_to_bookmark(self) -> None:
        entries = self.bookmark_entries()
        if not entries:
            self.bookmark_open = False
            return
        entry = entries[max(0, min(self.bookmark_index, len(entries) - 1))]
        path = Path(str(entry.get("path") or "")).expanduser()
        if not path.exists():
            self.message = f"Saved path is no longer available: {entry.get('name', path)}"
            return
        self.bookmark_open = False
        if self.rescan_callback:
            try:
                report = self.rescan_callback(path)
            except Exception as exc:
                self.message = f"Could not open saved path: {exc}"
                return
            self._apply_report(report, path)
            self.message = f"Opened saved path {entry.get('name', path.name)}."
            return
        matching = next(
            (node for node in self.nodes if str(node.get("_local_path")) == str(path.resolve())),
            None,
        )
        if matching:
            self.selected_id = matching.get("node_id")
            self.sync_selection_context()
            self.message = f"Selected saved path {entry.get('name', path.name)}."
        else:
            self.message = "This saved path is outside the current map. Restart with its path to inspect it."

    def save_last_workspace(self) -> None:
        roots = list(self.space_map.get("requested_roots") or self.space_map.get("roots") or [])
        selected = self.selected_local_path()
        agent_task: dict[str, Any] = {}
        if self.prompt or self.answer:
            agent_task = {
                "path": str(selected.resolve()) if selected and selected.exists() else None,
                "question": self.question,
                "has_answer": bool(self.answer),
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        self.workspace_state["last_workspace"] = {
            "roots": [str(item) for item in roots],
            "selected_path": str(selected.resolve()) if selected and selected.exists() else None,
            "agent_task": agent_task,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        try:
            save_workspace_state(self.workspace_state, self.workspace_file)
            self.message = "Saved the current path and scope as the last workspace."
        except OSError as exc:
            self.message = f"Could not save the workspace locally: {exc}"

    def restore_last_workspace(self) -> None:
        saved = self.workspace_state.get("last_workspace") or {}
        raw_path = saved.get("selected_path")
        if not raw_path:
            self.message = "No saved workspace path yet. Press w to save the current scope."
            return
        path = Path(str(raw_path)).expanduser()
        if not path.exists():
            self.message = f"The saved workspace path is no longer available: {display_saved_path(path)}"
            return
        if self.rescan_callback:
            try:
                report = self.rescan_callback(path)
            except Exception as exc:
                self.message = f"Could not restore the saved workspace: {exc}"
                return
            self._apply_report(report, path)
            self.message = f"Restored the saved workspace at {display_saved_path(path)}."
            return
        matching = next(
            (node for node in self.nodes if str(node.get("_local_path")) == str(path.resolve())),
            None,
        )
        if matching:
            self.selected_id = matching.get("node_id")
            self.sync_selection_context()
            self.message = "Restored the saved workspace selection."
        else:
            self.message = "The saved workspace is outside the current map. Restart with its saved path."

    def start_deep_analysis(self, force: bool = False) -> None:
        node = self.selected()
        if not node:
            self.message = "Nothing is selected."
            return
        node_id = str(node.get("node_id"))
        if self.deep_analysis_busy:
            self.deep_analysis_open = True
            self.message = "Deep path analysis is still running. You can keep browsing."
            return
        if node_id in self.deep_analysis_by_node and not force:
            self.deep_analysis_open = True
            self.message = "Showing the saved deep analysis for this path. Press D to run it again."
            return
        if local_node_path(node) is None:
            self.message = "Deep analysis needs a local path in this TUI session."
            return
        self.deep_analysis_busy = True
        self.deep_analysis_busy_node_id = node_id
        self.deep_analysis_spinner_index = 0
        self.deep_analysis_open = True
        self.deep_analysis_scroll = 0
        self.message = "Deep path analysis is reading local metadata only. Press Esc to close this view; it will continue in the background."

        def worker() -> None:
            result = analyze_path_relationships(node)
            self.deep_analysis_results.put((node_id, result))

        threading.Thread(target=worker, name="clean-your-data-deep-analysis", daemon=True).start()

    def poll_deep_analysis(self) -> None:
        if self.deep_analysis_busy:
            self.deep_analysis_spinner_index = (self.deep_analysis_spinner_index + 1) % len(SPINNER_FRAMES)
        try:
            node_id, result = self.deep_analysis_results.get_nowait()
        except queue.Empty:
            return
        self.deep_analysis_busy = False
        self.deep_analysis_busy_node_id = None
        self.deep_analysis_by_node[node_id] = result
        self.message = f"Deep path analysis ready for {result.get('root', 'the selected path')}."

    def _apply_report(self, report: dict[str, Any], preferred_local_path: Optional[Path] = None) -> None:
        self.report = report
        self.space_map = report.get("space_map") or {}
        self.nodes = list(self.space_map.get("nodes") or [])
        self.expanded = initial_expanded_nodes(self.nodes)
        active_ids = {str(node.get("node_id")) for node in self.nodes}
        self.cleanup_queue = {node_id: item for node_id, item in self.cleanup_queue.items() if node_id in active_ids}
        for mapping in (self.cleanup_advice_by_node, self.cleanup_advice_status_by_node, self.cleanup_advice_message_by_node):
            for node_id in list(mapping):
                if node_id not in active_ids:
                    mapping.pop(node_id, None)
        selected_id: Optional[str] = None
        if preferred_local_path is not None:
            preferred = str(preferred_local_path.resolve())
            selected_id = next(
                (str(node.get("node_id")) for node in self.nodes if str(node.get("_local_path")) == preferred),
                None,
            )
        if selected_id is None and self.nodes:
            selected_id = str(self.nodes[0].get("node_id"))
        self.selected_id = selected_id
        self.scroll = 0
        self.sync_selection_context()
        self._reset_selection_for_view()

    def cleanup_item(self, node_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        key = str(node_id if node_id is not None else self.selected_id)
        return self.cleanup_queue.get(key)

    def cleanup_queue_size(self) -> int:
        return sum(int(item.get("size_bytes") or 0) for item in self.cleanup_queue.values())

    def cleanup_queue_size_label(self) -> str:
        total = self.cleanup_queue_size()
        if total <= 0:
            return "0 B"
        units = ("B", "KB", "MB", "GB", "TB")
        value = float(total)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{total} B"

    def queue_selected_for_cleanup(self) -> None:
        node = self.selected()
        if not node:
            self.message = "Nothing is selected."
            return
        node_id = str(node.get("node_id"))
        if node_id in self.cleanup_queue:
            advice_status = self.cleanup_advice_status_by_node.get(node_id, "not_requested")
            if advice_status in {"waiting", "cancelled", "unavailable"} and not self.ai_busy:
                self.cleanup_advice_status_by_node[node_id] = "awaiting_agent"
                self.cleanup_advice_message_by_node.pop(node_id, None)
                self.start_ai(node, cleanup_prompt(node), kind="cleanup")
                self.message = f"Retrying the coding agent advice for {display_node_name(node)}. Nothing was moved."
            else:
                self.message = f"{display_node_name(node)} is already in the cleanup basket. Nothing was moved."
            return
        allowed, reason = cleanup_gate(node)
        if not allowed and not cleanup_review_path_available(node):
            self.cleanup_advice_status_by_node[node_id] = "blocked"
            self.cleanup_advice_message_by_node[node_id] = reason
            self.message = f"Cannot stage {display_node_name(node)}: {reason}."
            return
        self.cleanup_queue[node_id] = {
            "node_id": node_id,
            "path": node.get("path"),
            "local_path": str(local_node_path(node)),
            "name": display_node_name(node),
            "kind": node.get("kind"),
            "category": node.get("category"),
            "size_bytes": node.get("allocated_bytes"),
            "human_size": node.get("human_size"),
            "measurement_status": node.get("measurement_status"),
            "status": "queued" if allowed else "blocked",
            "preliminary_advice": preliminary_cleanup_advice(node),
            "queued_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        self.cleanup_advice_status_by_node[node_id] = "awaiting_agent"
        if allowed:
            self.message = f"Staged {display_node_name(node)}. This is preliminary scan evidence; nothing moved."
        else:
            self.cleanup_advice_message_by_node[node_id] = reason
            self.message = f"Staged {display_node_name(node)} for review only: {reason}. Nothing moved."
        if self.ai_busy:
            self.cleanup_advice_status_by_node[node_id] = "waiting"
            self.cleanup_advice_message_by_node[node_id] = "Codex is answering another request."
            self.message += " Codex is busy; ask for advice after it finishes."
            return
        self.start_ai(node, cleanup_prompt(node), kind="cleanup")

    def begin_trash_confirmation(self) -> None:
        node = self.selected()
        if not node:
            self.message = "Nothing is selected."
            return
        node_id = str(node.get("node_id"))
        if node_id not in self.cleanup_queue:
            self.message = "Press dd first. That stages the exact path without moving it."
            return
        allowed, reason = cleanup_gate(node)
        if not allowed:
            self.message = f"Cannot move this path: {reason}."
            return
        advice_status = self.cleanup_advice_status_by_node.get(node_id, "not_requested")
        if advice_status in {"awaiting_agent", "waiting"}:
            self.message = "Wait for the coding agent's cleanup advice before confirming, or press Esc to stop it."
            return
        self.trash_confirmation = True
        self.trash_confirmation_node_id = node_id
        self.message = "Review the exact path. Press y to move it to system Trash, or Esc to cancel."

    def cancel_trash_confirmation(self) -> None:
        self.trash_confirmation = False
        self.trash_confirmation_node_id = None
        self.message = "Trash move cancelled. The cleanup candidate remains staged."

    def _remove_node_subtree(self, node_id: str) -> list[dict[str, Any]]:
        removed: list[dict[str, Any]] = []
        pending = {node_id}
        removed_ids = {node_id}
        while pending:
            current = pending.pop()
            for node in self.nodes:
                if str(node.get("parent_id")) == current:
                    child_id = str(node.get("node_id"))
                    pending.add(child_id)
                    removed_ids.add(child_id)
        for node in self.nodes:
            if str(node.get("node_id")) in removed_ids:
                removed.append(node)
        self.nodes = [node for node in self.nodes if str(node.get("node_id")) not in removed_ids]
        self.expanded.difference_update(removed_ids)
        for removed_id in removed_ids:
            self.cleanup_queue.pop(removed_id, None)
        return removed

    def rescan_after_cleanup(self, preferred_local_path: Optional[Path] = None) -> bool:
        """Refresh only the focused map after a move or restore."""
        if self.rescan_callback is None:
            return False
        try:
            report = self.rescan_callback(None)
        except Exception as exc:
            self.message = f"Action completed, but the focused map could not be refreshed: {exc}"
            return False
        self._apply_report(report, preferred_local_path)
        return True

    def execute_confirmed_trash(self) -> None:
        node_id = self.trash_confirmation_node_id
        node = self.node_by_id(node_id)
        item = self.cleanup_queue.get(str(node_id)) if node_id is not None else None
        if not node or not item:
            self.cancel_trash_confirmation()
            self.message = "The staged path is no longer visible. Nothing was moved."
            return
        allowed, reason = cleanup_gate(node)
        if not allowed:
            self.cancel_trash_confirmation()
            self.message = f"Move stopped: {reason}."
            return
        visible_before = self.visible()
        selected_index = next((index for index, row in enumerate(visible_before) if str(row.get("node_id")) == str(node_id)), 0)
        original_path = local_node_path(node)
        try:
            record = move_to_trash(
                local_node_path(node) or Path(""),
                node=node,
                trash_root=self.cleanup_trash_root,
                history_path=self.cleanup_history_file,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            self.cancel_trash_confirmation()
            self.message = f"Could not move {display_node_name(node)} to Trash: {exc}"
            return
        removed = self._remove_node_subtree(str(node_id))
        self.removed_nodes_by_record[str(record["record_id"])] = removed
        self.cleanup_history = load_cleanup_history(self.cleanup_history_file)
        self.trash_confirmation = False
        self.trash_confirmation_node_id = None
        if self.rescan_after_cleanup(original_path.parent if original_path else None):
            self.message = f"Moved {record['name']} to system Trash and refreshed the focused map. Press u to undo."
            return
        visible_after = self.visible()
        if visible_after:
            self.select_index(min(selected_index, len(visible_after) - 1))
        else:
            self.selected_id = None
            self.sync_selection_context()
        self.message = f"Moved {record['name']} to system Trash. Press u to undo."

    def undo_last_cleanup(self) -> None:
        record = next((item for item in reversed(self.cleanup_history) if item.get("status") == "trashed"), None)
        if not record:
            self.message = "There is no recent cleanup action to undo."
            return
        try:
            restored = restore_trash_record(record, self.cleanup_history_file)
        except (OSError, ValueError) as exc:
            self.message = f"Could not restore the Trash item: {exc}"
            return
        record_id = str(restored.get("record_id"))
        restored_nodes = self.removed_nodes_by_record.pop(record_id, [])
        if self.rescan_after_cleanup(Path(str(restored.get("original_path"))).parent):
            self.message = f"Restored {restored.get('name', 'the item')} and refreshed the focused map."
            self.cleanup_history = load_cleanup_history(self.cleanup_history_file)
            return
        if restored_nodes:
            self.nodes.extend(restored_nodes)
            restored_id = str(restored_nodes[0].get("node_id"))
            self.selected_id = restored_id
            self.sync_selection_context()
        self.cleanup_history = load_cleanup_history(self.cleanup_history_file)
        self.message = f"Restored {restored.get('name', 'the item')} to its original path."


def add_text(stdscr: Any, y: int, x: int, value: Any, width: int, attr: int = 0) -> None:
    if y < 0 or x < 0 or width <= 0:
        return
    try:
        stdscr.addnstr(y, x, str(value), width, attr)
    except curses.error:
        pass


def draw_wrapped(stdscr: Any, y: int, x: int, value: Any, width: int, height: int, attr: int = 0) -> int:
    for line in wrap_lines(value, width)[: max(0, height)]:
        add_text(stdscr, y, x, line, width, attr)
        y += 1
    return y


def draw_header(stdscr: Any, state: TuiState, width: int) -> None:
    scope = ", ".join(str(item) for item in state.space_map.get("roots", [])[:3]) or "workspace roots"
    if len(scope) > 28:
        scope = scope[:25] + "..."
    status = display_label(state.space_map.get("status", "unknown"))
    gate = display_label((state.report.get("action_gate") or {}).get("status", "review_only"))
    _, ai_label = resolve_ai_command()
    if state.ai_busy:
        ai_label = f"{ai_label} thinking {state.spinner()}"
    add_text(stdscr, 0, 0, "CLEAN YOUR DATA / TERMINAL EXPLORER", width, curses.A_BOLD | palette("title"))
    add_text(stdscr, 1, 0, f"Tab: {state.tab_status()}  |  Scope: {scope}  |  Map: {status}  |  Decision: {gate}  |  AI: {ai_label}", width, palette("status"))
    search = state.search_query or "off"
    add_text(stdscr, 2, 0, f"VIEW  Search: {search}  |  Filter: {state.filter_label()}  |  Sort: {state.sort_label()}", width, palette("status"))
    add_text(stdscr, 3, 0, "MOVE j/k   ENTER open/close   / search   f filter   s sort   T tags   N new tab   ? help   q quit", width, palette("muted"))
    add_text(stdscr, 4, 0, "-" * max(0, width), width, palette("rule"))


def draw_tree(stdscr: Any, state: TuiState, y: int, height: int, width: int) -> None:
    visible = state.visible()
    if visible:
        selected_index = next((i for i, node in enumerate(visible) if node.get("node_id") == state.selected_id), 0)
        if selected_index < state.scroll:
            state.scroll = selected_index
        if selected_index >= state.scroll + height:
            state.scroll = selected_index - height + 1
        state.scroll = max(0, min(state.scroll, max(0, len(visible) - height)))
    else:
        state.scroll = 0
        add_text(stdscr, y, 0, "No areas are available for this selection.", width, palette("muted"))
        return

    by_parent = children_by_parent(state.nodes)
    for row, node in enumerate(visible[state.scroll : state.scroll + height]):
        has_children = bool(by_parent.get(node.get("node_id"))) or bool(node.get("can_expand"))
        is_open = str(node.get("node_id")) in state.expanded
        marker = "v" if has_children and is_open else ">" if has_children else " "
        selected = "*" if node.get("node_id") == state.selected_id else " "
        basket = "+" if state.cleanup_item(str(node.get("node_id"))) else " "
        tagged = "@" if state.node_tags(node) else " "
        indent = "  " * min(int(node.get("depth") or 0), 8)
        name = display_node_name(node)
        line = f"{selected}{basket}{tagged} {marker} {indent}{name}  {display_size(node)}"
        attr = curses.A_BOLD | palette("selected") if selected == "*" else palette("basket") if basket == "+" else palette("folder") if node.get("kind") == "folder" else 0
        add_text(stdscr, y + row, 0, line, width, attr)


def inspector_lines(state: TuiState, width: int) -> list[tuple[str, int]]:
    node = state.selected()
    if not node:
        return [("SELECTED AREA", curses.A_BOLD), ("Nothing selected.", 0)]
    node_id = str(node.get("node_id"))
    cleanup_item = state.cleanup_item(node_id)
    cleanup_status = state.cleanup_advice_status_by_node.get(node_id, "not_requested")
    cleanup_lines: list[tuple[str, int]] = [
        ("CLEANUP REVIEW", curses.A_BOLD | palette("title")),
        (
            f"Basket: {display_label(cleanup_item.get('status'))}  |  {len(state.cleanup_queue)} item(s) queued"
            if cleanup_item
            else "Basket: Not staged",
            palette("basket") if cleanup_item else curses.A_DIM,
        ),
    ]
    if cleanup_item:
        cleanup_lines.append((f"Planned total: {state.cleanup_queue_size_label()}", curses.A_DIM))
        cleanup_lines.append(("PRELIMINARY SCAN", curses.A_BOLD | palette("muted")))
        for line in wrap_lines(cleanup_item.get("preliminary_advice"), max(10, width)):
            cleanup_lines.append((line, curses.A_DIM | palette("muted")))
        cleanup_lines.append((f"CODING AGENT: {display_label(cleanup_status)}", curses.A_BOLD | palette("answer")))
        agent_advice = state.cleanup_advice_by_node.get(node_id)
        if agent_advice:
            for line in wrap_lines(agent_advice, max(10, width))[:10]:
                cleanup_lines.append((line, 0))
        elif cleanup_status in {"awaiting_agent", "waiting"}:
            cleanup_lines.append(("Waiting for the coding agent to review this preliminary evidence.", curses.A_DIM | palette("muted")))
        elif cleanup_status == "unavailable":
            cleanup_lines.append(("No coding agent answered; human review is still required.", curses.A_DIM | palette("muted")))
        if state.cleanup_advice_message_by_node.get(node_id):
            cleanup_lines.append((state.cleanup_advice_message_by_node[node_id], curses.A_DIM | palette("muted")))
        cleanup_lines.extend(
            [
                ("dd stage  Y review  y confirm Trash  u undo", curses.A_DIM | palette("muted")),
                ("The agent advises; only your exact confirmation moves files.", curses.A_DIM | palette("muted")),
            ]
        )
    else:
        cleanup_lines.append(("Press dd to stage this exact path for review.", curses.A_DIM | palette("muted")))
    cleanup_lines.extend(
        [
            ("PATH ACTIONS", curses.A_BOLD | palette("title")),
            ("t terminal  v VS Code  c Cursor  o Finder", curses.A_DIM | palette("muted")),
            ("m bookmark  M bookmarks  T tags  D deep analysis", curses.A_DIM | palette("muted")),
            ("Bookmark: " + ("saved" if state.is_bookmarked(node) else "not saved"), curses.A_DIM),
            ("Tags: " + (", ".join(state.node_tags(node)) if state.node_tags(node) else "none"), curses.A_DIM),
            ("", 0),
        ]
    )
    is_file = node.get("kind") == "file"
    if is_file:
        lines: list[tuple[str, int]] = [
            *cleanup_lines,
            ("ABOUT THIS AREA", curses.A_BOLD | palette("title")),
            (display_node_name(node), curses.A_BOLD),
            (f"Path: {display_node_path(node)}", curses.A_DIM),
            ("CONTENT PREVIEW", curses.A_BOLD | palette("answer")),
        ]
        for line in state.preview_for(node):
            lines.append((line, 0))
        lines.extend(
            [
                ("", 0),
                ("DETAILS", curses.A_BOLD | palette("title")),
                (f"Space: {display_size(node)}", 0),
                (f"Last changed: {display_date(node.get('modified_at'))}", 0),
                (f"Area: {display_label(node.get('area') or 'unknown scope')}", 0),
                ("Preview is local only and is not sent to Codex.", curses.A_DIM | palette("muted")),
            ]
        )
    else:
        lines = [
            *cleanup_lines,
            ("ABOUT THIS AREA", curses.A_BOLD | palette("title")),
            (display_node_name(node), curses.A_BOLD | palette("folder")),
            (f"Path: {display_node_path(node)}", curses.A_DIM),
            (f"Space: {display_size(node)}", 0),
            (f"Last changed: {display_date(node.get('modified_at'))}", 0),
            ("Kind: Folder", 0),
            (f"Area: {display_label(node.get('area') or 'unknown scope')}", 0),
            (f"Measurement: {display_label(node.get('measurement_status') or 'unknown')}", 0),
            ("", 0),
            ("WHAT WE KNOW", curses.A_BOLD | palette("title")),
        ]
        explanation = "We checked this folder's name, size, dates, and visible entries. We did not open file contents, so its exact purpose is not confirmed."
        lines.extend([("", 0)])
        for line in wrap_lines(explanation, max(10, width)):
            lines.append((line, curses.A_DIM | palette("muted")))
        lines.extend(
            [
                ("", 0),
                ("NEXT STEP", curses.A_BOLD | palette("title")),
                ("Press A to ask Codex what this area is likely for.", curses.A_DIM | palette("muted")),
            ]
        )
    if state.ai_busy and state.ai_busy_node_id == node_id:
        lines.extend([("", 0), (f"CODEX THINKING {state.spinner()}", curses.A_BOLD | palette("answer"))])
        if state.answer:
            lines.append(("Previous answer remains below.", curses.A_DIM | palette("muted")))
            lines.extend((line, 0) for line in wrap_lines(state.answer, max(10, width)))
    elif state.answer:
        lines.extend([("", 0), ("CODEX ANSWER", curses.A_BOLD | palette("answer"))])
        for line in wrap_lines(state.answer, max(10, width)):
            lines.append((line, 0))
    elif state.prompt:
        lines.extend(
            [
                ("", 0),
                ("CODEX QUESTION READY", curses.A_BOLD | palette("title")),
                ("Press C to copy the metadata-only context.", curses.A_DIM | palette("muted")),
            ]
        )
        for line in wrap_lines(state.question, max(10, width)):
            lines.append((line, curses.A_DIM))
    return lines


def draw_inspector(stdscr: Any, state: TuiState, y: int, height: int, x: int, width: int) -> None:
    add_text(stdscr, y, x, "INSPECTOR", width, curses.A_BOLD | palette("title"))
    current_y = y + 1
    for text, attr in inspector_lines(state, width)[: max(0, height - 1)]:
        add_text(stdscr, current_y, x, text, width, attr)
        current_y += 1


def draw_vertical_divider(stdscr: Any, y: int, height: int, x: int) -> None:
    for row in range(max(0, height)):
        add_text(stdscr, y + row, x, "|", 1, palette("rule"))


def draw_help(stdscr: Any, width: int, height: int) -> None:
    box_width = min(max(50, width - 6), 78)
    box_height = min(24, max(8, height - 4))
    left = max(0, (width - box_width) // 2)
    top = max(0, (height - box_height) // 2)
    add_text(stdscr, top, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    for row in range(1, max(1, box_height - 1)):
        add_text(stdscr, top + row, left, "|" + " " * max(0, box_width - 2) + "|", box_width, palette("rule"))
    if box_height > 1:
        add_text(stdscr, top + box_height - 1, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    add_text(stdscr, top + 1, left + 2, "KEYS / HOW TO USE", box_width - 4, curses.A_BOLD | palette("title"))
    help_lines = [
        "j/k or arrows  move; h/l parent or first child; Enter open/close",
        "gg / G / Home / End / Page  jump through the visible tree",
        "Mouse          click select; double-click a folder to open it",
        "/              fuzzy search names, paths, areas, and tags",
        "f              filter: folders, files, large, recent, rebuildable...",
        "s              sort siblings by tree, name, size, date, or kind",
        "T              add or edit local tags; @ marks tagged rows",
        "N / gt / gT / X  open, switch, or close tabs",
        "a / A          ask Codex about the selected area",
        "t/v/c/o        open Terminal, VS Code, Cursor, or Finder",
        "m / M          bookmark; browse bookmarks and recent paths",
        "w / W          save or restore the last workspace",
        "D              deep metadata-only path relationship analysis",
        "dd / Y / y / u  stage, review, Trash, or undo cleanup",
        "C / r          copy AI context or reload a file preview",
        "Esc/Ctrl-C     close an overlay or stop waiting for Codex",
        "q              quit the explorer",
        "",
        "Press any key to close this help.",
    ]
    for index, line in enumerate(help_lines[: max(0, box_height - 5)]):
        add_text(stdscr, top + 3 + index, left + 2, line, box_width - 4)


def draw_input_box(stdscr: Any, title: str, value: str, hint: str, width: int, height: int) -> None:
    box_width = min(max(48, width - 6), 92)
    box_height = 6
    left = max(0, (width - box_width) // 2)
    top = max(0, (height - box_height) // 2)
    add_text(stdscr, top, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    for row in range(1, box_height - 1):
        add_text(stdscr, top + row, left, "|" + " " * max(0, box_width - 2) + "|", box_width, palette("rule"))
    add_text(stdscr, top + box_height - 1, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    add_text(stdscr, top + 1, left + 2, title, box_width - 4, curses.A_BOLD | palette("title"))
    input_width = max(1, box_width - 6)
    visible = value[-input_width:]
    add_text(stdscr, top + 2, left + 2, "> " + visible, box_width - 4, palette("selected"))
    add_text(stdscr, top + 4, left + 2, hint, box_width - 4, curses.A_DIM | palette("muted"))
    try:
        stdscr.move(top + 2, left + 4 + min(len(visible), input_width))
    except curses.error:
        pass


def draw_choice_menu(
    stdscr: Any,
    title: str,
    options: tuple[tuple[str, str], ...],
    selected_index: int,
    width: int,
    height: int,
) -> None:
    box_width = min(max(56, width - 6), 94)
    box_height = min(len(options) + 5, max(8, height - 4))
    left = max(0, (width - box_width) // 2)
    top = max(0, (height - box_height) // 2)
    add_text(stdscr, top, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    for row in range(1, max(1, box_height - 1)):
        add_text(stdscr, top + row, left, "|" + " " * max(0, box_width - 2) + "|", box_width, palette("rule"))
    add_text(stdscr, top + box_height - 1, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    add_text(stdscr, top + 1, left + 2, title, box_width - 4, curses.A_BOLD | palette("title"))
    for index, (_, label) in enumerate(options[: max(0, box_height - 5)]):
        marker = ">" if index == selected_index else " "
        attr = curses.A_BOLD | palette("selected") if marker == ">" else 0
        add_text(stdscr, top + 3 + index, left + 2, f"{marker} {label}", box_width - 4, attr)
    add_text(stdscr, top + box_height - 2, left + 2, "j/k move    Enter apply    Esc close", box_width - 4, curses.A_DIM | palette("muted"))


def draw_tag_box(stdscr: Any, state: TuiState, width: int, height: int) -> None:
    draw_input_box(stdscr, "EDIT TAGS  comma-separated", state.tag_buffer, "Enter save    Esc cancel", width, height)


def draw_question_box(stdscr: Any, state: TuiState, y: int, x: int, width: int) -> None:
    box_height = 4
    if width < 12:
        return
    if width >= 36:
        heading = "| ASK CODEX  Enter send  Esc cancel"
    elif width >= 26:
        heading = "| ASK CODEX | Enter | Esc"
    else:
        heading = "| ASK CODEX"
    add_text(stdscr, y, x, "+" + "-" * max(0, width - 2) + "+", width, palette("rule"))
    add_text(stdscr, y + 1, x, heading, width, curses.A_BOLD | palette("title"))
    input_width = max(1, width - 4)
    visible = state.question_buffer[-input_width:]
    add_text(stdscr, y + 2, x, "| " + visible, width, palette("selected"))
    add_text(stdscr, y + 3, x, "+" + "-" * max(0, width - 2) + "+", width, palette("rule"))
    try:
        stdscr.move(y + 2, x + 2 + min(len(visible), input_width))
    except curses.error:
        pass


def draw_trash_confirmation(stdscr: Any, state: TuiState, width: int, height: int) -> None:
    node = state.node_by_id(state.trash_confirmation_node_id)
    if not node:
        return
    box_width = min(max(52, width - 6), 92)
    box_height = min(9, max(7, height - 4))
    left = max(0, (width - box_width) // 2)
    top = max(0, (height - box_height) // 2)
    add_text(stdscr, top, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("danger"))
    for row in range(1, max(1, box_height - 1)):
        add_text(stdscr, top + row, left, "|" + " " * max(0, box_width - 2) + "|", box_width, palette("danger"))
    if box_height > 1:
        add_text(stdscr, top + box_height - 1, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("danger"))
    add_text(stdscr, top + 1, left + 2, "MOVE EXACT PATH TO SYSTEM TRASH?", box_width - 4, curses.A_BOLD | palette("danger"))
    add_text(stdscr, top + 2, left + 2, display_node_path(node), box_width - 4, curses.A_BOLD)
    add_text(stdscr, top + 3, left + 2, f"Size: {display_size(node)}  |  This is reversible with u.", box_width - 4, palette("muted"))
    add_text(stdscr, top + 4, left + 2, "The scan is preliminary; the coding agent's advice is shown behind this dialog.", box_width - 4, palette("muted"))
    add_text(stdscr, top + box_height - 2, left + 2, "y confirm    Esc cancel", box_width - 4, curses.A_BOLD | palette("selected"))


def display_saved_path(value: Any) -> str:
    path = Path(str(value or "")).expanduser()
    try:
        relative = path.resolve().relative_to(Path.home().resolve())
        return "~/" + str(relative) if str(relative) else "~"
    except (OSError, ValueError):
        parts = path.parts
        return "<external>/" + "/".join(parts[-3:]) if parts else "<external>"


def draw_bookmarks(stdscr: Any, state: TuiState, width: int, height: int) -> None:
    entries = state.bookmark_entries()
    if not entries:
        return
    box_width = min(max(64, width - 6), 96)
    box_height = min(max(10, len(entries) + 6), max(8, height - 4))
    left = max(0, (width - box_width) // 2)
    top = max(0, (height - box_height) // 2)
    add_text(stdscr, top, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    for row in range(1, max(1, box_height - 1)):
        add_text(stdscr, top + row, left, "|" + " " * max(0, box_width - 2) + "|", box_width, palette("rule"))
    add_text(stdscr, top + box_height - 1, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    add_text(stdscr, top + 1, left + 2, "BOOKMARKS / RECENT PATHS", box_width - 4, curses.A_BOLD | palette("title"))
    for index, entry in enumerate(entries[: max(0, box_height - 5)]):
        marker = ">" if index == state.bookmark_index else " "
        kind = "bookmark" if entry.get("entry_kind") == "bookmark" else "recent"
        line = f"{marker} {kind:9} {entry.get('name', 'unnamed')}  {display_saved_path(entry.get('path'))}"
        add_text(stdscr, top + 3 + index, left + 2, line, box_width - 4, palette("selected") if marker == ">" else 0)
    add_text(stdscr, top + box_height - 2, left + 2, "j/k move    Enter open    Esc close", box_width - 4, curses.A_DIM | palette("muted"))


def deep_analysis_lines(state: TuiState, width: int) -> list[str]:
    node = state.node_by_id(state.deep_analysis_busy_node_id) if state.deep_analysis_busy else state.selected()
    node_id = str(node.get("node_id")) if node else ""
    result = state.deep_analysis_by_node.get(node_id)
    if state.deep_analysis_busy:
        return [
            "DEEP PATH ANALYSIS",
            "",
            f"Reading metadata {state.deep_spinner()}",
            "This does not read file contents or calculate hashes.",
            "Press Esc to close this view; the analysis continues in the background.",
        ]
    if not result:
        return ["DEEP PATH ANALYSIS", "", "Press D on a selected path to start."]
    lines = [
        "DEEP PATH ANALYSIS",
        f"Root: {result.get('root', 'unknown')}",
        f"Status: {display_label(result.get('status', 'unknown'))}  |  Files: {result.get('files_scanned', 0)}  |  Folders: {result.get('directories_seen', 0)}",
        f"Metadata size seen: {human_relation_size(int(result.get('bytes_scanned') or 0))}",
        "",
        "FILE MIX",
    ]
    counts = result.get("counts") or {}
    for key in ("source", "tests", "documentation", "configuration", "media", "other"):
        if counts.get(key):
            lines.append(f"{key:16} {counts[key]}")
    lines.extend(["", "RELATIONSHIPS"])
    for relation in result.get("relations") or []:
        lines.append(f"{relation.get('title', 'Finding')}: {relation.get('detail', '')}")
    if result.get("largest"):
        lines.extend(["", "LARGEST ITEMS"])
        for item in result["largest"][:5]:
            lines.append(f"{item.get('size', 'unknown'):>10}  {item.get('path', 'unknown')}")
    if result.get("duplicate_candidates"):
        lines.extend(["", "POSSIBLE SAME-NAME / SAME-SIZE MATCHES"])
        for group in result["duplicate_candidates"][:4]:
            lines.append("  = ".join(group))
    lines.extend(["", "Metadata-only, bounded analysis. D reruns it; Esc closes this view."])
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(wrap_lines(line, max(10, width - 6)) or [""])
    return wrapped


def draw_deep_analysis(stdscr: Any, state: TuiState, width: int, height: int) -> None:
    lines = deep_analysis_lines(state, width)
    box_width = min(max(72, width - 6), 112)
    box_height = min(max(12, height - 4), 28)
    left = max(0, (width - box_width) // 2)
    top = max(0, (height - box_height) // 2)
    add_text(stdscr, top, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    for row in range(1, max(1, box_height - 1)):
        add_text(stdscr, top + row, left, "|" + " " * max(0, box_width - 2) + "|", box_width, palette("rule"))
    add_text(stdscr, top + box_height - 1, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    visible_height = max(1, box_height - 5)
    max_scroll = max(0, len(lines) - visible_height)
    state.deep_analysis_scroll = max(0, min(state.deep_analysis_scroll, max_scroll))
    for index, line in enumerate(lines[state.deep_analysis_scroll : state.deep_analysis_scroll + visible_height]):
        attr = curses.A_BOLD | palette("title") if index == 0 else 0
        add_text(stdscr, top + 2 + index, left + 2, line, box_width - 4, attr)
    add_text(stdscr, top + box_height - 2, left + 2, "j/k scroll    D rerun    Esc close", box_width - 4, curses.A_DIM | palette("muted"))


def begin_question(stdscr: Any, state: TuiState) -> None:
    node = state.selected()
    if not node:
        state.message = "Nothing is selected."
        return
    if state.ai_busy:
        state.message = "Codex is already thinking. You can still move through the tree."
        return
    state.question_editing = True
    state.question_buffer = ""
    state.message = "Type a question in the right panel. Enter sends; Esc cancels."
    try:
        curses.curs_set(1)
    except curses.error:
        pass


def submit_question(stdscr: Any, state: TuiState) -> None:
    node = state.selected()
    if not node:
        state.question_editing = False
        return
    state.question = state.question_buffer.strip() or DEFAULT_QUESTION
    state.prompt = build_prompt(node, state.question)
    state.question_editing = False
    state.question_buffer = ""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    state.start_ai(node, state.prompt)


def cancel_question(stdscr: Any, state: TuiState) -> None:
    state.question_editing = False
    state.question_buffer = ""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    state.message = "Question cancelled."


def handle_search_key(stdscr: Any, state: TuiState, key: Any) -> bool:
    if key_matches(key, 27, "\x1b", 3, "\x03"):
        state.cancel_search()
    elif key_matches(key, "\n", "\r", 10, 13, curses.KEY_ENTER):
        state.apply_search()
    elif key_matches(key, curses.KEY_BACKSPACE, 8, 127, "\b"):
        state.search_buffer = state.search_buffer[:-1]
    elif key_matches(key, 21, "\x15"):
        state.search_buffer = ""
    elif isinstance(key, str) and len(key) == 1 and ord(key) >= 32:
        state.search_buffer += key
    elif isinstance(key, int) and 32 <= key <= 126:
        state.search_buffer += chr(key)
    return True


def handle_tag_key(stdscr: Any, state: TuiState, key: Any) -> bool:
    if key_matches(key, 27, "\x1b", 3, "\x03"):
        state.tag_editing = False
        state.tag_buffer = ""
        state.tag_node_id = None
        state.message = "Tag editing cancelled."
    elif key_matches(key, "\n", "\r", 10, 13, curses.KEY_ENTER):
        state.save_tags()
    elif key_matches(key, curses.KEY_BACKSPACE, 8, 127, "\b"):
        state.tag_buffer = state.tag_buffer[:-1]
    elif key_matches(key, 21, "\x15"):
        state.tag_buffer = ""
    elif isinstance(key, str) and len(key) == 1 and ord(key) >= 32:
        state.tag_buffer += key
    elif isinstance(key, int) and 32 <= key <= 126:
        state.tag_buffer += chr(key)
    return True


def handle_choice_key(state: TuiState, key: Any, kind: str) -> bool:
    options = FILTER_OPTIONS if kind == "filter" else SORT_OPTIONS
    index = state.filter_index if kind == "filter" else state.sort_index
    if key_matches(key, 27, "\x1b", 3, "\x03"):
        if kind == "filter":
            state.filter_open = False
        else:
            state.sort_open = False
        state.message = f"{kind.capitalize()} selection cancelled."
    elif key_matches(key, "j", curses.KEY_DOWN, ord("j")):
        index = min(index + 1, len(options) - 1)
    elif key_matches(key, "k", curses.KEY_UP, ord("k")):
        index = max(index - 1, 0)
    elif key_matches(key, "\n", "\r", 10, 13, curses.KEY_ENTER):
        if kind == "filter":
            state.choose_filter(index)
        else:
            state.choose_sort(index)
    if kind == "filter":
        state.filter_index = index
    else:
        state.sort_index = index
    return True


def handle_question_key(stdscr: Any, state: TuiState, key: Any) -> bool:
    if key_matches(key, 27, "\x1b", 3, "\x03"):
        cancel_question(stdscr, state)
    elif key_matches(key, "\n", "\r", 10, 13, curses.KEY_ENTER):
        submit_question(stdscr, state)
    elif key_matches(key, curses.KEY_BACKSPACE, 8, 127, "\b"):
        state.question_buffer = state.question_buffer[:-1]
    elif key_matches(key, 21, "\x15"):
        state.question_buffer = ""
    elif isinstance(key, str) and len(key) == 1 and ord(key) >= 32:
        state.question_buffer += key
    elif isinstance(key, int) and 32 <= key <= 126:
        state.question_buffer += chr(key)
    return True


def handle_mouse(state: TuiState, tree_y: int, tree_height: int, tree_width: int) -> bool:
    try:
        _, x, y, _, button_state = curses.getmouse()
    except curses.error:
        return True
    visible = state.visible()
    if not visible:
        return True
    wheel_up = getattr(curses, "BUTTON4_PRESSED", 0)
    wheel_down = getattr(curses, "BUTTON5_PRESSED", 0)
    if button_state & wheel_up:
        current = next((i for i, node in enumerate(visible) if node.get("node_id") == state.selected_id), 0)
        state.select_index(current - 3)
        return True
    if button_state & wheel_down:
        current = next((i for i, node in enumerate(visible) if node.get("node_id") == state.selected_id), 0)
        state.select_index(current + 3)
        return True
    if x < 0 or x >= tree_width or y < tree_y or y >= tree_y + tree_height:
        return True
    index = state.scroll + y - tree_y
    if index < 0 or index >= len(visible):
        return True
    state.select_index(index)
    double_click = getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0)
    if button_state & double_click:
        selected = state.selected()
        if selected:
            state.open_or_close(selected)
    else:
        state.message = "Selected area. Double-click a folder to open it."
    return True


def handle_key(stdscr: Any, state: TuiState, key: Any, width: int, page_size: int = 10) -> bool:
    if state.question_editing:
        return handle_question_key(stdscr, state, key)
    if state.search_editing:
        return handle_search_key(stdscr, state, key)
    if state.tag_editing:
        return handle_tag_key(stdscr, state, key)
    if state.filter_open:
        return handle_choice_key(state, key, "filter")
    if state.sort_open:
        return handle_choice_key(state, key, "sort")
    if state.bookmark_open:
        entries = state.bookmark_entries()
        if key_matches(key, 27, "\x1b", 3, "\x03"):
            state.bookmark_open = False
            state.message = "Closed bookmarks."
        elif key_matches(key, "j", curses.KEY_DOWN, ord("j")) and entries:
            state.bookmark_index = min(state.bookmark_index + 1, len(entries) - 1)
        elif key_matches(key, "k", curses.KEY_UP, ord("k")) and entries:
            state.bookmark_index = max(state.bookmark_index - 1, 0)
        elif key_matches(key, "\n", "\r", 10, 13, curses.KEY_ENTER) and entries:
            state.jump_to_bookmark()
        return True
    if state.deep_analysis_open:
        if key_matches(key, 27, "\x1b", 3, "\x03"):
            state.deep_analysis_open = False
            state.message = "Closed deep path analysis."
        elif key_matches(key, "j", curses.KEY_DOWN, ord("j")):
            state.deep_analysis_scroll += 1
        elif key_matches(key, "k", curses.KEY_UP, ord("k")):
            state.deep_analysis_scroll = max(0, state.deep_analysis_scroll - 1)
        elif key_matches(key, "D", ord("D")):
            state.start_deep_analysis(force=True)
        return True
    if state.trash_confirmation:
        if key_matches(key, 27, "\x1b", 3, "\x03"):
            state.cancel_trash_confirmation()
        elif key_matches(key, "y", "Y", ord("y"), ord("Y")):
            state.execute_confirmed_trash()
        else:
            state.message = "Confirmation is waiting. Press y to move the exact path, or Esc to cancel."
        return True
    if state.help_open:
        state.help_open = False
        return True
    if state.ai_busy and key_matches(key, 27, "\x1b", 3, "\x03"):
        state.vim_pending_g = False
        state.cancel_ai()
        return True
    if state.vim_pending_g:
        state.vim_pending_g = False
        if key_matches(key, "g", ord("g")):
            visible = state.visible()
            if visible:
                state.select_index(0)
                state.message = "Moved to the top of the visible tree."
            return True
        if key_matches(key, "t", ord("t")):
            state.switch_tab(1)
            return True
        if key_matches(key, "T", ord("T")):
            state.switch_tab(-1)
            return True
        state.message = "Vim prefix cancelled. Use gg, gt, or gT."
        return True
    if state.vim_pending_d:
        state.vim_pending_d = False
        if key_matches(key, "d", ord("d")):
            state.queue_selected_for_cleanup()
        else:
            state.message = "dd cancelled. Nothing was moved."
        return True
    visible = state.visible()
    if key_matches(key, "q", "Q", ord("q"), ord("Q")):
        return False
    if key_matches(key, "?", ord("?")):
        state.vim_pending_g = False
        state.help_open = True
        return True
    if key_matches(key, "u", "U", ord("u"), ord("U")):
        state.undo_last_cleanup()
        return True
    if key_matches(key, "/", ord("/")):
        state.begin_search()
        return True
    if key_matches(key, "f", ord("f")):
        state.begin_filter()
        return True
    if key_matches(key, "s", ord("s")):
        state.begin_sort()
        return True
    if key_matches(key, "T", ord("T")):
        state.begin_tag_edit()
        return True
    if key_matches(key, "N", ord("N")):
        state.open_new_tab()
        return True
    if key_matches(key, "X", ord("X")):
        state.close_tab()
        return True
    if not visible:
        return True
    current_index = next((i for i, node in enumerate(visible) if node.get("node_id") == state.selected_id), 0)
    if key_matches(key, curses.KEY_UP, "k", ord("k")):
        state.select_index(current_index - 1)
    elif key_matches(key, curses.KEY_DOWN, "j", ord("j")):
        state.select_index(current_index + 1)
    elif key_matches(key, curses.KEY_LEFT, "h", ord("h")):
        current = visible[current_index]
        node_id = str(current.get("node_id"))
        if current.get("kind") == "folder" and node_id in state.expanded:
            state.expanded.remove(node_id)
            state.message = f"Closed {display_node_name(current)}"
        elif current.get("parent_id"):
            parent_index = next((index for index, item in enumerate(visible) if item.get("node_id") == current.get("parent_id")), current_index)
            state.select_index(parent_index)
            state.message = "Moved to the parent folder."
    elif key_matches(key, curses.KEY_RIGHT, "l", ord("l")):
        current = visible[current_index]
        node_id = str(current.get("node_id"))
        children = state.load_children(current) if current.get("kind") == "folder" else []
        if current.get("kind") == "folder" and children and node_id not in state.expanded:
            state.expanded.add(node_id)
            state.message = f"Opened {display_node_name(current)}"
        elif children:
            child_index = next((index for index, item in enumerate(visible) if item.get("node_id") == children[0].get("node_id")), current_index)
            state.select_index(child_index)
            state.message = "Moved to the first item inside the folder."
    elif key_matches(key, "\n", "\r", " ", 10, 13, curses.KEY_ENTER, ord(" ")):
        current = visible[current_index]
        state.open_or_close(current)
    elif key_matches(key, "G", ord("G")):
        state.select_index(len(visible) - 1)
        state.message = "Moved to the bottom of the visible tree."
    elif key_matches(key, curses.KEY_HOME):
        state.select_index(0)
        state.message = "Moved to the top of the visible tree."
    elif key_matches(key, curses.KEY_END):
        state.select_index(len(visible) - 1)
        state.message = "Moved to the bottom of the visible tree."
    elif key_matches(key, curses.KEY_PPAGE):
        state.select_index(current_index - max(1, page_size - 1))
    elif key_matches(key, curses.KEY_NPAGE):
        state.select_index(current_index + max(1, page_size - 1))
    elif key_matches(key, "g", ord("g")):
        state.vim_pending_g = True
        state.message = "Press g again to move to the top."
    elif key_matches(key, "d", ord("d")):
        state.vim_pending_d = True
        state.message = "Press d again to stage the selected path. Nothing will move yet."
    elif key_matches(key, "t", ord("t")):
        state.launch_selected("terminal")
    elif key_matches(key, "v", ord("v")):
        state.launch_selected("vscode")
    elif key_matches(key, "c", ord("c")):
        state.launch_selected("cursor")
    elif key_matches(key, "o", ord("o")):
        state.launch_selected("finder")
    elif key_matches(key, "m", ord("m")):
        state.toggle_bookmark()
    elif key_matches(key, "M", ord("M")):
        state.open_bookmarks()
    elif key_matches(key, "w", ord("w")):
        state.save_last_workspace()
    elif key_matches(key, "W", ord("W")):
        state.restore_last_workspace()
    elif key_matches(key, "D", ord("D")):
        state.start_deep_analysis()
    elif key_matches(key, "Y", ord("Y")):
        state.begin_trash_confirmation()
    elif key_matches(key, "a", "A", ord("a"), ord("A")):
        begin_question(stdscr, state)
    elif key_matches(key, "C", ord("C")):
        if state.prompt:
            state.message = copy_to_clipboard(state.prompt)
        else:
            state.message = "Ask a question first so there is AI context to copy."
    elif key_matches(key, "r", "R", ord("r"), ord("R")):
        current = visible[current_index]
        if current.get("kind") == "file":
            state.preview_cache.pop(str(current.get("node_id")), None)
            state.message = "File preview reloaded."
    return True


def app(
    stdscr: Any,
    report: dict[str, Any],
    expand_callback: Optional[Callable[[dict[str, Any]], tuple[list[dict[str, Any]], str]]] = None,
    rescan_callback: Optional[Callable[[Optional[Path]], dict[str, Any]]] = None,
) -> None:
    state = TuiState(report, expand_callback, rescan_callback)
    stdscr.keypad(True)
    stdscr.timeout(100)
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)
    except curses.error:
        pass
    setup_palette(stdscr)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    while True:
        state.poll_ai()
        state.poll_deep_analysis()
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        draw_header(stdscr, state, width)
        footer_height = 3
        content_top = 6
        content_height = max(4, height - content_top - footer_height)
        tree_y = content_top
        if width >= 76:
            list_width = max(32, width * 52 // 100)
            tree_height = content_height
            tree_width = list_width - 2
            draw_tree(stdscr, state, tree_y, tree_height, tree_width)
            draw_vertical_divider(stdscr, content_top, content_height, list_width - 1)
            inspector_x = list_width + 1
            inspector_y = content_top
            inspector_width = width - list_width - 2
            draw_inspector(stdscr, state, inspector_y, content_height, inspector_x, inspector_width)
        else:
            list_height = max(4, content_height // 2)
            tree_height = list_height
            tree_width = width - 1
            draw_tree(stdscr, state, tree_y, tree_height, tree_width)
            add_text(stdscr, content_top + list_height, 0, "-" * max(0, width), width, palette("rule"))
            inspector_x = 0
            inspector_y = content_top + list_height + 1
            inspector_width = width - 1
            draw_inspector(stdscr, state, inspector_y, content_height - list_height - 1, inspector_x, inspector_width)
        if state.question_editing:
            draw_question_box(stdscr, state, inspector_y, inspector_x, inspector_width)
            footer = "ENTER send question   ESC/Ctrl-C cancel   Q remains part of the question"
        elif state.search_editing:
            footer = "ENTER apply search   ESC cancel   Ctrl-U clear"
        elif state.tag_editing:
            footer = "ENTER save tags   ESC cancel   comma separates tags"
        elif state.filter_open:
            footer = "j/k choose filter   ENTER apply   ESC close"
        elif state.sort_open:
            footer = "j/k choose sort   ENTER apply   ESC close"
        elif state.trash_confirmation:
            footer = "y confirm move to system Trash   ESC cancel"
        elif state.bookmark_open:
            footer = "j/k move bookmark   ENTER open   ESC close"
        elif state.deep_analysis_open:
            footer = "j/k scroll analysis   D rerun   ESC close"
        elif state.ai_busy:
            footer = "ESC/Ctrl-C stop Codex   UP/DOWN keep moving   Q quit"
        else:
            footer = "dd stage   Y review   y confirm Trash   u undo   Press ? for help."
        add_text(stdscr, height - 2, 0, state.message, width, curses.A_DIM | palette("muted"))
        add_text(stdscr, height - 1, 0, footer, width, curses.A_DIM | palette("muted"))
        if state.help_open:
            draw_help(stdscr, width, height)
        elif state.search_editing:
            draw_input_box(stdscr, "SEARCH  fuzzy across names, paths, areas, and tags", state.search_buffer, "Enter apply    Esc cancel", width, height)
        elif state.tag_editing:
            draw_tag_box(stdscr, state, width, height)
        elif state.filter_open:
            draw_choice_menu(stdscr, "FILTER AREAS", FILTER_OPTIONS, state.filter_index, width, height)
        elif state.sort_open:
            draw_choice_menu(stdscr, "SORT SIBLINGS", SORT_OPTIONS, state.sort_index, width, height)
        elif state.trash_confirmation:
            draw_trash_confirmation(stdscr, state, width, height)
        elif state.bookmark_open:
            draw_bookmarks(stdscr, state, width, height)
        elif state.deep_analysis_open:
            draw_deep_analysis(stdscr, state, width, height)
        stdscr.refresh()
        try:
            key = stdscr.get_wch()
        except curses.error:
            key = None
        if key is not None:
            if key_matches(key, curses.KEY_MOUSE) and not state.question_editing and not state.search_editing and not state.tag_editing and not state.filter_open and not state.sort_open and not state.help_open and not state.bookmark_open and not state.deep_analysis_open and not state.trash_confirmation:
                handle_mouse(state, tree_y, tree_height, tree_width)
            elif not handle_key(stdscr, state, key, width, tree_height):
                return


def setup_palette(stdscr: Any) -> None:
    global PALETTE
    PALETTE = {}
    if not curses.has_colors():
        return
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_GREEN, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_GREEN, -1)
        curses.init_pair(6, curses.COLOR_MAGENTA, -1)
        curses.init_pair(7, curses.COLOR_RED, -1)
        PALETTE = {
            "title": curses.color_pair(1),
            "folder": curses.color_pair(2),
            "status": curses.color_pair(3),
            "selected": curses.color_pair(4),
            "answer": curses.color_pair(5),
            "basket": curses.color_pair(6),
            "danger": curses.color_pair(7),
            "muted": 0,
            "rule": curses.color_pair(1),
        }
    except curses.error:
        PALETTE = {}


def run_tui(
    report: dict[str, Any],
    expand_callback: Optional[Callable[[dict[str, Any]], tuple[list[dict[str, Any]], str]]] = None,
    rescan_callback: Optional[Callable[[Optional[Path]], dict[str, Any]]] = None,
) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("The terminal explorer needs an interactive terminal. Use --format json for a non-interactive report.", file=sys.stderr)
        return 2
    try:
        curses.wrapper(app, report, expand_callback, rescan_callback)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    print("Run audit_local_files.py --tui so the scanner can prepare the report first.", file=sys.stderr)
    raise SystemExit(2)
