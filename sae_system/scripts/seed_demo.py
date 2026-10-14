#!/usr/bin/env python3
"""Seed a demo student account  -  Phase 10A Step 9.

Creates ONE clearly-marked demo account via the app's real registration
API (auth.register  -  same path the login page uses, no parallel schema),
so a fresh install has something to log into immediately without waiting
on a full Ollama-generated roadmap (that already happens, with its own
progress UI, the first time any student picks a domain in the dashboard  - 
duplicating it here would just be a second, slower, non-interactive copy
of a flow the app already handles well).

Deterministic and safe to re-run: if the demo account already exists,
this exits cleanly without modifying anything (auth.register itself
rejects duplicate emails/usernames)  -  it will never overwrite a real
student's account, demo or otherwise.

Usage:
    python scripts/seed_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEMO_NAME = "Demo Student"
DEMO_USERNAME = "demo_student"
DEMO_EMAIL = "demo@sae.local"
DEMO_PASSWORD = "SaeDemo123!"


def main() -> int:
    from auth.auth import register

    print("Seeding demo account (safe to re-run  -  no-ops if it already exists)...")
    ok, message = register(DEMO_NAME, DEMO_USERNAME, DEMO_EMAIL, DEMO_PASSWORD, DEMO_PASSWORD)

    if ok:
        print("Created demo account:")
    elif "already" in message.lower() or "exists" in message.lower() or "taken" in message.lower():
        print("Demo account already exists  -  leaving it as-is. Credentials:")
        ok = True  # not a failure  -  the desired end state already holds
    else:
        print(f"Could not create demo account: {message}")
        return 1

    print(f"  Username: {DEMO_USERNAME}")
    print(f"  Email:    {DEMO_EMAIL}")
    print(f"  Password: {DEMO_PASSWORD}")
    print()
    print("Log in with these credentials, then pick any domain from the")
    print("dashboard to generate a real roadmap (requires Ollama running  - ")
    print("run scripts/check_environment.py first if unsure).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
