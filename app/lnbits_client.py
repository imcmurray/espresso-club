"""Thin async client for the LNbits HTTP API.

Only the endpoints we actually use:
- POST /usermanager/api/v1/users           — create user + wallet
- GET  /api/v1/wallet                       — fetch wallet balance
- POST /api/v1/payments                     — create invoice OR pay one
- POST /api/v1/payments/decode              — decode bolt11
- GET  /api/v1/payments/{payment_hash}     — check payment status

LNbits returns balances in millisatoshis (msat); we convert to sats at the
boundary so the rest of the app deals in whole sats.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class LNbitsError(RuntimeError):
    pass


@dataclass
class WalletInfo:
    id: str
    name: str
    balance_sats: int
    admin_key: str
    invoice_key: str


@dataclass
class Invoice:
    payment_hash: str
    payment_request: str  # bolt11
    checking_id: str


class LNbitsClient:
    def __init__(self, base_url: str, admin_key: str, *, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.admin_key = admin_key
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- low-level -----------------------------------------------------------

    async def _request(self, method: str, path: str, *, key: str | None = None,
                        json: dict | None = None) -> dict:
        # /api/v1/account is unauthenticated; everything else uses an X-Api-Key.
        headers = {}
        api_key = key if key is not None else self.admin_key
        if api_key:
            headers["X-Api-Key"] = api_key
        r = await self._client.request(method, f"{self.base_url}{path}",
                                        headers=headers, json=json)
        if r.status_code >= 400:
            raise LNbitsError(f"{method} {path} -> {r.status_code}: {r.text}")
        return r.json() if r.content else {}

    # -- account / wallet creation -------------------------------------------

    async def create_user_and_wallet(self, *, user_name: str,
                                      wallet_name: str | None = None) -> WalletInfo:
        """Create a fresh LNbits user-and-wallet for one staff member.

        Uses POST /api/v1/account, which is built into LNbits v1.5+ and
        doesn't require admin auth (each call creates a new
        independently-keyed wallet). The legacy User Manager extension
        served the same purpose on older LNbits releases but no longer has
        a v1.x-compatible release in the manifests, so we use the core
        endpoint directly.
        """
        body = {"name": wallet_name or f"{user_name}'s tab"}
        data = await self._request("POST", "/api/v1/account", json=body)
        return WalletInfo(
            id=data["id"],
            name=data["name"],
            balance_sats=int(data.get("balance_msat", 0)) // 1000,
            admin_key=data["adminkey"],
            invoice_key=data["inkey"],
        )

    # -- wallet balance / invoices / payments --------------------------------

    async def wallet_balance_sats(self, *, invoice_key: str) -> int:
        data = await self._request("GET", "/api/v1/wallet", key=invoice_key)
        return int(data["balance"]) // 1000  # msat -> sat

    async def create_invoice(self, *, invoice_key: str, amount_sats: int,
                              memo: str = "") -> Invoice:
        body = {"out": False, "amount": amount_sats, "memo": memo}
        data = await self._request("POST", "/api/v1/payments", key=invoice_key, json=body)
        return Invoice(
            payment_hash=data["payment_hash"],
            payment_request=data["payment_request"],
            checking_id=data["checking_id"],
        )

    async def is_invoice_paid(self, *, invoice_key: str, payment_hash: str) -> bool:
        # LNbits v1.5.x returns 404 "Payment does not exist" for invoices
        # that haven't been paid yet (older versions returned {"paid": false}).
        # Treat 404 as "not paid yet" — anything else is a real error.
        try:
            data = await self._request("GET", f"/api/v1/payments/{payment_hash}",
                                        key=invoice_key)
        except LNbitsError as e:
            if " 404:" in str(e):
                return False
            raise
        return bool(data.get("paid"))

    async def pay_invoice(self, *, admin_key: str, bolt11: str) -> dict:
        body = {"out": True, "bolt11": bolt11}
        return await self._request("POST", "/api/v1/payments", key=admin_key, json=body)

    async def transfer_internal(self, *, source_admin_key: str,
                                 dest_invoice_key: str, amount_sats: int,
                                 memo: str = "") -> dict:
        """Move sats between two LNbits wallets. Used for drink purchases:
        debit the user's wallet, credit the operator/treasury wallet.

        Implementation: create an invoice on the destination, pay it from the
        source. LNbits short-circuits internal transfers so this is instant
        and free.
        """
        invoice = await self.create_invoice(
            invoice_key=dest_invoice_key, amount_sats=amount_sats, memo=memo,
        )
        return await self.pay_invoice(admin_key=source_admin_key,
                                       bolt11=invoice.payment_request)

    # -- admin -------------------------------------------------------------

    async def health(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/api/v1/health")
            return r.status_code == 200
        except httpx.HTTPError:
            return False
