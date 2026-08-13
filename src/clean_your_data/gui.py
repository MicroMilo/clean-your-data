"""Local browser GUI backed by the same scanner and safety gates as the TUI."""

from __future__ import annotations

import argparse
import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import parse_qs, urlparse

from .ai_config import (
    config_for_display,
    load_ai_config,
    parse_command,
    save_ai_config,
)
from .audit_local_files import expand_space_map_node, scan_space_map
from .audit_tui import (
    analyze_path_relationships,
    ask_local_ai,
    build_path_evidence_prompt,
    cleanup_gate,
    load_cleanup_history,
    move_to_trash,
    preliminary_cleanup_advice,
    read_file_preview,
    restore_trash_record,
)


GUI_BODY_LIMIT = 32 * 1024
GUI_QUESTION_LIMIT = 2_000
GUI_DEFAULT_NODE_LIMIT = 600
GUI_DEFAULT_DEPTH = 2
GUI_DEFAULT_TIME_BUDGET = 30
GUI_DEFAULT_TIMEOUT = 5
REBUILDABLE_NAMES = {
    "node_modules",
    ".venv",
    "venv",
    "build",
    "dist",
    ".next",
    "target",
    ".pytest_cache",
    "__pycache__",
}


class GuiRequestError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = int(status)


class GuiSession:
    """Mutable local GUI state. Absolute paths never enter public responses."""

    def __init__(
        self,
        root: Path,
        *,
        home: Optional[Path] = None,
        depth: int = GUI_DEFAULT_DEPTH,
        node_limit: int = GUI_DEFAULT_NODE_LIMIT,
        timeout: int = GUI_DEFAULT_TIMEOUT,
        time_budget: int = GUI_DEFAULT_TIME_BUDGET,
        trash_root: Optional[Path] = None,
        history_path: Optional[Path] = None,
        ai_config_path: Optional[Path] = None,
    ) -> None:
        requested = root.expanduser()
        try:
            resolved = requested.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"GUI path is unavailable: {requested}: {exc}") from exc
        if not resolved.is_dir():
            raise ValueError(f"GUI path must be a directory: {requested}")
        self.root = resolved
        self.home = (home or Path.home()).expanduser().resolve()
        self.depth = max(0, depth)
        self.node_limit = max(10, node_limit)
        self.timeout = max(1, timeout)
        self.time_budget = max(0, time_budget)
        self.trash_root = trash_root
        self.history_path = history_path
        self.ai_config_path = ai_config_path
        self.lock = threading.RLock()
        self.nodes: list[dict[str, Any]] = []
        self.nodes_by_id: dict[str, dict[str, Any]] = {}
        self.status = "unknown"
        self.errors: list[str] = []
        self.staged: set[str] = set()
        self.last_records: list[dict[str, Any]] = []
        self.refresh()

    def refresh(self) -> None:
        mapped = scan_space_map(
            [self.root],
            [],
            [self.root],
            self.home,
            self.depth,
            self.node_limit,
            self.timeout,
            self.time_budget,
            True,
            include_local_paths=True,
            allow_skipped_root=True,
        )
        with self.lock:
            self.nodes = list(mapped.get("nodes") or [])
            self.nodes_by_id = {str(node.get("node_id")): node for node in self.nodes}
            self.status = str(mapped.get("status") or "unknown")
            self.errors = list(mapped.get("errors") or [])
            self.staged.intersection_update(self.nodes_by_id)

    def root_node(self) -> dict[str, Any]:
        node = next((item for item in self.nodes if item.get("parent_id") is None), None)
        if not node:
            raise GuiRequestError("The selected path could not be measured.", HTTPStatus.SERVICE_UNAVAILABLE)
        return node

    def node(self, node_id: str) -> dict[str, Any]:
        with self.lock:
            node = self.nodes_by_id.get(str(node_id))
        if not node:
            raise GuiRequestError("The selected path is no longer available.", HTTPStatus.NOT_FOUND)
        return node

    def public_node(self, node: dict[str, Any]) -> dict[str, Any]:
        # Keep list rendering cheap. The selected path receives the Git-index
        # check in inspect(), staging, and final confirmation.
        allowed, reason = self.cleanup_eligibility(node, check_git=False)
        name = str(node.get("name") or "")
        category = str(node.get("category") or "unknown")
        if not allowed:
            risk = "protected"
        elif category == "cache" or name in REBUILDABLE_NAMES:
            risk = "rebuildable"
        else:
            risk = "review"
        return {
            key: value
            for key, value in node.items()
            if not str(key).startswith("_") and key != "measurement_error"
        } | {
            "risk": risk,
            "cleanup_eligible": allowed,
            "cleanup_reason": reason,
            "staged": str(node.get("node_id")) in self.staged,
        }

    def payload(self) -> dict[str, Any]:
        with self.lock:
            nodes = [self.public_node(node) for node in self.nodes]
            staged = list(self.staged)
        root = self.public_node(self.root_node())
        provider = config_for_display(load_ai_config(self.ai_config_path))
        return {
            "version": 1,
            "scope": root,
            "status": self.status,
            "errors": self.errors[:10],
            "nodes": nodes,
            "staged": staged,
            "ai": provider,
            "privacy": {
                "redacted_paths": True,
                "preview_limit_bytes": 4096,
                "preview_sent_to_ai": False,
                "server": "127.0.0.1",
            },
        }

    def expand(self, node_id: str) -> dict[str, Any]:
        node = self.node(node_id)
        if node.get("kind") != "folder":
            raise GuiRequestError("Only folders can be expanded.")
        with self.lock:
            loaded = [item for item in self.nodes if item.get("parent_id") == node.get("node_id")]
        if loaded:
            return {"status": "complete", "nodes": [self.public_node(item) for item in loaded]}
        children, status = expand_space_map_node(
            node,
            self.home,
            True,
            self.timeout,
            self.node_limit,
            self.time_budget,
        )
        with self.lock:
            for child in children:
                child_id = str(child.get("node_id"))
                if child_id not in self.nodes_by_id:
                    self.nodes.append(child)
                    self.nodes_by_id[child_id] = child
        return {"status": status, "nodes": [self.public_node(item) for item in children]}

    def preview(self, node_id: str) -> dict[str, Any]:
        node = self.node(node_id)
        if node.get("kind") == "folder":
            with self.lock:
                children = [item for item in self.nodes if item.get("parent_id") == node.get("node_id")]
            if children:
                lines = [
                    f"{item.get('name')}{'/' if item.get('kind') == 'folder' else ''}  {item.get('human_size') or 'unknown'}"
                    for item in children[:24]
                ]
                if len(children) > 24:
                    lines.append(f"... {len(children) - 24} more loaded entries ...")
            elif node.get("can_expand"):
                lines = ["Open this folder to load its next level."]
            else:
                lines = ["(empty folder)"]
            return {"kind": "folder", "lines": lines, "limited": len(children) > 24}
        lines = read_file_preview(node)
        return {"kind": "file", "lines": lines, "limited": any("preview limited" in line for line in lines)}

    def inspect(self, node_id: str) -> dict[str, Any]:
        node = self.node(node_id)
        allowed, reason = self.cleanup_eligibility(node)
        return {
            "node": self.public_node(node),
            "advice": preliminary_cleanup_advice(node),
            "cleanup": {"eligible": allowed, "reason": reason},
            "ai_context": {
                "includes": ["redacted path", "name", "kind", "size", "modified time", "category", "project markers", "bounded relationships", "optional local trace association"],
                "excludes": ["file preview", "file contents", "credentials", "cleanup authority"],
            },
        }

    def relationships(self, node_id: str) -> dict[str, Any]:
        return analyze_path_relationships(self.node(node_id))

    def cleanup_eligibility(self, node: dict[str, Any], *, check_git: bool = True) -> tuple[bool, str]:
        if str(node.get("node_id")) == str(self.root_node().get("node_id")):
            return False, "the active GUI scope is protected"
        local_path = Path(str(node.get("_local_path") or ""))
        try:
            local_path.resolve().relative_to(self.root)
        except (OSError, RuntimeError, ValueError):
            return False, "the path is outside the active GUI scope"
        return cleanup_gate(node, check_git=check_git)

    def toggle_stage(self, node_id: str) -> dict[str, Any]:
        node = self.node(node_id)
        allowed, reason = self.cleanup_eligibility(node)
        if not allowed:
            raise GuiRequestError(f"This path cannot enter the cleanup basket: {reason}", HTTPStatus.CONFLICT)
        with self.lock:
            if node_id in self.staged:
                self.staged.remove(node_id)
                staged = False
            else:
                self.staged.add(node_id)
                staged = True
        return {"node_id": node_id, "staged": staged, "basket": self.basket()}

    def basket(self) -> dict[str, Any]:
        with self.lock:
            selected = [self.nodes_by_id[node_id] for node_id in self.staged if node_id in self.nodes_by_id]
        return {
            "nodes": [self.public_node(node) for node in selected],
            "total_bytes": sum(int(node.get("allocated_bytes") or 0) for node in selected),
        }

    def ask(self, node_id: str, question: str) -> dict[str, Any]:
        node = self.node(node_id)
        clean_question = question.strip()
        if not clean_question:
            raise GuiRequestError("Question cannot be empty.")
        if len(clean_question) > GUI_QUESTION_LIMIT:
            raise GuiRequestError(f"Question must be at most {GUI_QUESTION_LIMIT} characters.")
        answer, message = ask_local_ai(
            build_path_evidence_prompt(node, clean_question, home=self.home),
            config_path=self.ai_config_path,
        )
        if answer is None:
            provider = config_for_display(load_ai_config(self.ai_config_path)).get("provider") or "Configured Agent"
            raise GuiRequestError(
                f"{provider} did not return an answer. Check the local provider configuration and try again.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return {"node_id": node_id, "answer": answer, "provider_message": message}

    def move_staged_to_trash(self, confirmations: dict[str, str]) -> dict[str, Any]:
        with self.lock:
            staged_ids = sorted(
                self.staged,
                key=lambda node_id: str(self.nodes_by_id.get(node_id, {}).get("path") or node_id),
            )
        if not staged_ids:
            raise GuiRequestError("The cleanup basket is empty.", HTTPStatus.CONFLICT)

        staged_nodes = [self.node(node_id) for node_id in staged_ids]
        for node in staged_nodes:
            node_id = str(node.get("node_id"))
            if confirmations.get(node_id) != str(node.get("path")):
                raise GuiRequestError("Exact path confirmation did not match.", HTTPStatus.CONFLICT)
            allowed, reason = self.cleanup_eligibility(node)
            if not allowed:
                raise GuiRequestError(f"{node.get('path')}: {reason}", HTTPStatus.CONFLICT)

        records: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for node in staged_nodes:
            try:
                record = move_to_trash(
                    Path(str(node.get("_local_path"))),
                    node=node,
                    trash_root=self.trash_root,
                    history_path=self.history_path,
                )
            except (OSError, RuntimeError, ValueError):
                errors.append(
                    {
                        "path": str(node.get("path") or "unknown"),
                        "error": "The path could not be moved. It may have changed or become unavailable.",
                    }
                )
                continue
            records.append(record)
            with self.lock:
                self.staged.discard(str(node.get("node_id")))
        self.last_records = records
        self.refresh()
        return {
            "moved": len(records),
            "errors": errors,
            "records": [
                {
                    "record_id": record.get("record_id"),
                    "name": record.get("name"),
                    "human_size": record.get("human_size"),
                    "status": record.get("status"),
                }
                for record in records
            ],
            "session": self.payload(),
        }

    def undo(self) -> dict[str, Any]:
        if not self.last_records:
            raise GuiRequestError("There is no cleanup action to undo.", HTTPStatus.CONFLICT)
        pending_records = list(self.last_records)
        restored: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        failed_record_ids: set[str] = set()
        for record in reversed(pending_records):
            try:
                restored.append(restore_trash_record(record, self.history_path))
            except (OSError, RuntimeError, ValueError):
                record_id = str(record.get("record_id") or "")
                failed_record_ids.add(record_id)
                errors.append(
                    {
                        "name": str(record.get("name") or "unknown"),
                        "error": "The Trash item could not be restored. Its original path may now be occupied.",
                    }
                )
        self.last_records = [
            record for record in pending_records if str(record.get("record_id") or "") in failed_record_ids
        ]
        self.refresh()
        return {
            "restored": len(restored),
            "errors": errors,
            "records": [{"record_id": row.get("record_id"), "name": row.get("name")} for row in restored],
            "session": self.payload(),
        }

    def cleanup_history(self) -> list[dict[str, Any]]:
        rows = load_cleanup_history(self.history_path)
        return [
            {
                "record_id": row.get("record_id"),
                "name": row.get("name"),
                "kind": row.get("kind"),
                "human_size": row.get("human_size"),
                "moved_at": row.get("moved_at"),
                "restored_at": row.get("restored_at"),
                "status": row.get("status"),
            }
            for row in rows[-50:]
        ]

    def set_ai_config(self, mode: str, command_text: str = "") -> dict[str, Any]:
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"auto", "codex", "command", "off"}:
            raise GuiRequestError("Unknown AI mode.")
        try:
            command = parse_command(command_text) if normalized_mode == "command" else []
        except ValueError as exc:
            raise GuiRequestError(str(exc)) from exc
        config = save_ai_config(
            {"version": 1, "mode": normalized_mode, "command": command},
            self.ai_config_path,
        )
        return config_for_display(config)


def load_gui_html(token: str) -> bytes:
    template = resources.files("clean_your_data").joinpath("web/index.html").read_text(encoding="utf-8")
    return template.replace("__CYD_SESSION_TOKEN__", token).encode("utf-8")


class GuiHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        session: GuiSession,
        token: str,
        *,
        verbose: bool = False,
    ) -> None:
        self.session = session
        self.token = token
        self.verbose = verbose
        self.html = load_gui_html(token)
        super().__init__(server_address, GuiRequestHandler)


class GuiRequestHandler(BaseHTTPRequestHandler):
    server: GuiHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.verbose:
            super().log_message(format, *args)

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'none'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        self.end_headers()

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _send_error_json(self, exc: Exception) -> None:
        if isinstance(exc, GuiRequestError):
            status = exc.status
            message = str(exc)
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            message = "The local GUI could not complete this request."
        self._send_json({"error": message}, status)

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-CYD-Token", ""), self.server.token)

    def _check_local_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == self.server.server_port

    def _check_local_host(self) -> bool:
        host = self.headers.get("Host", "")
        try:
            parsed = urlparse("//" + host)
            port = parsed.port
        except ValueError:
            return False
        return parsed.hostname in {"127.0.0.1", "localhost"} and (
            port == self.server.server_port or (port is None and self.server.server_port == 80)
        )

    def _json_body(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("application/json"):
            raise GuiRequestError("Requests must use application/json.", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise GuiRequestError("Invalid request length.") from exc
        if length < 0 or length > GUI_BODY_LIMIT:
            raise GuiRequestError("Request body is too large.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GuiRequestError("Request body is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise GuiRequestError("Request body must be a JSON object.")
        return payload

    def _require_api_access(self) -> bool:
        if not self._check_local_host() or not self._authorized() or not self._check_local_origin():
            self._send_json({"error": "Local GUI session authorization failed."}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            if not self._check_local_host():
                self._send_json({"error": "Local GUI host validation failed."}, HTTPStatus.FORBIDDEN)
                return
            body = self.server.html
            self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
            return
        if not self._require_api_access():
            return
        try:
            query = parse_qs(parsed.query)
            if parsed.path == "/api/session":
                self._send_json(self.server.session.payload())
            elif parsed.path == "/api/preview":
                self._send_json(self.server.session.preview(_one(query, "node_id")))
            elif parsed.path == "/api/inspect":
                self._send_json(self.server.session.inspect(_one(query, "node_id")))
            elif parsed.path == "/api/relationships":
                self._send_json(self.server.session.relationships(_one(query, "node_id")))
            elif parsed.path == "/api/config":
                self._send_json(config_for_display(load_ai_config(self.server.session.ai_config_path)))
            elif parsed.path == "/api/history":
                self._send_json({"history": self.server.session.cleanup_history()})
            else:
                self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error_json(exc)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self._require_api_access():
            return
        try:
            payload = self._json_body()
            if parsed.path == "/api/expand":
                result = self.server.session.expand(str(payload.get("node_id") or ""))
            elif parsed.path == "/api/stage":
                result = self.server.session.toggle_stage(str(payload.get("node_id") or ""))
            elif parsed.path == "/api/ask":
                result = self.server.session.ask(
                    str(payload.get("node_id") or ""),
                    str(payload.get("question") or ""),
                )
            elif parsed.path == "/api/config":
                result = self.server.session.set_ai_config(
                    str(payload.get("mode") or ""),
                    str(payload.get("command") or ""),
                )
            elif parsed.path == "/api/trash":
                confirmations = payload.get("confirmations")
                if not isinstance(confirmations, dict):
                    raise GuiRequestError("Exact path confirmations are required.")
                result = self.server.session.move_staged_to_trash(
                    {str(key): str(value) for key, value in confirmations.items()}
                )
            elif parsed.path == "/api/undo":
                result = self.server.session.undo()
            elif parsed.path == "/api/rescan":
                self.server.session.refresh()
                result = self.server.session.payload()
            elif parsed.path == "/api/shutdown":
                result = {"stopping": True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(result)
        except Exception as exc:
            self._send_error_json(exc)


def _one(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name) or []
    if len(values) != 1 or not values[0]:
        raise GuiRequestError(f"Missing query parameter: {name}")
    return values[0]


def create_server(
    session: GuiSession,
    *,
    port: int = 0,
    token: Optional[str] = None,
    verbose: bool = False,
) -> GuiHTTPServer:
    if port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")
    return GuiHTTPServer(("127.0.0.1", port), session, token or secrets.token_urlsafe(32), verbose=verbose)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cyd gui",
        description="Open the local Clean Your Data browser GUI.",
    )
    parser.add_argument("path", nargs="?", default=".", help="Directory to explore. Defaults to the current directory.")
    parser.add_argument("--no-open", action="store_true", help="Start the local GUI server without opening a browser.")
    parser.add_argument("--port", type=int, default=0, help="Loopback port. Defaults to a random available port.")
    parser.add_argument("--depth", type=int, default=GUI_DEFAULT_DEPTH, help="Initial scan depth. Deeper folders load on demand.")
    parser.add_argument("--node-limit", type=int, default=GUI_DEFAULT_NODE_LIMIT, help="Maximum nodes in the initial map.")
    parser.add_argument("--time-budget", type=int, default=GUI_DEFAULT_TIME_BUDGET, help="Initial scan time budget in seconds.")
    parser.add_argument("--verbose", action="store_true", help="Print local HTTP request logs.")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(list(argv or []))
    try:
        session = GuiSession(
            Path(args.path),
            depth=args.depth,
            node_limit=args.node_limit,
            time_budget=args.time_budget,
        )
        server = create_server(session, port=args.port, verbose=args.verbose)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Clean Your Data GUI: {url}")
    print("Local only. Press Ctrl-C to stop the server.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping Clean Your Data GUI.")
    finally:
        server.server_close()
    return 0
