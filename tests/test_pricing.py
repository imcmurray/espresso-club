from config import sats_to_usd, usd_to_sats


def test_round_trip_at_default_rate():
    sats = usd_to_sats(1.10)
    # 1.10 / 50000 * 100_000_000 = 2200
    assert sats == 2200
    assert abs(sats_to_usd(sats) - 1.10) < 0.001


def test_at_custom_rate():
    # If BTC is at 100k, $1 = 1000 sats.
    assert usd_to_sats(1.0, btc_usd=100_000) == 1000


def test_zero_amount():
    assert usd_to_sats(0) == 0
    assert sats_to_usd(0) == 0.0
