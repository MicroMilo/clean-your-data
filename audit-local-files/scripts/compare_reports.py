#!/usr/bin/env python3
"""Compare two JSON reports produced by audit_local_files.py."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def human_size(value: Optional[int]) -> str:
    if value is None:
        return "unknown"
    sign = "-" if value < 0 else ""
    number = float(abs(value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{sign}{int(number)} {unit}"
            return f"{sign}{number:.1f} {unit}"
        number /= 1024.0
    return f"{sign}{number:.1f} TB"


def load_report(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON report {path}: {exc}") from exc
    if not isinstance(data, dict) or "target_areas" not in data:
        raise ValueError(f"not an audit report: {path}")
    return data


def rows_by_path(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("path")): row for row in rows if row.get("path")}


def diff_rows(before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before = rows_by_path(before_rows)
    after = rows_by_path(after_rows)
    result: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path, {})
        new = after.get(path, {})
        old_size = old.get("allocated_bytes")
        new_size = new.get("allocated_bytes")
        old_status = old.get("measurement_status", "measured" if isinstance(old_size, int) else "unknown")
        new_status = new.get("measurement_status", "measured" if isinstance(new_size, int) else "unknown")
        if path not in before and isinstance(new_size, int):
            old_size = 0
            old_status = "missing"
        if path not in after and isinstance(old_size, int):
            new_size = 0
            new_status = "missing"
        incomplete_statuses = {"timeout", "error", "unknown"}
        if old_status in incomplete_statuses or new_status in incomplete_statuses:
            result.append(
                {
                    "path": path,
                    "label": new.get("label") or old.get("label") or new.get("name") or old.get("name") or "",
                    "category": new.get("category") or old.get("category") or "",
                    "before_bytes": old_size if isinstance(old_size, int) else None,
                    "after_bytes": new_size if isinstance(new_size, int) else None,
                    "delta_bytes": None,
                    "before": human_size(old_size if isinstance(old_size, int) else None),
                    "after": human_size(new_size if isinstance(new_size, int) else None),
                    "delta": "unknown",
                    "status": "incomplete",
                    "measurement_status_before": old_status,
                    "measurement_status_after": new_status,
                }
            )
            continue
        if not isinstance(old_size, int) or not isinstance(new_size, int):
            continue
        delta = new_size - old_size
        if delta == 0:
            continue
        result.append(
            {
                "path": path,
                "label": new.get("label") or old.get("label") or new.get("name") or old.get("name") or "",
                "category": new.get("category") or old.get("category") or "",
                "before_bytes": old_size,
                "after_bytes": new_size,
                "delta_bytes": delta,
                "before": human_size(old_size),
                "after": human_size(new_size),
                "delta": human_size(delta),
                "status": "new" if path not in before else "removed" if path not in after else "changed",
                "measurement_status_before": old_status,
                "measurement_status_after": new_status,
            }
        )
    return sorted(result, key=lambda row: abs(row["delta_bytes"] or 0), reverse=True)


def diff_buckets(before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before = {str(row.get("bucket")): row for row in before_rows if row.get("bucket")}
    after = {str(row.get("bucket")): row for row in after_rows if row.get("bucket")}
    result: list[dict[str, Any]] = []
    for bucket in sorted(set(before) | set(after)):
        old = before.get(bucket, {})
        new = after.get(bucket, {})
        row = {
            "bucket": bucket,
            "repo_delta": int(new.get("repo_count", 0)) - int(old.get("repo_count", 0)),
            "dirty_repo_delta": int(new.get("dirty_repo_count", 0)) - int(old.get("dirty_repo_count", 0)),
            "dirty_change_delta": int(new.get("dirty_change_count", 0)) - int(old.get("dirty_change_count", 0)),
        }
        if any(row[key] for key in ("repo_delta", "dirty_repo_delta", "dirty_change_delta")):
            result.append(row)
    return sorted(result, key=lambda row: abs(row["dirty_change_delta"]) + abs(row["repo_delta"]), reverse=True)


def diff_coverage(before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before = {str(row.get("label")): row for row in before_rows if row.get("label")}
    after = {str(row.get("label")): row for row in after_rows if row.get("label")}
    result: list[dict[str, Any]] = []
    for label in sorted(set(before) | set(after)):
        old = before.get(label, {})
        new = after.get(label, {})
        old_status = old.get("status", "not_found")
        new_status = new.get("status", "not_found")
        old_bytes = old.get("measured_bytes")
        new_bytes = new.get("measured_bytes")
        delta = new_bytes - old_bytes if isinstance(old_bytes, int) and isinstance(new_bytes, int) and old_status == new_status == "measured" else None
        if old_status != new_status or delta not in (None, 0):
            result.append(
                {
                    "label": label,
                    "before_status": old_status,
                    "after_status": new_status,
                    "delta_bytes": delta,
                    "delta": human_size(delta),
                }
            )
    return result


def diff_duplicates(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_duplicates = before.get("duplicates") or {}
    after_duplicates = after.get("duplicates") or {}
    before_groups = {
        str(row.get("duplicate_group_id")): row
        for row in before_duplicates.get("groups", [])
        if row.get("duplicate_group_id")
    }
    after_groups = {
        str(row.get("duplicate_group_id")): row
        for row in after_duplicates.get("groups", [])
        if row.get("duplicate_group_id")
    }
    before_bytes = before_duplicates.get("potential_duplicate_bytes")
    after_bytes = after_duplicates.get("potential_duplicate_bytes")
    both_complete = before_duplicates.get("status") == after_duplicates.get("status") == "complete"
    return {
        "before_enabled": bool(before_duplicates.get("enabled")),
        "after_enabled": bool(after_duplicates.get("enabled")),
        "before_status": before_duplicates.get("status", "unknown"),
        "after_status": after_duplicates.get("status", "unknown"),
        "before_group_count": len(before_groups),
        "after_group_count": len(after_groups),
        "group_delta": len(after_groups) - len(before_groups),
        "before_potential_duplicate_bytes": before_bytes if isinstance(before_bytes, int) else None,
        "after_potential_duplicate_bytes": after_bytes if isinstance(after_bytes, int) else None,
        "potential_duplicate_delta_bytes": after_bytes - before_bytes if both_complete and isinstance(before_bytes, int) and isinstance(after_bytes, int) else None,
        "added_groups": sorted(set(after_groups) - set(before_groups)),
        "removed_groups": sorted(set(before_groups) - set(after_groups)),
    }


def diff_space_map(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_map = before.get("space_map") or {}
    after_map = after.get("space_map") or {}
    before_roots = set(str(item) for item in before_map.get("roots", []) if item)
    after_roots = set(str(item) for item in after_map.get("roots", []) if item)
    return {
        "before_enabled": bool(before_map.get("enabled")),
        "after_enabled": bool(after_map.get("enabled")),
        "before_status": before_map.get("status", "unknown"),
        "after_status": after_map.get("status", "unknown"),
        "before_node_count": int(before_map.get("node_count", len(before_map.get("nodes", [])))),
        "after_node_count": int(after_map.get("node_count", len(after_map.get("nodes", [])))),
        "node_delta": int(after_map.get("node_count", len(after_map.get("nodes", []))))
        - int(before_map.get("node_count", len(before_map.get("nodes", [])))),
        "added_roots": sorted(after_roots - before_roots),
        "removed_roots": sorted(before_roots - after_roots),
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_disk = before.get("disk", {})
    after_disk = after.get("disk", {})
    used_before = before_disk.get("used_bytes")
    used_after = after_disk.get("used_bytes")
    free_before = before_disk.get("free_bytes")
    free_after = after_disk.get("free_bytes")
    disk = {
        "used_delta_bytes": used_after - used_before if isinstance(used_before, int) and isinstance(used_after, int) else None,
        "free_delta_bytes": free_after - free_before if isinstance(free_before, int) and isinstance(free_after, int) else None,
    }
    before_codex = before.get("codex") or {}
    after_codex = after.get("codex") or {}
    codex = {
        key: int(after_codex.get(key, 0)) - int(before_codex.get(key, 0))
        for key in ("date_dir_count", "work_dir_count", "outputs_dir_count")
    }
    return {
        "schema_version": "1.3",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "before_generated_at": before.get("generated_at"),
        "after_generated_at": after.get("generated_at"),
        "redaction": {
            "before": (before.get("settings") or {}).get("redact", True),
            "after": (after.get("settings") or {}).get("redact", True),
            "origins_included": bool((before.get("settings") or {}).get("include_git_origins"))
            or bool((after.get("settings") or {}).get("include_git_origins")),
        },
        "disk": disk,
        "target_areas": diff_rows(before.get("target_areas", []), after.get("target_areas", [])),
        "coverage": diff_coverage(before.get("coverage", []), after.get("coverage", [])),
        "codex": codex,
        "git_buckets": diff_buckets(
            (before.get("git") or {}).get("buckets", []),
            (after.get("git") or {}).get("buckets", []),
        ),
        "artifacts": diff_rows(before.get("artifacts", []), after.get("artifacts", [])),
        "duplicates": diff_duplicates(before, after),
        "space_map": diff_space_map(before, after),
        "action_gate": {
            "before": (before.get("action_gate") or {}).get("status", "unknown"),
            "after": (after.get("action_gate") or {}).get("status", "unknown"),
        },
    }


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Local Audit Comparison",
        "",
        f"Before: `{result.get('before_generated_at') or 'unknown'}`",
        f"After: `{result.get('after_generated_at') or 'unknown'}`",
        "",
        "This comparison uses report metadata only. It does not read local file contents.",
        "",
        "## Change Summary",
        "",
    ]
    disk = result["disk"]
    lines.append(f"- Disk used: `{human_size(disk['used_delta_bytes'])}`")
    lines.append(f"- Disk free: `{human_size(disk['free_delta_bytes'])}`")
    codex = result["codex"]
    lines.append(
        "- Codex counts: "
        f"date dirs `{codex['date_dir_count']:+d}`, "
        f"work `{codex['work_dir_count']:+d}`, "
        f"outputs `{codex['outputs_dir_count']:+d}`"
    )
    lines.append(f"- Action gate: `{result['action_gate']['before']}` -> `{result['action_gate']['after']}`")
    if result["redaction"]["origins_included"]:
        lines.append("- Privacy warning: one input report included Git origins; keep this comparison private.")
    lines.append("")
    if result["coverage"]:
        lines.append("## Coverage Changes")
        lines.append("")
        rows = [
            [row["before_status"], row["after_status"], row["delta"], row["label"]]
            for row in result["coverage"][:20]
        ]
        lines.append(markdown_table(["Before", "After", "Measured change", "Target"], rows))
        lines.append("")
    lines.append("## Largest Target Changes")
    lines.append("")
    rows = [
        [row["delta"], row["status"], row["category"], f"`{row['path']}`", row["label"]]
        for row in result["target_areas"][:20]
    ]
    lines.append(markdown_table(["Change", "Status", "Category", "Path", "Label"], rows) or "No measured target-area changes.")
    lines.append("")
    if result["git_buckets"]:
        lines.append("## Git Changes")
        lines.append("")
        rows = [
            [row["bucket"], f"{row['repo_delta']:+d}", f"{row['dirty_repo_delta']:+d}", f"{row['dirty_change_delta']:+d}"]
            for row in result["git_buckets"][:20]
        ]
        lines.append(markdown_table(["Bucket", "Repos", "Dirty Repos", "Dirty Changes"], rows))
        lines.append("")
    if result["artifacts"]:
        lines.append("## Artifact Changes")
        lines.append("")
        rows = [
            [row["delta"], row["status"], row["label"], f"`{row['path']}`"]
            for row in result["artifacts"][:20]
        ]
        lines.append(markdown_table(["Change", "Status", "Name", "Path"], rows))
        lines.append("")
    duplicates = result.get("duplicates") or {}
    lines.append("## Exact Duplicate Changes")
    lines.append("")
    lines.append(
        f"- Scan: `{duplicates.get('before_status', 'unknown')}` -> `{duplicates.get('after_status', 'unknown')}`; groups `{duplicates.get('before_group_count', 0)}` -> `{duplicates.get('after_group_count', 0)}`"
    )
    lines.append(f"- Potential logical bytes: `{human_size(duplicates.get('potential_duplicate_delta_bytes'))}`")
    if duplicates.get("added_groups"):
        lines.append(f"- New opaque group IDs: {', '.join(f'`{item}`' for item in duplicates['added_groups'][:20])}")
    if duplicates.get("removed_groups"):
        lines.append(f"- Removed opaque group IDs: {', '.join(f'`{item}`' for item in duplicates['removed_groups'][:20])}")
    lines.append("")
    space_map = result.get("space_map") or {}
    lines.append("## Interactive Map")
    lines.append("")
    lines.append(
        f"- Status: `{space_map.get('before_status', 'unknown')}` -> `{space_map.get('after_status', 'unknown')}`; "
        f"areas `{space_map.get('before_node_count', 0)}` -> `{space_map.get('after_node_count', 0)}`"
    )
    if space_map.get("added_roots"):
        lines.append(f"- Newly selected roots: {', '.join(f'`{item}`' for item in space_map['added_roots'][:20])}")
    if space_map.get("removed_roots"):
        lines.append(f"- Roots no longer selected: {', '.join(f'`{item}`' for item in space_map['removed_roots'][:20])}")
    lines.append("")
    lines.extend(
        [
            "## Suggested Review",
            "",
            "Review the largest increases first. Confirm whether each change is a durable deliverable, active work, app-managed state, synchronized data, or a rebuildable artifact before taking action.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two Clean Your Data JSON reports.")
    parser.add_argument("before", type=Path, help="Earlier JSON audit report.")
    parser.add_argument("after", type=Path, help="Later JSON audit report.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", type=Path, help="Write comparison to this path.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        result = compare(load_report(args.before), load_report(args.after))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    output = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else render_markdown(result)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
