"""Shared in-memory state for the touchscreen UI.

The touchscreen has a single "current user" — whoever last tapped their card.
This is held in memory; we don't try to multi-tenant the screen because it's
a single physical device.

Also caches a small drink-purchase queue so the screen can show "processing..."
animations.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from config import DrinksConfig, Settings
from db import Database, Drink
from lnbits_client import LNbitsClient
from phoenixd_client import PhoenixdClient
from relay import Relay


@dataclass
class GiftBannerEntry:
    sender_name: str
    drink_name: str | None
    amount_usd: float


@dataclass
class CurrentSession:
    user_id: int
    user_name: str
    balance_sats: int
    expires_at: float
    # Gift-flow sub-state. mode == "menu" is the default drinks-grid view;
    # "gift_pick_recipient" shows a list of users to gift to;
    # "gift_pick_drink" shows the drinks grid framed as "gift X a ...".
    mode: str = "menu"
    gift_recipient_id: int | None = None
    gift_recipient_name: str | None = None
    # Unread-gift banner shown to the recipient on tap. Cleared when the
    # session ends; the underlying gift rows are marked acknowledged so
    # they don't re-appear on subsequent taps.
    gift_banner: list[GiftBannerEntry] = field(default_factory=list)

    def is_active(self) -> bool:
        return time.time() < self.expires_at


@dataclass
class AppState:
    settings: Settings
    drinks: DrinksConfig
    db: Database
    ln: LNbitsClient
    relay: Relay
    phoenixd: PhoenixdClient | None = None

    current: CurrentSession | None = None
    last_message: str | None = None
    last_message_expires_at: float = 0.0
    # CTAs that ride along with the message. Both are cleared at the same
    # time as the message. Only one is shown at a time (join takes priority
    # over topup if both happen to be set).
    last_message_join_card_uid: str | None = None
    last_message_topup_user_id: int | None = None
    # Most-recently tapped UID that didn't match any registered user.
    # Cleared on a successful onboard or after UNKNOWN_TAP_WINDOW_SECONDS,
    # whichever comes first. The /onboard page polls this to know when to
    # unlock its form.
    last_unknown_tap_uid: str | None = None
    last_unknown_tap_at: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    SESSION_TIMEOUT_SECONDS = 30
    MESSAGE_TIMEOUT_SECONDS = 30
    UNKNOWN_TAP_WINDOW_SECONDS = 60

    async def set_session(self, user_id: int, user_name: str,
                           balance_sats: int,
                           gift_banner: list[GiftBannerEntry] | None = None) -> None:
        async with self._lock:
            self.current = CurrentSession(
                user_id=user_id,
                user_name=user_name,
                balance_sats=balance_sats,
                expires_at=time.time() + self.SESSION_TIMEOUT_SECONDS,
                gift_banner=gift_banner or [],
            )
            self.last_message = None

    async def update_session_mode(self, *, mode: str,
                                   recipient_id: int | None = None,
                                   recipient_name: str | None = None) -> None:
        async with self._lock:
            if not self.current or not self.current.is_active():
                return
            self.current.mode = mode
            self.current.gift_recipient_id = recipient_id
            self.current.gift_recipient_name = recipient_name
            # Refresh the timer on interaction so users don't time out
            # mid-flow.
            self.current.expires_at = time.time() + self.SESSION_TIMEOUT_SECONDS

    async def clear_session(self, message: str | None = None, *,
                              join_card_uid: str | None = None,
                              topup_user_id: int | None = None) -> None:
        async with self._lock:
            self.current = None
            self.last_message = message
            self.last_message_join_card_uid = join_card_uid if message else None
            self.last_message_topup_user_id = topup_user_id if message else None
            # Auto-expire the message after 30s so user balances and "Enjoy
            # your X!" lines don't linger on the screen after the customer
            # has walked away.
            self.last_message_expires_at = (
                time.time() + self.MESSAGE_TIMEOUT_SECONDS if message else 0.0
            )

    def session_or_none(self) -> CurrentSession | None:
        if self.current and self.current.is_active():
            return self.current
        return None

    def message_or_none(self) -> str | None:
        """Return the post-session message if it was set within the last
        MESSAGE_TIMEOUT_SECONDS, else None. Polled by the touchscreen
        fragment, so once it ages out it just disappears on the next poll."""
        if self.last_message and time.time() < self.last_message_expires_at:
            return self.last_message
        return None

    def join_card_uid_or_none(self) -> str | None:
        """If the most recent message has an associated card-UID for the
        'Join with this card' CTA, return it (subject to the same expiry
        as the message itself)."""
        if (self.last_message_join_card_uid
                and time.time() < self.last_message_expires_at):
            return self.last_message_join_card_uid
        return None

    def topup_user_id_or_none(self) -> int | None:
        """User ID for an attached 'Top up now' CTA on the message div, or
        None if there's no current message or no topup target."""
        if (self.last_message_topup_user_id
                and time.time() < self.last_message_expires_at):
            return self.last_message_topup_user_id
        return None

    async def record_unknown_tap(self, uid: str) -> None:
        """Stash an unknown-card UID so the /onboard page can unlock its
        form once the user gets there. Window matches the time it'd
        plausibly take a person to walk to the kiosk and visit /onboard."""
        async with self._lock:
            self.last_unknown_tap_uid = uid
            self.last_unknown_tap_at = (
                time.time() + self.UNKNOWN_TAP_WINDOW_SECONDS
            )

    def recent_unknown_tap(self) -> str | None:
        """Return the most-recently-stashed unknown UID if it's still in
        the watch window, else None."""
        if (self.last_unknown_tap_uid
                and time.time() < self.last_unknown_tap_at):
            return self.last_unknown_tap_uid
        return None

    async def consume_unknown_tap(self) -> None:
        """Clear the stashed UID after a successful onboard so it doesn't
        keep nudging the form."""
        async with self._lock:
            self.last_unknown_tap_uid = None
            self.last_unknown_tap_at = 0.0

    # -- drinks live in the DB now; YAML is just a seed source ---------------

    def list_active_drinks(self) -> list[Drink]:
        return self.db.list_drinks(active_only=True)

    def get_drink(self, drink_id: str) -> Drink | None:
        d = self.db.get_drink(drink_id)
        return d if (d and d.active) else None
