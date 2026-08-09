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
    """Run the explorer, defaulting to the current directory in the TUI."""

    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--version"], ["-V"]):
        print(f"clean-your-data {__version__}")
        return 0
    return audit_main(normalize_argv(args))
