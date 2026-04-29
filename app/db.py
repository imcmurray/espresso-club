"""SQLite-backed storage for users and the drink ledger.

Balances are *not* stored here — they're authoritative in LNbits. We re-fetch
on demand. The ledger is for analytics, leaderboards, and audit ("show me every
drink Sarah bought last month").
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    nfc_uid TEXT UNIQUE,
    lnbits_wallet_id TEXT NOT NULL,
    lnbits_admin_key TEXT NOT NULL,
    lnbits_invoice_key TEXT NOT NULL,
    slack_user_id TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_nfc_uid ON users(nfc_uid);
CREATE INDEX IF NOT EXISTS idx_users_slack ON users(slack_user_id);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('purchase','topup','adjustment')),
    drink_id TEXT,
    amount_sats INTEGER NOT NULL,
    amount_usd REAL NOT NULL,
    balance_after_sats INTEGER,
    timestamp INTEGER NOT NULL,
    meta TEXT
);

CREATE INDEX IF NOT EXISTS idx_ledger_user_ts ON ledger(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_kind ON ledger(kind);

CREATE TABLE IF NOT EXISTS drinks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '',
    price_usd REAL NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_drinks_active_sort ON drinks(active, sort_order);
"""


@dataclass
class User:
    id: int
    name: str
    nfc_uid: str | None
    lnbits_wallet_id: str
    lnbits_admin_key: str
    lnbits_invoice_key: str
    slack_user_id: str | None
    created_at: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "User":
        return cls(**{k: row[k] for k in row.keys()})


@dataclass
class Drink:
    id: str
    name: str
    emoji: str
    price_usd: float
    description: str
    sort_order: int
    active: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Drink":
        return cls(
            id=row["id"], name=row["name"], emoji=row["emoji"],
            price_usd=row["price_usd"], description=row["description"],
            sort_order=row["sort_order"], active=bool(row["active"]),
        )


@dataclass
class LedgerEntry:
    id: int
    user_id: int
    kind: str
    drink_id: str | None
    amount_sats: int
    amount_usd: float
    balance_after_sats: int | None
    timestamp: int
    meta: dict


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- users ---------------------------------------------------------------

    def create_user(
        self,
        *,
        name: str,
        lnbits_wallet_id: str,
        lnbits_admin_key: str,
        lnbits_invoice_key: str,
        nfc_uid: str | None = None,
        slack_user_id: str | None = None,
    ) -> User:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (name, nfc_uid, lnbits_wallet_id,
                    lnbits_admin_key, lnbits_invoice_key, slack_user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, nfc_uid, lnbits_wallet_id, lnbits_admin_key,
                 lnbits_invoice_key, slack_user_id, int(time.time())),
            )
            user_id = cur.lastrowid
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return User.from_row(row)

    def get_user(self, user_id: int) -> User | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return User.from_row(row) if row else None

    def get_user_by_nfc(self, nfc_uid: str) -> User | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE nfc_uid = ?", (nfc_uid,)).fetchone()
            return User.from_row(row) if row else None

    def get_user_by_slack(self, slack_user_id: str) -> User | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE slack_user_id = ?", (slack_user_id,)
            ).fetchone()
            return User.from_row(row) if row else None

    def assign_nfc(self, user_id: int, nfc_uid: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE users SET nfc_uid = ? WHERE id = ?", (nfc_uid, user_id))

    def list_users(self) -> list[User]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
            return [User.from_row(r) for r in rows]

    # -- ledger --------------------------------------------------------------

    def record(
        self,
        *,
        user_id: int,
        kind: str,
        amount_sats: int,
        amount_usd: float,
        drink_id: str | None = None,
        balance_after_sats: int | None = None,
        meta: dict | None = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO ledger (user_id, kind, drink_id, amount_sats, amount_usd,
                    balance_after_sats, timestamp, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, kind, drink_id, amount_sats, amount_usd,
                 balance_after_sats, int(time.time()),
                 json.dumps(meta) if meta else None),
            )
            return cur.lastrowid

    def recent_for_user(self, user_id: int, limit: int = 20) -> list[LedgerEntry]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ledger WHERE user_id = ? "
                "ORDER BY timestamp DESC, id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [_to_entry(r) for r in rows]

    def recent_global(self, limit: int = 50) -> list[tuple[LedgerEntry, str]]:
        """Return recent entries paired with the user's name."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT l.*, u.name AS user_name FROM ledger l
                JOIN users u ON u.id = l.user_id
                ORDER BY l.timestamp DESC, l.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [(_to_entry(r), r["user_name"]) for r in rows]

    # -- drinks --------------------------------------------------------------

    def list_drinks(self, *, active_only: bool = True) -> list[Drink]:
        sql = ("SELECT * FROM drinks "
               + ("WHERE active = 1 " if active_only else "")
               + "ORDER BY sort_order, name")
        with self.connect() as conn:
            rows = conn.execute(sql).fetchall()
            return [Drink.from_row(r) for r in rows]

    def get_drink(self, drink_id: str) -> Drink | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM drinks WHERE id = ?", (drink_id,)
            ).fetchone()
            return Drink.from_row(row) if row else None

    def create_drink(self, drink: Drink) -> Drink:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO drinks (id, name, emoji, price_usd, description,
                    sort_order, active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (drink.id, drink.name, drink.emoji, drink.price_usd,
                 drink.description, drink.sort_order, int(drink.active)),
            )
        return drink

    def update_drink(self, drink_id: str, *, name: str, emoji: str,
                      price_usd: float, description: str,
                      sort_order: int, active: bool) -> Drink | None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE drinks
                   SET name = ?, emoji = ?, price_usd = ?, description = ?,
                       sort_order = ?, active = ?
                 WHERE id = ?
                """,
                (name, emoji, price_usd, description, sort_order,
                 int(active), drink_id),
            )
        return self.get_drink(drink_id)

    def soft_delete_drink(self, drink_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE drinks SET active = 0 WHERE id = ?", (drink_id,))

    def count_drinks(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM drinks").fetchone()
            return int(row["n"])

    def seed_drinks(self, drinks: list[Drink]) -> None:
        """Bulk-insert. Used on first boot when the drinks table is empty."""
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO drinks (id, name, emoji, price_usd,
                    description, sort_order, active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [(d.id, d.name, d.emoji, d.price_usd, d.description,
                  d.sort_order, int(d.active)) for d in drinks],
            )

    # -- analytics -----------------------------------------------------------

    def leaderboard(self, since_ts: int) -> list[tuple[str, int, int]]:
        """Top spenders since `since_ts`. Returns (name, drinks, sats_spent)."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT u.name, COUNT(*) AS drinks, SUM(l.amount_sats) AS sats
                FROM ledger l JOIN users u ON u.id = l.user_id
                WHERE l.kind = 'purchase' AND l.timestamp >= ?
                GROUP BY u.id ORDER BY sats DESC
                """,
                (since_ts,),
            ).fetchall()
            return [(r["name"], r["drinks"], r["sats"]) for r in rows]


def _to_entry(row: sqlite3.Row) -> LedgerEntry:
    return LedgerEntry(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        drink_id=row["drink_id"],
        amount_sats=row["amount_sats"],
        amount_usd=row["amount_usd"],
        balance_after_sats=row["balance_after_sats"],
        timestamp=row["timestamp"],
        meta=json.loads(row["meta"]) if row["meta"] else {},
    )
