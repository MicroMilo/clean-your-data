#!/usr/bin/env python3
"""Deterministic tests for the approval-gated Trash loop."""

from __future__ import annotations

import importlib.util
import os
import tempfile
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
            assert "preliminary" in tui.cleanup_prompt(node).lower()

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
    finally:
        if previous_ai is None:
            os.environ.pop("CLEAN_YOUR_DATA_AI_COMMAND", None)
        else:
            os.environ["CLEAN_YOUR_DATA_AI_COMMAND"] = previous_ai
    print("cleanup test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
