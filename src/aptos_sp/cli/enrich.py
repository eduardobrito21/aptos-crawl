"""`uv run enrich` — populate qualitative columns + dedup flags.

Reads `aptos` rows that need re-extraction (raw_html_hash changed since
the last enrich, or never enriched), runs `pipeline.extract` against
the stored `descricao` + `amenities`, writes the qualitative columns,
then runs `pipeline.dedup` to flag possible duplicates.

No network calls — the data this needs is already in SQLite (Plan 0001
fetched description + amenities during scrape, see ADR-013). When ZAP
republishes a listing with a new description, `raw_html_hash` changes
and that row gets re-extracted on the next enrich run.
"""

import json
import sqlite3
import traceback

from aptos_sp.config import filters as filters_config
from aptos_sp.config.filters import Filters
from aptos_sp.db import conn as db_conn
from aptos_sp.db import runs
from aptos_sp.pipeline.dedup import find_and_flag_dups
from aptos_sp.pipeline.extract import QualitativeFields, extract_qualitative
from aptos_sp.pipeline.normalize import area_min_with_flex, normalize_endereco


def main() -> int:
    config = filters_config.load()
    conn = db_conn.connect()
    run_id = runs.start(conn, source="enrich")
    try:
        n_extracted = _run_extract(conn)
        n_normalized = _run_normalize_endereco(conn)
        n_eligible = _run_eligibility(conn, config.filters)
        dup_stats = find_and_flag_dups(conn)
        runs.finish(
            conn,
            run_id,
            status="success",
            n_listings=n_extracted,
            n_updated=n_normalized,
        )
        print(
            f"[enrich] extracted={n_extracted} "
            f"normalized={n_normalized} "
            f"eligible={n_eligible} "
            f"dups(strong/weak/cleared)={dup_stats.n_strong}/"
            f"{dup_stats.n_weak}/{dup_stats.n_cleared}"
        )
        return 0
    except Exception as e:
        runs.finish(
            conn,
            run_id,
            status="failed",
            n_errors=1,
            error_summary=f"{type(e).__name__}: {e}",
        )
        traceback.print_exc()
        return 1
    finally:
        conn.close()


def _run_extract(conn: sqlite3.Connection) -> int:
    """Re-extract every row whose `raw_html_hash` differs from
    `extracted_at_hash`. Returns the count of rows updated."""
    cur = conn.execute(
        """
        SELECT id, descricao, amenities, raw_html_hash
        FROM aptos
        WHERE raw_html_hash IS NOT NULL
          AND (extracted_at_hash IS NULL OR extracted_at_hash != raw_html_hash)
        """
    )
    n = 0
    for row in cur.fetchall():
        amenities = _decode_amenities(row["amenities"])
        fields = extract_qualitative(row["descricao"], amenities)
        _write_qualitative(conn, row["id"], fields, row["raw_html_hash"])
        n += 1
    conn.commit()
    return n


def _run_normalize_endereco(conn: sqlite3.Connection) -> int:
    """Recompute `endereco_normalized` whenever it's missing or stale."""
    cur = conn.execute(
        """
        SELECT id, endereco, endereco_normalized
        FROM aptos
        WHERE endereco IS NOT NULL
        """
    )
    n = 0
    for row in cur.fetchall():
        normalized = normalize_endereco(row["endereco"])
        if normalized != row["endereco_normalized"]:
            conn.execute(
                "UPDATE aptos SET endereco_normalized = ? WHERE id = ?",
                (normalized, row["id"]),
            )
            n += 1
    conn.commit()
    return n


def _run_eligibility(conn: sqlite3.Connection, filters: Filters) -> int:
    """Set `aptos.eligible` based on `filters.yaml`. Server-side filters
    are already applied at scrape time; this catches the outliers that
    leak through (Plan 0001 saw 0-bedroom + R$2M/mo entries) and applies
    the `area_min_m2_flex` rule that lives in code, not YAML."""
    cur = conn.execute(
        """
        SELECT a.id, a.quartos, a.vagas, a.area_m2, a.descricao, a.eligible,
            (
                SELECT total FROM precos_historico
                WHERE apto_id = a.id
                ORDER BY snapshot_date DESC LIMIT 1
            ) AS total
        FROM aptos a
        """
    )
    n_eligible = 0
    for row in cur.fetchall():
        eligible = _is_eligible(row, filters)
        if bool(row["eligible"]) != eligible:
            conn.execute(
                "UPDATE aptos SET eligible = ? WHERE id = ?",
                (eligible, row["id"]),
            )
        if eligible:
            n_eligible += 1
    conn.commit()
    return n_eligible


def _is_eligible(row: sqlite3.Row, filters: Filters) -> bool:
    quartos = row["quartos"]
    if quartos is None or not (filters.quartos_min <= quartos <= filters.quartos_max):
        return False
    vagas = row["vagas"]
    if vagas is None or vagas < filters.vagas_min:
        return False
    total = row["total"]
    if total is None or total > filters.total_max:
        return False
    area = row["area_m2"]
    if area is None:
        return False
    floor = area_min_with_flex(filters, quartos=quartos, descricao=row["descricao"])
    return area >= floor


def _decode_amenities(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(decoded, list):
        return [str(a) for a in decoded if a]
    return []


def _write_qualitative(
    conn: sqlite3.Connection,
    apto_id: int,
    fields: QualitativeFields,
    hash_at_extract: str,
) -> None:
    conn.execute(
        """
        UPDATE aptos SET
            chuveiro_gas = ?,
            chuveirinho = ?,
            ar_condicionado = ?,
            vidro_anti_ruido = ?,
            cozinha_layout = ?,
            lavabo = ?,
            extracted_by = 'keyword',
            extracted_at_hash = ?
        WHERE id = ?
        """,
        (
            fields.chuveiro_gas,
            fields.chuveirinho,
            fields.ar_condicionado,
            fields.vidro_anti_ruido,
            fields.cozinha_layout,
            fields.lavabo,
            hash_at_extract,
            apto_id,
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
