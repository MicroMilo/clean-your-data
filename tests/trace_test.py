#!/usr/bin/env python3
"""Deterministic coverage for the opt-in local command tracer."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        root.mkdir()
        (root / "existing.txt").write_text("before\n", encoding="utf-8")
        (root / "remove.txt").write_text("remove\n", encoding="utf-8")
        state_dir = Path(tmp) / "state"
        command_code = (
            "from pathlib import Path; import time; "
            "root=Path.cwd(); "
            "(root/'added.txt').write_text('created\\n'); "
            "(root/'existing.txt').write_text('after\\n'); "
            "(root/'remove.txt').unlink(); "
            "time.sleep(0.08)"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "clean_your_data",
                "trace",
                "--path",
                str(root),
                "--cwd",
                str(root),
                "--interval",
                "0.01",
                "--state-dir",
                str(state_dir),
                "--format",
                "json",
                "--",
                sys.executable,
                "-c",
                command_code,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["trace_schema_version"] == "1.0"
        assert report["session"]["return_code"] == 0
        assert report["session"]["cwd"] == "."
        assert report["observation"]["attribution"].startswith("associated with")
        events = {item["path"]: item for item in report["events"]}
        assert events["./added.txt"]["event_types"] == ["created"]
        assert events["./existing.txt"]["event_types"] == ["modified"]
        assert events["./existing.txt"]["changed_fields"] == ["size", "modified time"]
        assert events["./remove.txt"]["event_types"] == ["deleted"]
        assert events["./remove.txt"]["after"] is None
        assert report["store"]["saved"] is True

        database = state_dir / "provenance.sqlite3"
        assert database.exists()
        assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(database.stat().st_mode) == 0o600
        with sqlite3.connect(database) as connection:
            session_count = connection.execute("SELECT COUNT(*) FROM trace_sessions").fetchone()[0]
            event_count = connection.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
        assert session_count == 1
        assert event_count == 3
        assert str(root) not in result.stdout

    print("trace test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
