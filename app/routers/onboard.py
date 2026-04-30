"""New-user onboarding.

Two paths:
1. Web form (/onboard) — fill in name, then tap card on the reader. The next
   tap is captured as their NFC UID.
2. Slack: handled by the Slack bot, which calls into this same logic.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/onboard", response_class=HTMLResponse)
async def onboard_form(request: Request, card: str | None = None):
    """Optional ?card=<uid> query param pre-fills the form with that NFC
    UID, so when an unknown card is tapped the user can click "Join with
    this card" on /menu and land here ready to type their name. Submit
    registers the card directly — no separate tap-to-register step needed.
    """
    return templates.TemplateResponse(
        request, "onboard.html",
        {"prefilled_card_uid": (card or "").strip()},
    )


@router.post("/onboard")
async def onboard_submit(request: Request,
                          name: str = Form(...),
                          nfc_uid: str = Form("")):
    state = request.app.state.app_state
    name = name.strip()
    if not name:
        raise HTTPException(400, "Name is required")

    nfc_uid = nfc_uid.strip() or None

    # If a card UID came in via the form, refuse to overwrite an existing
    # user's claim on it. Better than silently re-routing some else's card.
    if nfc_uid:
        existing = state.db.get_user_by_nfc(nfc_uid)
        if existing:
            raise HTTPException(
                409,
                f"Card '{nfc_uid}' is already assigned to {existing.name}. "
                "Ask the operator to re-assign it via /admin if it's actually yours."
            )

    wallet = await state.ln.create_user_and_wallet(user_name=name)
    user = state.db.create_user(
        name=name,
        lnbits_wallet_id=wallet.id,
        lnbits_admin_key=wallet.admin_key,
        lnbits_invoice_key=wallet.invoice_key,
        nfc_uid=nfc_uid,
    )

    if nfc_uid:
        # Card already linked; no tap-to-register window needed.
        state.last_message = f"Welcome, {name}! Top up below, then tap your card to drink."
    else:
        # Legacy flow: ask the user to tap within 30s. Used when /onboard is
        # visited directly without a card UID.
        state.last_message = (
            f"Welcome, {name}! Tap your card on the reader within 30 seconds to register it."
        )
        request.app.state.pending_nfc_user_id = user.id
        request.app.state.pending_nfc_expires = _now() + 30

    return RedirectResponse(url=f"/topup/{user.id}", status_code=303)


def _now() -> float:
    import time as _t
    return _t.time()
