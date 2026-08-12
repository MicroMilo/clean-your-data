"""Trace a local command and report metadata-only file changes.

This is a bounded, opt-in observer. It does not read file contents, inspect
environment variables, or claim kernel-level process attribution. Changes are
associated with the traced command because they were observed in its scope
while that command was running.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import sqlite3
import stat as stat_module
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence


TRACE_SCHEMA_VERSION = "1.0"
DEFAULT_INTERVAL_SECONDS = 0.5
DEFAULT_MAX_ENTRIES = 20_000
TRACE_STATE_ENV = "CLEAN_YOUR_DATA_STATE_DIR"
TRACE_DB_NAME = "provenance.sqlite3"


@dataclass(frozen=True)
class EntryState:
    """The small set of stat fields needed to detect a local change."""

    kind: str
    size: Optional[int]
    mtime_ns: Optional[int]
    mode: int
    inode: int


@dataclass
class Snapshot:
    entries: dict[str, EntryState]
    roots: list[Path]
    scanned_entries: int
    skipped_paths: list[str]
    limited: bool


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def session_id() -> str:
    return "trace-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


def entry_state(stat_result: os.stat_result) -> EntryState:
    mode = stat_result.st_mode
    if stat_module.S_ISDIR(mode):
        kind = "folder"
        size: Optional[int] = None
    elif stat_module.S_ISREG(mode):
        kind = "file"
        size = int(stat_result.st_size)
    elif stat_module.S_ISLNK(mode):
        kind = "symlink"
        size = int(stat_result.st_size)
    else:
        kind = "other"
        size = int(stat_result.st_size)
    return EntryState(
        kind=kind,
        size=size,
        mtime_ns=int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
        mode=int(mode & 0o7777),
        inode=int(getattr(stat_result, "st_ino", 0)),
    )


def snapshot(roots: Sequence[Path], max_entries: int) -> Snapshot:
    """Walk roots without following symlinks or reading file contents."""
    entries: dict[str, EntryState] = {}
    skipped: list[str] = []
    limited = False
    pending: list[Path] = list(reversed(list(roots)))

    while pending:
        path = pending.pop()
        key = str(path)
        if key in entries:
            continue
        if len(entries) >= max_entries:
            limited = True
            break
        try:
            stat_result = path.lstat()
        except OSError as exc:
            if len(skipped) < 30:
                skipped.append(f"{path}: {exc}")
            continue
        state = entry_state(stat_result)
        entries[key] = state
        if state.kind != "folder":
            continue
        try:
            children = sorted(path.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            if len(skipped) < 30:
                skipped.append(f"{path}: {exc}")
            continue
        for child in reversed(children):
            if len(entries) + len(pending) >= max_entries:
                limited = True
                break
            pending.append(child)

    return Snapshot(
        entries=entries,
        roots=list(roots),
        scanned_entries=len(entries),
        skipped_paths=skipped,
        limited=limited,
    )


def normalize_roots(raw_roots: Sequence[str], cwd: Path) -> list[Path]:
    requested = [Path(value).expanduser() for value in raw_roots] or [cwd]
    roots: list[Path] = []
    for path in requested:
        try:
            resolved = path.resolve()
        except RuntimeError as exc:
            raise ValueError(f"trace path could not be resolved: {path}") from exc
        if not resolved.exists():
            raise ValueError(f"trace path does not exist: {path}")
        if resolved not in roots:
            roots.append(resolved)
    return roots


def state_dict(state: Optional[EntryState]) -> Optional[dict[str, Any]]:
    if state is None:
        return None
    return {
        "kind": state.kind,
        "size": state.size,
        "mtime_ns": state.mtime_ns,
        "mode": oct(state.mode),
        "inode": state.inode,
    }


def changed_fields(before: EntryState, after: EntryState) -> list[str]:
    fields: list[str] = []
    if before.kind != after.kind:
        fields.append("kind")
    if before.size != after.size:
        fields.append("size")
    if before.mtime_ns != after.mtime_ns:
        fields.append("modified time")
    if before.mode != after.mode:
        fields.append("permissions")
    if before.inode != after.inode:
        fields.append("inode")
    return fields


def record_event(
    events: dict[str, dict[str, Any]],
    path: str,
    event_type: str,
    before: Optional[EntryState],
    after: Optional[EntryState],
    observed_at: str,
    fields: Optional[list[str]] = None,
) -> None:
    event = events.get(path)
    if event is None:
        event = {
            "absolute_path": path,
            "kind": (after or before).kind if (after or before) else "unknown",
            "event_types": [],
            "changed_fields": [],
            "first_observed_at": observed_at,
            "last_observed_at": observed_at,
            "before": state_dict(before),
            "after": state_dict(after),
        }
        events[path] = event
    if event_type not in event["event_types"]:
        event["event_types"].append(event_type)
    if fields:
        for field in fields:
            if field not in event["changed_fields"]:
                event["changed_fields"].append(field)
    event["last_observed_at"] = observed_at
    event["after"] = state_dict(after)
    if after is not None:
        event["kind"] = after.kind


def observe_delta(
    previous: Snapshot,
    current: Snapshot,
    baseline: Snapshot,
    events: dict[str, dict[str, Any]],
) -> None:
    observed_at = timestamp()
    paths = sorted(set(previous.entries) | set(current.entries))
    for path in paths:
        old = previous.entries.get(path)
        new = current.entries.get(path)
        before = baseline.entries.get(path)
        if old is None and new is not None:
            record_event(events, path, "created", before, new, observed_at)
            continue
        if old is not None and new is None:
            record_event(events, path, "deleted", before, None, observed_at)
            continue
        if old is None or new is None:
            continue
        fields = changed_fields(old, new)
        # Directory mtimes change when a child changes. Report the child event,
        # not every ancestor as a misleading file modification.
        if fields and not (old.kind == "folder" and new.kind == "folder"):
            record_event(events, path, "modified", before, new, observed_at, fields)


def display_path(path: str, roots: Sequence[Path], redact: bool) -> str:
    candidate = Path(path)
    for root in roots:
        try:
            relative = candidate.relative_to(root)
            return "." if not relative.parts else "./" + str(relative)
        except ValueError:
            continue
    if redact:
        home = Path.home().resolve()
        try:
            return "~/" + str(candidate.relative_to(home))
        except ValueError:
            return "<outside trace scope>"
    return str(candidate)


def public_event(event: dict[str, Any], roots: Sequence[Path], redact: bool) -> dict[str, Any]:
    result = dict(event)
    absolute = result.pop("absolute_path")
    result["path"] = display_path(absolute, roots, redact)
    return result


def public_report(report: dict[str, Any], roots: Sequence[Path], redact: bool) -> dict[str, Any]:
    result = dict(report)
    session = dict(result["session"])
    if redact:
        home_text = str(Path.home().resolve())
        session["command"] = [str(item).replace(home_text, "~") for item in session["command"]]
    session["cwd"] = display_path(str(Path(session["cwd"]).resolve()), roots, redact)
    session["scope_roots"] = [display_path(str(root), roots, redact) for root in roots]
    result["session"] = session
    observation = dict(result["observation"])
    safe_skipped: list[str] = []
    for item in observation.get("skipped_paths") or []:
        path_text, separator, detail = str(item).partition(": ")
        shown_path = display_path(path_text, roots, redact)
        safe_skipped.append(f"{shown_path}{separator}{detail}" if separator else shown_path)
    observation["skipped_paths"] = safe_skipped
    result["observation"] = observation
    result["events"] = [public_event(event, roots, redact) for event in report["events"]]
    return result


def persist_trace(
    report: dict[str, Any],
    store_path: Path,
) -> Optional[str]:
    """Persist local provenance records without sending them anywhere."""
    try:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(store_path.parent, 0o700)
        except OSError:
            pass
        descriptor = os.open(store_path, os.O_CREAT | os.O_APPEND, 0o600)
        os.close(descriptor)
        try:
            os.chmod(store_path, 0o600)
        except OSError:
            pass
        with sqlite3.connect(store_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    roots_json TEXT NOT NULL,
                    return_code INTEGER,
                    observed_count INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    event_types_json TEXT NOT NULL,
                    changed_fields_json TEXT NOT NULL,
                    first_observed_at TEXT NOT NULL,
                    last_observed_at TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    FOREIGN KEY(session_id) REFERENCES trace_sessions(session_id)
                )
                """
            )
            session = report["session"]
            connection.execute(
                """
                INSERT OR REPLACE INTO trace_sessions
                (session_id, started_at, finished_at, command_json, cwd, roots_json, return_code, observed_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["id"],
                    session["started_at"],
                    session["finished_at"],
                    json.dumps(session["command"], ensure_ascii=False),
                    session["cwd"],
                    json.dumps(session["scope_roots"], ensure_ascii=False),
                    session["return_code"],
                    len(report["events"]),
                ),
            )
            connection.execute("DELETE FROM trace_events WHERE session_id = ?", (session["id"],))
            for event in report["events"]:
                connection.execute(
                    """
                    INSERT INTO trace_events
                    (session_id, path, kind, event_types_json, changed_fields_json,
                     first_observed_at, last_observed_at, before_json, after_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session["id"],
                        event["absolute_path"],
                        event["kind"],
                        json.dumps(event["event_types"], ensure_ascii=False),
                        json.dumps(event["changed_fields"], ensure_ascii=False),
                        event["first_observed_at"],
                        event["last_observed_at"],
                        json.dumps(event["before"], ensure_ascii=False) if event["before"] else None,
                        json.dumps(event["after"], ensure_ascii=False) if event["after"] else None,
                    ),
                )
    except (OSError, sqlite3.Error) as exc:
        return str(exc)
    return None


def run_trace(
    command: Sequence[str],
    roots: Sequence[Path],
    cwd: Path,
    interval: float,
    max_entries: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started_at = timestamp()
    started = time.monotonic()
    trace_id = session_id()
    before = snapshot(roots, max_entries)
    events: dict[str, dict[str, Any]] = {}
    process: Optional[subprocess.Popen[bytes]] = None
    interrupted = False
    return_code: Optional[int] = None
    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            start_new_session=(os.name != "nt"),
        )
        previous = before
        while True:
            return_code = process.poll()
            if return_code is not None:
                break
            time.sleep(interval)
            current = snapshot(roots, max_entries)
            observe_delta(previous, current, before, events)
            previous = current
        after = snapshot(roots, max_entries)
        observe_delta(previous, after, before, events)
    except KeyboardInterrupt:
        interrupted = True
        if process is not None and process.poll() is None:
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except OSError:
                pass
            process.wait()
        return_code = 130
        after = snapshot(roots, max_entries)
        observe_delta(before, after, before, events)
    except OSError:
        raise

    finished_at = timestamp()
    report = {
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "session": {
            "id": trace_id,
            "command": list(command),
            "cwd": str(cwd),
            "scope_roots": [str(root) for root in roots],
            "pid": process.pid if process is not None else None,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(time.monotonic() - started, 3),
            "return_code": return_code,
            "interrupted": interrupted,
        },
        "observation": {
            "method": "metadata snapshots while the traced command runs",
            "attribution": "associated with the traced command; not kernel-level proof",
            "interval_seconds": interval,
            "max_entries": max_entries,
            "before_entries": before.scanned_entries,
            "after_entries": after.scanned_entries,
            "limited": before.limited or after.limited,
            "skipped_paths": before.skipped_paths[:15] + after.skipped_paths[:15],
        },
        "events": sorted(events.values(), key=lambda item: item["absolute_path"]),
    }
    return report, {"before": before, "after": after}


def render_text(report: dict[str, Any], roots: Sequence[Path], redact: bool, store_path: Optional[Path], store_error: Optional[str]) -> str:
    public = public_report(report, roots, redact)
    session = public["session"]
    observation = public["observation"]
    lines = [
        "CLEAN YOUR DATA / TRACE",
        f"Session: {session['id']}",
        f"Command: {shlex.join(session['command'])}",
        f"Scope: {', '.join(session['scope_roots'])}",
        f"Result: exit {session['return_code']}  |  {session['duration_seconds']}s  |  {len(public['events'])} changed path(s)",
        "",
        "ATTRIBUTION",
        "Changes below were observed inside the selected scope while this command was running.",
        "This is evidence of association, not kernel-level proof of the exact writer process.",
        "",
    ]
    if not public["events"]:
        lines.append("No changed paths were observed.")
    else:
        for event in public["events"]:
            types = "+".join(event["event_types"]).upper()
            details = f" [{', '.join(event['changed_fields'])}]" if event["changed_fields"] else ""
            lines.append(f"{types:<18} {event['path']} ({event['kind']}){details}")
    lines.extend(
        [
            "",
            "OBSERVATION",
            f"Metadata entries: {observation['before_entries']} before, {observation['after_entries']} after",
            f"Polling interval: {observation['interval_seconds']}s",
        ]
    )
    if observation["limited"]:
        lines.append("Warning: the snapshot reached its entry limit; this trace is partial.")
    if observation["skipped_paths"]:
        lines.append(f"Warning: {len(observation['skipped_paths'])} paths could not be read.")
    if store_path and not store_error:
        lines.append(f"Saved locally: {display_path(str(store_path), roots, redact)}")
    elif store_error:
        lines.append(f"Could not save the local trace record: {store_error}")
    return "\n".join(lines)


def state_dir() -> Path:
    configured = os.environ.get(TRACE_STATE_ENV, "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".clean-your-data"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cyd trace",
        description="Run a local command and record metadata-only file changes in selected paths.",
    )
    parser.add_argument("--path", action="append", default=[], help="Directory or file to observe. May be repeated. Defaults to the command working directory.")
    parser.add_argument("--cwd", help="Working directory for the traced command. Defaults to the first --path or the current directory.")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS, help="Seconds between metadata snapshots. Defaults to 0.5.")
    parser.add_argument("--max-entries", type=int, default=DEFAULT_MAX_ENTRIES, help="Maximum entries per snapshot. Defaults to 20000.")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Trace report format.")
    parser.add_argument("--output", help="Write the report to this path instead of stdout.")
    parser.add_argument("--state-dir", help="Local directory for the provenance SQLite record.")
    parser.add_argument("--no-redact", action="store_true", help="Show absolute paths outside the selected scope.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after `--`, for example `codex` or `claude`.")
    args = parser.parse_args(list(argv))
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after `--`, for example: cyd trace -- codex")
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    if args.max_entries <= 0:
        parser.error("--max-entries must be greater than zero")
    args.command = command
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        requested_cwd = Path(args.cwd).expanduser().resolve() if args.cwd else None
        default_cwd = requested_cwd or Path.cwd().resolve()
        roots = normalize_roots(args.path, default_cwd)
        cwd = requested_cwd or (roots[0] if roots[0].is_dir() else roots[0].parent)
        if not cwd.is_dir():
            raise ValueError(f"trace working directory is not a directory: {cwd}")
        report, _ = run_trace(args.command, roots, cwd, args.interval, args.max_entries)
    except (OSError, ValueError) as exc:
        print(f"trace error: {exc}", file=sys.stderr)
        return 2

    store_root = Path(args.state_dir).expanduser() if args.state_dir else state_dir()
    store_path = store_root / TRACE_DB_NAME
    store_error = persist_trace(report, store_path)
    public = public_report(report, roots, not args.no_redact)
    public["store"] = {
        "saved": store_error is None,
        "path": display_path(str(store_path), roots, not args.no_redact),
    }
    if store_error:
        public["store"]["error"] = store_error if args.no_redact else "The local trace record could not be saved."

    if args.format == "json":
        output = json.dumps(public, ensure_ascii=False, indent=2)
    else:
        output = render_text(report, roots, not args.no_redact, store_path, store_error)
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
        try:
            os.chmod(output_path, 0o600)
        except OSError:
            pass
    else:
        print(output)
    return int(report["session"]["return_code"] or 0)


if __name__ == "__main__":
    raise SystemExit(main())
