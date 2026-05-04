"""Persistence tests: upsert idempotency + price snapshot behavior.

Uses a fresh sqlite file per test against the canonical
`db/schema.sql`. No mocking — the schema is the contract.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from aptos_sp.db import conn as db_conn
from aptos_sp.pipeline.persist import upsert_listings
from aptos_sp.scrapers.base import ListingStub


@pytest.fixture
def conn(tmp_path: Path):
    c = db_conn.connect(tmp_path / "test.db")
    yield c
    c.close()


def _stub(source_id: str = "abc-1", **overrides: Any) -> ListingStub:
    fields: dict[str, Any] = {
        "source": "zap",
        "source_id": source_id,
        "url": f"https://www.zapimoveis.com.br/imovel/{source_id}/",
        "bairro": "Pinheiros",
        "endereco": "Rua dos Pinheiros, 500",
        "area_m2": 78.0,
        "quartos": 2,
        "banheiros": 2,
        "vagas": 1,
        "aluguel": 7800.0,
        "condominio": 1200.0,
        "iptu": 300.0,
        "total": 9300.0,
    }
    fields.update(overrides)
    return ListingStub(**fields)


def test_first_run_inserts(conn):
    stats = upsert_listings(conn, [_stub("a"), _stub("b")])
    assert stats.n_listings == 2
    assert stats.n_new == 2
    assert stats.n_updated == 0
    assert stats.n_skipped == 0
    assert _count(conn, "aptos") == 2


def test_in_memory_dedup_by_source_id(conn):
    """ZAP returns featured listings on multiple pages — same source_id
    appears twice in one batch. We keep the first, skip the rest."""
    stats = upsert_listings(conn, [_stub("a"), _stub("a"), _stub("b")])
    assert stats.n_listings == 2
    assert stats.n_new == 2
    assert stats.n_skipped == 1
    assert _count(conn, "aptos") == 2


def test_distinct_source_ids_with_same_url_both_persist(conn):
    """URL is no longer UNIQUE — the same URL can legitimately appear
    under different source_ids (ZAP republishes listings). Identity is
    `(source, source_id)`."""
    stats = upsert_listings(
        conn,
        [
            _stub("a", url="https://www.zapimoveis.com.br/imovel/shared/"),
            _stub("b", url="https://www.zapimoveis.com.br/imovel/shared/"),
        ],
    )
    assert stats.n_new == 2
    assert stats.n_skipped == 0
    assert _count(conn, "aptos") == 2


def test_rerun_does_not_duplicate(conn):
    upsert_listings(conn, [_stub("a")])
    stats = upsert_listings(conn, [_stub("a")])
    assert stats.n_new == 0
    assert stats.n_updated == 1
    assert _count(conn, "aptos") == 1


def test_price_snapshot_recorded_once_per_day(conn):
    today = date.today()
    upsert_listings(conn, [_stub("a", aluguel=7800.0)], snapshot_day=today)
    upsert_listings(conn, [_stub("a", aluguel=7800.0)], snapshot_day=today)
    rows = list(conn.execute("SELECT total, is_change FROM precos_historico"))
    assert len(rows) == 1
    assert rows[0]["total"] == 9300.0
    assert rows[0]["is_change"] == 0


def test_price_change_flagged_across_days(conn):
    yesterday = date.today() - timedelta(days=1)
    today = date.today()
    upsert_listings(conn, [_stub("a", aluguel=7800.0, total=9300.0)], snapshot_day=yesterday)
    upsert_listings(conn, [_stub("a", aluguel=8200.0, total=9700.0)], snapshot_day=today)
    rows = list(
        conn.execute(
            "SELECT snapshot_date, total, is_change FROM precos_historico ORDER BY snapshot_date"
        )
    )
    assert [r["is_change"] for r in rows] == [0, 1]
    assert rows[1]["total"] == 9700.0


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
