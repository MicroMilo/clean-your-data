#!/usr/bin/env python3
"""Build and exercise the same wheel users install."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False, **kwargs)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        temporary = Path(tmp)
        wheels = temporary / "wheels"
        wheels.mkdir()
        built = run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(wheels),
                ".",
            ],
            cwd=ROOT,
        )
        assert built.returncode == 0, built.stderr
        wheel = next(wheels.glob("clean_your_data-0.5.0-*.whl"))

        environment = temporary / "venv"
        created = run([sys.executable, "-m", "venv", str(environment)])
        assert created.returncode == 0, created.stderr
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        cyd = environment / ("Scripts/cyd.exe" if sys.platform == "win32" else "bin/cyd")
        installed = run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)])
        assert installed.returncode == 0, installed.stderr

        version = run([str(cyd), "--version"])
        assert version.returncode == 0, version.stderr
        assert version.stdout.strip() == "clean-your-data 0.5.0"
        help_result = run([str(cyd), "--help"])
        assert help_result.returncode == 0, help_result.stderr
        assert "cyd why" in help_result.stdout

        home = temporary / "home"
        project = home / "sample-project"
        build = project / "build"
        build.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (build / "artifact.bin").write_bytes(b"private body must not appear")
        explained = run(
            [
                str(cyd),
                "why",
                str(build),
                "--home",
                str(home),
                "--no-trace",
                "--format",
                "json",
                "--time-budget",
                "1",
            ]
        )
        assert explained.returncode == 0, explained.stderr
        report = json.loads(explained.stdout)
        assert report["path"]["display"] == "~/sample-project/build"
        assert report["read_only"] is True
        assert report["action_gate"]["authorizes_move"] is False
        assert str(temporary) not in explained.stdout
        assert "private body must not appear" not in explained.stdout

    print("install test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
