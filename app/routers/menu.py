"""Touchscreen menu UI."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from config import sats_to_usd

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/menu", response_class=HTMLResponse)
async def menu(request: Request):
    state = request.app.state.app_state
    session = state.session_or_none()
    return templates.TemplateResponse(
        request,
        "menu.html",
        {
            "session": session,
            "drinks": state.list_active_drinks(),
            "balance_usd": sats_to_usd(session.balance_sats) if session else None,
            "message": state.message_or_none(),
        },
    )


@router.get("/menu/state", response_class=HTMLResponse)
async def menu_state(request: Request):
    """HTMX-polled fragment that updates the screen when a card is tapped."""
    return _render_state(request)


# ---- gift-flow mode transitions (touchscreen UI) -------------------------

@router.post("/menu/gift/start", response_class=HTMLResponse)
async def gift_start(request: Request):
    """Sender clicked 'Gift a drink'. Switch to recipient picker."""
    state = request.app.state.app_state
    await state.update_session_mode(mode="gift_pick_recipient")
    return _render_state(request)


@router.post("/menu/gift/recipient/{recipient_user_id}", response_class=HTMLResponse)
async def gift_recipient(recipient_user_id: int, request: Request):
    """Sender picked a recipient. Switch to drink picker."""
    state = request.app.state.app_state
    session = state.session_or_none()
    if not session:
        return _render_state(request)
    recipient = state.db.get_user(recipient_user_id)
    if not recipient or recipient.id == session.user_id:
        return _render_state(request)
    await state.update_session_mode(
        mode="gift_pick_drink",
        recipient_id=recipient.id,
        recipient_name=recipient.name,
    )
    return _render_state(request)


@router.post("/menu/gift/cancel", response_class=HTMLResponse)
async def gift_cancel(request: Request):
    """Back out of the gift flow to the normal drinks menu."""
    state = request.app.state.app_state
    await state.update_session_mode(mode="menu")
    return _render_state(request)


# ---- helpers --------------------------------------------------------------

def _render_state(request: Request):
    state = request.app.state.app_state
    session = state.session_or_none()

    # In recipient-picker mode the page needs the list of users (sans self).
    other_users = []
    if session and session.mode == "gift_pick_recipient":
        other_users = [u for u in state.db.list_users() if u.id != session.user_id]

    return templates.TemplateResponse(
        request,
        "_menu_state.html",
        {
            "session": session,
            "drinks": state.list_active_drinks(),
            "balance_usd": sats_to_usd(session.balance_sats) if session else None,
            "message": state.message_or_none(),
            "other_users": other_users,
        },
    )
