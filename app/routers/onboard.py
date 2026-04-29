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
async def onboard_form(request: Request):
    return templates.TemplateResponse(request, "onboard.html")


@router.post("/onboard")
async def onboard_submit(request: Request, name: str = Form(...)):
    state = request.app.state.app_state
    name = name.strip()
    if not name:
        raise HTTPException(400, "Name is required")

    wallet = await state.ln.create_user_and_wallet(user_name=name)
    user = state.db.create_user(
        name=name,
        lnbits_wallet_id=wallet.id,
        lnbits_admin_key=wallet.admin_key,
        lnbits_invoice_key=wallet.invoice_key,
    )
    # The next NFC tap will be claimed for this user — see api.tap.
    state.last_message = (
        f"Welcome, {name}! Tap your card on the reader within 30 seconds to register it."
    )
    request.app.state.pending_nfc_user_id = user.id
    request.app.state.pending_nfc_expires = _now() + 30

    return RedirectResponse(url=f"/topup/{user.id}", status_code=303)


def _now() -> float:
    import time as _t
    return _t.time()
