#!/usr/bin/env python3
"""Compatibility wrapper for the packaged scanner."""

from __future__ import annotations

import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from clean_your_data.audit_local_files import *  # noqa: F401,F403,E402
from clean_your_data.audit_local_files import main as _main


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
