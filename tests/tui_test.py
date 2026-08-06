#!/usr/bin/env python3
"""Deterministic tests for the terminal explorer's non-curses logic."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TUI_SCRIPT = ROOT / "audit-local-files" / "scripts" / "audit_tui.py"


def load_tui():
    spec = importlib.util.spec_from_file_location("clean_your_data_tui", TUI_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load terminal UI")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    tui = load_tui()
    nodes = [
        {
            "node_id": "space-root",
            "parent_id": None,
            "depth": 0,
            "name": "project",
            "path": "~/Desktop/project",
            "kind": "folder",
            "human_size": "4.0 KB",
            "area": "Selected area",
            "measurement_status": "measured",
            "can_expand": True,
        },
        {
            "node_id": "space-child-folder",
            "parent_id": "space-root",
            "depth": 1,
            "name": "src",
            "path": "~/Desktop/project/src",
            "kind": "folder",
            "human_size": "1.0 KB",
            "area": "Selected area",
            "measurement_status": "measured",
            "can_expand": True,
        },
        {
            "node_id": "space-grandchild-folder",
            "parent_id": "space-child-folder",
            "depth": 2,
            "name": "lib",
            "path": "~/Desktop/project/src/lib",
            "kind": "folder",
            "human_size": "512 B",
            "area": "Selected area",
            "measurement_status": "measured",
            "can_expand": True,
        },
        {
            "node_id": "space-next-level",
            "parent_id": "space-grandchild-folder",
            "depth": 3,
            "name": "notes.txt",
            "path": "~/Desktop/project/src/lib/notes.txt",
            "kind": "file",
            "human_size": "12 B",
            "area": "Selected area",
            "measurement_status": "measured",
            "can_expand": False,
        },
    ]
    assert tui.display_label("app-state") == "App data"
    assert tui.display_node_name(nodes[1]) == "src/"
    assert tui.display_node_path(nodes[1]) == "~/Desktop/project/src/"
    prompt = tui.build_prompt(nodes[3], "What should I check first?")
    assert "~/Desktop/project/src/lib/notes.txt" in prompt
    assert "What should I check first?" in prompt
    assert "private" not in prompt
    assert "contents" in prompt
    assert tui.key_matches("q", ord("q"))
    assert tui.key_matches("?", ord("?"))
    assert tui.key_matches("\n", 10)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as preview_file:
        preview_file.write("line one\nline two\n")
        preview_file.flush()
        nodes[3]["_local_path"] = preview_file.name
        assert tui.read_file_preview(nodes[3]) == ["line one", "line two"]
    state = tui.TuiState({"space_map": {"nodes": nodes}})
    assert state.selected()["name"] == "project"
    assert "metadata-only" in state.message
    assert [node["name"] for node in state.visible()] == ["project", "src", "lib"]
    state.selected_id = "space-grandchild-folder"
    assert tui.handle_key(None, state, "\n", 80) is True
    assert [node["name"] for node in state.visible()] == ["project", "src", "lib", "notes.txt"]
    assert tui.handle_key(None, state, "\n", 80) is True
    assert [node["name"] for node in state.visible()] == ["project", "src", "lib"]
    assert tui.handle_key(None, state, "G", 80) is True
    assert state.selected()["name"] == "lib"
    assert tui.handle_key(None, state, "g", 80) is True
    assert state.vim_pending_g is True
    assert tui.handle_key(None, state, "g", 80) is True
    assert state.selected()["name"] == "project"
    assert state.vim_pending_g is False
    assert tui.handle_key(None, state, tui.curses.KEY_END, 80) is True
    assert state.selected()["name"] == "lib"
    assert tui.handle_key(None, state, tui.curses.KEY_HOME, 80) is True
    assert state.selected()["name"] == "project"
    assert tui.handle_key(None, state, tui.curses.KEY_NPAGE, 80, 3) is True
    assert state.selected()["name"] == "lib"
    assert tui.handle_key(None, state, tui.curses.KEY_PPAGE, 80, 3) is True
    assert state.selected()["name"] == "project"
    assert tui.handle_key(None, state, "?", 80) is True
    assert state.help_open is True
    assert tui.handle_key(None, state, "x", 80) is True
    assert state.help_open is False
    assert tui.handle_key(None, state, "q", 80) is False

    lazy_child = dict(nodes[3])
    lazy_child["node_id"] = "lazy-child"
    lazy_child["parent_id"] = "space-grandchild-folder"
    lazy_child["name"] = "lazy.txt"
    lazy_child["path"] = "~/Desktop/project/src/lib/lazy.txt"
    lazy_root = dict(nodes[2])
    lazy_root["node_id"] = "lazy-root"
    lazy_root["parent_id"] = None
    lazy_root["name"] = "lazy"
    lazy_root["path"] = "~/Desktop/lazy"
    lazy_root["depth"] = 0
    lazy_root["can_expand"] = True
    expanded_state = tui.TuiState(
        {"space_map": {"nodes": [lazy_root]}},
        lambda node: ([dict(lazy_child, parent_id=node["node_id"], depth=1)], "complete"),
    )
    expanded_state.expanded.clear()
    expanded_state.open_or_close(lazy_root)
    assert [node["name"] for node in expanded_state.visible()] == ["lazy", "lazy.txt"]

    question_state = tui.TuiState({"space_map": {"nodes": [nodes[0]]}})
    tui.begin_question(None, question_state)
    assert question_state.question_editing is True
    assert tui.handle_key(None, question_state, "g", 80) is True
    assert question_state.question_buffer == "g"
    assert question_state.vim_pending_g is False
    assert tui.handle_key(None, question_state, "?", 80) is True
    assert question_state.question_buffer == "g?"
    assert tui.handle_key(None, question_state, 27, 80) is True
    assert question_state.question_editing is False
    assert "cancelled" in question_state.message.lower()

    previous = os.environ.get("CLEAN_YOUR_DATA_AI_COMMAND")
    os.environ["CLEAN_YOUR_DATA_AI_COMMAND"] = "cat"
    answer, message = tui.ask_local_ai("metadata only")
    assert answer == "metadata only"
    assert "answer" in message.lower()
    async_state = tui.TuiState({"space_map": {"nodes": [nodes[0]]}})
    async_state.question = "What is this folder?"
    async_state.start_ai(nodes[0], "metadata only")
    for _ in range(30):
        async_state.poll_ai()
        if not async_state.ai_busy:
            break
        time.sleep(0.01)
    assert async_state.answer == "metadata only"
    assert "answer" in async_state.message.lower()
    if previous is None:
        os.environ.pop("CLEAN_YOUR_DATA_AI_COMMAND", None)
    else:
        os.environ["CLEAN_YOUR_DATA_AI_COMMAND"] = previous
    print("tui test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
