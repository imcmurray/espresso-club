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


def main() -> int:
    data = _find_data_folder()
    super_user = (data / ".super_user").read_text().strip()
    if not super_user:
        sys.exit(f"error: {data}/.super_user is empty")

    conn = sqlite3.connect(f"file:{data / 'database.sqlite3'}?mode=ro", uri=True)
    try:
        row = conn.execute(
            'SELECT adminkey FROM wallets WHERE "user" = ? LIMIT 1',
            (super_user,),
        ).fetchone()
    finally:
        conn.close()

    if not row or not row[0]:
        sys.exit(f"error: no wallet row found for super-user {super_user}")
    adminkey = row[0]

    host = os.environ.get("HOST", "<your-host>")
    port = os.environ.get("LNBITS_PORT", "5000")

    print(f"LNbits super-user URL:")
    print(f"  http://{host}:{port}/wallet?usr={super_user}")
    print()
    print(f"LNbits admin API key:")
    print(f"  {adminkey}")
    print()
    print("To bypass the auto-bootstrap, paste this into Dockge's Env tab")
    print("for the espresso-app service, then redeploy:")
    print()
    print(f"  LNBITS_ADMIN_KEY={adminkey}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
