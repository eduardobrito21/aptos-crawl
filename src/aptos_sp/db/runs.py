"""Per-run audit log helpers (`runs` table).

Used by every CLI entry point: insert a row at start with the source
name and `started_at`; update the same row on finish with status,
counts, and timing. Auto-disable (ADR-005) reads from this table.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Literal

RunStatus = Literal["success", "failed", "partial", "disabled"]

# ADR-005 §2: a source auto-disables after this many consecutive failed
# runs. Operator clears the disable by editing the `runs` table or
# (future) running with `--reset-source-disable`.
AUTO_DISABLE_THRESHOLD = 3


def start(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute(
        "INSERT INTO runs (source, started_at) VALUES (?, ?)",
        (source, datetime.now(UTC)),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


def is_disabled(conn: sqlite3.Connection, source: str) -> bool:
    """ADR-005 §2: a source is auto-disabled after `AUTO_DISABLE_THRESHOLD`
    consecutive failed runs. Returns True when the *most recent* run
    for that source has `status='disabled'`, OR when the last
    `AUTO_DISABLE_THRESHOLD` finished runs were all `failed`.

    The first form prevents repeated retries once a disable has been
    written; the second form is the trigger for writing the next
    `disabled` row at start of run.
    """
    last_finished = conn.execute(
        """
        SELECT status FROM runs
        WHERE source = ? AND status IS NOT NULL
        ORDER BY id DESC LIMIT ?
        """,
        (source, AUTO_DISABLE_THRESHOLD),
    ).fetchall()
    statuses = [row["status"] for row in last_finished]
    if statuses and statuses[0] == "disabled":
        return True
    if len(statuses) >= AUTO_DISABLE_THRESHOLD and all(s == "failed" for s in statuses):
        return True
    return False


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
