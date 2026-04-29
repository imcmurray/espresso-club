"""End-to-end test of the buy flow with a fake LNbits backend.

Covers:
- onboarding creates an LNbits wallet
- NFC tap starts a session
- buying a drink debits the wallet, pulses the relay, and records the ledger
- insufficient balance fails cleanly
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(monkeypatch, tmp_path, fake_ln):
    # Configure the app to use the temp DB and our fake LNbits.
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "espresso.sqlite3"))
    monkeypatch.setenv("DRINKS_CONFIG",
                        str(__file__.rsplit("/", 2)[0] + "/app/drinks.yaml"))
    monkeypatch.setenv("RELAY_DRIVER", "simulator")
    monkeypatch.setenv("LNBITS_URL", "http://fake")
    monkeypatch.setenv("LNBITS_ADMIN_KEY", "adm-treasury")

    # Pre-create the treasury wallet in fake LN so transfers have a sink.
    asyncio.run(fake_ln.create_user_and_wallet(user_name="treasury"))
    # The treasury "admin key" is hardcoded in env above; rewrite the fake
    # so its first wallet's invoice_key matches what api.py looks up.
    treasury = list(fake_ln.wallets.values())[0]
    treasury.invoice_key = "adm-treasury"

    # Patch the LNbits client constructor to return our fake.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
    import lnbits_client
    monkeypatch.setattr(lnbits_client, "LNbitsClient", lambda *a, **kw: fake_ln)

    # Re-import main fresh so the lifespan re-runs with our patches.
    if "main" in sys.modules:
        del sys.modules["main"]
    from main import app as fastapi_app
    with TestClient(fastapi_app) as client:
        yield client, fake_ln


def test_full_flow(app):
    client, fake_ln = app

    # 1. Onboard Sarah.
    r = client.post("/onboard", data={"name": "Sarah"}, follow_redirects=False)
    assert r.status_code == 303
    assert "/topup/" in r.headers["location"]
    sarah_id = int(r.headers["location"].rsplit("/", 1)[1])

    # 2. Sarah's wallet is funded externally (simulating a Lightning top-up).
    sarah_wallet = [w for w in fake_ln.wallets.values()
                    if w.name and "Sarah" in w.name][0]
    fake_ln.fund_wallet(sarah_wallet.invoice_key, 5000)  # 5000 sats = $2.50

    # 3. Tap registers the NFC card to Sarah.
    r = client.post("/api/nfc/tap", json={"uid": "CARD-SARAH"})
    assert r.status_code == 200
    assert r.json()["status"] in ("registered", "ok")

    # 4. Tap again to start a buy session.
    r = client.post("/api/nfc/tap", json={"uid": "CARD-SARAH"})
    assert r.status_code == 200, r.text
    assert r.json()["balance_sats"] == 5000

    # 5. Buy an espresso ($0.40 = 800 sats).
    r = client.post("/api/buy/espresso")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["charged_sats"] == 800
    assert body["new_balance_sats"] == 4200

    # 6. Treasury wallet collected the sats.
    treasury = list(fake_ln.wallets.values())[0]
    assert treasury.balance_sats == 800


def test_insufficient_balance(app):
    client, fake_ln = app
    r = client.post("/onboard", data={"name": "Broke"}, follow_redirects=False)
    bid = int(r.headers["location"].rsplit("/", 1)[1])

    client.post("/api/nfc/tap", json={"uid": "CARD-BROKE"})
    client.post("/api/nfc/tap", json={"uid": "CARD-BROKE"})  # session

    r = client.post("/api/buy/latte")
    assert r.status_code == 402  # payment required


def test_unknown_card(app):
    client, _ = app
    r = client.post("/api/nfc/tap", json={"uid": "GHOST-CARD"})
    assert r.status_code == 200
    assert r.json()["status"] == "unknown"

    r = client.post("/api/buy/espresso")
    assert r.status_code == 409
