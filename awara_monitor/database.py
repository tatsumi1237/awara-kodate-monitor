"""SQLite 永続化層.

物件情報はすべて公開情報。秘密情報（Discord Webhook など）は保存しない。
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
from typing import Any, Iterable, Optional

from .models import now_iso

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    internal_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_type            TEXT NOT NULL,              -- sale | rent
    property_type        TEXT,                       -- 一戸建て
    address              TEXT,
    address_norm         TEXT,
    town                 TEXT,
    layout               TEXT,
    land_area            REAL,
    building_area        REAL,
    built_year           INTEGER,
    station_name         TEXT,
    station_distance_m   INTEGER,
    station_walk_minutes INTEGER,
    distance_method      TEXT,
    distance_confidence  TEXT,                       -- ok | uncertain | out
    distance_note        TEXT,
    sites                TEXT,                       -- JSON: ["suumo", "awara"]
    urls                 TEXT,                       -- JSON: {"suumo": "http..."}
    first_seen_at        TEXT,
    last_seen_at         TEXT,
    previous_price       INTEGER,
    current_price        INTEGER,
    status               TEXT DEFAULT 'active',      -- active | delisted
    dedup_info           TEXT,                       -- JSON
    created_at           TEXT,
    updated_at           TEXT
);

CREATE TABLE IF NOT EXISTS listings (
    listing_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    internal_id      INTEGER REFERENCES properties(internal_id),
    source           TEXT NOT NULL,
    site_property_id TEXT NOT NULL,
    url              TEXT,
    deal_type        TEXT,
    price            INTEGER,
    raw_json         TEXT,
    first_seen_at    TEXT,
    last_seen_at     TEXT,
    status           TEXT DEFAULT 'active',
    UNIQUE(source, site_property_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    internal_id INTEGER,
    listing_id  INTEGER,
    source      TEXT,
    old_price   INTEGER,
    new_price   INTEGER,
    direction   TEXT,                                -- down | up
    changed_at  TEXT
);

CREATE TABLE IF NOT EXISTS dedup_candidates (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    internal_id_a  INTEGER,
    internal_id_b  INTEGER,
    score          REAL,
    reason         TEXT,
    created_at     TEXT,
    UNIQUE(internal_id_a, internal_id_b)
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    address    TEXT PRIMARY KEY,
    lat        REAL,
    lon        REAL,
    hit        INTEGER,                              -- 1: 取得成功 / 0: 失敗
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT,                                 -- new | price_change | error
    dedup_key  TEXT,
    sent_at    TEXT,
    UNIQUE(kind, dedup_key)
);

CREATE TABLE IF NOT EXISTS run_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT,
    finished_at  TEXT,
    summary_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_listings_internal ON listings(internal_id);
CREATE INDEX IF NOT EXISTS idx_properties_status ON properties(status, deal_type);
CREATE INDEX IF NOT EXISTS idx_price_history_internal ON price_history(internal_id);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    # -- lifecycle ---------------------------------------------------------
    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def commit(self) -> None:
        self.conn.commit()

    # -- geocode cache ---------------------------------------------------------
    def get_geocode(self, address: str) -> Optional[tuple[float, float]] | None:
        """(lat, lon) / None(=キャッシュ済みだが未取得) / 未キャッシュなら sentinel。

        戻り値の区別:
          - tuple            : 座標あり
          - None             : キャッシュにヒットしたが座標なし
          - 未キャッシュ時は KeyError ではなく、呼び出し側は
            ``get_geocode() is _MISSING`` で判定できるよう別APIにする。
        """
        row = self.conn.execute(
            "SELECT lat, lon, hit FROM geocode_cache WHERE address = ?", (address,)
        ).fetchone()
        if row is None:
            return _MISSING
        if row["hit"] and row["lat"] is not None:
            return (row["lat"], row["lon"])
        return None

    def put_geocode(self, address: str, result: Optional[tuple[float, float]]) -> None:
        if result:
            lat, lon, hit = result[0], result[1], 1
        else:
            lat, lon, hit = None, None, 0
        self.conn.execute(
            "INSERT OR REPLACE INTO geocode_cache(address, lat, lon, hit, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (address, lat, lon, hit, now_iso()),
        )
        self.conn.commit()

    # -- listings ---------------------------------------------------------
    def find_listing(self, source: str, site_property_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM listings WHERE source = ? AND site_property_id = ?",
            (source, site_property_id),
        ).fetchone()

    def all_listing_keys(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT source, site_property_id FROM listings WHERE status = 'active'"
        ).fetchall()
        return {f"{r['source']}:{r['site_property_id']}" for r in rows}

    def insert_listing(
        self,
        *,
        internal_id: int,
        source: str,
        site_property_id: str,
        url: str,
        deal_type: str,
        price: Optional[int],
        raw_json: str,
    ) -> int:
        ts = now_iso()
        cur = self.conn.execute(
            "INSERT INTO listings(internal_id, source, site_property_id, url, deal_type, "
            "price, raw_json, first_seen_at, last_seen_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')",
            (internal_id, source, site_property_id, url, deal_type, price, raw_json, ts, ts),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_listing_seen(
        self, listing_id: int, price: Optional[int], raw_json: str
    ) -> None:
        self.conn.execute(
            "UPDATE listings SET price = ?, raw_json = ?, last_seen_at = ?, status = 'active' "
            "WHERE listing_id = ?",
            (price, raw_json, now_iso(), listing_id),
        )
        self.conn.commit()

    def listings_for_property(self, internal_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM listings WHERE internal_id = ? ORDER BY source", (internal_id,)
        ).fetchall()

    def mark_missing_listings_delisted(self, ok_sources: Iterable[str], seen_keys: set[str]) -> list[int]:
        """今回取得できたサイトについて、今回見つからなかった掲載を delisted にする。

        返り値: delisted になった listing の internal_id リスト。
        """
        ok_sources = tuple(ok_sources)
        if not ok_sources:
            return []
        placeholder = ",".join("?" * len(ok_sources))
        rows = self.conn.execute(
            f"SELECT * FROM listings WHERE status = 'active' AND source IN ({placeholder})",
            ok_sources,
        ).fetchall()
        affected: list[int] = []
        for row in rows:
            key = f"{row['source']}:{row['site_property_id']}"
            if key not in seen_keys:
                self.conn.execute(
                    "UPDATE listings SET status = 'delisted', last_seen_at = last_seen_at "
                    "WHERE listing_id = ?",
                    (row["listing_id"],),
                )
                affected.append(row["internal_id"])
        self.conn.commit()
        return affected

    def refresh_property_status(self, internal_id: int) -> str:
        """紐づく listing が全部 delisted なら property も delisted（履歴は残す）。"""
        rows = self.conn.execute(
            "SELECT status FROM listings WHERE internal_id = ?", (internal_id,)
        ).fetchall()
        if rows and all(r["status"] == "delisted" for r in rows):
            new_status = "delisted"
        else:
            new_status = "active"
        self.conn.execute(
            "UPDATE properties SET status = ?, updated_at = ? WHERE internal_id = ?",
            (new_status, now_iso(), internal_id),
        )
        self.conn.commit()
        return new_status

    # -- properties ---------------------------------------------------------
    def active_properties(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM properties WHERE status = 'active'"
        ).fetchall()

    def get_property(self, internal_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM properties WHERE internal_id = ?", (internal_id,)
        ).fetchone()

    def insert_property(self, data: dict[str, Any]) -> int:
        ts = now_iso()
        data = dict(data)
        data.setdefault("first_seen_at", ts)
        data.setdefault("last_seen_at", ts)
        data["created_at"] = ts
        data["updated_at"] = ts
        data.setdefault("status", "active")
        cols = list(data.keys())
        cur = self.conn.execute(
            f"INSERT INTO properties({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [data[c] for c in cols],
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_property(self, internal_id: int, data: dict[str, Any]) -> None:
        if not data:
            return
        data = dict(data)
        data["updated_at"] = now_iso()
        sets = ",".join(f"{k} = ?" for k in data)
        self.conn.execute(
            f"UPDATE properties SET {sets} WHERE internal_id = ?",
            [*data.values(), internal_id],
        )
        self.conn.commit()

    def set_property_price(self, internal_id: int, old_price: Optional[int], new_price: Optional[int]) -> None:
        self.conn.execute(
            "UPDATE properties SET previous_price = ?, current_price = ?, updated_at = ? "
            "WHERE internal_id = ?",
            (old_price, new_price, now_iso(), internal_id),
        )
        self.conn.commit()

    # -- price history ---------------------------------------------------------
    def insert_price_history(
        self,
        *,
        internal_id: int,
        listing_id: Optional[int],
        source: str,
        old_price: Optional[int],
        new_price: Optional[int],
    ) -> None:
        direction = ""
        if old_price is not None and new_price is not None:
            direction = "down" if new_price < old_price else "up"
        self.conn.execute(
            "INSERT INTO price_history(internal_id, listing_id, source, old_price, new_price, "
            "direction, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (internal_id, listing_id, source, old_price, new_price, direction, now_iso()),
        )
        self.conn.commit()

    def price_history_for(self, internal_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM price_history WHERE internal_id = ? ORDER BY changed_at", (internal_id,)
        ).fetchall()

    # -- dedup candidates ---------------------------------------------------------
    def insert_dedup_candidate(
        self, internal_id_a: int, internal_id_b: int, score: float, reason: str
    ) -> None:
        a, b = sorted((internal_id_a, internal_id_b))
        self.conn.execute(
            "INSERT OR IGNORE INTO dedup_candidates(internal_id_a, internal_id_b, score, reason, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (a, b, score, reason, now_iso()),
        )
        self.conn.commit()

    # -- notifications ---------------------------------------------------------
    def was_notified(self, kind: str, dedup_key: str) -> bool:
        row = self.conn.execute(
            "SELECT sent_at FROM notifications WHERE kind = ? AND dedup_key = ?",
            (kind, dedup_key),
        ).fetchone()
        return row is not None

    def record_notification(self, kind: str, dedup_key: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO notifications(kind, dedup_key, sent_at) VALUES (?, ?, ?)",
            (kind, dedup_key, now_iso()),
        )
        self.conn.commit()

    def should_send_error(self, source: str, cooldown_hours: int) -> bool:
        row = self.conn.execute(
            "SELECT sent_at FROM notifications WHERE kind = 'error' AND dedup_key = ?",
            (source,),
        ).fetchone()
        if row is None:
            return True
        try:
            last = datetime.datetime.fromisoformat(row["sent_at"])
        except ValueError:
            return True
        now = datetime.datetime.now(last.tzinfo) if last.tzinfo else datetime.datetime.now()
        return (now - last) >= datetime.timedelta(hours=cooldown_hours)

    # -- run log ---------------------------------------------------------
    def write_run_log(self, started_at: str, summary: dict) -> None:
        self.conn.execute(
            "INSERT INTO run_log(started_at, finished_at, summary_json) VALUES (?, ?, ?)",
            (started_at, now_iso(), json.dumps(summary, ensure_ascii=False)),
        )
        self.conn.commit()

    # -- misc ---------------------------------------------------------
    def stats(self) -> dict[str, int]:
        def one(q: str) -> int:
            return int(self.conn.execute(q).fetchone()[0])

        return {
            "properties_total": one("SELECT COUNT(*) FROM properties"),
            "properties_active": one("SELECT COUNT(*) FROM properties WHERE status='active'"),
            "listings_total": one("SELECT COUNT(*) FROM listings"),
            "listings_active": one("SELECT COUNT(*) FROM listings WHERE status='active'"),
            "price_changes": one("SELECT COUNT(*) FROM price_history"),
            "dedup_candidates": one("SELECT COUNT(*) FROM dedup_candidates"),
        }


class _Missing:
    def __repr__(self) -> str:  # pragma: no cover
        return "<MISSING>"


_MISSING = _Missing()
