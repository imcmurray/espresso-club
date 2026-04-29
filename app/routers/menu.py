"""Touchscreen menu UI."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import sats_to_usd

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/menu", response_class=HTMLResponse)
async def menu(request: Request):
    state = request.app.state.app_state
    session = state.session_or_none()
    return templates.TemplateResponse(
        "menu.html",
        {
            "request": request,
            "session": session,
            "drinks": state.drinks.drinks,
            "balance_usd": sats_to_usd(session.balance_sats) if session else None,
            "message": state.last_message,
        },
    )


@router.get("/menu/state", response_class=HTMLResponse)
async def menu_state(request: Request):
    """HTMX-polled fragment that updates the screen when a card is tapped."""
    state = request.app.state.app_state
    session = state.session_or_none()
    return templates.TemplateResponse(
        "_menu_state.html",
        {
            "request": request,
            "session": session,
            "drinks": state.drinks.drinks,
            "balance_usd": sats_to_usd(session.balance_sats) if session else None,
            "message": state.last_message,
        },
    )
