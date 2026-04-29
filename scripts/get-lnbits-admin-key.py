#!/usr/bin/env python3
"""Print LNbits' super-user admin API key for the running stack.

Designed to run *inside* a container that has access to LNbits' data folder.
Two ways to invoke:

  # Pipe from your repo checkout (no copy-paste, no temp file):
  docker exec -i espresso-lnbits python3 < scripts/get-lnbits-admin-key.py

  # Or fetch straight from GitHub:
  curl -fsSL https://raw.githubusercontent.com/imcmurray/espresso-club/main/scripts/get-lnbits-admin-key.py \\
    | docker exec -i espresso-lnbits python3

  # Or mount the file into the container and run it:
  docker exec -it espresso-lnbits python3 /path/to/get-lnbits-admin-key.py

Auto-detects whether it's running in espresso-lnbits (data at /data) or in
espresso-app (data at /lnbits-data, when the read-only mount is configured).

Output goes to stdout in a copy-paste-friendly form: the admin URL, the admin
API key, and the exact env-var line you'd paste into Dockge to skip the
auto-bootstrap.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


def _find_data_folder() -> Path:
    """Locate LNbits' data folder. Prefer a few well-known paths in order."""
    candidates = [
        Path(os.environ.get("LNBITS_DATA_FOLDER", "/data")),
        Path("/data"),
        Path("/lnbits-data"),
    ]
    for p in candidates:
        if (p / ".super_user").exists() and (p / "database.sqlite3").exists():
            return p
    sys.exit(
        "error: couldn't find LNbits data folder. Tried:\n  "
        + "\n  ".join(str(p) for p in candidates)
        + "\n\nAre you running this inside the espresso-lnbits container?\n"
        "  docker exec -i espresso-lnbits python3 < scripts/get-lnbits-admin-key.py"
    )


def _find_data_folder_or_exit() -> Path:
    """Locate LNbits' data folder by looking for the SQLite DB.
    The .super_user file may or may not exist; we don't require it.
    """
    candidates = [
        Path(os.environ.get("LNBITS_DATA_FOLDER", "/data")),
        Path("/data"),
        Path("/lnbits-data"),
    ]
    for p in candidates:
        if (p / "database.sqlite3").exists():
            return p
    sys.exit(
        "error: couldn't find LNbits' database.sqlite3. Tried:\n  "
        + "\n  ".join(str(p) for p in candidates)
        + "\n\nAre you running this inside the espresso-lnbits container?\n"
        "  docker exec -i espresso-lnbits python3 < scripts/get-lnbits-admin-key.py"
    )


def main() -> int:
    data = _find_data_folder_or_exit()
    db_path = data / "database.sqlite3"
    su_file = data / ".super_user"

    host = os.environ.get("HOST", "<your-host>")
    port = os.environ.get("LNBITS_PORT", "5000")

    # Path 1: super-user file exists. Print its info — this is the easy case.
    if su_file.exists():
        super_user = su_file.read_text().strip()
        if super_user:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    'SELECT adminkey FROM wallets WHERE "user" = ? LIMIT 1',
                    (super_user,),
                ).fetchone()
            finally:
                conn.close()
            if row and row[0]:
                _print_super_user_block(host, port, super_user, row[0])
                return 0

    # Path 2: no super-user file (LNbits 0.10.x doesn't write it until /admin
    # is visited). Fall back to listing every wallet so the operator can pick
    # one to promote to admin.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            'SELECT "user", name, adminkey FROM wallets ORDER BY "user", name'
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        sys.exit(
            "error: no wallets exist in LNbits yet.\n"
            "Visit http://<your-host>:5000/wallet, create any wallet through\n"
            "the UI (it just needs a name), then re-run this script."
        )

    _print_no_super_user_block(host, port, rows)
    return 0


def _print_super_user_block(host: str, port: str, su: str, key: str) -> None:
    print("LNbits super-user URL:")
    print(f"  http://{host}:{port}/wallet?usr={su}")
    print()
    print("LNbits admin API key (super-user's wallet):")
    print(f"  {key}")
    print()
    print("To bypass the espresso-app's auto-bootstrap, paste into Dockge's")
    print("Env tab for the espresso-app service:")
    print()
    print(f"  LNBITS_ADMIN_KEY={key}")


def _print_no_super_user_block(host: str, port: str, rows: list) -> None:
    print(".super_user file not present — LNbits 0.10.x only creates it when")
    print("someone visits /admin in a browser. Two ways to get unblocked:")
    print()
    print("OPTION 1 — let LNbits create the super-user properly:")
    print(f"  Open http://{host}:{port}/admin once. That writes .super_user.")
    print("  Then re-run this script for the easy path.")
    print()
    print("OPTION 2 — promote one of your existing wallet users to admin.")
    print("Pick a row below, then in Dockge set TWO env vars and redeploy:")
    print(f"  LNBITS_ADMIN_USERS=<user_id>          (on the lnbits service)")
    print(f"  LNBITS_ADMIN_KEY=<adminkey>           (on the espresso-app service)")
    print()
    print(f"  {'user_id':<34}  {'wallet_name':<24}  adminkey")
    print(f"  {'-' * 34}  {'-' * 24}  {'-' * 34}")
    for u, n, k in rows:
        print(f"  {u:<34}  {(n or '')[:24]:<24}  {k}")


if __name__ == "__main__":
    sys.exit(main())
