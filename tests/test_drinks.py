"""DB CRUD for drinks + seed-from-YAML behavior."""

from db import Drink


def _drink(**overrides):
    d = dict(id="latte", name="Latte", emoji="🥛", price_usd=1.10,
             description="big milk", sort_order=10, active=True)
    d.update(overrides)
    return Drink(**d)


def test_create_then_get(tmp_db):
    tmp_db.create_drink(_drink())
    got = tmp_db.get_drink("latte")
    assert got.name == "Latte" and got.price_usd == 1.10 and got.active


def test_list_active_only_excludes_soft_deleted(tmp_db):
    tmp_db.create_drink(_drink(id="espresso", name="Espresso",
                                price_usd=0.40, sort_order=1))
    tmp_db.create_drink(_drink(id="latte", price_usd=1.10, sort_order=10))
    tmp_db.soft_delete_drink("latte")
    active = tmp_db.list_drinks(active_only=True)
    all_drinks = tmp_db.list_drinks(active_only=False)
    assert [d.id for d in active] == ["espresso"]
    assert sorted(d.id for d in all_drinks) == ["espresso", "latte"]


def test_list_orders_by_sort_order(tmp_db):
    tmp_db.create_drink(_drink(id="b", sort_order=20))
    tmp_db.create_drink(_drink(id="a", sort_order=10))
    tmp_db.create_drink(_drink(id="c", sort_order=30))
    assert [d.id for d in tmp_db.list_drinks()] == ["a", "b", "c"]


def test_update_changes_fields(tmp_db):
    tmp_db.create_drink(_drink())
    tmp_db.update_drink("latte", name="Big Latte", emoji="🥛🥛",
                         price_usd=1.50, description="bigger",
                         sort_order=5, active=True)
    got = tmp_db.get_drink("latte")
    assert got.name == "Big Latte" and got.price_usd == 1.50 and got.sort_order == 5


def test_seed_is_idempotent(tmp_db):
    drinks = [_drink(id="a"), _drink(id="b")]
    tmp_db.seed_drinks(drinks)
    tmp_db.seed_drinks(drinks)  # second call should not duplicate
    assert tmp_db.count_drinks() == 2


def test_count_drinks_zero_initially(tmp_db):
    assert tmp_db.count_drinks() == 0
