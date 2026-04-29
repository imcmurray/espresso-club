"""Operator dashboard."""

from __future__ import annotations

import re
import time

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from config import sats_to_usd
from db import Drink

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("_", name.lower()).strip("_") or "drink"


# -- drinks CRUD ------------------------------------------------------------

@router.get("/admin/drinks", response_class=HTMLResponse)
async def drinks_list(request: Request):
    state = request.app.state.app_state
    drinks = state.db.list_drinks(active_only=False)
    return templates.TemplateResponse(
        request, "admin_drinks.html", {"drinks": drinks},
    )


@router.post("/admin/drinks", response_class=HTMLResponse)
async def drinks_create(
    request: Request,
    name: str = Form(...),
    emoji: str = Form(""),
    price_usd: float = Form(...),
    description: str = Form(""),
    sort_order: int = Form(100),
    drink_id: str = Form(""),
):
    state = request.app.state.app_state
    new_id = drink_id.strip() or _slugify(name)
    if state.db.get_drink(new_id):
        raise HTTPException(409, f"drink id '{new_id}' already exists")
    drink = state.db.create_drink(Drink(
        id=new_id, name=name.strip(), emoji=emoji.strip(),
        price_usd=float(price_usd), description=description.strip(),
        sort_order=int(sort_order), active=True,
    ))
    return templates.TemplateResponse(
        request, "_drink_row.html",
        {"d": drink, "swap_oob": "afterbegin:#drinks-tbody"},
    )


@router.get("/admin/drinks/{drink_id}/edit", response_class=HTMLResponse)
async def drinks_edit_form(request: Request, drink_id: str):
    state = request.app.state.app_state
    d = state.db.get_drink(drink_id)
    if not d:
        raise HTTPException(404, "no such drink")
    return templates.TemplateResponse(
        request, "_drink_edit_row.html", {"d": d},
    )


@router.get("/admin/drinks/{drink_id}", response_class=HTMLResponse)
async def drinks_row(request: Request, drink_id: str):
    state = request.app.state.app_state
    d = state.db.get_drink(drink_id)
    if not d:
        raise HTTPException(404, "no such drink")
    return templates.TemplateResponse(
        request, "_drink_row.html", {"d": d, "swap_oob": None},
    )


@router.post("/admin/drinks/{drink_id}", response_class=HTMLResponse)
async def drinks_update(
    request: Request,
    drink_id: str,
    name: str = Form(...),
    emoji: str = Form(""),
    price_usd: float = Form(...),
    description: str = Form(""),
    sort_order: int = Form(...),
    active: str = Form("on"),
):
    state = request.app.state.app_state
    if not state.db.get_drink(drink_id):
        raise HTTPException(404, "no such drink")
    d = state.db.update_drink(
        drink_id,
        name=name.strip(), emoji=emoji.strip(),
        price_usd=float(price_usd), description=description.strip(),
        sort_order=int(sort_order),
        active=(active.lower() in ("on", "true", "1", "yes")),
    )
    return templates.TemplateResponse(
        request, "_drink_row.html", {"d": d, "swap_oob": None},
    )


@router.post("/admin/drinks/{drink_id}/delete")
async def drinks_delete(request: Request, drink_id: str):
    state = request.app.state.app_state
    if not state.db.get_drink(drink_id):
        raise HTTPException(404, "no such drink")
    state.db.soft_delete_drink(drink_id)
    # Return the row in its now-inactive form so HTMX can replace inline.
    d = state.db.get_drink(drink_id)
    return templates.TemplateResponse(
        request, "_drink_row.html", {"d": d, "swap_oob": None},
    )


# -- main dashboard ---------------------------------------------------------

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    state = request.app.state.app_state
    users = state.db.list_users()

    # Hydrate balances from LNbits in parallel (sequentially here for
    # simplicity; for >50 users use asyncio.gather).
    user_rows = []
    for u in users:
        try:
            bal = await state.ln.wallet_balance_sats(invoice_key=u.lnbits_invoice_key)
        except Exception:
            bal = -1
        user_rows.append({
            "id": u.id, "name": u.name, "nfc_uid": u.nfc_uid,
            "balance_sats": bal, "balance_usd": sats_to_usd(bal) if bal >= 0 else None,
        })

    recent = state.db.recent_global(limit=30)
    month_ago = int(time.time()) - 30 * 86400
    leaderboard = state.db.leaderboard(since_ts=month_ago)

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "users": user_rows,
            "recent": recent,
            "leaderboard": leaderboard,
            "sats_to_usd": sats_to_usd,
        },
    )
