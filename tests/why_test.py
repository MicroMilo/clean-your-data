#!/usr/bin/env python3
"""Contract tests for the read-only, Agent-facing path explanation command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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


def explain(path: Path, home: Path, state_dir: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = run_module(
        "why",
        str(path),
        "--home",
        str(home),
        "--state-dir",
        str(state_dir),
        "--format",
        "json",
        "--max-files",
        "200",
        "--time-budget",
        "2",
        *extra,
    )
    payload = json.loads(result.stdout)
    return result, payload


def assert_private_values_absent(text: str, *values: str) -> None:
    for value in values:
        assert value not in text, f"private value leaked into output: {value}"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        temporary_root = Path(tmp)
        home = temporary_root / "private-home"
        project = home / "work" / "agent-project"
        source = project / "src" / "main.py"
        build = project / "build"
        state_dir = temporary_root / "state"
        source.parent.mkdir(parents=True)
        build.mkdir()

        source_secret = "PRIVATE_SOURCE_BODY_MUST_NOT_LEAK"
        build_secret = "PRIVATE_BUILD_BODY_MUST_NOT_LEAK"
        env_secret = "PRIVATE_ENV_VALUE_MUST_NOT_LEAK"
        source.write_text(f"print('{source_secret}')\n", encoding="utf-8")
        (build / "bundle.js").write_text(build_secret + "\n", encoding="utf-8")
        (project / "package.json").write_text('{"scripts":{"build":"private-command"}}\n', encoding="utf-8")
        (project / ".env").write_text(f"TOKEN={env_secret}\n", encoding="utf-8")

        git_init = subprocess.run(["git", "init", "-q", str(project)], capture_output=True, text=True, check=False)
        assert git_init.returncode == 0, git_init.stderr
        git_add = subprocess.run(["git", "-C", str(project), "add", "src/main.py"], capture_output=True, text=True, check=False)
        assert git_add.returncode == 0, git_add.stderr

        build_result, build_report = explain(build, home, state_dir, "--no-trace")
        assert build_result.returncode == 0, build_result.stderr
        assert build_report["why_schema_version"] == "1.0"
        assert build_report["read_only"] is True
        assert build_report["content_read"] is False
        assert build_report["path"]["display"] == "~/work/agent-project/build"
        assert build_report["classification"]["id"] == "cache"
        assert build_report["likely_source"]["basis"] == "path_pattern_and_project_context"
        assert build_report["impact_if_moved"]["risk"] == "medium"
        assert build_report["action_gate"]["status"] == "review_only"
        assert build_report["action_gate"]["authorizes_move"] is False
        assert build_report["analysis_scope"]["selected_path"] == "~/work/agent-project/build"
        assert build_report["analysis_scope"]["relationship_path"] == "~/work/agent-project/build"
        assert build_report["analysis_scope"]["mode"] == "selected_directory"
        assert build_report["limits"]["file_contents_read"] is False
        assert_private_values_absent(
            build_result.stdout,
            str(temporary_root),
            source_secret,
            build_secret,
            env_secret,
            "private-command",
        )

        source_result, source_report = explain(source, home, state_dir, "--no-trace")
        assert source_result.returncode == 0, source_result.stderr
        assert source_report["status"] == "complete"
        assert source_report["analysis_scope"]["mode"] == "selected_file_only"
        assert source_report["analysis_scope"]["files_scanned"] == 0
        assert source_report["impact_if_moved"]["risk"] == "high"
        assert source_report["action_gate"]["status"] == "blocked"
        assert "Git status" in source_report["safest_next_check"]
        git_evidence = [item for item in source_report["evidence"] if item["kind"] == "git"]
        assert git_evidence and "tracked by Git" in git_evidence[0]["detail"]
        assert "content and dirty state were not inspected" in git_evidence[0]["detail"]
        assert_private_values_absent(source_result.stdout, str(temporary_root), source_secret)

        tracked_build = build / "tracked.js"
        tracked_build.write_text("PRIVATE_TRACKED_BUILD_BODY", encoding="utf-8")
        git_add_build = subprocess.run(
            ["git", "-C", str(project), "add", "build/tracked.js"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert git_add_build.returncode == 0, git_add_build.stderr
        tracked_build_result, tracked_build_report = explain(tracked_build, home, state_dir, "--no-trace")
        assert tracked_build_result.returncode == 0, tracked_build_result.stderr
        assert tracked_build_report["classification"]["id"] == "cache"
        assert tracked_build_report["impact_if_moved"]["risk"] == "high"
        assert "tracked by Git" in tracked_build_report["impact_if_moved"]["summary"]
        assert_private_values_absent(tracked_build_result.stdout, str(temporary_root), "PRIVATE_TRACKED_BUILD_BODY")

        home_result, home_report = explain(home, home, state_dir, "--no-trace")
        assert home_result.returncode == 0, home_result.stderr
        assert home_report["classification"]["id"] == "protected"
        assert home_report["action_gate"]["status"] == "blocked"

        env_result, env_report = explain(project / ".env", home, state_dir, "--no-trace")
        assert env_result.returncode == 0, env_result.stderr
        assert env_report["classification"]["id"] == "protected"
        assert env_report["likely_source"]["basis"] == "protected_path_boundary"
        assert env_report["impact_if_moved"]["risk"] == "critical"
        assert env_report["content_read"] is False
        assert_private_values_absent(env_result.stdout, str(temporary_root), env_secret)

        external = temporary_root / "external-private" / "target"
        external.mkdir(parents=True)
        external_secret = "PRIVATE_SYMLINK_TARGET_BODY_MUST_NOT_LEAK"
        (external / "secret.txt").write_text(external_secret, encoding="utf-8")
        link = home / "linked-area"
        link.symlink_to(external, target_is_directory=True)
        link_result, link_report = explain(link, home, state_dir)
        assert link_result.returncode == 0, link_result.stderr
        assert link_report["path"]["kind"] == "symlink"
        assert link_report["analysis_scope"]["mode"] == "selected_symlink_only"
        assert link_report["limits"]["symlink_targets_followed"] is False
        assert link_report["action_gate"]["status"] == "blocked"
        assert_private_values_absent(link_result.stdout, str(temporary_root), str(external), external_secret)

        protected_dir = home / ".ssh"
        protected_dir.mkdir()
        protected_child_name = "private-customer-key-name"
        (protected_dir / protected_child_name).write_text("PRIVATE_PROTECTED_BODY", encoding="utf-8")
        protected_result, protected_report = explain(protected_dir, home, state_dir, "--no-trace")
        assert protected_result.returncode == 0, protected_result.stderr
        assert protected_report["classification"]["id"] == "protected"
        assert protected_report["analysis_scope"]["mode"] == "selected_directory_metadata_only"
        assert protected_report["analysis_scope"]["files_scanned"] == 0
        assert_private_values_absent(protected_result.stdout, protected_child_name, "PRIVATE_PROTECTED_BODY")

        unowned_dir = temporary_root / "unowned-private-area"
        unowned_dir.mkdir()
        external_file = unowned_dir / "unowned.bin"
        external_file.write_bytes(b"PRIVATE_EXTERNAL_BODY_MUST_NOT_LEAK")
        external_result, external_report = explain(external_file, home, state_dir, "--no-trace")
        assert external_result.returncode == 0, external_result.stderr
        assert external_report["path"]["display"] == "<external>/unowned.bin"
        assert external_report["classification"]["id"] == "unknown"
        assert external_report["action_gate"]["status"] == "blocked"
        assert_private_values_absent(
            external_result.stdout,
            str(temporary_root),
            "external-private",
            "PRIVATE_EXTERNAL_BODY_MUST_NOT_LEAK",
        )

        ambiguous_target = unowned_dir / "target"
        ambiguous_target.mkdir()
        ambiguous_result, ambiguous_report = explain(ambiguous_target, home, state_dir, "--no-trace")
        assert ambiguous_result.returncode == 0, ambiguous_result.stderr
        assert ambiguous_report["classification"]["id"] == "unknown"
        assert ambiguous_report["action_gate"]["status"] == "blocked"

        relation_root = home / "relationship-check"
        relation_root.mkdir()
        (relation_root / "local.txt").write_bytes(b"local")
        large_external = unowned_dir / "large-private.bin"
        large_external.write_bytes(b"x" * 100_000)
        (relation_root / "external-link.bin").symlink_to(large_external)
        sys.path.insert(0, str(SRC))
        from clean_your_data.audit_tui import analyze_path_relationships

        relationship_report = analyze_path_relationships(
            {"path": "~/relationship-check", "kind": "folder", "_local_path": str(relation_root)},
            max_files=20,
            time_budget=2,
        )
        assert relationship_report["files_scanned"] == 1
        assert relationship_report["bytes_scanned"] == 5

        missing = temporary_root / "outside-private-area" / "missing.txt"
        missing_result, missing_report = explain(missing, home, state_dir, "--no-trace")
        assert missing_result.returncode == 2
        assert missing_report["status"] == "error"
        assert "<external>/missing.txt" in missing_report["error"]
        assert_private_values_absent(missing_result.stdout, str(temporary_root), "outside-private-area")

        traced = project / "agent-output.txt"
        trace_body = "PRIVATE_TRACED_BODY_MUST_NOT_LEAK"
        trace_code = (
            "from pathlib import Path; import time; "
            f"Path('agent-output.txt').write_text('{trace_body}'); "
            "time.sleep(0.08)"
        )
        trace_result = run_module(
            "trace",
            "--path",
            str(project),
            "--cwd",
            str(project),
            "--interval",
            "0.01",
            "--state-dir",
            str(state_dir),
            "--format",
            "json",
            "--",
            sys.executable,
            "-c",
            trace_code,
        )
        assert trace_result.returncode == 0, trace_result.stderr
        traced_result, traced_report = explain(traced, home, state_dir)
        assert traced_result.returncode == 0, traced_result.stderr
        assert traced_report["likely_source"]["basis"] == "observed_association"
        trace_evidence = [item for item in traced_report["evidence"] if item["kind"] == "trace"]
        assert trace_evidence
        assert "does not prove the exact writer" in trace_evidence[0]["detail"]
        assert_private_values_absent(
            traced_result.stdout,
            str(temporary_root),
            str(Path(sys.executable).parent),
            trace_body,
            trace_code,
        )

        text_result = run_module(
            "why",
            str(build),
            "--home",
            str(home),
            "--state-dir",
            str(state_dir),
            "--no-trace",
            "--time-budget",
            "1",
        )
        assert text_result.returncode == 0, text_result.stderr
        for section in (
            "LIKELY SOURCE",
            "EVIDENCE",
            "IMPACT IF MOVED",
            "UNKNOWNS",
            "SAFEST NEXT CHECK",
            "ACTION GATE",
        ):
            assert section in text_result.stdout
        assert_private_values_absent(text_result.stdout, str(temporary_root), build_secret)

        nested_package = project / "packages" / "child"
        nested_package.mkdir(parents=True)
        (nested_package / "package.json").write_text("{}\n", encoding="utf-8")
        nested_source = nested_package / "tracked.ts"
        nested_source.write_text("PRIVATE_NESTED_SOURCE", encoding="utf-8")
        nested_add = subprocess.run(
            ["git", "-C", str(project), "add", "packages/child/tracked.ts"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert nested_add.returncode == 0, nested_add.stderr
        nested_result, nested_report = explain(nested_source, home, state_dir, "--no-trace")
        assert nested_result.returncode == 0, nested_result.stderr
        assert nested_report["analysis_scope"]["project_context_root"] == "~/work/agent-project/packages/child"
        assert nested_report["action_gate"]["status"] == "blocked"
        assert any(item["kind"] == "git" and "tracked" in item["detail"] for item in nested_report["evidence"])
        assert_private_values_absent(nested_result.stdout, str(temporary_root), "PRIVATE_NESTED_SOURCE")

    print("why test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
