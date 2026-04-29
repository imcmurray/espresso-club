"""Operator dashboard."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import sats_to_usd

router = APIRouter()
templates = Jinja2Templates(directory="templates")


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
        "admin.html",
        {
            "request": request,
            "users": user_rows,
            "recent": recent,
            "leaderboard": leaderboard,
            "sats_to_usd": sats_to_usd,
        },
    )
