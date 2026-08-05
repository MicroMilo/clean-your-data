#!/usr/bin/env python3
"""No-dependency smoke test for the standalone scanner."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit-local-files" / "scripts" / "audit_local_files.py"
COMPARE_SCRIPT = ROOT / "audit-local-files" / "scripts" / "compare_reports.py"
VALIDATE_SCRIPT = ROOT / "audit-local-files" / "scripts" / "validate_report.py"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "Desktop" / "project-a" / ".git").mkdir(parents=True)
        (home / "Desktop" / "project-a" / "node_modules" / "pkg").mkdir(parents=True)
        (home / "Desktop" / "project-a" / "node_modules" / "pkg" / "blob.txt").write_text("fixture\n")
        (home / "Documents" / "Codex" / "2026-01-01" / "task" / "outputs").mkdir(parents=True)
        (home / "Library" / "Containers" / "com.bytedance.macos.feishu").mkdir(parents=True)
        (home / "Desktop" / "project-a" / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/example/private-repo.git\n'
        )

        command = [
            sys.executable,
            str(SCRIPT),
            "--home",
            str(home),
            "--mode",
            "full",
            "--artifacts",
            "--git-status",
            "--format",
            "json",
            "--min-mb",
            "0",
        ]
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=True,
        )
        report = json.loads(result.stdout)
        raw = result.stdout
        assert report["read_only"] is True
        assert report["schema_version"] == "1.1"
        assert report["settings"]["home"] == "~"
        assert report["settings"]["scope_id"] == "home"
        assert report["disk"]["path"] == "~"
        assert str(home) not in raw
        assert "https://github.com/example/private-repo.git" not in raw
        assert report["codex"]["outputs_dir_count"] == 1
        assert len(report["git"]["repos"]) == 1
        assert all("origin" not in repo for repo in report["git"]["repos"])
        assert any(item["name"] == "node_modules" for item in report["artifacts"])
        assert any(item["label"] == "Desktop" for item in report["coverage"])
        assert all("measurement_status" in item for item in report["target_areas"])
        assert report["findings"]
        assert report["action_gate"]["status"] == "approval_required"
        assert report["action_gate"]["exact_cleanup_allowed"] is False
        artifact_finding = next(
            item for item in report["findings"]
            if item.get("path_redacted", "").endswith("node_modules")
        )
        assert artifact_finding["counted_in_total"] is True

        before = home / "before.json"
        before.write_text(result.stdout, encoding="utf-8")
        subprocess.run([sys.executable, str(VALIDATE_SCRIPT), str(before)], check=True)
        (home / "Desktop" / "growth.bin").write_bytes(b"x" * (2 * 1024 * 1024))
        (home / "Downloads").mkdir()
        (home / "Downloads" / "new.bin").write_bytes(b"x" * (2 * 1024 * 1024))
        after_result = subprocess.run(command, text=True, capture_output=True, check=True)
        after = home / "after.json"
        after.write_text(after_result.stdout, encoding="utf-8")
        subprocess.run([sys.executable, str(VALIDATE_SCRIPT), str(after)], check=True)
        comparison = subprocess.run(
            [
                sys.executable,
                str(COMPARE_SCRIPT),
                str(before),
                str(after),
                "--format",
                "json",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        comparison_report = json.loads(comparison.stdout)
        assert comparison_report["schema_version"] == "1.1"
        assert "coverage" in comparison_report
        assert comparison_report["action_gate"]["before"] == "approval_required"
        desktop_change = next(
            row for row in comparison_report["target_areas"] if row["path"] == "~/Desktop"
        )
        assert desktop_change["delta_bytes"] > 0
        downloads_change = next(
            row for row in comparison_report["target_areas"] if row["path"] == "~/Downloads"
        )
        assert downloads_change["status"] == "new"
    print("smoke test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
