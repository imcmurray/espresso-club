"""Espresso Club — FastAPI/HTMX app.

UI surfaces:
- /            — auto-redirects to /menu (touchscreen)
- /menu        — touchscreen UI; reacts to NFC taps
- /onboard     — register a new user + tap their card
- /topup/{user_id} — generate a Lightning invoice QR for top-up
- /admin       — operator dashboard

Machine-to-machine:
- POST /api/nfc/tap        — NFC daemon posts here on every tap
- GET  /api/state          — current touchscreen state (HTMX polls this)
- POST /api/buy/{drink_id} — touchscreen buttons hit this
- GET  /healthz            — liveness
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from config import get_drinks, get_settings
from db import Database, Drink
from lnbits_client import LNbitsClient
from phoenixd_client import PhoenixdClient, discover_password as discover_phoenixd_password
from relay import make_relay
from routers import admin, api, menu, onboard, topup
from state import AppState

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("espresso")


def _bootstrap_lnbits_admin_key() -> str | None:
    """Discover the LNbits super-user's wallet admin API key by reading the
    mounted lnbits-data volume.

    Why: the espresso app needs an admin key to call the User Manager
    extension's POST /usermanager/api/v1/users (which creates per-staff
    sub-wallets). Forcing operators to log into LNbits, find the key, and
    paste it into env makes "clone the repo and deploy" significantly less
    smooth. Instead, we read /lnbits-data/.super_user (LNbits writes this on
    first boot when LNBITS_ADMIN_UI=true) and look up that user's wallet's
    admin key in LNbits' own SQLite. Read-only — we never mutate LNbits' DB.

    Returns None if the mount or files are missing; caller falls back to the
    LNBITS_ADMIN_KEY env var (which still wins if set explicitly).
    """
    mount_root = Path("/lnbits-data")
    su_path = mount_root / ".super_user"
    db_path = mount_root / "database.sqlite3"
    if not mount_root.is_dir():
        log.warning("LNbits admin-key bootstrap: %s isn't a directory — "
                    "is the lnbits-data:/lnbits-data:ro mount missing from "
                    "this service in compose?", mount_root)
        return None
    if not su_path.exists():
        log.warning("LNbits admin-key bootstrap: %s missing. LNbits writes "
                    "this on first boot when LNBITS_ADMIN_UI=true; if you "
                    "see this on a fresh stack, check that LNbits actually "
                    "started (check 'docker logs espresso-lnbits').", su_path)
        return None
    if not db_path.exists():
        log.warning("LNbits admin-key bootstrap: %s missing. LNbits' SQLite "
                    "DB should be in the same data folder.", db_path)
        return None
    try:
        super_user_id = su_path.read_text().strip()
        if not super_user_id:
            log.warning("LNbits admin-key bootstrap: %s is empty", su_path)
            return None
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT adminkey FROM wallets WHERE "user" = ? LIMIT 1',
                (super_user_id,),
            ).fetchone()
            if row and row["adminkey"]:
                return row["adminkey"]
            log.warning("LNbits admin-key bootstrap: super-user %s has no "
                        "wallet row in %s yet. This usually self-resolves "
                        "after the first request to LNbits forces wallet "
                        "creation; restart this container to retry.",
                        super_user_id, db_path)
            return None
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.warning("LNbits admin-key bootstrap query failed: %s", e)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    drinks_cfg = get_drinks()
    db = Database(settings.database_path)

    # If the operator didn't set LNBITS_ADMIN_KEY explicitly, try to discover
    # it from the mounted lnbits-data volume so onboarding works out of the
    # box on a fresh deploy.
    admin_key = settings.lnbits_admin_key
    if not admin_key:
        discovered = _bootstrap_lnbits_admin_key()
        if discovered:
            admin_key = discovered
            log.info("bootstrapped LNbits admin key from /lnbits-data "
                     "(super-user wallet); set LNBITS_ADMIN_KEY env to override")
        else:
            log.warning("LNBITS_ADMIN_KEY is empty and bootstrap failed (see "
                        "warnings above) — onboarding will fail with 401. "
                        "Either: (a) mount lnbits-data:/lnbits-data:ro on "
                        "this service in compose, or (b) set LNBITS_ADMIN_KEY "
                        "env (run scripts/lnbits-admin-url.sh on the host to "
                        "fetch the value).")

    # Optional admin username/password for admin-only LNbits endpoints (e.g.
    # PUT /users/api/v1/user/{id} to set usernames on auto-created accounts
    # so they show up named in the LNbits user list). Written by lnbits-init
    # to /lnbits-data/admin.json on first boot.
    admin_username, admin_password = None, None
    creds_path = Path("/lnbits-data/admin.json")
    if creds_path.exists():
        try:
            creds = json.loads(creds_path.read_text())
            admin_username = creds.get("username")
            admin_password = creds.get("password")
            if admin_username:
                log.info("loaded LNbits admin credentials from %s", creds_path)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("couldn't read %s: %s", creds_path, e)

    ln = LNbitsClient(
        settings.lnbits_url, admin_key,
        admin_username=admin_username,
        admin_password=admin_password,
    )
    relay = make_relay(settings.relay_driver, settings.shelly_host)

    # Optional Phoenixd client for the /admin/node status page. Password is
    # auto-discovered from the same volume mount we use for LNbits's
    # phoenix.conf reading. If phoenixd-data isn't mounted (FakeWallet
    # deployment) the client is created with no password and the status
    # page will say "Phoenixd not configured."
    phoenixd_password = discover_phoenixd_password()
    phoenixd = PhoenixdClient(settings.phoenixd_url, phoenixd_password)
    if phoenixd_password:
        log.info("Phoenixd client configured (url=%s)", settings.phoenixd_url)
    else:
        log.info("Phoenixd password not found at /phoenixd-data/phoenix.conf — "
                 "/admin/node will show as unconfigured")

    # First-boot seed: if the drinks table is empty, populate it from the
    # YAML. After that, the YAML is ignored — the admin UI is the source of
    # truth. To re-seed (e.g. blow away your edits), delete the drinks table.
    if db.count_drinks() == 0:
        db.seed_drinks([
            Drink(id=d.id, name=d.name, emoji=d.emoji,
                  price_usd=d.price_usd, description=d.description,
                  sort_order=i, active=True)
            for i, d in enumerate(drinks_cfg.drinks)
        ])
        log.info("seeded %d drinks from %s", len(drinks_cfg.drinks),
                 settings.drinks_config)

    state = AppState(settings=settings, drinks=drinks_cfg, db=db, ln=ln,
                      relay=relay, phoenixd=phoenixd)
    app.state.app_state = state

    log.info("Espresso app starting — relay=%s lnbits=%s",
             settings.relay_driver, settings.lnbits_url)
    try:
        yield
    finally:
        await ln.aclose()
        await phoenixd.aclose()


app = FastAPI(title="Espresso Club", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")),
          name="static")
app.include_router(menu.router)
app.include_router(onboard.router)
app.include_router(topup.router)
app.include_router(admin.router)
app.include_router(api.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/menu")


@app.get("/healthz")
async def healthz():
    return {"ok": True}
