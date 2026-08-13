#!/usr/bin/env python3
"""Deterministic tests for the approval-gated Trash loop."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TUI_SCRIPT = ROOT / "audit-local-files" / "scripts" / "audit_tui.py"


def load_tui():
    spec = importlib.util.spec_from_file_location("clean_your_data_cleanup_tui", TUI_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load terminal UI")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    tui = load_tui()
    previous_ai = os.environ.get("CLEAN_YOUR_DATA_AI_COMMAND")
    os.environ["CLEAN_YOUR_DATA_AI_COMMAND"] = "cat"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "build-cache.txt"
            source.write_text("rebuildable fixture\n", encoding="utf-8")
            trash = root / "Trash"
            history = root / "state" / "cleanup-history.json"
            node = {
                "node_id": "cache-node",
                "parent_id": None,
                "depth": 0,
                "name": source.name,
                "path": "~/workspace/build-cache.txt",
                "kind": "file",
                "human_size": "18 B",
                "allocated_bytes": 18,
                "area": "Rebuildable",
                "category": "cache",
                "measurement_status": "measured",
                "can_expand": False,
                "_local_path": str(source),
            }

            def rescan():
                return {"space_map": {"nodes": [node] if source.exists() else []}}

            state = tui.TuiState(
                {"space_map": {"nodes": [node]}},
                rescan_callback=rescan,
                cleanup_history_file=history,
                cleanup_trash_root=trash,
            )
            assert tui.cleanup_gate(node)[0] is True
            assert tui.cleanup_gate(dict(node, category="app-state"))[0] is False
            protected_root = root / "project"
            protected_root.mkdir()
            root_node = dict(
                node,
                node_id="root-node",
                name="project",
                kind="folder",
                _local_path=str(protected_root),
            )
            assert tui.cleanup_gate(root_node)[0] is False
            assert "scope" in tui.cleanup_gate(root_node)[1]

            git_dir = protected_root / ".git"
            git_dir.mkdir()
            git_node = dict(
                root_node,
                node_id="git-node",
                parent_id="root-node",
                name=".git",
                _local_path=str(git_dir),
            )
            assert tui.cleanup_gate(git_node)[0] is False
            assert "protected" in tui.cleanup_gate(git_node)[1]

            env_file = protected_root / ".env"
            env_file.write_text("TOKEN=fixture\n", encoding="utf-8")
            env_node = dict(
                node,
                node_id="env-node",
                parent_id="root-node",
                name=".env",
                _local_path=str(env_file),
            )
            assert tui.cleanup_gate(env_node)[0] is False
            assert "credential" in tui.cleanup_gate(env_node)[1]
            production_env = protected_root / ".env.production"
            production_env.write_text("TOKEN=fixture\n", encoding="utf-8")
            production_env_node = dict(env_node, name=production_env.name, _local_path=str(production_env))
            assert tui.cleanup_gate(production_env_node)[0] is False

            repository = root / "repository"
            repository.mkdir()
            tracked_file = repository / "tracked.txt"
            tracked_file.write_text("tracked\n", encoding="utf-8")
            git_init = subprocess.run(["git", "init", "-q", str(repository)], capture_output=True, text=True, check=False)
            assert git_init.returncode == 0, git_init.stderr
            git_add = subprocess.run(["git", "-C", str(repository), "add", "tracked.txt"], capture_output=True, text=True, check=False)
            assert git_add.returncode == 0, git_add.stderr
            tracked_stat = tracked_file.lstat()
            tracked_node = dict(
                node,
                node_id="tracked-file",
                name="tracked.txt",
                path="~/workspace/repository/tracked.txt",
                _local_path=str(tracked_file),
                _stat_device=int(tracked_stat.st_dev),
                _stat_inode=int(tracked_stat.st_ino),
                _stat_mode=int(tracked_stat.st_mode),
                _stat_ctime_ns=int(tracked_stat.st_ctime_ns),
            )
            assert tui.cleanup_gate(tracked_node)[0] is False
            assert "tracked by Git" in tui.cleanup_gate(tracked_node)[1]
            assert "preliminary" in tui.cleanup_prompt(node).lower()

            original = root / "replace-me.txt"
            original.write_text("original\n", encoding="utf-8")
            original_stat = original.lstat()
            replacement_node = dict(
                node,
                node_id="replacement-node",
                name=original.name,
                _local_path=str(original),
                _stat_device=original_stat.st_dev,
                _stat_inode=original_stat.st_ino,
                _stat_mode=original_stat.st_mode,
                _stat_ctime_ns=getattr(
                    original_stat,
                    "st_ctime_ns",
                    int(original_stat.st_ctime * 1_000_000_000),
                ),
            )
            original.unlink()
            original.write_text("replacement\n", encoding="utf-8")
            assert tui.cleanup_gate(replacement_node)[0] is False
            assert "changed since" in tui.cleanup_gate(replacement_node)[1]
            try:
                tui.move_to_trash(Path(replacement_node["_local_path"]), node=replacement_node, trash_root=trash, history_path=history)
            except ValueError as exc:
                assert "changed since" in str(exc)
            else:
                raise AssertionError("the Trash operation must re-check path identity immediately before moving")

            assert tui.handle_key(None, state, "d", 80) is True
            assert state.vim_pending_d is True
            assert tui.handle_key(None, state, "d", 80) is True
            assert "cache-node" in state.cleanup_queue
            assert source.exists()

            for _ in range(40):
                state.poll_ai()
                if not state.ai_busy:
                    break
                time.sleep(0.01)
            assert state.cleanup_advice_status_by_node["cache-node"] == "ready"
            assert "metadata" in state.cleanup_advice_by_node["cache-node"]

            assert tui.handle_key(None, state, "Y", 80) is True
            assert state.trash_confirmation is True
            assert source.exists()
            assert tui.handle_key(None, state, "y", 80) is True
            assert source.exists() is False
            assert state.nodes == []
            assert list(trash.iterdir())
            assert state.cleanup_history[-1]["status"] == "trashed"

            assert tui.handle_key(None, state, "u", 80) is True
            assert source.exists()
            assert [item["name"] for item in state.nodes] == [source.name]
            assert state.cleanup_history[-1]["status"] == "restored"

            first_record = tui.move_to_trash(source, node=node, trash_root=trash, history_path=history)
            tui.restore_trash_record(first_record, history)
            second_record = tui.move_to_trash(source, node=node, trash_root=trash, history_path=history)
            assert first_record["record_id"] != second_record["record_id"]
            tui.restore_trash_record(second_record, history)

            rollback_record = tui.move_to_trash(source, node=node, trash_root=trash, history_path=history)
            function_globals = tui.restore_trash_record.__globals__
            original_save_history = function_globals["save_cleanup_history"]

            def fail_restore_history(*_args, **_kwargs):
                raise OSError("fixture history failure")

            function_globals["save_cleanup_history"] = fail_restore_history
            try:
                try:
                    tui.restore_trash_record(rollback_record, history)
                except RuntimeError as exc:
                    assert "rolled back" in str(exc)
                else:
                    raise AssertionError("a failed history write must roll the restore back into Trash")
            finally:
                function_globals["save_cleanup_history"] = original_save_history
            assert not source.exists()
            assert Path(str(rollback_record["trash_path"])).exists()
            tui.restore_trash_record(rollback_record, history)
    finally:
        if previous_ai is None:
            os.environ.pop("CLEAN_YOUR_DATA_AI_COMMAND", None)
        else:
            os.environ["CLEAN_YOUR_DATA_AI_COMMAND"] = previous_ai
    print("cleanup test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
