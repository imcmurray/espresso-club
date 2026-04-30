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
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    SESSION_TIMEOUT_SECONDS = 30

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

    async def clear_session(self, message: str | None = None) -> None:
        async with self._lock:
            self.current = None
            self.last_message = message

    def session_or_none(self) -> CurrentSession | None:
        if self.current and self.current.is_active():
            return self.current
        return None

    # -- drinks live in the DB now; YAML is just a seed source ---------------

    def list_active_drinks(self) -> list[Drink]:
        return self.db.list_drinks(active_only=True)

    def get_drink(self, drink_id: str) -> Drink | None:
        d = self.db.get_drink(drink_id)
        return d if (d and d.active) else None
