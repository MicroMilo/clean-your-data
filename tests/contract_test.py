#!/usr/bin/env python3
"""Deterministic contract checks for incomplete measurements."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit-local-files" / "scripts" / "audit_local_files.py"


def load_scanner():
    spec = importlib.util.spec_from_file_location("audit_local_files_contract", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scanner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    scanner = load_scanner()
    implementation = sys.modules[scanner.scan_targets.__module__]
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "Desktop").mkdir()
        original_du_size = scanner.du_size

        def timed_out(_path: Path, _timeout: int):
            return None, "simulated timeout", True

        implementation.du_size = timed_out
        try:
            records = scanner.scan_targets(home, 1, None, True)
        finally:
            implementation.du_size = original_du_size

        desktop = next(row for row in records if row["label"] == "Desktop")
        assert desktop["allocated_bytes"] is None
        assert desktop["measurement_status"] == "timeout"
        coverage = scanner.target_coverage(records)
        desktop_coverage = next(row for row in coverage if row["label"] == "Desktop")
        assert desktop_coverage["status"] == "timeout"
        findings = scanner.build_findings(records, {"buckets": [], "status_collected": True}, [])
        assert findings[0]["status"] == "timeout"
        gate = scanner.action_gate(records, {"buckets": [], "status_collected": True}, [])
        assert gate["status"] == "review_only"
        assert gate["exact_cleanup_allowed"] is False
    print("contract test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
