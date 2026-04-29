#!/usr/bin/env python3
"""Insert a few demo users into the espresso DB for quick UI demos.

Talks to a running espresso-app over HTTP. Useful before you have NFC cards
in hand.

Usage:
    python3 scripts/seed_demo_users.py
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx


DEMO_USERS = [
    ("Sarah", "DEMO-CARD-SARAH"),
    ("Marcus", "DEMO-CARD-MARCUS"),
    ("Priya", "DEMO-CARD-PRIYA"),
    ("Diego", "DEMO-CARD-DIEGO"),
]


def seed(app: str, nfc: str) -> None:
    with httpx.Client(timeout=10.0) as c:
        for name, uid in DEMO_USERS:
            print(f"creating {name}…", flush=True)
            r = c.post(f"{app}/onboard", data={"name": name},
                       follow_redirects=False)
            r.raise_for_status()
            time.sleep(0.5)
            r = c.post(f"{nfc}/tap", json={"uid": uid})
            r.raise_for_status()
            print(f"  → registered card {uid}")
        print("\nDone. Try a tap:")
        print(f"  curl -X POST {nfc}/tap -d '{{\"uid\":\"DEMO-CARD-SARAH\"}}' "
              "-H 'Content-Type: application/json'")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:8080")
    ap.add_argument("--nfc", default="http://localhost:9999")
    args = ap.parse_args()
    seed(args.app, args.nfc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
