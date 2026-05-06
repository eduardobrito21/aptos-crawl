"""Tests for `db/runs.py` auto-disable logic (ADR-005 §2)."""

import pytest

from aptos_sp.db import runs
from aptos_sp.db.conn import connect


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def _seed(db, *, source: str, status: str) -> int:
    """Insert one fully-finished run with the given status."""
    run_id = runs.start(db, source=source)
    runs.finish(db, run_id, status=status)  # type: ignore[arg-type]
    return run_id


def test_is_disabled_returns_false_with_no_history(db):
    assert runs.is_disabled(db, "quintoandar") is False


def test_is_disabled_false_with_recent_success(db):
    _seed(db, source="quintoandar", status="success")
    assert runs.is_disabled(db, "quintoandar") is False


def test_is_disabled_false_with_two_failures(db):
    _seed(db, source="quintoandar", status="failed")
    _seed(db, source="quintoandar", status="failed")
    assert runs.is_disabled(db, "quintoandar") is False


def test_is_disabled_true_after_three_consecutive_failures(db):
    """ADR-005 §2 trigger: three failed runs in a row."""
    _seed(db, source="quintoandar", status="failed")
    _seed(db, source="quintoandar", status="failed")
    _seed(db, source="quintoandar", status="failed")
    assert runs.is_disabled(db, "quintoandar") is True


def test_is_disabled_resets_after_success(db):
    """A success between failures resets the streak — only the most
    recent N runs matter."""
    _seed(db, source="quintoandar", status="failed")
    _seed(db, source="quintoandar", status="failed")
    _seed(db, source="quintoandar", status="success")
    _seed(db, source="quintoandar", status="failed")
    _seed(db, source="quintoandar", status="failed")
    assert runs.is_disabled(db, "quintoandar") is False


def test_is_disabled_true_when_last_row_is_disabled(db):
    """Once a `disabled` row is written, stay disabled until the
    operator clears it manually."""
    _seed(db, source="quintoandar", status="disabled")
    assert runs.is_disabled(db, "quintoandar") is True


def test_is_disabled_scoped_per_source(db):
    """One source's failures don't disable another."""
    _seed(db, source="quintoandar", status="failed")
    _seed(db, source="quintoandar", status="failed")
    _seed(db, source="quintoandar", status="failed")
    assert runs.is_disabled(db, "quintoandar") is True
    assert runs.is_disabled(db, "zap") is False


def test_is_disabled_ignores_in_progress_runs(db):
    """A run started but not finished (status=NULL) shouldn't count
    toward the failure streak. With three real failures plus an
    in-progress row mixed in, the disable still trips correctly."""
    _seed(db, source="quintoandar", status="failed")
    _seed(db, source="quintoandar", status="failed")
    runs.start(db, source="quintoandar")  # in-progress, no finish
    _seed(db, source="quintoandar", status="failed")
    assert runs.is_disabled(db, "quintoandar") is True


def test_is_disabled_only_counts_recent_runs(db, tmp_path):
    """In a fresh DB with only an in-progress row, no disable."""
    fresh = connect(tmp_path / "fresh.db")
    runs.start(fresh, source="quintoandar")
    assert runs.is_disabled(fresh, "quintoandar") is False
    fresh.close()
