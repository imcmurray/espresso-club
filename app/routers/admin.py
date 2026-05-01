"""Operator dashboard."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from config import sats_to_usd
from db import Drink

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("_", name.lower()).strip("_") or "drink"


def fmt_ts(ts: int) -> str:
    """Friendly timestamp for ledger displays.

    < 1 minute  → "just now"
    < 1 hour    → "12 min ago"
    < 24 hours  → "3 hr ago"
    < 7 days    → "2 days ago"
    older       → absolute UTC date+time
    """
    if not ts:
        return "—"
    delta = time.time() - int(ts)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)} min ago"
    if delta < 86400:
        return f"{int(delta / 3600)} hr ago"
    if delta < 7 * 86400:
        return f"{int(delta / 86400)} days ago"
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


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
    # Unchecked HTML checkboxes don't submit at all, so the absence of a
    # value means active=False. (If we used Form("on") as default, an
    # unchecked checkbox would silently leave the drink active.)
    active: str | None = Form(None),
):
    state = request.app.state.app_state
    if not state.db.get_drink(drink_id):
        raise HTTPException(404, "no such drink")
    d = state.db.update_drink(
        drink_id,
        name=name.strip(), emoji=emoji.strip(),
        price_usd=float(price_usd), description=description.strip(),
        sort_order=int(sort_order),
        active=(active is not None
                and active.lower() in ("on", "true", "1", "yes")),
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


# -- assign / re-assign NFC card to a user ---------------------------------

@router.post("/admin/users/{user_id}/assign-nfc")
async def admin_assign_nfc(
    user_id: int,
    request: Request,
    nfc_uid: str = Form(...),
):
    """Operator manually sets (or replaces) a user's NFC card UID.

    Useful when:
    - A user was created via /onboard but never tapped a card within the
      30-second registration window.
    - A staff member's existing card is lost / damaged and gets replaced.
    """
    state = request.app.state.app_state
    user = state.db.get_user(user_id)
    if not user:
        raise HTTPException(404, "no such user")

    nfc_uid = nfc_uid.strip()
    if not nfc_uid:
        raise HTTPException(400, "nfc_uid required")

    existing = state.db.get_user_by_nfc(nfc_uid)
    if existing and existing.id != user_id:
        raise HTTPException(
            409, f"card '{nfc_uid}' is already assigned to {existing.name}"
        )

    state.db.assign_nfc(user_id, nfc_uid)

    # Mirror the change into LNbits's external_id so the LNbits user list
    # stays a useful cross-reference. Best-effort.
    if user.lnbits_user_id:
        await state.ln.update_user_metadata(
            user.lnbits_user_id, external_id=nfc_uid,
        )

    return RedirectResponse(url="/admin", status_code=303)


# -- Phoenixd / Lightning node status --------------------------------------

@router.get("/admin/node", response_class=HTMLResponse)
async def admin_node(request: Request):
    """Lightning node status: phoenixd connectivity, channel balances,
    recent payments. Phoenixd doesn't implement LNbits's "Node API"
    (which assumes LND/CLN-shaped channel detail), so this page calls
    Phoenixd's own HTTP API directly."""
    state = request.app.state.app_state
    snap = await state.phoenixd.snapshot() if state.phoenixd else None

    # Total sats currently parked in user sub-wallets (sum across LNbits
    # users). For an espresso club, this is "money the staff have credit for"
    # vs. the operator wallet's "money you can sweep out."
    user_sats_total = 0
    for u in state.db.list_users():
        try:
            user_sats_total += await state.ln.wallet_balance_sats(
                invoice_key=u.lnbits_invoice_key)
        except Exception:
            pass

    return templates.TemplateResponse(
        request, "admin_node.html",
        {"snap": snap, "user_sats_total": user_sats_total,
         "sats_to_usd": sats_to_usd},
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
            "fmt_ts": fmt_ts,
        },
    )
