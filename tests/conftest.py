"""Test fixtures for the espresso app.

We use a fake LNbits client and an in-memory SQLite to keep tests fast and
hermetic. Real LN integration is exercised by scripts/smoke_test.sh against a
running stack.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


@dataclass
class FakeWallet:
    id: str
    invoice_key: str
    admin_key: str
    name: str
    balance_sats: int = 0


class FakeLNbits:
    """In-memory stand-in for LNbitsClient.

    Captures wallet creates, balance reads, internal transfers, and invoices.
    """

    def __init__(self):
        self.wallets: dict[str, FakeWallet] = {}
        self.invoices: dict[str, tuple[str, int]] = {}  # hash -> (invoice_key, sats)
        self._next_id = 1
        # Mirrors LNbitsClient.admin_key — the operator wallet's adminkey,
        # used as the treasury "destination" by the buy_drink flow.
        self.admin_key: str = "adm-treasury"

    async def aclose(self):
        pass

    async def create_user_and_wallet(self, *, user_name, wallet_name=None):
        # Mirrors POST /api/v1/account in LNbits v1.5+: anonymous, no auth,
        # returns a single wallet keyed for the implicit new user. The
        # production code also calls a best-effort admin endpoint to set
        # the LNbits username + external_id, but tests don't exercise that.
        wid = f"w{self._next_id}"
        self._next_id += 1
        w = FakeWallet(
            id=wid,
            invoice_key=f"inv-{wid}",
            admin_key=f"adm-{wid}",
            name=wallet_name or f"{user_name}'s tab",
        )
        self.wallets[wid] = w
        return type("WalletInfo", (), dict(
            id=w.id, name=w.name, balance_sats=0,
            admin_key=w.admin_key, invoice_key=w.invoice_key,
            user_id=f"u{wid}",
        ))

    async def update_user_metadata(self, user_id, *,
                                    display_name=None, external_id=None):
        """No-op stub matching the production client's interface so call
        sites can hit it unconditionally in tests."""
        return True

    def _wallet_by_invoice(self, invoice_key) -> FakeWallet:
        for w in self.wallets.values():
            if w.invoice_key == invoice_key:
                return w
        raise KeyError(invoice_key)

    def _wallet_by_admin(self, admin_key) -> FakeWallet:
        for w in self.wallets.values():
            if w.admin_key == admin_key:
                return w
        raise KeyError(admin_key)

    async def wallet_balance_sats(self, *, invoice_key):
        return self._wallet_by_invoice(invoice_key).balance_sats

    async def create_invoice(self, *, invoice_key, amount_sats, memo=""):
        h = f"hash-{len(self.invoices)+1}"
        self.invoices[h] = (invoice_key, amount_sats)
        return type("Invoice", (), dict(
            payment_hash=h,
            payment_request=f"lnbc{amount_sats}n1p{h}",
            checking_id=h,
        ))

    async def is_invoice_paid(self, *, invoice_key, payment_hash):
        # In tests we mark invoices "paid" by calling fund_wallet directly.
        return payment_hash not in self.invoices

    async def pay_invoice(self, *, admin_key, bolt11):
        # Find the matching invoice. In real flow LNbits decodes bolt11; here
        # we look it up by the hash embedded in the fake bolt11 string.
        h = bolt11.split("p")[-1]
        inv = self.invoices.pop(h, None)
        if not inv:
            raise RuntimeError("invoice not found / already paid")
        dest_invoice_key, sats = inv
        src = self._wallet_by_admin(admin_key)
        if src.balance_sats < sats:
            self.invoices[h] = inv  # restore
            raise RuntimeError("insufficient")
        dst = self._wallet_by_invoice(dest_invoice_key)
        src.balance_sats -= sats
        dst.balance_sats += sats
        return {"ok": True}

    async def transfer_internal(self, *, source_admin_key, dest_invoice_key,
                                 amount_sats, memo=""):
        invoice = await self.create_invoice(
            invoice_key=dest_invoice_key, amount_sats=amount_sats, memo=memo)
        return await self.pay_invoice(admin_key=source_admin_key,
                                       bolt11=invoice.payment_request)

    # test helpers ------------------------------------------------------
    def fund_wallet(self, invoice_key: str, sats: int):
        self._wallet_by_invoice(invoice_key).balance_sats += sats


@pytest.fixture
def fake_ln():
    return FakeLNbits()


@pytest.fixture
def tmp_db(tmp_path):
    from db import Database
    return Database(str(tmp_path / "test.sqlite3"))
