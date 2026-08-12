#!/usr/bin/env python3
"""Integration tests for the local browser GUI and its safety boundary."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def request_json(
    url: str,
    token: str,
    *,
    method: str = "GET",
    payload: Optional[dict[str, object]] = None,
    origin: Optional[str] = None,
) -> tuple[int, dict[str, object]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"X-CYD-Token": token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main() -> int:
    import sys

    sys.path.insert(0, str(SRC))
    from clean_your_data.ai_config import config_for_display, load_ai_config
    import clean_your_data.gui as gui_module
    from clean_your_data.gui import GuiRequestError, GuiSession, create_server

    previous_ai = os.environ.get("CLEAN_YOUR_DATA_AI_COMMAND")
    os.environ["CLEAN_YOUR_DATA_AI_COMMAND"] = "cat"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / "workspace"
            root.mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "README.md").write_text("# Demo\nprivate preview marker\n", encoding="utf-8")
            mutable = root / "mutable.txt"
            mutable.write_text("safe before scan\n", encoding="utf-8")
            outside_secret = home / "outside-secret.txt"
            outside_secret.write_text("must-not-follow-replacement\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=must-not-be-previewed\n", encoding="utf-8")
            (root / ".env.production").write_text("TOKEN=also-hidden\n", encoding="utf-8")
            build = root / "build"
            build.mkdir()
            (build / "generated.bin").write_bytes(b"x" * 4096)
            source = root / "src"
            source.mkdir()
            (source / "main.py").write_text("print('hello')\n", encoding="utf-8")

            trash = home / "Trash"
            history = home / "state" / "cleanup-history.json"
            ai_config = home / "state" / "ai-config.json"
            session = GuiSession(
                root,
                home=home,
                depth=1,
                node_limit=100,
                timeout=2,
                time_budget=10,
                trash_root=trash,
                history_path=history,
                ai_config_path=ai_config,
            )

            payload = session.payload()
            serialized = json.dumps(payload)
            assert str(home) not in serialized
            assert all(not any(str(key).startswith("_") for key in node) for node in payload["nodes"])
            assert payload["scope"]["path"] == "~/workspace"
            assert payload["privacy"]["preview_sent_to_ai"] is False
            assert payload["scope"]["cleanup_eligible"] is False
            assert "scope is protected" in payload["scope"]["cleanup_reason"]

            by_name = {node["name"]: node for node in payload["nodes"]}
            readme_node = by_name["README.md"]
            env_node = by_name[".env"]
            production_env_node = by_name[".env.production"]
            mutable_node = by_name["mutable.txt"]
            build_node = by_name["build"]

            readme_preview = session.preview(readme_node["node_id"])
            assert "private preview marker" in "\n".join(readme_preview["lines"])
            secret_preview = session.preview(env_node["node_id"])
            assert "must-not-be-previewed" not in "\n".join(secret_preview["lines"])
            assert "hidden" in "\n".join(secret_preview["lines"]).lower()
            production_preview = session.preview(production_env_node["node_id"])
            assert "also-hidden" not in "\n".join(production_preview["lines"])
            assert "hidden" in "\n".join(production_preview["lines"]).lower()
            mutable.unlink()
            mutable.symlink_to(outside_secret)
            replaced_preview = session.preview(mutable_node["node_id"])
            assert "must-not-follow-replacement" not in "\n".join(replaced_preview["lines"])
            assert "unavailable" in "\n".join(replaced_preview["lines"]).lower()
            try:
                session.toggle_stage(env_node["node_id"])
            except GuiRequestError as exc:
                assert "credential" in str(exc).lower()
            else:
                raise AssertionError("credential configuration must not enter the cleanup basket")

            answer = session.ask(readme_node["node_id"], "What is this?")
            assert "What is this?" in answer["answer"]
            assert "private preview marker" not in answer["answer"]

            os.environ.pop("CLEAN_YOUR_DATA_AI_COMMAND", None)
            saved = session.set_ai_config("command", "cat")
            assert saved["mode"] == "command"
            assert saved["command"] == ""
            assert saved["command_configured"] is True
            assert load_ai_config(ai_config)["command"] == ["cat"]
            displayed = config_for_display(load_ai_config(ai_config))
            assert displayed["has_api_key_field"] is False
            assert displayed["stores_command_arguments"] is True
            assert displayed["command"] == ""
            configured_answer = session.ask(readme_node["node_id"], "Does saved config work?")
            assert "Does saved config work?" in configured_answer["answer"]
            assert "Category:" in configured_answer["answer"]
            try:
                session.set_ai_config("command", "'unterminated")
            except GuiRequestError as exc:
                assert "invalid AI command" in str(exc)
            else:
                raise AssertionError("invalid custom commands must return an actionable request error")
            failing_agent = home / "failing-agent.py"
            failing_agent.write_text(
                "import sys\nsys.stderr.write(" + repr(str(home)) + ")\nraise SystemExit(1)\n",
                encoding="utf-8",
            )
            session.set_ai_config("command", f"{sys.executable} {failing_agent}")
            assert str(home) not in json.dumps(session.payload())
            try:
                session.ask(readme_node["node_id"], "Do not leak provider stderr")
            except GuiRequestError as exc:
                assert str(home) not in str(exc)
                assert "did not return an answer" in str(exc)
            else:
                raise AssertionError("a failing provider must return a sanitized GUI error")
            session.set_ai_config("command", "cat")
            os.environ["CLEAN_YOUR_DATA_AI_COMMAND"] = "cat"

            staged = session.toggle_stage(build_node["node_id"])
            assert staged["staged"] is True
            try:
                session.move_staged_to_trash({build_node["node_id"]: "~/wrong"})
            except GuiRequestError as exc:
                assert "confirmation" in str(exc).lower()
            else:
                raise AssertionError("mismatched path confirmation must be rejected")
            assert build.exists()

            moved = session.move_staged_to_trash({build_node["node_id"]: build_node["path"]})
            assert moved["moved"] == 1
            assert not build.exists()
            assert list(trash.iterdir())
            restored = session.undo()
            assert restored["restored"] == 1
            assert build.exists()

            build_id = next(node["node_id"] for node in session.payload()["nodes"] if node["name"] == "build")
            source_id = next(node["node_id"] for node in session.payload()["nodes"] if node["name"] == "src")
            session.toggle_stage(build_id)
            session.toggle_stage(source_id)
            original_move_to_trash = gui_module.move_to_trash

            def fail_source_move(path, **kwargs):
                if path.name == "src":
                    raise OSError("fixture failure with a private absolute path")
                return original_move_to_trash(path, **kwargs)

            gui_module.move_to_trash = fail_source_move
            try:
                partial = session.move_staged_to_trash(
                    {
                        build_id: next(node["path"] for node in session.payload()["nodes"] if node["node_id"] == build_id),
                        source_id: next(node["path"] for node in session.payload()["nodes"] if node["node_id"] == source_id),
                    }
                )
            finally:
                gui_module.move_to_trash = original_move_to_trash
            assert partial["moved"] == 1
            assert len(partial["errors"]) == 1
            assert str(home) not in json.dumps(partial["errors"])
            assert not build.exists()
            assert source.exists()
            assert source_id in partial["session"]["staged"]
            assert session.undo()["restored"] == 1
            assert build.exists()
            session.toggle_stage(source_id)

            fresh_payload = session.payload()
            build_node = next(node for node in fresh_payload["nodes"] if node["name"] == "build")
            backup_node = next(node for node in fresh_payload["nodes"] if node["name"] == "README.md")
            session.toggle_stage(build_node["node_id"])
            session.toggle_stage(backup_node["node_id"])
            two_moves = session.move_staged_to_trash(
                {
                    build_node["node_id"]: build_node["path"],
                    backup_node["node_id"]: backup_node["path"],
                }
            )
            assert two_moves["moved"] == 2
            original_restore = gui_module.restore_trash_record

            def fail_readme_restore(record, history_path=None):
                if record.get("name") == "README.md":
                    raise FileExistsError("fixture failure with a private absolute path")
                return original_restore(record, history_path)

            gui_module.restore_trash_record = fail_readme_restore
            try:
                partial_undo = session.undo()
            finally:
                gui_module.restore_trash_record = original_restore
            assert partial_undo["restored"] == 1
            assert len(partial_undo["errors"]) == 1
            assert str(home) not in json.dumps(partial_undo["errors"])
            assert build.exists()
            assert not (root / "README.md").exists()
            assert len(session.last_records) == 1
            assert session.undo()["restored"] == 1
            assert (root / "README.md").exists()

            token = "gui-test-token"
            server = create_server(session, token=token)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(base + "/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                assert token in html
                assert "__CYD_SESSION_TOKEN__" not in html

                spoofed_host = urllib.request.Request(base + "/", headers={"Host": "example.com"})
                try:
                    urllib.request.urlopen(spoofed_host, timeout=5)
                except urllib.error.HTTPError as exc:
                    assert exc.code == 403
                else:
                    raise AssertionError("a non-loopback Host header must be rejected")

                try:
                    urllib.request.urlopen(base + "/api/session", timeout=5)
                except urllib.error.HTTPError as exc:
                    assert exc.code == 403
                else:
                    raise AssertionError("API request without the session token must fail")

                status, api_payload = request_json(base + "/api/session", token)
                assert status == 200
                assert api_payload["scope"]["path"] == "~/workspace"

                try:
                    request_json(
                        base + "/api/session",
                        token,
                        origin="https://example.com",
                    )
                except urllib.error.HTTPError as exc:
                    assert exc.code == 403
                else:
                    raise AssertionError("cross-origin request must fail")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                assert not thread.is_alive()
    finally:
        if previous_ai is None:
            os.environ.pop("CLEAN_YOUR_DATA_AI_COMMAND", None)
        else:
            os.environ["CLEAN_YOUR_DATA_AI_COMMAND"] = previous_ai

    print("gui test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
