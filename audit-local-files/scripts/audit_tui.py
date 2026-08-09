#!/usr/bin/env python3
"""Compatibility wrapper for the packaged terminal explorer."""

from __future__ import annotations

import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from clean_your_data.audit_tui import *  # noqa: F401,F403,E402


if __name__ == "__main__":
    print("Run audit_local_files.py --tui so the scanner can prepare the report first.", file=sys.stderr)
    raise SystemExit(2)
