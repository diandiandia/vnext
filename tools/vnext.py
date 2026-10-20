#!/usr/bin/env python3
"""Run the checkout's canonical CLI without a working-directory or PYTHONPATH dependency."""

from pathlib import Path
import sys


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from reachable_audit.cli import main

    raise SystemExit(main())
