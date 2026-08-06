#!/usr/bin/env python3
"""Dependency-free terminal UI for exploring a metadata-only audit report."""

from __future__ import annotations

import curses
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
import textwrap
import time
from pathlib import Path
from typing import Any, Callable, Optional


DEFAULT_QUESTION = "What is this area likely used for, and what should I check before changing it?"
INITIAL_TREE_LEVELS = 3
SPINNER_FRAMES = ("|", "/", "-", "\\")
PREVIEW_MAX_BYTES = 4096
PREVIEW_MAX_LINES = 14

PALETTE: dict[str, int] = {}

DISPLAY_LABELS = {
    "measured": "Checked",
    "timeout": "Timed out",
    "error": "Could not check",
    "missing": "Not found",
    "not_found": "Not found",
    "unknown": "Needs review",
    "complete": "Complete",
    "disabled": "Not run",
    "partial": "Partial",
    "limit": "Stopped early",
    "exact": "Identical files",
    "dirty": "Uncommitted work",
    "strong_inference": "Likely",
    "confirmed": "Confirmed",
    "low": "Uncertain",
    "review_only": "Review first",
    "approval_required": "Needs approval",
    "workspace": "Work files",
    "inbox": "Inbox / Downloads",
    "app-state": "App data",
    "cloud-sync": "Cloud files",
    "cache": "Rebuildable",
    "deliverable": "Finished work",
    "duplicate": "Repeated files",
    "user-data": "Your files",
    "review": "Check first",
    "unknown scope": "Unknown area",
    "Codex date workspaces": "Codex dated folders",
    "Source roots": "Code folders",
    "Cloud sync": "Cloud folders",
    "AI and coding agents": "AI tools and agents",
    "Feishu/Lark": "Feishu / Lark",
}


def display_label(value: Any) -> str:
    raw = "" if value is None else str(value)
    return DISPLAY_LABELS.get(raw, raw.replace("_", " ").replace("-", " ").strip().capitalize())


def display_date(value: Any) -> str:
    if not value:
        return "Not available"
    return str(value).replace("T", " ").replace("+08:00", "").replace("Z", "")


def display_size(node: dict[str, Any]) -> str:
    return str(node.get("human_size") or "Not available")


def display_node_name(node: dict[str, Any]) -> str:
    name = str(node.get("name") or node.get("path") or "unnamed")
    return f"{name}/" if node.get("kind") == "folder" and not name.endswith("/") else name


def display_node_path(node: dict[str, Any]) -> str:
    path = str(node.get("path") or "Path unavailable")
    return f"{path}/" if node.get("kind") == "folder" and not path.endswith("/") else path


def sensitive_preview_path(path: Path) -> bool:
    name = path.name.lower()
    sensitive_names = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "credentials",
        "credentials.json",
        "secrets.json",
        "id_rsa",
        "id_ed25519",
        "known_hosts",
    }
    sensitive_suffixes = (".pem", ".key", ".p12", ".pfx", ".kdbx")
    return name in sensitive_names or name.endswith(sensitive_suffixes)


def read_file_preview(node: dict[str, Any]) -> list[str]:
    """Read a small, local text preview without making it part of AI context."""
    local_path = node.get("_local_path")
    if not local_path:
        return ["Preview unavailable for this path."]
    path = Path(str(local_path))
    if sensitive_preview_path(path):
        return ["Preview hidden because this filename may contain credentials or private configuration."]
    try:
        with path.open("rb") as handle:
            data = handle.read(PREVIEW_MAX_BYTES + 1)
    except OSError as exc:
        return [f"Preview unavailable: {exc}"]
    if b"\x00" in data[:PREVIEW_MAX_BYTES]:
        return ["Binary file; text preview is unavailable."]
    truncated = len(data) > PREVIEW_MAX_BYTES
    text = data[:PREVIEW_MAX_BYTES].decode("utf-8", errors="replace")
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        safe_line = "".join(char if char == "\t" or ord(char) >= 32 else "?" for char in line)
        lines.append(safe_line)
    if not lines:
        lines = ["(empty file)"]
    if len(lines) > PREVIEW_MAX_LINES:
        lines = lines[:PREVIEW_MAX_LINES]
        truncated = True
    if truncated:
        lines.append("... preview limited to the first 4 KB / 14 lines ...")
    return lines


def palette(name: str) -> int:
    return PALETTE.get(name, 0)


def key_matches(key: Any, *candidates: Any) -> bool:
    """Match both get_wch() characters and curses integer key codes."""
    for candidate in candidates:
        if key == candidate:
            return True
        if isinstance(key, str) and isinstance(candidate, int) and len(key) == 1 and ord(key) == candidate:
            return True
    return False


def resolve_ai_command() -> tuple[Optional[list[str]], str]:
    """Prefer an explicit command, otherwise use a read-only ephemeral Codex CLI."""
    configured = os.environ.get("CLEAN_YOUR_DATA_AI_COMMAND", "").strip()
    if configured:
        try:
            command = shlex.split(configured)
        except ValueError:
            return None, "Configured local AI command is invalid."
        return (command or None), "Configured local AI"
    codex = shutil.which("codex")
    if codex:
        return (
            [
                codex,
                "exec",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color",
                "never",
                "-C",
                "/tmp",
                "-",
            ],
            "Codex",
        )
    return None, "No local AI command"


def build_prompt(node: dict[str, Any], question: str = DEFAULT_QUESTION) -> str:
    """Build the exact metadata-only context used by the optional AI command."""
    return "\n".join(
        [
            "Please help me understand this area of my local computer using only the metadata below.",
            "Do not ask me to upload or open file contents unless I explicitly approve it.",
            "",
            f"Path: {node.get('path', 'unknown')}",
            f"Name: {node.get('name', 'unknown')}",
            f"Kind: {'folder' if node.get('kind') == 'folder' else 'file'}",
            f"Size: {node.get('human_size') or 'unknown'}",
            f"Last changed: {display_date(node.get('modified_at'))}",
            f"Area: {node.get('area') or 'unknown'}",
            f"Measurement: {node.get('measurement_status') or 'unknown'}",
            "",
            f"My question: {question.strip() or DEFAULT_QUESTION}",
            "",
            "Please answer in the same language as my question and use plain language: what this area is likely used for, what evidence supports that, what remains unknown, and the safest next check. Do not recommend deleting anything merely because it is large.",
        ]
    )


def children_by_parent(nodes: list[dict[str, Any]]) -> dict[Optional[str], list[dict[str, Any]]]:
    result: dict[Optional[str], list[dict[str, Any]]] = {}
    for node in nodes:
        result.setdefault(node.get("parent_id"), []).append(node)
    return result


def visible_nodes(nodes: list[dict[str, Any]], expanded: set[str]) -> list[dict[str, Any]]:
    """Return the report tree in display order, respecting collapsed folders."""
    by_parent = children_by_parent(nodes)
    visible: list[dict[str, Any]] = []

    def visit(parent_id: Optional[str]) -> None:
        for node in by_parent.get(parent_id, []):
            visible.append(node)
            if node.get("kind") == "folder" and node.get("node_id") in expanded:
                visit(str(node.get("node_id")))

    visit(None)
    return visible


def wrap_lines(value: Any, width: int) -> list[str]:
    text = "" if value is None else str(value)
    if width <= 1:
        return [""]
    lines: list[str] = []
    for source in text.splitlines() or [""]:
        lines.extend(textwrap.wrap(source, width=width, break_long_words=True, break_on_hyphens=False) or [""])
    return lines


def copy_to_clipboard(value: str) -> str:
    """Use an installed native clipboard command without adding a dependency."""
    candidates = []
    if shutil.which("pbcopy"):
        candidates.append(["pbcopy"])
    if shutil.which("wl-copy"):
        candidates.append(["wl-copy"])
    if shutil.which("xclip"):
        candidates.append(["xclip", "-selection", "clipboard"])
    if not candidates:
        return "No clipboard command found. Press A to ask Codex or copy the context manually."
    for command in candidates:
        try:
            result = subprocess.run(
                command,
                input=value,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return "Metadata-only AI context copied to the clipboard."
    return "Clipboard access failed. Press A to ask Codex or copy the context manually."


def ask_local_ai(prompt: str, cancel_event: Optional[threading.Event] = None) -> tuple[Optional[str], str]:
    """Call the configured local AI, or a read-only ephemeral Codex CLI when available."""
    command, provider = resolve_ai_command()
    if not command:
        return None, f"{provider} Press c to copy the metadata-only context."
    process: Optional[subprocess.Popen[str]] = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started = time.monotonic()
        sent_input = False
        while True:
            if cancel_event and cancel_event.is_set():
                process.kill()
                process.communicate()
                return None, f"{provider} request cancelled."
            if time.monotonic() - started >= 60:
                process.kill()
                process.communicate()
                return None, f"{provider} timed out. Press c to copy the context."
            try:
                stdout, stderr = process.communicate(input=prompt if not sent_input else None, timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                sent_input = True
                continue
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return None, f"{provider} did not answer: {exc}. Press c to copy the context."
    if process.returncode != 0:
        detail = stderr.strip() or f"exit code {process.returncode}"
        return None, f"{provider} failed: {detail}. Press c to copy the context."
    answer = stdout.strip()
    if not answer:
        return None, f"{provider} returned no answer. Press c to copy the context."
    return answer, f"{provider} answer ready. Press A to ask a follow-up."


class TuiState:
    def __init__(
        self,
        report: dict[str, Any],
        expand_callback: Optional[Callable[[dict[str, Any]], tuple[list[dict[str, Any]], str]]] = None,
    ):
        self.report = report
        self.space_map = report.get("space_map") or {}
        self.nodes = list(self.space_map.get("nodes") or [])
        self.expand_callback = expand_callback
        # Show the root plus two child levels first. Enter reveals one more level;
        # pressing Enter again on that folder collapses it.
        loaded_children = children_by_parent(self.nodes)
        self.expanded = {
            str(node.get("node_id"))
            for node in self.nodes
            if node.get("kind") == "folder"
            and node.get("can_expand")
            and loaded_children.get(node.get("node_id"))
            and int(node.get("depth") or 0) < INITIAL_TREE_LEVELS - 1
        }
        self.selected_id = self.nodes[0].get("node_id") if self.nodes else None
        self.scroll = 0
        self.message = "Select an area. The scan is read-only and metadata-only. Press A to ask Codex."
        self.question = DEFAULT_QUESTION
        self.prompt = ""
        self.answer = ""
        self.question_editing = False
        self.question_buffer = ""
        self.questions_by_node: dict[str, str] = {}
        self.prompts_by_node: dict[str, str] = {}
        self.answers_by_node: dict[str, str] = {}
        self.ai_messages_by_node: dict[str, str] = {}
        self.preview_cache: dict[str, list[str]] = {}
        self.ai_results: queue.Queue[tuple[int, str, Optional[str], str]] = queue.Queue()
        self.ai_busy = False
        self.ai_busy_node_id: Optional[str] = None
        self.ai_spinner_index = 0
        self.ai_request_id = 0
        self.ai_current_request_id: Optional[int] = None
        self.ai_cancel_event: Optional[threading.Event] = None
        self.ai_cancelled_requests: set[int] = set()
        self.help_open = False
        self.vim_pending_g = False

    def visible(self) -> list[dict[str, Any]]:
        return visible_nodes(self.nodes, self.expanded)

    def selected(self) -> Optional[dict[str, Any]]:
        for node in self.visible():
            if node.get("node_id") == self.selected_id:
                return node
        visible = self.visible()
        return visible[0] if visible else None

    def node_by_id(self, node_id: Optional[str]) -> Optional[dict[str, Any]]:
        if node_id is None:
            return None
        return next((node for node in self.nodes if str(node.get("node_id")) == str(node_id)), None)

    def sync_selection_context(self) -> None:
        node_id = str(self.selected_id) if self.selected_id is not None else ""
        self.question = self.questions_by_node.get(node_id, DEFAULT_QUESTION)
        self.prompt = self.prompts_by_node.get(node_id, "")
        self.answer = self.answers_by_node.get(node_id, "")

    def preview_for(self, node: dict[str, Any]) -> list[str]:
        if node.get("kind") != "file":
            return []
        node_id = str(node.get("node_id"))
        if node_id not in self.preview_cache:
            self.preview_cache[node_id] = read_file_preview(node)
        return self.preview_cache[node_id]

    def select_index(self, index: int) -> None:
        visible = self.visible()
        if not visible:
            self.selected_id = None
            return
        index = max(0, min(index, len(visible) - 1))
        self.selected_id = visible[index].get("node_id")
        self.sync_selection_context()
        selected_node = self.selected()
        if self.ai_busy:
            self.message = "You can keep moving. Codex is thinking " + SPINNER_FRAMES[self.ai_spinner_index] + "."
        elif selected_node and self.ai_messages_by_node.get(str(selected_node.get("node_id"))):
            self.message = self.ai_messages_by_node[str(selected_node.get("node_id"))]
        else:
            self.message = "Selected area changed. Press A to ask Codex about it."

    def load_children(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        node_id = str(node.get("node_id"))
        existing = children_by_parent(self.nodes).get(node.get("node_id"), [])
        if existing:
            return existing
        if not node.get("can_expand") or self.expand_callback is None:
            return []
        try:
            new_nodes, status = self.expand_callback(node)
        except Exception as exc:
            self.message = f"Could not open this folder: {exc}"
            return []
        if new_nodes:
            self.nodes.extend(new_nodes)
            self.message = f"Loaded {len(new_nodes)} entries from {display_node_name(node)}"
        elif status in {"partial", "limit"}:
            self.message = f"This folder could not be fully opened ({display_label(status)})."
        else:
            self.message = "This folder has no readable entries."
        return children_by_parent(self.nodes).get(node.get("node_id"), [])

    def open_or_close(self, node: dict[str, Any]) -> None:
        if node.get("kind") != "folder":
            return
        node_id = str(node.get("node_id"))
        children = children_by_parent(self.nodes).get(node.get("node_id"), [])
        if not children:
            children = self.load_children(node)
        if not children:
            return
        if node_id in self.expanded:
            self.expanded.remove(node_id)
            self.message = f"Closed {display_node_name(node)}"
        else:
            self.expanded.add(node_id)
            self.message = f"Opened {display_node_name(node)}"

    def start_ai(self, node: dict[str, Any], prompt: str) -> bool:
        if self.ai_busy:
            self.message = "Codex is already thinking. You can still move through the tree."
            return False
        node_id = str(node.get("node_id"))
        self.prompts_by_node[node_id] = prompt
        self.questions_by_node[node_id] = self.question
        self.ai_busy = True
        self.ai_busy_node_id = node_id
        self.ai_spinner_index = 0
        self.ai_request_id += 1
        request_id = self.ai_request_id
        self.ai_current_request_id = request_id
        cancel_event = threading.Event()
        self.ai_cancel_event = cancel_event
        self.ai_messages_by_node[node_id] = "Codex is thinking..."

        def worker() -> None:
            answer, message = ask_local_ai(prompt, cancel_event)
            self.ai_results.put((request_id, node_id, answer, message))

        threading.Thread(target=worker, name="clean-your-data-codex", daemon=True).start()
        self.message = "Codex is thinking " + SPINNER_FRAMES[self.ai_spinner_index] + ". You can keep moving."
        return True

    def cancel_ai(self) -> None:
        if not self.ai_busy or self.ai_current_request_id is None:
            return
        request_id = self.ai_current_request_id
        self.ai_cancelled_requests.add(request_id)
        if self.ai_cancel_event:
            self.ai_cancel_event.set()
        self.ai_busy = False
        self.ai_busy_node_id = None
        self.ai_current_request_id = None
        self.ai_cancel_event = None
        self.message = "Codex request cancelled. You can keep browsing."

    def poll_ai(self) -> None:
        if self.ai_busy:
            self.ai_spinner_index = (self.ai_spinner_index + 1) % len(SPINNER_FRAMES)
        try:
            request_id, node_id, answer, message = self.ai_results.get_nowait()
        except queue.Empty:
            return
        if request_id in self.ai_cancelled_requests:
            self.ai_cancelled_requests.remove(request_id)
            return
        if request_id != self.ai_current_request_id:
            return
        self.ai_busy = False
        self.ai_busy_node_id = None
        self.ai_current_request_id = None
        self.ai_cancel_event = None
        if answer:
            self.answers_by_node[node_id] = answer
        self.ai_messages_by_node[node_id] = message
        if str(self.selected_id) == node_id:
            self.sync_selection_context()
            self.message = message
        else:
            node = self.node_by_id(node_id)
            self.message = f"{display_node_name(node) if node else 'Selected area'}: {message}"

    def spinner(self) -> str:
        return SPINNER_FRAMES[self.ai_spinner_index]


def add_text(stdscr: Any, y: int, x: int, value: Any, width: int, attr: int = 0) -> None:
    if y < 0 or x < 0 or width <= 0:
        return
    try:
        stdscr.addnstr(y, x, str(value), width, attr)
    except curses.error:
        pass


def draw_wrapped(stdscr: Any, y: int, x: int, value: Any, width: int, height: int, attr: int = 0) -> int:
    for line in wrap_lines(value, width)[: max(0, height)]:
        add_text(stdscr, y, x, line, width, attr)
        y += 1
    return y


def draw_header(stdscr: Any, state: TuiState, width: int) -> None:
    scope = ", ".join(str(item) for item in state.space_map.get("roots", [])[:3]) or "workspace roots"
    status = display_label(state.space_map.get("status", "unknown"))
    gate = display_label((state.report.get("action_gate") or {}).get("status", "review_only"))
    _, ai_label = resolve_ai_command()
    if state.ai_busy:
        ai_label = f"{ai_label} thinking {state.spinner()}"
    add_text(stdscr, 0, 0, "CLEAN YOUR DATA / TERMINAL EXPLORER", width, curses.A_BOLD | palette("title"))
    add_text(stdscr, 1, 0, f"Scope: {scope}  |  Map: {status}  |  Decision: {gate}  |  AI: {ai_label}", width, palette("status"))
    add_text(stdscr, 2, 0, "READ ONLY  |  Metadata scan  |  Selected text files show a small local preview", width, palette("muted"))
    add_text(stdscr, 3, 0, "UP/DOWN move   gg top   G bottom   ENTER open/close   A ask Codex   ? help   Q quit", width, palette("muted"))
    add_text(stdscr, 4, 0, "-" * max(0, width), width, palette("rule"))


def draw_tree(stdscr: Any, state: TuiState, y: int, height: int, width: int) -> None:
    visible = state.visible()
    if visible:
        selected_index = next((i for i, node in enumerate(visible) if node.get("node_id") == state.selected_id), 0)
        if selected_index < state.scroll:
            state.scroll = selected_index
        if selected_index >= state.scroll + height:
            state.scroll = selected_index - height + 1
        state.scroll = max(0, min(state.scroll, max(0, len(visible) - height)))
    else:
        state.scroll = 0
        add_text(stdscr, y, 0, "No areas are available for this selection.", width, palette("muted"))
        return

    by_parent = children_by_parent(state.nodes)
    for row, node in enumerate(visible[state.scroll : state.scroll + height]):
        has_children = bool(by_parent.get(node.get("node_id"))) or bool(node.get("can_expand"))
        is_open = str(node.get("node_id")) in state.expanded
        marker = "v" if has_children and is_open else ">" if has_children else " "
        selected = "*" if node.get("node_id") == state.selected_id else " "
        indent = "  " * min(int(node.get("depth") or 0), 8)
        name = display_node_name(node)
        line = f"{selected} {marker} {indent}{name}  {display_size(node)}"
        attr = curses.A_BOLD | palette("selected") if selected == "*" else palette("folder") if node.get("kind") == "folder" else 0
        add_text(stdscr, y + row, 0, line, width, attr)


def inspector_lines(state: TuiState, width: int) -> list[tuple[str, int]]:
    node = state.selected()
    if not node:
        return [("SELECTED AREA", curses.A_BOLD), ("Nothing selected.", 0)]
    is_file = node.get("kind") == "file"
    if is_file:
        lines: list[tuple[str, int]] = [
            ("ABOUT THIS AREA", curses.A_BOLD | palette("title")),
            (display_node_name(node), curses.A_BOLD),
            (f"Path: {display_node_path(node)}", curses.A_DIM),
            ("CONTENT PREVIEW", curses.A_BOLD | palette("answer")),
        ]
        for line in state.preview_for(node):
            lines.append((line, 0))
        lines.extend(
            [
                ("", 0),
                ("DETAILS", curses.A_BOLD | palette("title")),
                (f"Space: {display_size(node)}", 0),
                (f"Last changed: {display_date(node.get('modified_at'))}", 0),
                (f"Area: {display_label(node.get('area') or 'unknown scope')}", 0),
                ("Preview is local only and is not sent to Codex.", curses.A_DIM | palette("muted")),
            ]
        )
    else:
        lines = [
            ("ABOUT THIS AREA", curses.A_BOLD | palette("title")),
            (display_node_name(node), curses.A_BOLD | palette("folder")),
            (f"Path: {display_node_path(node)}", curses.A_DIM),
            (f"Space: {display_size(node)}", 0),
            (f"Last changed: {display_date(node.get('modified_at'))}", 0),
            ("Kind: Folder", 0),
            (f"Area: {display_label(node.get('area') or 'unknown scope')}", 0),
            (f"Measurement: {display_label(node.get('measurement_status') or 'unknown')}", 0),
            ("", 0),
            ("WHAT WE KNOW", curses.A_BOLD | palette("title")),
        ]
        explanation = "We checked this folder's name, size, dates, and visible entries. We did not open file contents, so its exact purpose is not confirmed."
        lines.extend([("", 0)])
        for line in wrap_lines(explanation, max(10, width)):
            lines.append((line, curses.A_DIM | palette("muted")))
        lines.extend(
            [
                ("", 0),
                ("NEXT STEP", curses.A_BOLD | palette("title")),
                ("Press A to ask Codex what this area is likely for.", curses.A_DIM | palette("muted")),
            ]
        )
    node_id = str(node.get("node_id"))
    if state.ai_busy and state.ai_busy_node_id == node_id:
        lines.extend([("", 0), (f"CODEX THINKING {state.spinner()}", curses.A_BOLD | palette("answer"))])
        if state.answer:
            lines.append(("Previous answer remains below.", curses.A_DIM | palette("muted")))
            lines.extend((line, 0) for line in wrap_lines(state.answer, max(10, width)))
    elif state.answer:
        lines.extend([("", 0), ("CODEX ANSWER", curses.A_BOLD | palette("answer"))])
        for line in wrap_lines(state.answer, max(10, width)):
            lines.append((line, 0))
    elif state.prompt:
        lines.extend(
            [
                ("", 0),
                ("CODEX QUESTION READY", curses.A_BOLD | palette("title")),
                ("Press C to copy the metadata-only context.", curses.A_DIM | palette("muted")),
            ]
        )
        for line in wrap_lines(state.question, max(10, width)):
            lines.append((line, curses.A_DIM))
    return lines


def draw_inspector(stdscr: Any, state: TuiState, y: int, height: int, x: int, width: int) -> None:
    add_text(stdscr, y, x, "INSPECTOR", width, curses.A_BOLD | palette("title"))
    current_y = y + 1
    for text, attr in inspector_lines(state, width)[: max(0, height - 1)]:
        add_text(stdscr, current_y, x, text, width, attr)
        current_y += 1


def draw_vertical_divider(stdscr: Any, y: int, height: int, x: int) -> None:
    for row in range(max(0, height)):
        add_text(stdscr, y + row, x, "|", 1, palette("rule"))


def draw_help(stdscr: Any, width: int, height: int) -> None:
    box_width = min(max(50, width - 6), 78)
    box_height = min(15, max(8, height - 4))
    left = max(0, (width - box_width) // 2)
    top = max(0, (height - box_height) // 2)
    add_text(stdscr, top, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    for row in range(1, max(1, box_height - 1)):
        add_text(stdscr, top + row, left, "|" + " " * max(0, box_width - 2) + "|", box_width, palette("rule"))
    if box_height > 1:
        add_text(stdscr, top + box_height - 1, left, "+" + "-" * max(0, box_width - 2) + "+", box_width, palette("rule"))
    add_text(stdscr, top + 1, left + 2, "KEYS / HOW TO USE", box_width - 4, curses.A_BOLD | palette("title"))
    help_lines = [
        "Up / Down   move through visible areas",
        "Left        collapse a folder or move to its parent",
        "Right       expand a folder or move to its first child",
        "Enter       open one more level, then close it",
        "gg          jump to the top of the visible tree",
        "G           jump to the bottom of the visible tree",
        "PageUp/Down move by one screen",
        "Home/End    jump to top or bottom",
        "Mouse       click select, double-click folder to open",
        "a           ask Codex about the selected area",
        "c           copy the metadata-only context",
        "r           reload a selected file preview",
        "Esc/Ctrl-C   cancel a question or stop waiting for Codex",
        "q           quit the explorer",
        "",
        "Press any key to close this help.",
    ]
    for index, line in enumerate(help_lines):
        add_text(stdscr, top + 3 + index, left + 2, line, box_width - 4)


def draw_question_box(stdscr: Any, state: TuiState, y: int, x: int, width: int) -> None:
    box_height = 4
    if width < 12:
        return
    if width >= 36:
        heading = "| ASK CODEX  Enter send  Esc cancel"
    elif width >= 26:
        heading = "| ASK CODEX | Enter | Esc"
    else:
        heading = "| ASK CODEX"
    add_text(stdscr, y, x, "+" + "-" * max(0, width - 2) + "+", width, palette("rule"))
    add_text(stdscr, y + 1, x, heading, width, curses.A_BOLD | palette("title"))
    input_width = max(1, width - 4)
    visible = state.question_buffer[-input_width:]
    add_text(stdscr, y + 2, x, "| " + visible, width, palette("selected"))
    add_text(stdscr, y + 3, x, "+" + "-" * max(0, width - 2) + "+", width, palette("rule"))
    try:
        stdscr.move(y + 2, x + 2 + min(len(visible), input_width))
    except curses.error:
        pass


def begin_question(stdscr: Any, state: TuiState) -> None:
    node = state.selected()
    if not node:
        state.message = "Nothing is selected."
        return
    if state.ai_busy:
        state.message = "Codex is already thinking. You can still move through the tree."
        return
    state.question_editing = True
    state.question_buffer = ""
    state.message = "Type a question in the right panel. Enter sends; Esc cancels."
    try:
        curses.curs_set(1)
    except curses.error:
        pass


def submit_question(stdscr: Any, state: TuiState) -> None:
    node = state.selected()
    if not node:
        state.question_editing = False
        return
    state.question = state.question_buffer.strip() or DEFAULT_QUESTION
    state.prompt = build_prompt(node, state.question)
    state.question_editing = False
    state.question_buffer = ""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    state.start_ai(node, state.prompt)


def cancel_question(stdscr: Any, state: TuiState) -> None:
    state.question_editing = False
    state.question_buffer = ""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    state.message = "Question cancelled."


def handle_question_key(stdscr: Any, state: TuiState, key: Any) -> bool:
    if key_matches(key, 27, "\x1b", 3, "\x03"):
        cancel_question(stdscr, state)
    elif key_matches(key, "\n", "\r", 10, 13, curses.KEY_ENTER):
        submit_question(stdscr, state)
    elif key_matches(key, curses.KEY_BACKSPACE, 8, 127, "\b"):
        state.question_buffer = state.question_buffer[:-1]
    elif key_matches(key, 21, "\x15"):
        state.question_buffer = ""
    elif isinstance(key, str) and len(key) == 1 and ord(key) >= 32:
        state.question_buffer += key
    elif isinstance(key, int) and 32 <= key <= 126:
        state.question_buffer += chr(key)
    return True


def handle_mouse(state: TuiState, tree_y: int, tree_height: int, tree_width: int) -> bool:
    try:
        _, x, y, _, button_state = curses.getmouse()
    except curses.error:
        return True
    visible = state.visible()
    if not visible:
        return True
    wheel_up = getattr(curses, "BUTTON4_PRESSED", 0)
    wheel_down = getattr(curses, "BUTTON5_PRESSED", 0)
    if button_state & wheel_up:
        current = next((i for i, node in enumerate(visible) if node.get("node_id") == state.selected_id), 0)
        state.select_index(current - 3)
        return True
    if button_state & wheel_down:
        current = next((i for i, node in enumerate(visible) if node.get("node_id") == state.selected_id), 0)
        state.select_index(current + 3)
        return True
    if x < 0 or x >= tree_width or y < tree_y or y >= tree_y + tree_height:
        return True
    index = state.scroll + y - tree_y
    if index < 0 or index >= len(visible):
        return True
    state.select_index(index)
    double_click = getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0)
    if button_state & double_click:
        selected = state.selected()
        if selected:
            state.open_or_close(selected)
    else:
        state.message = "Selected area. Double-click a folder to open it."
    return True


def handle_key(stdscr: Any, state: TuiState, key: Any, width: int, page_size: int = 10) -> bool:
    if state.question_editing:
        return handle_question_key(stdscr, state, key)
    if state.help_open:
        state.help_open = False
        return True
    if state.ai_busy and key_matches(key, 27, "\x1b", 3, "\x03"):
        state.vim_pending_g = False
        state.cancel_ai()
        return True
    if state.vim_pending_g:
        state.vim_pending_g = False
        if key_matches(key, "g", ord("g")):
            visible = state.visible()
            if visible:
                state.select_index(0)
                state.message = "Moved to the top of the visible tree."
            return True
    visible = state.visible()
    if key_matches(key, "q", "Q", ord("q"), ord("Q")):
        return False
    if key_matches(key, "?", ord("?")):
        state.vim_pending_g = False
        state.help_open = True
        return True
    if not visible:
        return True
    current_index = next((i for i, node in enumerate(visible) if node.get("node_id") == state.selected_id), 0)
    if key_matches(key, curses.KEY_UP, "k", ord("k")):
        state.select_index(current_index - 1)
    elif key_matches(key, curses.KEY_DOWN, "j", ord("j")):
        state.select_index(current_index + 1)
    elif key_matches(key, curses.KEY_LEFT, "h", ord("h")):
        current = visible[current_index]
        node_id = str(current.get("node_id"))
        if current.get("kind") == "folder" and node_id in state.expanded:
            state.expanded.remove(node_id)
            state.message = f"Closed {display_node_name(current)}"
        elif current.get("parent_id"):
            parent_index = next((index for index, item in enumerate(visible) if item.get("node_id") == current.get("parent_id")), current_index)
            state.select_index(parent_index)
            state.message = "Moved to the parent folder."
    elif key_matches(key, curses.KEY_RIGHT, "l", ord("l")):
        current = visible[current_index]
        node_id = str(current.get("node_id"))
        children = state.load_children(current) if current.get("kind") == "folder" else []
        if current.get("kind") == "folder" and children and node_id not in state.expanded:
            state.expanded.add(node_id)
            state.message = f"Opened {display_node_name(current)}"
        elif children:
            child_index = next((index for index, item in enumerate(visible) if item.get("node_id") == children[0].get("node_id")), current_index)
            state.select_index(child_index)
            state.message = "Moved to the first item inside the folder."
    elif key_matches(key, "\n", "\r", " ", 10, 13, curses.KEY_ENTER, ord(" ")):
        current = visible[current_index]
        state.open_or_close(current)
    elif key_matches(key, "G", ord("G")):
        state.select_index(len(visible) - 1)
        state.message = "Moved to the bottom of the visible tree."
    elif key_matches(key, curses.KEY_HOME):
        state.select_index(0)
        state.message = "Moved to the top of the visible tree."
    elif key_matches(key, curses.KEY_END):
        state.select_index(len(visible) - 1)
        state.message = "Moved to the bottom of the visible tree."
    elif key_matches(key, curses.KEY_PPAGE):
        state.select_index(current_index - max(1, page_size - 1))
    elif key_matches(key, curses.KEY_NPAGE):
        state.select_index(current_index + max(1, page_size - 1))
    elif key_matches(key, "g", ord("g")):
        state.vim_pending_g = True
        state.message = "Press g again to move to the top."
    elif key_matches(key, "a", "A", ord("a"), ord("A")):
        begin_question(stdscr, state)
    elif key_matches(key, "c", "C", ord("c"), ord("C")):
        if state.prompt:
            state.message = copy_to_clipboard(state.prompt)
        else:
            state.message = "Ask a question first so there is AI context to copy."
    elif key_matches(key, "r", "R", ord("r"), ord("R")):
        current = visible[current_index]
        if current.get("kind") == "file":
            state.preview_cache.pop(str(current.get("node_id")), None)
            state.message = "File preview reloaded."
    return True


def app(
    stdscr: Any,
    report: dict[str, Any],
    expand_callback: Optional[Callable[[dict[str, Any]], tuple[list[dict[str, Any]], str]]] = None,
) -> None:
    state = TuiState(report, expand_callback)
    stdscr.keypad(True)
    stdscr.timeout(100)
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)
    except curses.error:
        pass
    setup_palette(stdscr)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    while True:
        state.poll_ai()
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        draw_header(stdscr, state, width)
        footer_height = 3
        content_top = 6
        content_height = max(4, height - content_top - footer_height)
        tree_y = content_top
        if width >= 76:
            list_width = max(32, width * 52 // 100)
            tree_height = content_height
            tree_width = list_width - 2
            draw_tree(stdscr, state, tree_y, tree_height, tree_width)
            draw_vertical_divider(stdscr, content_top, content_height, list_width - 1)
            inspector_x = list_width + 1
            inspector_y = content_top
            inspector_width = width - list_width - 2
            draw_inspector(stdscr, state, inspector_y, content_height, inspector_x, inspector_width)
        else:
            list_height = max(4, content_height // 2)
            tree_height = list_height
            tree_width = width - 1
            draw_tree(stdscr, state, tree_y, tree_height, tree_width)
            add_text(stdscr, content_top + list_height, 0, "-" * max(0, width), width, palette("rule"))
            inspector_x = 0
            inspector_y = content_top + list_height + 1
            inspector_width = width - 1
            draw_inspector(stdscr, state, inspector_y, content_height - list_height - 1, inspector_x, inspector_width)
        if state.question_editing:
            draw_question_box(stdscr, state, inspector_y, inspector_x, inspector_width)
            footer = "ENTER send question   ESC/Ctrl-C cancel   Q remains part of the question"
        elif state.ai_busy:
            footer = "ESC/Ctrl-C stop Codex   UP/DOWN keep moving   Q quit"
        else:
            footer = "Press ? for help. Q exits without changing files."
        add_text(stdscr, height - 2, 0, state.message, width, curses.A_DIM | palette("muted"))
        add_text(stdscr, height - 1, 0, footer, width, curses.A_DIM | palette("muted"))
        if state.help_open:
            draw_help(stdscr, width, height)
        stdscr.refresh()
        try:
            key = stdscr.get_wch()
        except curses.error:
            key = None
        if key is not None:
            if key_matches(key, curses.KEY_MOUSE) and not state.question_editing and not state.help_open:
                handle_mouse(state, tree_y, tree_height, tree_width)
            elif not handle_key(stdscr, state, key, width, tree_height):
                return


def setup_palette(stdscr: Any) -> None:
    global PALETTE
    PALETTE = {}
    if not curses.has_colors():
        return
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_GREEN, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_GREEN, -1)
        PALETTE = {
            "title": curses.color_pair(1),
            "folder": curses.color_pair(2),
            "status": curses.color_pair(3),
            "selected": curses.color_pair(4),
            "answer": curses.color_pair(5),
            "muted": 0,
            "rule": curses.color_pair(1),
        }
    except curses.error:
        PALETTE = {}


def run_tui(
    report: dict[str, Any],
    expand_callback: Optional[Callable[[dict[str, Any]], tuple[list[dict[str, Any]], str]]] = None,
) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("The terminal explorer needs an interactive terminal. Use --format json for a non-interactive report.", file=sys.stderr)
        return 2
    try:
        curses.wrapper(app, report, expand_callback)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    print("Run audit_local_files.py --tui so the scanner can prepare the report first.", file=sys.stderr)
    raise SystemExit(2)
