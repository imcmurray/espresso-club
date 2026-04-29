"""Machine-to-machine endpoints.

- POST /api/nfc/tap — NFC daemon posts here on every card tap.
- POST /api/buy/{drink_id} — touchscreen buys a drink (debit + relay pulse).
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import sats_to_usd, usd_to_sats
from state import GiftBannerEntry

log = logging.getLogger("espresso.api")
router = APIRouter(prefix="/api")


class TapEvent(BaseModel):
    uid: str


@router.post("/nfc/tap")
async def nfc_tap(event: TapEvent, request: Request):
    state = request.app.state.app_state

    # Onboarding capture: if the most recent /onboard submission is awaiting a
    # tap, claim this UID for that user.
    pending_user_id = getattr(request.app.state, "pending_nfc_user_id", None)
    pending_expires = getattr(request.app.state, "pending_nfc_expires", 0)
    if pending_user_id and time.time() < pending_expires:
        existing = state.db.get_user_by_nfc(event.uid)
        if existing and existing.id != pending_user_id:
            return {"status": "error", "message": f"that card is already assigned to {existing.name}"}
        state.db.assign_nfc(pending_user_id, event.uid)
        request.app.state.pending_nfc_user_id = None
        user = state.db.get_user(pending_user_id)
        log.info("NFC %s registered to user %s (%d)", event.uid, user.name, user.id)
        balance = await state.ln.wallet_balance_sats(invoice_key=user.lnbits_invoice_key)
        await state.set_session(user.id, user.name, balance)
        return {"status": "registered", "user": user.name}

    # Normal tap: look up the user and start a session.
    user = state.db.get_user_by_nfc(event.uid)
    if not user:
        await state.clear_session(message=f"Unknown card ({event.uid[:8]}…). Visit /onboard.")
        return {"status": "unknown", "uid": event.uid}

    balance = await state.ln.wallet_balance_sats(invoice_key=user.lnbits_invoice_key)

    # Pull any unread gifts and build a banner. Acknowledge them in the same
    # tap so they don't re-appear; the banner is held for the session
    # lifetime, then disappears with the session.
    banner: list[GiftBannerEntry] = []
    for gift, sender_name in state.db.unacknowledged_gifts_for(user.id):
        banner.append(GiftBannerEntry(
            sender_name=sender_name,
            drink_name=gift.drink_name,
            amount_usd=gift.amount_usd,
        ))
    if banner:
        state.db.acknowledge_gifts_for(user.id)

    await state.set_session(user.id, user.name, balance, gift_banner=banner)
    log.info("tap: %s (balance %d sats / $%.2f) — %d unread gift(s)",
             user.name, balance, sats_to_usd(balance), len(banner))
    return {"status": "ok", "user": user.name, "balance_sats": balance,
            "unread_gifts": len(banner)}


@router.post("/buy/{drink_id}")
async def buy_drink(drink_id: str, request: Request):
    state = request.app.state.app_state
    session = state.session_or_none()
    if not session:
        raise HTTPException(409, "no active session — tap your card first")

    drink = state.get_drink(drink_id)
    if not drink:
        raise HTTPException(404, "unknown drink")

    user = state.db.get_user(session.user_id)
    if not user:
        raise HTTPException(500, "session user vanished")

    cost_sats = usd_to_sats(drink.price_usd)
    if session.balance_sats < cost_sats:
        await state.clear_session(
            message=f"{user.name}: balance too low for {drink.name} (${drink.price_usd:.2f}). "
                    f"Top up at /topup/{user.id}."
        )
        raise HTTPException(402, "insufficient balance")

    # Sink wallet: the operator's main LNbits wallet is the recipient. We
    # identify it by LNBITS_ADMIN_KEY in settings — this is the wallet you
    # logged into LNbits with first; its invoice key resolves at the LNbits
    # /api/v1/wallet endpoint. For simplicity we burn sats by paying the same
    # admin wallet in dev mode.
    treasury_key = state.settings.lnbits_admin_key
    await state.ln.transfer_internal(
        source_admin_key=user.lnbits_admin_key,
        dest_invoice_key=treasury_key,
        amount_sats=cost_sats,
        memo=f"{user.name}: {drink.name}",
    )

    new_balance = await state.ln.wallet_balance_sats(invoice_key=user.lnbits_invoice_key)
    state.db.record(
        user_id=user.id, kind="purchase", drink_id=drink.id,
        amount_sats=cost_sats, amount_usd=drink.price_usd,
        balance_after_sats=new_balance,
        meta={"drink_name": drink.name},
    )
    await state.relay.pulse(state.settings.grinder_pulse_seconds)
    await state.clear_session(
        message=f"☕ Enjoy your {drink.name}, {user.name}! (-${drink.price_usd:.2f}, "
                f"balance ${sats_to_usd(new_balance):.2f})"
    )
    return {
        "status": "ok",
        "drink": drink.name,
        "charged_usd": drink.price_usd,
        "charged_sats": cost_sats,
        "new_balance_sats": new_balance,
    }


# ---- gift flow ------------------------------------------------------------

@router.post("/gift/{recipient_user_id}/{drink_id}")
async def send_gift(recipient_user_id: int, drink_id: str, request: Request):
    """Sender (current session) gifts a specific drink to recipient.

    Funds flow sender_wallet → recipient_wallet via the same internal
    transfer used for normal purchases. A gift row is recorded so the
    recipient sees a banner the next time they tap.
    """
    state = request.app.state.app_state
    session = state.session_or_none()
    if not session:
        raise HTTPException(409, "no active session — tap your card first")

    sender = state.db.get_user(session.user_id)
    if not sender:
        raise HTTPException(500, "session user vanished")

    if recipient_user_id == sender.id:
        raise HTTPException(400, "you can't gift yourself")

    recipient = state.db.get_user(recipient_user_id)
    if not recipient:
        raise HTTPException(404, "recipient not found")

    drink = state.get_drink(drink_id)
    if not drink:
        raise HTTPException(404, "unknown drink")

    cost_sats = usd_to_sats(drink.price_usd)
    if session.balance_sats < cost_sats:
        await state.clear_session(
            message=f"{sender.name}: not enough to gift {drink.name} "
                    f"(${drink.price_usd:.2f}). Top up at /topup/{sender.id}."
        )
        raise HTTPException(402, "insufficient balance")

    # Move sats from sender's wallet to recipient's wallet via LNbits internal
    # transfer. Same primitive as a drink purchase — just a different sink.
    await state.ln.transfer_internal(
        source_admin_key=sender.lnbits_admin_key,
        dest_invoice_key=recipient.lnbits_invoice_key,
        amount_sats=cost_sats,
        memo=f"🎁 from {sender.name}: {drink.name}",
    )

    # Record the gift so the recipient sees a banner on their next tap.
    state.db.create_gift(
        sender_user_id=sender.id,
        recipient_user_id=recipient.id,
        drink_id=drink.id,
        drink_name=drink.name,
        amount_sats=cost_sats,
        amount_usd=drink.price_usd,
    )

    # Ledger entries for both sides — keeps leaderboards & history complete.
    state.db.record(
        user_id=sender.id, kind="adjustment", drink_id=drink.id,
        amount_sats=cost_sats, amount_usd=drink.price_usd,
        meta={"event": "gift_sent",
              "recipient_user_id": recipient.id,
              "recipient_name": recipient.name,
              "drink_name": drink.name},
    )
    state.db.record(
        user_id=recipient.id, kind="adjustment", drink_id=drink.id,
        amount_sats=cost_sats, amount_usd=drink.price_usd,
        meta={"event": "gift_received",
              "sender_user_id": sender.id,
              "sender_name": sender.name,
              "drink_name": drink.name},
    )

    await state.clear_session(
        message=f"🎁 You gifted {recipient.name} a {drink.name}! "
                f"They'll see it on their next tap."
    )
    return {
        "status": "ok",
        "recipient": recipient.name,
        "drink": drink.name,
        "charged_sats": cost_sats,
    }


@router.get("/state")
async def state_json(request: Request):
    state = request.app.state.app_state
    s = state.session_or_none()
    return {
        "session": (
            {"user_name": s.user_name, "balance_sats": s.balance_sats}
            if s else None
        ),
        "message": state.last_message,
    }


# ---- endpoints used by the Slack bot --------------------------------------

@router.get("/slack/user/{slack_user_id}")
async def slack_user(slack_user_id: str, request: Request):
    state = request.app.state.app_state
    user = state.db.get_user_by_slack(slack_user_id)
    if not user:
        return {"found": False}
    bal = await state.ln.wallet_balance_sats(invoice_key=user.lnbits_invoice_key)
    return {
        "found": True,
        "id": user.id,
        "name": user.name,
        "balance_sats": bal,
        "balance_usd": sats_to_usd(bal),
    }


@router.get("/leaderboard")
async def leaderboard(request: Request):
    import time as _t
    state = request.app.state.app_state
    since = int(_t.time()) - 30 * 86400
    rows = state.db.leaderboard(since_ts=since)
    return [{"name": n, "drinks": d, "sats": s, "usd": sats_to_usd(s)}
            for (n, d, s) in rows]


@router.get("/low-balance")
async def low_balance(request: Request, threshold_usd: float = 2.0):
    state = request.app.state.app_state
    out = []
    for u in state.db.list_users():
        try:
            bal = await state.ln.wallet_balance_sats(invoice_key=u.lnbits_invoice_key)
        except Exception:
            continue
        if sats_to_usd(bal) < threshold_usd:
            out.append({
                "id": u.id, "name": u.name,
                "slack_user_id": u.slack_user_id,
                "balance_sats": bal, "balance_usd": sats_to_usd(bal),
            })
    return out
