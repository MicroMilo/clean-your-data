#!/usr/bin/env python3
"""Fixture coverage for the metadata-only interactive space map."""

from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit-local-files" / "scripts" / "audit_local_files.py"
VALIDATE_SCRIPT = ROOT / "audit-local-files" / "scripts" / "validate_report.py"
SCANNER_SCRIPT = ROOT / "audit-local-files" / "scripts" / "audit_local_files.py"


def load_scanner():
    spec = importlib.util.spec_from_file_location("clean_your_data_scanner", SCANNER_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scanner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        focus = home / "Desktop" / "project"
        (focus / "reports" / "2026").mkdir(parents=True)
        (focus / "notes.txt").write_text("private fixture content\n", encoding="utf-8")
        (focus / "reports" / "2026" / "summary.md").write_text("not reported\n", encoding="utf-8")

        command = [
            sys.executable,
            str(SCRIPT),
            "--home",
            str(home),
            "--path",
            str(focus),
            "--focus-depth",
            "2",
            "--focus-limit",
            "20",
            "--focus-time-budget",
            "0",
            "--format",
            "json",
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=True)
        report = json.loads(result.stdout)
        space_map = report["space_map"]
        assert report["schema_version"] == "1.3"
        assert space_map["enabled"] is True
        assert space_map["status"] == "complete"
        assert space_map["roots"] == ["~/Desktop/project"]
        assert space_map["node_count"] >= 4
        root_node = next(node for node in space_map["nodes"] if node["parent_id"] is None)
        assert root_node["path"] == "~/Desktop/project"
        assert all(str(home) not in node["path"] for node in space_map["nodes"])
        assert all("_local_path" not in node for node in space_map["nodes"])
        deep_folder = next(node for node in space_map["nodes"] if node["name"] == "2026")
        assert deep_folder["can_expand"] is True
        assert "private fixture content" not in result.stdout

        scanner = load_scanner()
        mapped = scanner.scan_space_map(
            [focus],
            [],
            [focus],
            home,
            2,
            20,
            5,
            0,
            True,
            include_local_paths=True,
        )
        lazy_folder = next(node for node in mapped["nodes"] if node["name"] == "2026")
        children, status = scanner.expand_space_map_node(lazy_folder, home, True, 5, 20, 0)
        assert status == "complete"
        assert [node["name"] for node in children] == ["summary.md"]

        report_path = home / "interactive.json"
        report_path.write_text(result.stdout, encoding="utf-8")
        subprocess.run([sys.executable, str(VALIDATE_SCRIPT), str(report_path)], check=True)

        help_result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=True,
        )
        assert "--tui" in help_result.stdout
        assert "--focus-depth" in help_result.stdout

    print("interactive test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
