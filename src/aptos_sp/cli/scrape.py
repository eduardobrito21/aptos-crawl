"""`uv run scrape` — visit search-results pages, persist listings.

Wires concrete components (config loader → scrapers → persist) and
nothing else. Business logic stays in `pipeline/` and `scrapers/` per
ARCHITECTURE.md.

Each enabled source per `filters.yaml` runs in turn. Per ADR-005 §2,
sources auto-disable after `AUTO_DISABLE_THRESHOLD` consecutive
failures: a `disabled` row is written and the scraper is skipped for
this run.
"""

import sys
import traceback

from aptos_sp.config import filters as filters_config
from aptos_sp.db import conn as db_conn
from aptos_sp.db import runs
from aptos_sp.pipeline.persist import upsert_listings
from aptos_sp.scrapers.base import Scraper
from aptos_sp.scrapers.qa import QaScraper
from aptos_sp.scrapers.zap import ZapScraper


def main() -> int:
    config = filters_config.load()
    conn = db_conn.connect()

    enabled: list[Scraper] = []
    if config.sources.zap:
        enabled.append(ZapScraper())
    if config.sources.quintoandar:
        enabled.append(QaScraper())
    if not enabled:
        print("No sources enabled in filters.yaml; nothing to do.", file=sys.stderr)
        return 1

    overall = 0
    for scraper in enabled:
        if runs.is_disabled(conn, scraper.source):
            run_id = runs.start(conn, source=scraper.source)
            runs.finish(
                conn,
                run_id,
                status="disabled",
                error_summary=(
                    f"auto-disabled after {runs.AUTO_DISABLE_THRESHOLD} consecutive "
                    "failed runs (ADR-005). Edit the runs table to re-enable."
                ),
            )
            print(
                f"[{scraper.source}] AUTO-DISABLED — "
                f"{runs.AUTO_DISABLE_THRESHOLD} consecutive failures (ADR-005). "
                "Edit the runs table to re-enable.",
                file=sys.stderr,
            )
            continue

        run_id = runs.start(conn, source=scraper.source)
        try:
            listings = scraper.list_listings(config)
            stats = upsert_listings(conn, listings)
            runs.finish(
                conn,
                run_id,
                status="success",
                n_listings=stats.n_listings,
                n_new=stats.n_new,
                n_updated=stats.n_updated,
            )
            print(
                f"[{scraper.source}] {stats.n_listings} listings "
                f"({stats.n_new} new, {stats.n_updated} updated)"
            )
        except Exception as e:
            runs.finish(
                conn,
                run_id,
                status="failed",
                n_errors=1,
                error_summary=f"{type(e).__name__}: {e}",
            )
            traceback.print_exc()
            overall = 1

    conn.close()
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
