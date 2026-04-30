"""Gift-flow DB tests + end-to-end touchscreen flow with the fake LNbits."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from db import Drink


# ---- DB-only tests --------------------------------------------------------

def _make_user(db, name):
    return db.create_user(
        name=name, lnbits_wallet_id=f"w-{name}",
        lnbits_admin_key=f"adm-{name}", lnbits_invoice_key=f"inv-{name}",
    )


def test_create_and_list_unack_gifts(tmp_db):
    a = _make_user(tmp_db, "Alice")
    b = _make_user(tmp_db, "Bob")
    g = tmp_db.create_gift(
        sender_user_id=a.id, recipient_user_id=b.id,
        drink_id="latte", drink_name="Latte",
        amount_sats=2200, amount_usd=1.10,
    )
    assert g.id and g.acknowledged_at is None

    unread = tmp_db.unacknowledged_gifts_for(b.id)
    assert len(unread) == 1
    gift, sender_name = unread[0]
    assert gift.drink_name == "Latte" and sender_name == "Alice"


def test_acknowledge_clears_unread(tmp_db):
    a = _make_user(tmp_db, "Alice")
    b = _make_user(tmp_db, "Bob")
    tmp_db.create_gift(sender_user_id=a.id, recipient_user_id=b.id,
                        drink_id="latte", drink_name="Latte",
                        amount_sats=2200, amount_usd=1.10)
    tmp_db.create_gift(sender_user_id=a.id, recipient_user_id=b.id,
                        drink_id="espresso", drink_name="Espresso",
                        amount_sats=800, amount_usd=0.40)

    n = tmp_db.acknowledge_gifts_for(b.id)
    assert n == 2
    assert tmp_db.unacknowledged_gifts_for(b.id) == []


def test_unack_filters_to_recipient(tmp_db):
    a = _make_user(tmp_db, "Alice")
    b = _make_user(tmp_db, "Bob")
    c = _make_user(tmp_db, "Carol")
    tmp_db.create_gift(sender_user_id=a.id, recipient_user_id=b.id,
                        drink_id="latte", drink_name="Latte",
                        amount_sats=2200, amount_usd=1.10)
    # Carol shouldn't see Bob's gift.
    assert tmp_db.unacknowledged_gifts_for(c.id) == []
    assert len(tmp_db.unacknowledged_gifts_for(b.id)) == 1


# ---- End-to-end via the fake LNbits backend -------------------------------

@pytest.fixture
def app(monkeypatch, tmp_path, fake_ln):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "espresso.sqlite3"))
    monkeypatch.setenv("DRINKS_CONFIG",
                        str(__file__.rsplit("/", 2)[0] + "/app/drinks.yaml"))
    monkeypatch.setenv("RELAY_DRIVER", "simulator")
    monkeypatch.setenv("LNBITS_URL", "http://fake")
    monkeypatch.setenv("LNBITS_ADMIN_KEY", "adm-treasury")

    asyncio.run(fake_ln.create_user_and_wallet(user_name="treasury"))
    treasury = list(fake_ln.wallets.values())[0]
    treasury.invoice_key = "adm-treasury"

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
    import lnbits_client
    monkeypatch.setattr(lnbits_client, "LNbitsClient", lambda *a, **kw: fake_ln)

    # Clear cached settings/drinks so this test's env (DATABASE_PATH etc.)
    # actually gets read instead of leaking from a prior test.
    import config
    config.get_settings.cache_clear()
    config.get_drinks.cache_clear()

    if "main" in sys.modules:
        del sys.modules["main"]
    from main import app as fastapi_app
    with TestClient(fastapi_app) as client:
        yield client, fake_ln


def _onboard_and_fund(client, fake_ln, name, card_uid, sats):
    """Helper: onboard a user with their card UID supplied at signup, then
    fund their LNbits sub-wallet directly (simulating a paid Lightning
    invoice). No separate tap-to-register step needed since card is set
    on the form."""
    r = client.post("/onboard",
                     data={"name": name, "nfc_uid": card_uid},
                     follow_redirects=False)
    assert r.status_code == 303, r.text
    user_id = int(r.headers["location"].rsplit("/", 1)[1])
    wallet = next(w for w in fake_ln.wallets.values()
                   if w.name and name in w.name)
    fake_ln.fund_wallet(wallet.invoice_key, sats)
    return user_id, wallet


def test_full_gift_flow(app):
    client, fake_ln = app

    sarah_id, sarah_wallet = _onboard_and_fund(client, fake_ln,
                                                "Sarah", "CARD-S", 5000)
    # Tap a second time (first registered the card, second starts a session).
    client.post("/api/nfc/tap", json={"uid": "CARD-S"})

    marcus_id, marcus_wallet = _onboard_and_fund(client, fake_ln,
                                                  "Marcus", "CARD-M", 0)

    # Sarah taps her card to start a session.
    r = client.post("/api/nfc/tap", json={"uid": "CARD-S"})
    assert r.status_code == 200

    # Sarah gifts Marcus an espresso ($0.40 = 800 sats).
    r = client.post(f"/api/gift/{marcus_id}/espresso")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipient"] == "Marcus"
    assert body["charged_sats"] == 800

    # Sarah's wallet was debited; Marcus's was credited.
    assert sarah_wallet.balance_sats == 5000 - 800
    assert marcus_wallet.balance_sats == 800

    # Marcus taps. He should see the gift banner and his new balance.
    r = client.post("/api/nfc/tap", json={"uid": "CARD-M"})
    assert r.status_code == 200
    assert r.json()["unread_gifts"] == 1
    assert r.json()["balance_sats"] == 800

    # Tap again — banner should be gone (already acknowledged).
    r = client.post("/api/nfc/tap", json={"uid": "CARD-M"})
    assert r.status_code == 200
    assert r.json()["unread_gifts"] == 0


def test_gift_self_is_rejected(app):
    client, fake_ln = app
    sarah_id, _ = _onboard_and_fund(client, fake_ln, "Sarah", "CARD-S", 5000)
    client.post("/api/nfc/tap", json={"uid": "CARD-S"})  # session start

    r = client.post(f"/api/gift/{sarah_id}/espresso")
    assert r.status_code == 400


def test_gift_insufficient_balance(app):
    client, fake_ln = app
    _onboard_and_fund(client, fake_ln, "Broke", "CARD-B", 100)  # 100 sats only
    marcus_id, _ = _onboard_and_fund(client, fake_ln, "Marcus", "CARD-M", 0)
    client.post("/api/nfc/tap", json={"uid": "CARD-B"})

    r = client.post(f"/api/gift/{marcus_id}/latte")  # 2200 sats > 100
    assert r.status_code == 402


def test_gift_mode_transitions(app):
    client, fake_ln = app
    _onboard_and_fund(client, fake_ln, "Sarah", "CARD-S", 5000)
    marcus_id, _ = _onboard_and_fund(client, fake_ln, "Marcus", "CARD-M", 0)
    client.post("/api/nfc/tap", json={"uid": "CARD-S"})

    # Start the gift flow.
    r = client.post("/menu/gift/start")
    assert r.status_code == 200
    assert "Pick someone" in r.text

    # Pick a recipient.
    r = client.post(f"/menu/gift/recipient/{marcus_id}")
    assert r.status_code == 200
    assert "Gifting" in r.text and "Marcus" in r.text

    # Cancel returns to the menu.
    r = client.post("/menu/gift/cancel")
    assert r.status_code == 200
    assert "Pick a drink" in r.text or "drinks-grid" in r.text or "Gift a drink" in r.text
