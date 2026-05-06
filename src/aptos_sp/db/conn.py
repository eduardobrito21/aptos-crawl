"""SQLite connection helper. Opens `aptos.db` at the repo root and applies
`db/schema.sql` on first call.

Schema is applied via `executescript` against an idempotent file (every
statement is `CREATE ... IF NOT EXISTS`), so reapplying on every open is
safe and removes the need for a separate "migrate" command in v1.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = REPO_ROOT / "aptos.db"
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"


# Python 3.12 deprecated the implicit date/datetime adapters. Register
# ISO-8601 round-trippers once at import time so DATE / DATETIME columns
# round-trip cleanly via PARSE_DECLTYPES.
def _register_adapters() -> None:
    sqlite3.register_adapter(date, lambda d: d.isoformat())
    sqlite3.register_adapter(datetime, lambda dt: dt.isoformat(sep=" "))
    sqlite3.register_converter("DATE", lambda b: date.fromisoformat(b.decode()))
    sqlite3.register_converter("DATETIME", lambda b: datetime.fromisoformat(b.decode()))


_register_adapters()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection, apply schema, return it.

    Foreign keys are enforced; rows are returned as `sqlite3.Row` so
    callers can index by column name.
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _apply_schema(conn)
    _migrate(conn)
    return conn


def _apply_schema(conn: sqlite3.Connection) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()


# Columns added to `aptos` after the initial schema shipped. SQLite does
# not support `ALTER TABLE ADD COLUMN IF NOT EXISTS`, so we inspect
# `PRAGMA table_info` and add what's missing. Append-only — never rename
# or drop here.
_APTOS_LATE_COLUMNS: list[tuple[str, str]] = [
    ("descricao", "TEXT"),
    ("amenities", "TEXT"),
    ("extracted_at_hash", "TEXT"),
    ("anunciante_code", "TEXT"),
    ("criado_em", "DATE"),
    ("detail_fetched_at", "DATETIME"),
    ("accepts_pets", "BOOLEAN"),
    ("near_subway", "BOOLEAN"),
    ("tenant_service_fee", "REAL"),
    ("home_protection_fee", "REAL"),
    ("construction_year", "INTEGER"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(aptos)")}
    for name, decl in _APTOS_LATE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE aptos ADD COLUMN {name} {decl}")
    conn.commit()
