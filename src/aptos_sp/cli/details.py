"""`uv run details` — fetch detail pages and backfill the fields the
search-list / glue-api responses don't expose.

Walks `aptos` rows whose `detail_fetched_at` is null or older than
`last_seen` (i.e. the listing was re-scraped after we last grabbed
detail) and fetches each detail page in turn. Pacing matches the
scrapers' inter-page range (1.5–4s) — Cloudflare passes via curl_cffi
TLS impersonation per ADR-012, but we still don't want to look
synthetic.

Per-source fetcher + parser are looked up via `_HANDLERS`. Plan 0009
adds QuintoAndar; ZAP has been there since Plan 0002.

Resumable: an interrupt mid-run leaves earlier rows persisted; the
next invocation picks up where this one stopped (rows that didn't
update keep `detail_fetched_at IS NULL`).

Flags:
- `--limit N` — stop after N successful fetches across all sources.
- `--source NAME` — restrict to one source (`zap` or `quintoandar`).
  Defaults to all known sources.
"""

import argparse
import random
import sqlite3
import sys
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime

from aptos_sp.db import conn as db_conn
from aptos_sp.db import runs
from aptos_sp.scrapers.base import DetailFields
from aptos_sp.scrapers.qa import detail as qa_detail
from aptos_sp.scrapers.zap import detail as zap_detail

INTER_FETCH_DELAY_RANGE = (1.5, 4.0)


# Per-source handler: (fetch html, parse html, fetch error type).
# The error type lets us map source-specific 404/410 paths into
# our shared "expired listing" branch.
_HANDLERS: dict[
    str, tuple[Callable[[str], str], Callable[[str], DetailFields], type[Exception]]
] = {
    "zap": (zap_detail.fetch_detail_html, zap_detail.parse_detail, zap_detail.DetailFetchError),
    "quintoandar": (
        qa_detail.fetch_detail_html,
        qa_detail.parse_detail,
        qa_detail.QaDetailFetchError,
    ),
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    sources = [args.source] if args.source else list(_HANDLERS)
    for s in sources:
        if s not in _HANDLERS:
            print(f"unknown source: {s} (have {sorted(_HANDLERS)})", file=sys.stderr)
            return 2

    conn = db_conn.connect()
    run_id = runs.start(conn, source="details")

    n_fetched = 0
    n_errors = 0
    n_skipped_404 = 0
    error_summaries: list[str] = []
    try:
        rows = _candidates(conn, sources=sources, limit=args.limit)
        print(f"[details] {len(rows)} rows to fetch (sources={sources})", flush=True)
        for i, row in enumerate(rows):
            if i > 0:
                time.sleep(random.uniform(*INTER_FETCH_DELAY_RANGE))
            fetch, parse, err_type = _HANDLERS[row["source"]]
            try:
                html = fetch(row["url"])
            except err_type as e:
                msg = str(e)
                if "HTTP 404" in msg or "HTTP 410" in msg:
                    _mark_fetched(conn, row["id"])
                    n_skipped_404 += 1
                    continue
                n_errors += 1
                if len(error_summaries) < 3:
                    error_summaries.append(msg[:160])
                print(
                    f"[details] {row['source']}/{row['source_id']} ERROR: {msg[:160]}",
                    flush=True,
                )
                continue

            detail = parse(html)
            _persist(conn, row["id"], detail)
            n_fetched += 1
            if n_fetched % 50 == 0:
                print(
                    f"[details] {n_fetched}/{len(rows)} done"
                    f" (errors={n_errors}, expired={n_skipped_404})",
                    flush=True,
                )

        status = "success" if n_errors == 0 else "partial"
        runs.finish(
            conn,
            run_id,
            status=status,
            n_listings=n_fetched,
            n_errors=n_errors,
            error_summary="; ".join(error_summaries) or None,
        )
        print(
            f"[details] {n_fetched} fetched, {n_skipped_404} expired, {n_errors} errors",
            flush=True,
        )
        return 0 if n_errors == 0 else 1
    except Exception as e:
        runs.finish(
            conn,
            run_id,
            status="failed",
            n_listings=n_fetched,
            n_errors=n_errors + 1,
            error_summary=f"{type(e).__name__}: {e}",
        )
        traceback.print_exc()
        return 1
    finally:
        conn.close()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="details", description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="stop after N rows")
    parser.add_argument(
        "--source",
        choices=sorted(_HANDLERS),
        default=None,
        help="restrict to one source (default: all)",
    )
    return parser.parse_args(argv if argv is not None else sys.argv[1:])


def _candidates(
    conn: sqlite3.Connection, *, sources: list[str], limit: int | None
) -> list[sqlite3.Row]:
    """Rows that need a (re-)fetch: never fetched, or last_seen advanced
    past the previous fetch. ZAP rows come first (they tend to have
    richer descriptions; failures there are more diagnostic), then QA."""
    placeholders = ",".join("?" * len(sources))
    sql = f"""
        SELECT id, source, source_id, url, detail_fetched_at, last_seen
        FROM aptos
        WHERE source IN ({placeholders})
          AND url IS NOT NULL AND url != ''
          AND (detail_fetched_at IS NULL OR detail_fetched_at < last_seen)
        ORDER BY source, id
    """
    params: list[object] = [*sources]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params).fetchall())


def _persist(conn: sqlite3.Connection, apto_id: int, detail: DetailFields) -> None:
    """Update the row with detail-page fields.

    Detail-page values overwrite the search-list / API-supplied ones
    (the detail page is what the operator sees), with
    `COALESCE(detail, db)` falling back to the existing value when the
    detail parser couldn't find a field.

    `address_source = 'structured'` whenever the parser found
    coordinates — both ZAP (Maps iframe) and QA (`address.lat/lng` in
    the Next.js payload) expose them as structured markup.
    `address_precision` stays NULL; Plan 0005 (commute) will refine.

    `condominio` / `iptu` aren't on `aptos` (they live in
    `precos_historico` snapshots). The detail parser still extracts
    them on `DetailFields` for downstream use, but we don't UPDATE
    them here — splitting QA's bundled value across snapshots is a
    separate concern (Plan 0002 / `precos_historico` writer).
    """
    has_coords = detail.address_lat is not None and detail.address_lng is not None
    address_source = "structured" if has_coords else None
    conn.execute(
        """
        UPDATE aptos SET
            descricao = COALESCE(?, descricao),
            endereco = COALESCE(?, endereco),
            address_lat = COALESCE(?, address_lat),
            address_lng = COALESCE(?, address_lng),
            address_source = COALESCE(?, address_source),
            anunciante_code = ?,
            criado_em = ?,
            andar = COALESCE(?, andar),
            accepts_pets = COALESCE(?, accepts_pets),
            near_subway = COALESCE(?, near_subway),
            tenant_service_fee = COALESCE(?, tenant_service_fee),
            home_protection_fee = COALESCE(?, home_protection_fee),
            construction_year = COALESCE(?, construction_year),
            detail_fetched_at = ?
        WHERE id = ?
        """,
        (
            detail.description,
            detail.endereco,
            detail.address_lat,
            detail.address_lng,
            address_source,
            detail.anunciante_code,
            detail.criado_em,
            detail.andar,
            detail.accepts_pets,
            detail.near_subway,
            detail.tenant_service_fee,
            detail.home_protection_fee,
            detail.construction_year,
            datetime.now(UTC),
            apto_id,
        ),
    )
    conn.commit()


def _mark_fetched(conn: sqlite3.Connection, apto_id: int) -> None:
    """For 404/410: stamp `detail_fetched_at` without updating any
    other field, so we don't loop forever on expired listings."""
    conn.execute(
        "UPDATE aptos SET detail_fetched_at = ? WHERE id = ?",
        (datetime.now(UTC), apto_id),
    )
    conn.commit()


if __name__ == "__main__":
    raise SystemExit(main())
