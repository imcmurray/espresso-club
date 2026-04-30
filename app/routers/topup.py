"""Top-up flow: generate a Lightning invoice for a chosen amount."""

from __future__ import annotations

import io
from base64 import b64encode

import qrcode
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from config import sats_to_usd, usd_to_sats

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _qr_data_url(payload: str) -> str:
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + b64encode(buf.getvalue()).decode()


@router.get("/topup/{user_id}", response_class=HTMLResponse)
async def topup_page(request: Request, user_id: int):
    state = request.app.state.app_state
    user = state.db.get_user(user_id)
    if not user:
        raise HTTPException(404, "user not found")

    balance_sats = await state.ln.wallet_balance_sats(invoice_key=user.lnbits_invoice_key)
    return templates.TemplateResponse(
        request,
        "topup.html",
        {
            "user": user,
            "balance_usd": sats_to_usd(balance_sats),
            "amounts": state.drinks.topup_amounts_usd,
        },
    )


@router.post("/topup/{user_id}/{amount_usd}", response_class=HTMLResponse)
async def topup_invoice(request: Request, user_id: int, amount_usd: float):
    state = request.app.state.app_state
    user = state.db.get_user(user_id)
    if not user:
        raise HTTPException(404, "user not found")

    sats = usd_to_sats(amount_usd)
    invoice = await state.ln.create_invoice(
        invoice_key=user.lnbits_invoice_key,
        amount_sats=sats,
        memo=f"Espresso Club top-up for {user.name} — ${amount_usd:.2f}",
    )

    return templates.TemplateResponse(
        request,
        "_topup_invoice.html",
        {
            "user": user,
            "amount_usd": amount_usd,
            "amount_sats": sats,
            "bolt11": invoice.payment_request,
            "payment_hash": invoice.payment_hash,
            "qr": _qr_data_url(invoice.payment_request.upper()),
        },
    )


@router.get("/topup/{user_id}/check/{payment_hash}", response_class=HTMLResponse)
async def topup_check(request: Request, user_id: int, payment_hash: str,
                       amount_usd: float = 0.0):
    """HTMX poll target — returns 'paid' fragment when the invoice settles.

    While the invoice is unpaid, return an empty body with HX-Reswap: none.
    HTMX honors that header by skipping the swap entirely, so the existing
    QR card stays mounted and the user can keep scanning. The hx-trigger on
    the card ('every 2s') is preserved, so polling continues. Only once the
    invoice is paid do we return real content that replaces the card.

    `amount_usd` is the original topup amount, passed as a query param by
    the polling fragment (the topup endpoint knows it; the check endpoint
    otherwise wouldn't). Used to record an accurate ledger entry.
    """
    state = request.app.state.app_state
    user = state.db.get_user(user_id)
    if not user:
        raise HTTPException(404, "user not found")

    paid = await state.ln.is_invoice_paid(
        invoice_key=user.lnbits_invoice_key, payment_hash=payment_hash,
    )
    if not paid:
        return HTMLResponse("", headers={"HX-Reswap": "none"})

    balance_sats = await state.ln.wallet_balance_sats(invoice_key=user.lnbits_invoice_key)
    state.db.record(
        user_id=user.id, kind="topup",
        amount_sats=usd_to_sats(amount_usd),
        amount_usd=float(amount_usd),
        balance_after_sats=balance_sats,
        meta={"payment_hash": payment_hash},
    )
    # First-time topup → show the welcome explainer alongside the success
    # message. After this one, the user has at least one topup row and we
    # skip the welcome.
    is_first_topup = state.db.count_ledger_entries_for(user.id, "topup") == 1
    return templates.TemplateResponse(
        request,
        "_topup_paid.html",
        {"user": user, "balance_usd": sats_to_usd(balance_sats),
         "is_first_topup": is_first_topup},
    )
