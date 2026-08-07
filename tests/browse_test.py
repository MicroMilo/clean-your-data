#!/usr/bin/env python3
"""Deterministic tests for fuzzy browsing, view controls, tags, and tabs."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TUI_SCRIPT = ROOT / "audit-local-files" / "scripts" / "audit_tui.py"


def load_tui():
    spec = importlib.util.spec_from_file_location("clean_your_data_browse_tui", TUI_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load terminal explorer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    tui = load_tui()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "workspace"
        (root / "docs").mkdir(parents=True)
        (root / "src").mkdir()
        readme = root / "README.md"
        notes = root / "docs" / "notes.txt"
        app = root / "src" / "app.py"
        readme.write_text("readme\n", encoding="utf-8")
        notes.write_text("notes\n", encoding="utf-8")
        app.write_text("print('ok')\n", encoding="utf-8")

        root_node = {
            "node_id": "root",
            "parent_id": None,
            "depth": 0,
            "name": "workspace",
            "path": "~/workspace",
            "kind": "folder",
            "category": "workspace",
            "allocated_bytes": 300,
            "human_size": "300 B",
            "can_expand": True,
            "_local_path": str(root),
        }
        nodes = [
            root_node,
            {
                "node_id": "docs",
                "parent_id": "root",
                "depth": 1,
                "name": "docs",
                "path": "~/workspace/docs",
                "kind": "folder",
                "category": "workspace",
                "allocated_bytes": 10,
                "human_size": "10 B",
                "can_expand": True,
                "_local_path": str(root / "docs"),
            },
            {
                "node_id": "readme",
                "parent_id": "root",
                "depth": 1,
                "name": "README.md",
                "path": "~/workspace/README.md",
                "kind": "file",
                "category": "deliverable",
                "allocated_bytes": 200 * 1024 * 1024,
                "human_size": "200 MB",
                "_local_path": str(readme),
            },
            {
                "node_id": "notes",
                "parent_id": "docs",
                "depth": 2,
                "name": "notes.txt",
                "path": "~/workspace/docs/notes.txt",
                "kind": "file",
                "category": "user-data",
                "allocated_bytes": 20,
                "human_size": "20 B",
                "_local_path": str(notes),
            },
            {
                "node_id": "app",
                "parent_id": "root",
                "depth": 1,
                "name": "app.py",
                "path": "~/workspace/src/app.py",
                "kind": "file",
                "category": "workspace",
                "allocated_bytes": 50,
                "human_size": "50 B",
                "_local_path": str(app),
            },
        ]
        workspace_file = Path(tmp) / "state" / "workspace-state.json"
        state = tui.TuiState({"space_map": {"nodes": nodes}}, workspace_file=workspace_file)
        assert [node["name"] for node in state.visible()] == ["workspace", "docs", "notes.txt", "README.md", "app.py"]

        state.selected_id = "readme"
        state.begin_tag_edit()
        state.tag_buffer = "important, review"
        state.save_tags()
        saved = json.loads(workspace_file.read_text(encoding="utf-8"))
        assert saved["tags"][str(readme.resolve())] == ["important", "review"]
        assert state.node_tags(nodes[2]) == ["important", "review"]

        state.search_query = "impor"
        assert [node["name"] for node in state.visible()] == ["workspace", "README.md"]
        state.search_query = ""
        state.filter_mode = "files"
        assert [node["name"] for node in state.visible()] == ["workspace", "docs", "notes.txt", "README.md", "app.py"]
        state.filter_mode = "large"
        assert [node["name"] for node in state.visible()] == ["workspace", "README.md"]
        state.filter_mode = "all"
        state.sort_mode = "size"
        assert [node["name"] for node in state.visible()] == ["workspace", "README.md", "app.py", "docs", "notes.txt"]

        state.selected_id = "docs"
        reports = {"/second": {"space_map": {"nodes": [dict(root_node, name="second", path="~/second")]}}}

        def rescan(path: Path):
            return reports["/second"]

        state.rescan_callback = rescan
        assert tui.handle_key(None, state, "N", 100) is True
        assert len(state.tabs) == 2
        assert tui.handle_key(None, state, "g", 100) is True
        assert tui.handle_key(None, state, "T", 100) is True
        assert state.tab_index == 0
        assert tui.handle_key(None, state, "g", 100) is True
        assert tui.handle_key(None, state, "t", 100) is True
        assert state.tab_index == 1
        assert tui.handle_key(None, state, "X", 100) is True
        assert len(state.tabs) == 1

    print("browse test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
