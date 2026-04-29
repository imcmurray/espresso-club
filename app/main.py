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

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from config import get_drinks, get_settings
from db import Database, Drink
from lnbits_client import LNbitsClient
from relay import make_relay
from routers import admin, api, menu, onboard, topup
from state import AppState

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("espresso")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    drinks_cfg = get_drinks()
    db = Database(settings.database_path)
    ln = LNbitsClient(settings.lnbits_url, settings.lnbits_admin_key)
    relay = make_relay(settings.relay_driver, settings.shelly_host)

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

    state = AppState(settings=settings, drinks=drinks_cfg, db=db, ln=ln, relay=relay)
    app.state.app_state = state

    log.info("Espresso app starting — relay=%s lnbits=%s",
             settings.relay_driver, settings.lnbits_url)
    try:
        yield
    finally:
        await ln.aclose()


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
