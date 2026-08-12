"""Public command-line entry point for the Clean Your Data explorer."""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from . import __version__
from .audit_local_files import main as audit_main


def normalize_argv(argv: Sequence[str]) -> list[str]:
    """Make the short ``cyd PATH`` form explicit for the scanner."""

    args = list(argv)
    if not args:
        return ["--tui", "--path", "."]
    if args[0] == "--":
        args = args[1:]
    if args and not args[0].startswith("-"):
        return ["--tui", "--path", args[0], *args[1:]]
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the explorer or the opt-in local command tracer."""

    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--version"], ["-V"]):
        print(f"clean-your-data {__version__}")
        return 0
    if args and args[0] == "trace":
        from .trace import main as trace_main

        return trace_main(args[1:])
    if args and args[0] == "gui":
        from .gui import main as gui_main

        return gui_main(args[1:])
    if len(args) >= 2 and args[:2] == ["config", "ai"]:
        from .ai_config import config_main

        return config_main(args[2:])
    if args and args[0] == "config":
        print("usage: cyd config ai [--show|--auto|--codex|--command COMMAND|--off]", file=sys.stderr)
        return 2
    return audit_main(normalize_argv(args))
