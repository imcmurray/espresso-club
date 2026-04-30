"""Thin async client for the LNbits HTTP API.

Only the endpoints we actually use:
- POST /api/v1/account                       — create anonymous user+wallet
- PUT  /users/api/v1/user/{user_id}          — set username (admin auth)
- GET  /api/v1/wallet                         — fetch wallet balance
- POST /api/v1/payments                       — create invoice OR pay one
- GET  /api/v1/payments/{payment_hash}       — check payment status
- POST /api/v1/auth                           — admin login (gets JWT)

LNbits returns balances in millisatoshis (msat); we convert to sats at the
boundary so the rest of the app deals in whole sats.
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass

import httpx

log = logging.getLogger("espresso.lnbits")


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
    def __init__(self, base_url: str, admin_key: str, *,
                  admin_username: str | None = None,
                  admin_password: str | None = None,
                  timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.admin_key = admin_key
        # Optional super-user creds for admin-only endpoints (setting
        # usernames on accounts, etc.). Auto-discovered from the
        # /lnbits-data/admin.json file written by lnbits-init.
        self._admin_username = admin_username
        self._admin_password = admin_password
        self._admin_jwt: str | None = None
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- admin JWT (lazy, cached) ---------------------------------------------

    async def _get_admin_jwt(self) -> str | None:
        """Login as the LNbits super-user and cache the JWT. Returns None
        if no admin creds were provided at construction time."""
        if self._admin_jwt:
            return self._admin_jwt
        if not (self._admin_username and self._admin_password):
            return None
        try:
            r = await self._client.post(
                f"{self.base_url}/api/v1/auth",
                json={"username": self._admin_username,
                       "password": self._admin_password},
            )
            if r.status_code == 200:
                self._admin_jwt = r.json().get("access_token")
                return self._admin_jwt
            log.warning("admin login failed: %d %s", r.status_code, r.text[:120])
        except httpx.HTTPError as e:
            log.warning("admin login error: %s", e)
        return None

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
        independently-keyed wallet).

        After the wallet is created (anonymously), we make a best-effort
        admin call to set the username on the account so the LNbits user
        list shows who's who. Failure to set the username is logged but
        not fatal — the wallet is still usable; just shows up nameless
        in the LNbits admin UI.
        """
        body = {"name": wallet_name or f"{user_name}'s tab"}
        data = await self._request("POST", "/api/v1/account", json=body)
        wallet = WalletInfo(
            id=data["id"],
            name=data["name"],
            balance_sats=int(data.get("balance_msat", 0)) // 1000,
            admin_key=data["adminkey"],
            invoice_key=data["inkey"],
        )
        user_id = data.get("user")
        if user_id:
            await self._try_set_username(user_id, user_name)
        return wallet

    async def _try_set_username(self, user_id: str, display_name: str) -> None:
        """Best-effort: PUT /users/api/v1/user/{id} with a slugified
        username so the LNbits user list shows a recognizable label.

        LNbits requires `[a-zA-Z0-9._]{2,20}`, no leading/trailing dot or
        underscore, and no consecutive specials. We slugify the staff
        name and append 4 hex chars of randomness for uniqueness.
        """
        token = await self._get_admin_jwt()
        if not token:
            log.info("no admin JWT available — leaving LNbits username unset")
            return
        username = _slugify_for_lnbits(display_name)
        try:
            r = await self._client.put(
                f"{self.base_url}/users/api/v1/user/{user_id}",
                json={"username": username},
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code == 401:
                # JWT might have expired; re-login once and retry.
                self._admin_jwt = None
                token = await self._get_admin_jwt()
                if token:
                    r = await self._client.put(
                        f"{self.base_url}/users/api/v1/user/{user_id}",
                        json={"username": username},
                        headers={"Authorization": f"Bearer {token}"},
                    )
            if r.status_code >= 400:
                log.warning("set username '%s' on %s: %d %s",
                             username, user_id, r.status_code, r.text[:120])
            else:
                log.info("LNbits username set: %s -> %s", user_id, username)
        except httpx.HTTPError as e:
            log.warning("set_username request error: %s", e)

    # -- wallet balance / invoices / payments --------------------------------

    async def wallet_balance_sats(self, *, invoice_key: str) -> int:
        data = await self._request("GET", "/api/v1/wallet", key=invoice_key)
        return int(data["balance"]) // 1000  # msat -> sat

    async def create_invoice(self, *, invoice_key: str, amount_sats: int,
                              memo: str = "",
                              expiry: int = 3600) -> Invoice:
        """Create a Lightning invoice that expires after `expiry` seconds.

        Default 1 hour — long enough that someone can walk to their desk,
        open their Lightning wallet, and scan the QR without rush, but short
        enough that an abandoned QR won't sit around as a payment trap.
        """
        body = {"out": False, "amount": amount_sats, "memo": memo,
                "expiry": expiry}
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


def _slugify_for_lnbits(name: str) -> str:
    """Produce a username matching LNbits's ^[a-zA-Z0-9._]{2,20}$ regex.

    "Ian Test 1"     -> "Ian_Test_1_a3f4"
    "Sarah O'Brien"  -> "Sarah_OBrien_a3f4"
    "🥺 weird"       -> "weird_a3f4" (emoji stripped)
    "" or non-ASCII  -> "user_a3f4"
    """
    base = re.sub(r"[^a-zA-Z0-9]+", "_", name or "")
    base = base.strip("_.")[:14]
    if not base:
        base = "user"
    suffix = secrets.token_hex(2)  # 4 chars
    return f"{base}_{suffix}"
