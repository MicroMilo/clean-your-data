#!/usr/bin/env python3
"""Validate the Clean Your Data JSON report contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


MEASUREMENT_STATUSES = {"measured", "timeout", "error", "missing", "unknown"}
COVERAGE_STATUSES = MEASUREMENT_STATUSES | {"not_found"}
GATE_STATUSES = {"review_only", "approval_required"}
DUPLICATE_STATUSES = {"disabled", "complete", "timeout", "limit", "error", "not_found"}
SPACE_MAP_STATUSES = {"disabled", "complete", "partial", "limit", "not_found"}
SUPPORTED_SCHEMA_VERSIONS = {"1.1", "1.2", "1.3"}
FINDING_REQUIRED_FIELDS = {
    "finding_id",
    "scope_id",
    "path_redacted",
    "category",
    "owner",
    "size_bytes",
    "status",
    "evidence_refs",
    "confidence",
    "risk",
    "recommendation",
    "approval_required",
    "rollback_or_rebuild",
}


def validate(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema_version = report.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append("schema_version must be 1.1, 1.2, or 1.3")
    if report.get("read_only") is not True:
        errors.append("read_only must be true")
    settings = report.get("settings") or {}
    if settings.get("scope_id") != "home":
        errors.append("settings.scope_id must be home")
    if settings.get("size_kind") != "allocated_bytes":
        errors.append("settings.size_kind must be allocated_bytes")

    for index, row in enumerate(report.get("target_areas", [])):
        status = row.get("measurement_status")
        if status not in MEASUREMENT_STATUSES:
            errors.append(f"target_areas[{index}] has invalid measurement_status")
        if status != "measured" and row.get("allocated_bytes") is not None:
            errors.append(f"target_areas[{index}] must use null size when not measured")

    for index, row in enumerate(report.get("artifacts", [])):
        status = row.get("measurement_status")
        if status not in MEASUREMENT_STATUSES:
            errors.append(f"artifacts[{index}] has invalid measurement_status")
        if status != "measured" and row.get("allocated_bytes") is not None:
            errors.append(f"artifacts[{index}] must use null size when not measured")

    for index, row in enumerate(report.get("coverage", [])):
        if row.get("status") not in COVERAGE_STATUSES:
            errors.append(f"coverage[{index}] has invalid status")

    duplicates = report.get("duplicates")
    if schema_version in {"1.2", "1.3"}:
        if not isinstance(duplicates, dict):
            errors.append("duplicates must be an object in schema 1.2 or 1.3")
        else:
            duplicate_status = duplicates.get("status")
            if duplicate_status not in DUPLICATE_STATUSES:
                errors.append("duplicates.status is invalid")
            if duplicates.get("enabled") is not True and duplicate_status != "disabled":
                errors.append("disabled duplicate reports must use duplicates.status=disabled")
            if not isinstance(duplicates.get("groups", []), list):
                errors.append("duplicates.groups must be a list")
            for index, group in enumerate(duplicates.get("groups", [])):
                required = {
                    "duplicate_group_id",
                    "status",
                    "hash_algorithm",
                    "byte_kind",
                    "size_bytes",
                    "file_count",
                    "independent_copy_count",
                    "potential_duplicate_bytes",
                    "canonical_candidate_path",
                    "paths",
                }
                missing = sorted(required - set(group))
                if missing:
                    errors.append(f"duplicates.groups[{index}] missing: {', '.join(missing)}")
                if group.get("status") != "exact":
                    errors.append(f"duplicates.groups[{index}] must be exact")
                if group.get("hash_algorithm") != "sha256":
                    errors.append(f"duplicates.groups[{index}] must use sha256")
                if "digest" in group or "hash" in group:
                    errors.append(f"duplicates.groups[{index}] must not expose raw hashes")
                if not isinstance(group.get("paths"), list) or len(group.get("paths", [])) < 2:
                    errors.append(f"duplicates.groups[{index}].paths must contain at least two entries")

    if schema_version == "1.3":
        space_map = report.get("space_map")
        if not isinstance(space_map, dict):
            errors.append("space_map must be an object in schema 1.3")
        else:
            if not isinstance(space_map.get("enabled"), bool):
                errors.append("space_map.enabled must be boolean")
            if space_map.get("status") not in SPACE_MAP_STATUSES:
                errors.append("space_map.status is invalid")
            if not isinstance(space_map.get("nodes", []), list):
                errors.append("space_map.nodes must be a list")
            for index, node in enumerate(space_map.get("nodes", [])):
                required = {"node_id", "path", "kind", "allocated_bytes", "measurement_status"}
                missing = sorted(required - set(node))
                if missing:
                    errors.append(f"space_map.nodes[{index}] missing: {', '.join(missing)}")
                if node.get("measurement_status") not in MEASUREMENT_STATUSES:
                    errors.append(f"space_map.nodes[{index}] has invalid measurement_status")
                if node.get("measurement_status") != "measured" and node.get("allocated_bytes") is not None:
                    errors.append(f"space_map.nodes[{index}] must use null size when not measured")

    findings = report.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be a list")
    else:
        for index, finding in enumerate(findings):
            missing = sorted(FINDING_REQUIRED_FIELDS - set(finding))
            if missing:
                errors.append(f"findings[{index}] missing: {', '.join(missing)}")
            if not isinstance(finding.get("evidence_refs"), list):
                errors.append(f"findings[{index}].evidence_refs must be a list")
            if finding.get("approval_required") is not True:
                errors.append(f"findings[{index}].approval_required must be true")

    gate = report.get("action_gate") or {}
    if gate.get("status") not in GATE_STATUSES:
        errors.append("action_gate.status is invalid")
    if gate.get("exact_cleanup_allowed") is not False:
        errors.append("action_gate.exact_cleanup_allowed must be false")
    if gate.get("scanner_mutates_files") is not False:
        errors.append("action_gate.scanner_mutates_files must be false")
    return errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a Clean Your Data JSON report.")
    parser.add_argument("report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"invalid report: {exc}", file=sys.stderr)
        return 2
    errors = validate(report)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("report contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
