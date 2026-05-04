"""Tests for `pipeline/dedup.py` — fingerprint + 3-tier classifier."""

import sqlite3
from datetime import UTC, date, datetime

import pytest

from aptos_sp.db.conn import connect
from aptos_sp.pipeline.dedup import find_and_flag_dups
from aptos_sp.pipeline.normalize import normalize_endereco


@pytest.fixture
def db(tmp_path):
    """Fresh schema per test, so dedup state never leaks between cases."""
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def _insert(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_id: str,
    bairro: str,
    endereco: str,
    area: float,
    quartos: int,
    vagas: int,
    total: float | None = None,
) -> int:
    """Insert one row + one price snapshot, return aptos.id. Mirrors
    persist.py's shape but with only the columns dedup needs."""
    now = datetime.now(UTC)
    cur = conn.execute(
        """
        INSERT INTO aptos (
            source, source_id, url, bairro, endereco,
            endereco_normalized,
            area_m2, quartos, vagas,
            scraped_at, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source,
            source_id,
            f"https://example.com/{source_id}",
            bairro,
            endereco,
            normalize_endereco(endereco),
            area,
            quartos,
            vagas,
            now,
            now,
        ),
    )
    apto_id = int(cur.lastrowid or 0)
    if total is not None:
        conn.execute(
            """
            INSERT INTO precos_historico
                (apto_id, snapshot_date, aluguel, total)
            VALUES (?, ?, ?, ?)
            """,
            (apto_id, date.today(), total, total),
        )
    conn.commit()
    return apto_id


def _possible_dup_of(conn: sqlite3.Connection, apto_id: int) -> int | None:
    row = conn.execute("SELECT possible_dup_of FROM aptos WHERE id = ?", (apto_id,)).fetchone()
    return row["possible_dup_of"]


def test_strong_match_same_address_area_quartos_vagas(db):
    a = _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Pinheiros",
        endereco="Rua dos Pinheiros, 500",
        area=78,
        quartos=2,
        vagas=1,
        total=8000,
    )
    b = _insert(
        db,
        source="quintoandar",
        source_id="B",
        bairro="Pinheiros",
        endereco="R. dos Pinheiros 500",
        area=78.5,
        quartos=2,
        vagas=1,
        total=8200,
    )
    stats = find_and_flag_dups(db)
    assert stats.n_strong == 1
    assert _possible_dup_of(db, b) == a
    # Anchor stays clean.
    assert _possible_dup_of(db, a) is None


def test_weak_match_price_differs_significantly(db):
    a = _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Itaim Bibi",
        endereco="Rua Iguatemi, 100",
        area=80,
        quartos=2,
        vagas=1,
        total=10000,
    )
    b = _insert(
        db,
        source="quintoandar",
        source_id="B",
        bairro="Itaim Bibi",
        endereco="R. Iguatemi 100",
        area=83,
        quartos=2,
        vagas=2,
        total=12000,
    )
    stats = find_and_flag_dups(db)
    # Same street + bedrooms, area within ±5m², price 20% apart.
    # Different vagas blocks the strong match → weak.
    assert stats.n_weak == 1
    assert _possible_dup_of(db, b) == a


def test_no_match_when_address_differs(db):
    _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Moema",
        endereco="Rua Tuim, 100",
        area=80,
        quartos=2,
        vagas=1,
        total=8000,
    )
    b = _insert(
        db,
        source="zap",
        source_id="B",
        bairro="Moema",
        endereco="Rua Inhambu, 200",
        area=80,
        quartos=2,
        vagas=1,
        total=8000,
    )
    stats = find_and_flag_dups(db)
    assert stats.n_strong == 0
    assert stats.n_weak == 0
    assert _possible_dup_of(db, b) is None


def test_no_cross_bairro_match(db):
    """Same apartment can't be in two neighborhoods; never match across."""
    _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Pinheiros",
        endereco="Rua Comum, 100",
        area=80,
        quartos=2,
        vagas=1,
        total=8000,
    )
    b = _insert(
        db,
        source="zap",
        source_id="B",
        bairro="Itaim Bibi",
        endereco="Rua Comum, 100",
        area=80,
        quartos=2,
        vagas=1,
        total=8000,
    )
    find_and_flag_dups(db)
    assert _possible_dup_of(db, b) is None


def test_strong_match_within_1m2_tolerance(db):
    a = _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Vila Olímpia",
        endereco="Rua Funchal, 50",
        area=80.0,
        quartos=2,
        vagas=1,
        total=9000,
    )
    b = _insert(
        db,
        source="zap",
        source_id="B",
        bairro="Vila Olímpia",
        endereco="Rua Funchal, 50",
        area=80.9,
        quartos=2,
        vagas=1,
        total=9000,
    )
    find_and_flag_dups(db)
    assert _possible_dup_of(db, b) == a


def test_no_match_when_area_diverges_too_much(db):
    _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Vila Olímpia",
        endereco="Rua Funchal, 50",
        area=80,
        quartos=2,
        vagas=1,
        total=9000,
    )
    b = _insert(
        db,
        source="zap",
        source_id="B",
        bairro="Vila Olímpia",
        endereco="Rua Funchal, 50",
        area=120,
        quartos=2,
        vagas=1,
        total=12000,
    )
    find_and_flag_dups(db)
    # 40m² apart, beyond both tolerances. Likely a different unit at the
    # same address.
    assert _possible_dup_of(db, b) is None


def test_idempotent_rerun_does_not_double_flag(db):
    a = _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Moema",
        endereco="Rua Tuim, 50",
        area=80,
        quartos=2,
        vagas=1,
        total=8000,
    )
    b = _insert(
        db,
        source="quintoandar",
        source_id="B",
        bairro="Moema",
        endereco="R. Tuim 50",
        area=80,
        quartos=2,
        vagas=1,
        total=8000,
    )
    find_and_flag_dups(db)
    stats2 = find_and_flag_dups(db)
    # Second run sees the existing flag and re-applies it without
    # incrementing strong (the row's flag was already correct).
    assert _possible_dup_of(db, b) == a
    assert stats2.n_strong == 0
    assert stats2.n_cleared == 0


def test_street_number_guard_blocks_same_street_different_buildings(db):
    """ADR-006's address fingerprint drops street numbers. When both
    listings expose a number, require it to match — otherwise two
    different buildings on the same street collapse into one
    fingerprint. Realistic case: zap+zap pairs at "Cristiano Viana"
    where unit specs happen to align."""
    _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Pinheiros",
        endereco="Rua Cristiano Viana, 216",
        area=78,
        quartos=2,
        vagas=1,
        total=8000,
    )
    b = _insert(
        db,
        source="zap",
        source_id="B",
        bairro="Pinheiros",
        endereco="Rua Cristiano Viana, 540",
        area=78,
        quartos=2,
        vagas=1,
        total=8000,
    )
    find_and_flag_dups(db)
    assert _possible_dup_of(db, b) is None


def test_street_number_guard_allows_match_when_one_side_hides_number(db):
    """The cross-platform case ADR-006 designed for: ZAP includes the
    number, QA only has the street name. We can't distinguish, so trust
    the address fingerprint."""
    a = _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Pinheiros",
        endereco="Rua Cristiano Viana, 216",
        area=78,
        quartos=2,
        vagas=1,
        total=8000,
    )
    b = _insert(
        db,
        source="quintoandar",
        source_id="B",
        bairro="Pinheiros",
        endereco="Rua Cristiano Viana",
        area=78,
        quartos=2,
        vagas=1,
        total=8200,
    )
    find_and_flag_dups(db)
    assert _possible_dup_of(db, b) == a


def test_clears_stale_flag_when_anchor_no_longer_matches(db):
    a = _insert(
        db,
        source="zap",
        source_id="A",
        bairro="Moema",
        endereco="Rua Tuim, 50",
        area=80,
        quartos=2,
        vagas=1,
        total=8000,
    )
    b = _insert(
        db,
        source="quintoandar",
        source_id="B",
        bairro="Moema",
        endereco="R. Tuim 50",
        area=80,
        quartos=2,
        vagas=1,
        total=8000,
    )
    find_and_flag_dups(db)
    assert _possible_dup_of(db, b) == a
    # Mutate the anchor so it no longer matches; rerun should clear.
    db.execute("UPDATE aptos SET area_m2 = ? WHERE id = ?", (140.0, a))
    db.commit()
    stats = find_and_flag_dups(db)
    assert _possible_dup_of(db, b) is None
    assert stats.n_cleared == 1
