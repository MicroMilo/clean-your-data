#!/usr/bin/env python3
"""Smoke tests for the installable package and its public command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run_module(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + existing if existing else "")
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

    assert __version__ == "0.3.0"
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
    assert version.stdout.strip() == "clean-your-data 0.3.0"

    installed_command = shutil.which("cyd")
    if installed_command:
        installed_version = subprocess.run(
            [installed_command, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert installed_version.returncode == 0, installed_version.stderr
        assert installed_version.stdout.strip() == "clean-your-data 0.3.0"

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
