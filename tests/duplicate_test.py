#!/usr/bin/env python3
"""Fixture coverage for opt-in exact duplicate detection."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit-local-files" / "scripts" / "audit_local_files.py"
VALIDATE_SCRIPT = ROOT / "audit-local-files" / "scripts" / "validate_report.py"


def run_report(home: Path, *extra: str) -> tuple[dict, str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--home",
        str(home),
        "--duplicates",
        "--duplicate-min-mb",
        "0",
        "--duplicate-time-budget",
        "0",
        "--duplicate-max-mb",
        "0",
        "--duplicate-file-limit",
        "0",
        "--format",
        "json",
        *extra,
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=True)
    return json.loads(result.stdout), result.stdout


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        desktop_file = home / "Desktop" / "project" / "reports" / "report.txt"
        downloads_file = home / "Downloads" / "report-copy.txt"
        hardlink_file = home / "Desktop" / "project" / "reports" / "report-hardlink.txt"
        different_file = home / "Desktop" / "project" / "reports" / "different.txt"
        cloud_file = home / "Library" / "CloudStorage" / "Provider" / "report-cloud.txt"
        desktop_file.parent.mkdir(parents=True)
        downloads_file.parent.mkdir(parents=True)
        cloud_file.parent.mkdir(parents=True)
        content = b"same fixture content\n"
        desktop_file.write_bytes(content)
        downloads_file.write_bytes(content)
        os.link(desktop_file, hardlink_file)
        different_file.write_bytes(b"other fixture content\n")
        cloud_file.write_bytes(content)

        report, raw = run_report(home)
        assert report["schema_version"] == "1.3"
        assert report["duplicates"]["status"] == "complete"
        assert report["duplicates"]["group_count"] == 1
        group = report["duplicates"]["groups"][0]
        assert group["status"] == "exact"
        assert group["hash_algorithm"] == "sha256"
        assert group["file_count"] == 3
        assert group["independent_copy_count"] == 2
        assert group["hardlink_alias_count"] == 1
        assert group["potential_duplicate_bytes"] == len(content)
        assert group["canonical_candidate_context"] == "workspace"
        assert group["canonical_candidate_path"].startswith("~/Desktop/")
        assert group["contains_cloud_sync"] is False
        assert "Desktop" in group["parent_targets"]
        assert str(cloud_file) not in raw
        assert hashlib.sha256(content).hexdigest() not in raw
        assert all("digest" not in row for row in report["duplicates"]["groups"])
        assert any(item["category"] == "cloud-sync" for item in report["duplicates"]["excluded_scopes"])

        limited_report, _ = run_report(home, "--duplicate-file-limit", "1")
        assert limited_report["duplicates"]["status"] == "limit"
        assert limited_report["action_gate"]["status"] == "review_only"

        report_path = home / "duplicates.json"
        report_path.write_text(raw, encoding="utf-8")
        subprocess.run([sys.executable, str(VALIDATE_SCRIPT), str(report_path)], check=True)

        markdown_result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--home",
                str(home),
                "--duplicates",
                "--duplicate-min-mb",
                "0",
                "--duplicate-time-budget",
                "0",
                "--duplicate-max-mb",
                "0",
                "--duplicate-file-limit",
                "0",
                "--format",
                "markdown",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        assert "Exact Duplicate Groups" in markdown_result.stdout
        assert "sha256" in markdown_result.stdout.lower()
        assert str(home) not in markdown_result.stdout

        explicit_report, explicit_raw = run_report(home, "--duplicate-root", str(cloud_file.parent))
        explicit_group = explicit_report["duplicates"]["groups"][0]
        assert explicit_group["file_count"] == 4
        assert explicit_group["contains_cloud_sync"] is True
        assert "cloud folder" in " ".join(explicit_group["overlap_warnings"])
        assert str(cloud_file) not in explicit_raw

    print("duplicate test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
