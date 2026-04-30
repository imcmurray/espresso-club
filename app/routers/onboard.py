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
    """Show the onboarding page.

    Three sources for the NFC card UID, in priority order:
      1. ?card=<uid> query param (the "Join with this card" link from /menu)
      2. A recently-tapped unknown card stored in app state
      3. None — show a "tap a card to continue" gate that polls until one
         arrives, then unlocks the form.

    Account creation is gated on (1) or (2) — we never create an account
    without a real card UID. The polling gate handles (3).
    """
    state = request.app.state.app_state
    card_uid = (card or "").strip() or state.recent_unknown_tap()
    return templates.TemplateResponse(
        request, "onboard.html",
        {"prefilled_card_uid": card_uid},
    )


@router.get("/onboard/poll", response_class=HTMLResponse)
async def onboard_poll(request: Request):
    """HTMX poll target — returns the form fragment as soon as the user
    taps a card on the reader. Returns an empty body with HX-Reswap: none
    while we're still waiting, so the gate stays in place."""
    state = request.app.state.app_state
    card_uid = state.recent_unknown_tap()
    if not card_uid:
        return HTMLResponse("", headers={"HX-Reswap": "none"})
    return templates.TemplateResponse(
        request, "_onboard_form.html",
        {"prefilled_card_uid": card_uid},
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

    # The gate ensures the form only submits with a card UID, but a
    # determined user could remove the hidden input from DevTools.
    # Refuse server-side too — accounts without a card are useless on
    # the touchscreen.
    if not nfc_uid:
        raise HTTPException(
            400, "A card UID is required. Tap a new NFC card on the reader, "
                 "then submit the form again."
        )

    # If a card UID came in via the form, refuse to overwrite an existing
    # user's claim on it. Better than silently re-routing someone else's card.
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

    # The card is consumed by this onboard — clear the unknown-tap state so
    # the next visitor to /onboard doesn't see this user's UID.
    await state.consume_unknown_tap()

    state.last_message = f"Welcome, {name}! Top up below, then tap your card to drink."

    return RedirectResponse(url=f"/topup/{user.id}", status_code=303)
