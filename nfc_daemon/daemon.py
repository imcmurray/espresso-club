"""NFC daemon.

Watches a PN532 reader (or simulator) and POSTs tap events to the espresso app.

Modes:
- TAP_SIMULATOR=true  — opens a tiny HTTP listener on :9999 that accepts
                        POST /tap {uid: "..."} so you can fake taps from curl
                        or a browser. No hardware required.
- TAP_SIMULATOR=false — real PN532 via nfcpy. USB by default; for I²C on Pi
                        set NFC_DEVICE=i2c:/dev/i2c-1.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Callable

import httpx

log = logging.getLogger("nfc-daemon")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s: %(message)s")

ESPRESSO_APP_URL = os.environ.get("ESPRESSO_APP_URL", "http://espresso-app:8080")
SIMULATOR = os.environ.get("TAP_SIMULATOR", "true").lower() == "true"
NFC_DEVICE = os.environ.get("NFC_DEVICE", "usb")  # or "i2c:/dev/i2c-1"
DEBOUNCE_SECONDS = float(os.environ.get("NFC_DEBOUNCE_SECONDS", "2.0"))


async def post_tap(uid: str) -> None:
    """Forward a tap to the espresso app."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.post(f"{ESPRESSO_APP_URL}/api/nfc/tap",
                                  json={"uid": uid})
            log.info("tap %s -> %d %s", uid, r.status_code, r.text[:120])
        except httpx.HTTPError as e:
            log.warning("failed to post tap: %s", e)


# ---------------------------------------------------------------------------
# Simulator mode — tiny HTTP server. Useful in dev and CI.
# ---------------------------------------------------------------------------

async def run_simulator() -> None:
    from aiohttp import web
    log.info("starting simulator: POST http://0.0.0.0:9999/tap {\"uid\":\"...\"}")

    async def handle_tap(request: web.Request) -> web.Response:
        body = await request.json()
        uid = body.get("uid", "").strip()
        if not uid:
            return web.json_response({"error": "uid required"}, status=400)
        await post_tap(uid)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/tap", handle_tap)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 9999)
    await site.start()
    while True:
        await asyncio.sleep(3600)


# ---------------------------------------------------------------------------
# Real PN532 mode.
# ---------------------------------------------------------------------------

def run_real() -> None:
    import nfc  # type: ignore

    last_uid: str | None = None
    last_uid_at: float = 0.0

    def _on_connect(tag) -> bool:
        nonlocal last_uid, last_uid_at
        uid = tag.identifier.hex().upper()
        now = time.time()
        if uid == last_uid and (now - last_uid_at) < DEBOUNCE_SECONDS:
            return False  # debounce duplicate read
        last_uid, last_uid_at = uid, now
        log.info("card detected: %s", uid)
        try:
            asyncio.run(post_tap(uid))
        except Exception as e:
            log.exception("post_tap failed: %s", e)
        return False  # release tag immediately

    log.info("opening NFC device: %s", NFC_DEVICE)
    with nfc.ContactlessFrontend(NFC_DEVICE) as clf:
        log.info("PN532 ready — listening for taps")
        while True:
            clf.connect(rdwr={"on-connect": _on_connect})


def main() -> None:
    if SIMULATOR:
        asyncio.run(run_simulator())
    else:
        run_real()


if __name__ == "__main__":
    main()
