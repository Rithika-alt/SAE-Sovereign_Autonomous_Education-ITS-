#!/usr/bin/env python3
"""Cross-platform native launcher  -  Phase 10A Step 12.

Complements bootstrap.ps1/bootstrap.sh (the existing Docker-oriented
launchers at the repo root) with a native-mode equivalent: run the
preflight checker, then start the dashboard directly with the host
Python  -  no Docker required, matching README.md's documented "Quick
Start (local, no Docker)" path. One cross-platform script instead of a
separate start.bat/start.sh (Phase 10A Step 12's stated preference).

Usage:
    python scripts/start.py            # check, then start
    python scripts/start.py --no-check # skip the preflight check
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    skip_check = "--no-check" in sys.argv

    if not skip_check:
        print("Running environment check (skip with --no-check)...\n")
        result = subprocess.run([sys.executable, str(_ROOT / "scripts" / "check_environment.py")])
        if result.returncode != 0:
            print("\nEnvironment check found a required component missing  -  fix the")
            print("issue(s) above, or re-run with --no-check to start anyway.")
            return result.returncode
        print()

    print("Starting SAE dashboard at http://localhost:8501 ...")
    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", str(_ROOT / "dashboard" / "app.py")],
        cwd=str(_ROOT),
    )


if __name__ == "__main__":
    sys.exit(main())
