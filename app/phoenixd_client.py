"""Thin async client for Phoenixd's HTTP API.

LNbits's PhoenixdWallet integration covers payment plumbing (invoice in,
payment out), but doesn't expose enough state for an operator to see
"is my node healthy, what are my channel balances, who paid me recently?".

Phoenixd's own HTTP API is small and friendly — a handful of GETs returning
JSON. We auto-discover the API password from the same phoenixd-data volume
that LNbits reads it from.

Auth: HTTP Basic with empty username + the http-password from phoenix.conf.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger("espresso.phoenixd")


def discover_password() -> str | None:
    """Read Phoenixd's HTTP API password from the mounted phoenixd-data
    volume. Returns None if the file isn't there (FakeWallet mode or the
    operator hasn't enabled the phoenixd profile).
    """
    conf = Path("/phoenixd-data/phoenix.conf")
    if not conf.exists():
        return None
    for line in conf.read_text().splitlines():
        if line.startswith("http-password="):
            return line.split("=", 1)[1].strip()
    return None


@dataclass
class NodeInfo:
    node_id: str
    chain: str
    version: str
    channels_count: int
    channels: list[dict]


@dataclass
class BalanceInfo:
    """Phoenixd's view of the operator's funds.

    - balance_sats: spendable Lightning balance across open channels.
    - fee_credit_sats: pre-paid fees ACINQ holds for upcoming inbound liquidity
      events. Adds to your effective receive headroom.
    """
    balance_sats: int
    fee_credit_sats: int


@dataclass
class PhoenixdSnapshot:
    """One-shot collection used to render the /admin/node page."""
    reachable: bool
    info: NodeInfo | None = None
    balance: BalanceInfo | None = None
    channels: list[dict] = field(default_factory=list)
    incoming: list[dict] = field(default_factory=list)
    outgoing: list[dict] = field(default_factory=list)
    error: str | None = None


class PhoenixdClient:
    def __init__(self, url: str, password: str | None, *, timeout: float = 5.0):
        self.url = url.rstrip("/")
        self.password = password
        self._client = httpx.AsyncClient(timeout=timeout)
        if password:
            token = base64.b64encode(f":{password}".encode()).decode()
            self._headers = {"Authorization": f"Basic {token}"}
        else:
            self._headers = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def is_configured(self) -> bool:
        return self.password is not None

    async def _get_json(self, path: str) -> object:
        r = await self._client.get(f"{self.url}{path}", headers=self._headers)
        r.raise_for_status()
        return r.json()

    async def snapshot(self) -> PhoenixdSnapshot:
        """Pull everything the status page needs in one go. Each subcall is
        independent — if one fails we still surface what we have."""
        if not self.is_configured:
            return PhoenixdSnapshot(reachable=False, error="Phoenixd not configured")

        snap = PhoenixdSnapshot(reachable=False)

        try:
            info_data = await self._get_json("/getinfo")
            snap.info = NodeInfo(
                node_id=info_data.get("nodeId", ""),
                chain=info_data.get("chain", ""),
                version=info_data.get("version", ""),
                channels_count=len(info_data.get("channels", [])),
                channels=info_data.get("channels", []),
            )
            snap.reachable = True
        except (httpx.HTTPError, KeyError, TypeError) as e:
            snap.error = f"getinfo failed: {e}"
            return snap

        try:
            bal = await self._get_json("/getbalance")
            snap.balance = BalanceInfo(
                balance_sats=int(bal.get("balanceSat", 0)),
                fee_credit_sats=int(bal.get("feeCreditSat", 0)),
            )
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
            log.warning("phoenixd /getbalance failed: %s", e)

        try:
            ch = await self._get_json("/listchannels")
            snap.channels = ch if isinstance(ch, list) else []
        except (httpx.HTTPError, TypeError) as e:
            log.warning("phoenixd /listchannels failed: %s", e)

        try:
            data = await self._get_json("/payments/incoming?limit=10")
            snap.incoming = data if isinstance(data, list) else []
        except (httpx.HTTPError, TypeError) as e:
            log.warning("phoenixd incoming-payments failed: %s", e)

        try:
            data = await self._get_json("/payments/outgoing?limit=10")
            snap.outgoing = data if isinstance(data, list) else []
        except (httpx.HTTPError, TypeError) as e:
            log.warning("phoenixd outgoing-payments failed: %s", e)

        return snap
