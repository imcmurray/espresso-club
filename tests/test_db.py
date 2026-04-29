def test_create_user_and_assign_nfc(tmp_db):
    u = tmp_db.create_user(
        name="Sarah", lnbits_wallet_id="w1",
        lnbits_admin_key="adm-w1", lnbits_invoice_key="inv-w1",
    )
    assert u.id and u.name == "Sarah" and u.nfc_uid is None

    tmp_db.assign_nfc(u.id, "DEMO-CARD-1")
    refetched = tmp_db.get_user_by_nfc("DEMO-CARD-1")
    assert refetched and refetched.id == u.id


def test_ledger_record_and_recent(tmp_db):
    u = tmp_db.create_user(
        name="Bob", lnbits_wallet_id="w2",
        lnbits_admin_key="adm-w2", lnbits_invoice_key="inv-w2",
    )
    tmp_db.record(user_id=u.id, kind="purchase", drink_id="latte",
                   amount_sats=2200, amount_usd=1.10, balance_after_sats=10000)
    tmp_db.record(user_id=u.id, kind="topup",
                   amount_sats=20000, amount_usd=10.0, balance_after_sats=30000)
    rows = tmp_db.recent_for_user(u.id)
    assert len(rows) == 2
    assert rows[0].kind == "topup"  # most recent first


def test_leaderboard_ordering(tmp_db):
    a = tmp_db.create_user(name="A", lnbits_wallet_id="a",
                            lnbits_admin_key="x", lnbits_invoice_key="y")
    b = tmp_db.create_user(name="B", lnbits_wallet_id="b",
                            lnbits_admin_key="x2", lnbits_invoice_key="y2")
    tmp_db.record(user_id=a.id, kind="purchase", drink_id="latte",
                   amount_sats=2200, amount_usd=1.10)
    tmp_db.record(user_id=b.id, kind="purchase", drink_id="latte",
                   amount_sats=2200, amount_usd=1.10)
    tmp_db.record(user_id=b.id, kind="purchase", drink_id="cappuccino",
                   amount_sats=1800, amount_usd=0.90)
    board = tmp_db.leaderboard(since_ts=0)
    assert board[0][0] == "B"   # B drank more
    assert board[0][1] == 2     # 2 drinks
    assert board[1][0] == "A"
