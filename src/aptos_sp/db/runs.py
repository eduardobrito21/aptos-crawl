"""Per-run audit log helpers (`runs` table).

Used by every CLI entry point: insert a row at start with the source
name and `started_at`; update the same row on finish with status,
counts, and timing. Auto-disable (ADR-005) reads from this table.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Literal

RunStatus = Literal["success", "failed", "partial", "disabled"]


def start(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute(
        "INSERT INTO runs (source, started_at) VALUES (?, ?)",
        (source, datetime.now(UTC)),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


def finish(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: RunStatus,
    n_listings: int = 0,
    n_new: int = 0,
    n_updated: int = 0,
    n_errors: int = 0,
    error_summary: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE runs SET
            finished_at = ?,
            status = ?,
            n_listings = ?,
            n_new = ?,
            n_updated = ?,
            n_errors = ?,
            error_summary = ?
        WHERE id = ?
        """,
        (
            datetime.now(UTC),
            status,
            n_listings,
            n_new,
            n_updated,
            n_errors,
            error_summary,
            run_id,
        ),
    )
    conn.commit()
