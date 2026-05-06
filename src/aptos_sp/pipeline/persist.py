"""Persist scraped listings + price snapshots to SQLite.

Idempotency comes from the schema: `aptos.UNIQUE(source, source_id)`
makes upserts trivial via `INSERT … ON CONFLICT DO UPDATE`. Price
history (ADR-004) writes one row per `(apto_id, snapshot_date)` and is
no-op'd on the second run of the same day.

Returns a `PersistStats` so the CLI can update the `runs` row with
counts.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime

from aptos_sp.scrapers.base import ListingStub


@dataclass
class PersistStats:
    n_listings: int = 0
    n_new: int = 0
    n_updated: int = 0
    n_skipped: int = 0


def upsert_listings(
    conn: sqlite3.Connection,
    listings: list[ListingStub],
    snapshot_day: date | None = None,
) -> PersistStats:
    """Upsert each listing; record today's price snapshot.

    Dedup happens in two layers:

    - In-memory: ZAP returns the same `(source, source_id)` on multiple
      pages (featured listings, sponsored). Keep only the first
      occurrence per batch — the data is identical anyway.
    - Schema: `aptos.UNIQUE(url)` catches the rarer case where two
      distinct `source_id`s point at the same URL (ZAP republishes a
      listing under a new id). On that, `n_skipped++` and continue —
      crashing the whole run on one anomaly is the wrong tradeoff.

    `last_seen` always advances. `scraped_at` is set on insert and left
    alone on update (it's the original first-seen timestamp).
    """
    snapshot_day = snapshot_day or date.today()
    stats = PersistStats()
    now = datetime.now(UTC)

    seen: set[tuple[str, str]] = set()
    for stub in listings:
        key = (stub.source, stub.source_id)
        if key in seen:
            stats.n_skipped += 1
            continue
        seen.add(key)

        before = _existing_id(conn, stub.source, stub.source_id)
        try:
            apto_id = _upsert_one(conn, stub, now, before)
        except sqlite3.IntegrityError:
            # URL collision across distinct source_ids — schema-level
            # safety net (see docstring). Skip and continue.
            stats.n_skipped += 1
            continue

        stats.n_listings += 1
        if before is None:
            stats.n_new += 1
        else:
            stats.n_updated += 1
        _record_snapshot(conn, apto_id, snapshot_day, stub)

    conn.commit()
    return stats


def _upsert_one(
    conn: sqlite3.Connection,
    stub: ListingStub,
    now: datetime,
    before: int | None,
) -> int:
    """Run the parameterized upsert. Returns the row's `aptos.id`."""
    amenities_json = json.dumps(stub.amenities, ensure_ascii=False) if stub.amenities else None
    cur = conn.execute(
        """
        INSERT INTO aptos (
            source, source_id, url, bairro, endereco,
            area_m2, quartos, suites, banheiros, vagas,
            descricao, amenities, mobiliado,
            scraped_at, last_seen, raw_html_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            url = excluded.url,
            bairro = excluded.bairro,
            endereco = COALESCE(excluded.endereco, aptos.endereco),
            area_m2 = COALESCE(excluded.area_m2, aptos.area_m2),
            quartos = COALESCE(excluded.quartos, aptos.quartos),
            suites = COALESCE(excluded.suites, aptos.suites),
            banheiros = COALESCE(excluded.banheiros, aptos.banheiros),
            vagas = COALESCE(excluded.vagas, aptos.vagas),
            descricao = COALESCE(excluded.descricao, aptos.descricao),
            amenities = COALESCE(excluded.amenities, aptos.amenities),
            mobiliado = COALESCE(excluded.mobiliado, aptos.mobiliado),
            last_seen = excluded.last_seen,
            raw_html_hash = excluded.raw_html_hash
        """,
        (
            stub.source,
            stub.source_id,
            stub.url,
            stub.bairro,
            stub.endereco,
            stub.area_m2,
            stub.quartos,
            stub.suites,
            stub.banheiros,
            stub.vagas,
            stub.descricao,
            amenities_json,
            stub.is_furnished,
            stub.scraped_at,
            now,
            stub.raw_html_hash,
        ),
    )
    if before is None:
        assert cur.lastrowid is not None
        return int(cur.lastrowid)
    return before


def _existing_id(conn: sqlite3.Connection, source: str, source_id: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM aptos WHERE source = ? AND source_id = ?",
        (source, source_id),
    ).fetchone()
    return row["id"] if row else None


def _record_snapshot(
    conn: sqlite3.Connection,
    apto_id: int,
    snapshot_day: date,
    stub: ListingStub,
) -> None:
    """Insert a price row for today; mark `is_change` if the most recent
    prior snapshot's `total` differs."""
    if stub.aluguel is None and stub.condominio is None and stub.iptu is None:
        return
    prior = conn.execute(
        """
        SELECT total FROM precos_historico
        WHERE apto_id = ? AND snapshot_date < ?
        ORDER BY snapshot_date DESC LIMIT 1
        """,
        (apto_id, snapshot_day),
    ).fetchone()
    is_change = bool(prior and prior["total"] != stub.total)
    conn.execute(
        """
        INSERT INTO precos_historico
            (apto_id, snapshot_date, aluguel, condominio, iptu, total, is_change)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(apto_id, snapshot_date) DO UPDATE SET
            aluguel = excluded.aluguel,
            condominio = excluded.condominio,
            iptu = excluded.iptu,
            total = excluded.total
        """,
        (
            apto_id,
            snapshot_day,
            stub.aluguel,
            stub.condominio,
            stub.iptu,
            stub.total,
            is_change,
        ),
    )
