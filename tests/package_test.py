#!/usr/bin/env python3
"""Smoke tests for the installable package and its public command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run_module(
    *args: str,
    env_overrides: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + existing if existing else "")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "clean_your_data", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    sys.path.insert(0, str(SRC))
    from clean_your_data import __version__
    from clean_your_data.cli import normalize_argv

    assert __version__ == "0.5.0"
    assert resources.files("clean_your_data").joinpath("web/index.html").is_file()
    assert normalize_argv([]) == ["--tui", "--path", "."]
    assert normalize_argv(["/tmp/project", "--focus-depth", "3"]) == [
        "--tui",
        "--path",
        "/tmp/project",
        "--focus-depth",
        "3",
    ]
    assert normalize_argv(["--format", "json"]) == ["--format", "json"]

    version = run_module("--version")
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == "clean-your-data 0.5.0"

    help_result = run_module("--help")
    assert help_result.returncode == 0, help_result.stderr
    for command in ("cyd [PATH]", "cyd why", "cyd gui", "cyd trace", "cyd audit", "cyd config ai"):
        assert command in help_result.stdout

    audit_help = run_module("audit", "--help")
    assert audit_help.returncode == 0, audit_help.stderr
    assert "Read-only local file organization audit" in audit_help.stdout

    gui_help = run_module("gui", "--help")
    assert gui_help.returncode == 0, gui_help.stderr
    assert "cyd gui" in gui_help.stdout

    why_help = run_module("why", "--help")
    assert why_help.returncode == 0, why_help.stderr
    assert "cyd why" in why_help.stdout

    with tempfile.TemporaryDirectory() as state_dir:
        invalid_config = run_module(
            "config",
            "ai",
            "--command",
            "'unterminated",
            env_overrides={"CLEAN_YOUR_DATA_STATE_DIR": state_dir},
        )
        assert invalid_config.returncode == 2
        assert "invalid AI command" in invalid_config.stderr
        assert "Traceback" not in invalid_config.stderr

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "Desktop").mkdir()
        (home / "Documents").mkdir()
        report = run_module("--format", "json", "--home", str(home))
        assert report.returncode == 0, report.stderr
        payload = json.loads(report.stdout)
        assert payload["schema_version"]
        assert payload["settings"]["redact"] is True

    print("package test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
