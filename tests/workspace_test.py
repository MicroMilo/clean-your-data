#!/usr/bin/env python3
"""Deterministic tests for path-aware actions, bookmarks, and deep analysis."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TUI_SCRIPT = ROOT / "audit-local-files" / "scripts" / "audit_tui.py"


def load_tui():
    spec = importlib.util.spec_from_file_location("clean_your_data_workspace_tui", TUI_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load terminal UI")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    tui = load_tui()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        (root / ".git").mkdir(parents=True)
        (root / "src").mkdir(parents=True)
        (root / "src" / "copies-a").mkdir()
        (root / "src" / "copies-b").mkdir()
        (root / "build").mkdir()
        (root / "outputs").mkdir()
        (root / "node_modules" / "demo").mkdir(parents=True)
        (root / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
        (root / "src" / "copies-a" / "same.txt").write_text("same\n", encoding="utf-8")
        (root / "src" / "copies-b" / "same.txt").write_text("same\n", encoding="utf-8")
        (root / "build" / "app.js").write_text("built\n", encoding="utf-8")
        (root / "outputs" / "report.pdf").write_bytes(b"pdf")
        (root / "README.md").write_text("demo project\n", encoding="utf-8")
        (root / "package.json").write_text("{}\n", encoding="utf-8")

        node = {
            "node_id": "project-node",
            "parent_id": None,
            "depth": 0,
            "name": root.name,
            "path": "~/workspace/project",
            "kind": "folder",
            "human_size": "1 KB",
            "allocated_bytes": 1024,
            "measurement_status": "measured",
            "category": "workspace",
            "can_expand": True,
            "_local_path": str(root),
        }

        analysis = tui.analyze_path_relationships(node)
        assert analysis["status"] == "complete"
        assert analysis["counts"]["source"] == 1
        assert analysis["counts"]["documentation"] >= 1
        titles = {relation["title"] for relation in analysis["relations"]}
        assert "Project structure" in titles
        assert "Source -> build output" in titles
        assert "Possible outputs" in titles
        assert "Possible repeated files" in titles

        file_node = dict(node, node_id="file-node", kind="file", name="app.py", _local_path=str(root / "src" / "app.py"))
        original_which = tui.shutil.which
        tui.shutil.which = lambda _name: None
        try:
            terminal_command = tui.build_launch_command(file_node, "terminal")
            vscode_command = tui.build_launch_command(file_node, "vscode")
            cursor_command = tui.build_launch_command(file_node, "cursor")
        finally:
            tui.shutil.which = original_which
        assert str((root / "src").resolve()) in terminal_command
        assert str((root / "src" / "app.py").resolve()) in vscode_command
        assert str((root / "src" / "app.py").resolve()) in cursor_command

        workspace_file = Path(tmp) / "state" / "workspace-state.json"
        state = tui.TuiState(
            {"space_map": {"nodes": [file_node]}},
            workspace_file=workspace_file,
        )
        assert tui.handle_key(None, state, "m", 100) is True
        saved = json.loads(workspace_file.read_text(encoding="utf-8"))
        assert saved["bookmarks"][0]["path"] == str((root / "src" / "app.py").resolve())
        assert state.is_bookmarked(file_node)
        assert tui.handle_key(None, state, "M", 100) is True
        assert state.bookmark_open is True
        assert tui.handle_key(None, state, 27, 100) is True
        assert state.bookmark_open is False

    print("workspace test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
