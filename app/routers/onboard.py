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

    The form is gated on a *fresh* unknown tap stored in app state
    (UNKNOWN_TAP_WINDOW_SECONDS, currently 30s). The ?card=<uid> query
    param from the "Join with this card" menu link is intentionally
    NOT a fallback — if the link is stale (user came back to it hours
    later), recent_unknown_tap() returns None and the page shows the
    "tap a card to continue" gate instead. Forces a fresh tap rather
    than letting them link a card they once held to a brand-new
    account.
    """
    state = request.app.state.app_state
    card_uid = state.recent_unknown_tap()
    return templates.TemplateResponse(
        request, "onboard.html",
        {"prefilled_card_uid": card_uid},
    )


@router.get("/onboard/poll/form", response_class=HTMLResponse)
async def onboard_poll_from_form(request: Request):
    """Polled by the form view. Returns:
      - HX-Reswap: none while the card is still fresh (no DOM mutation,
        input value the user is typing stays put).
      - The waiting fragment once the freshness window expires, swapping
        the form out so a stale UID can't be submitted.
    """
    state = request.app.state.app_state
    if state.recent_unknown_tap():
        return HTMLResponse("", headers={"HX-Reswap": "none"})
    return templates.TemplateResponse(request, "_onboard_waiting.html", {})


@router.get("/onboard/poll/waiting", response_class=HTMLResponse)
async def onboard_poll_from_waiting(request: Request):
    """Polled by the waiting view. Returns:
      - HX-Reswap: none while no card has been tapped (waiting view stays).
      - The form fragment as soon as an unknown card hits the reader,
        swapping the waiting view out so the user can finish onboarding.
    """
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
