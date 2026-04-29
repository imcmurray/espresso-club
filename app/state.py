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
from relay import Relay


@dataclass
class CurrentSession:
    user_id: int
    user_name: str
    balance_sats: int
    expires_at: float

    def is_active(self) -> bool:
        return time.time() < self.expires_at


@dataclass
class AppState:
    settings: Settings
    drinks: DrinksConfig
    db: Database
    ln: LNbitsClient
    relay: Relay

    current: CurrentSession | None = None
    last_message: str | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    SESSION_TIMEOUT_SECONDS = 30

    async def set_session(self, user_id: int, user_name: str, balance_sats: int) -> None:
        async with self._lock:
            self.current = CurrentSession(
                user_id=user_id,
                user_name=user_name,
                balance_sats=balance_sats,
                expires_at=time.time() + self.SESSION_TIMEOUT_SECONDS,
            )
            self.last_message = None

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
