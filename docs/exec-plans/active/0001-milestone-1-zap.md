# Plan 0001 — Milestone 1: skeleton + ZAP scraper

**Status:** Not started

## Goal

Stand up the project skeleton and ship a working ZAP scraper that
populates `aptos.db` end-to-end with structured listings from the 6
target neighborhoods. This is the smallest vertical slice that proves
the pipeline shape works.

## Out of scope

- QuintoAndar (M4)
- Detail-page enrichment (M2)
- Cross-platform dedup (M2)
- Notion export (M3)
- Commute (M5)
- LLM enrichment (Inactive plan 0007)

## Steps

1. `uv init aptos-sp` (or matching `pyproject.toml`); add deps:
   `playwright`, `pydantic`, `pyyaml`, `pytest`.
2. `uv run playwright install chromium`.
3. Apply `db/schema.sql` to a fresh `aptos.db`. Add a small
   `db/conn.py` helper that opens a connection and runs migrations on
   first call.
4. Write pydantic schemas in `aptos_sp/config/` for `filters.yaml` and
   `keywords.yaml`. Validate against the example files.
5. Author `aptos_sp/scrapers/base.py` with the minimal `Scraper`
   interface: `list_listings(filters)` and `fetch_detail(url)`.
6. Implement `aptos_sp/scrapers/zap/`. Internal slug mapping:
   neighborhood canonical name → ZAP URL slug (table inside the
   scraper, NOT in user config — see ARCHITECTURE.md "Where new code
   goes").
7. Implement Playwright sync setup per ADR-002: persistent context at
   `~/.cache/aptos-sp/playwright-profile/`, headless default,
   `HEADED=1` toggle, locale + timezone, randomized 2–5s delays,
   exponential backoff on 403/429.
8. Save one HTML fixture per listing layout to `tests/fixtures/zap/`.
   Write parser unit tests against fixtures (no live scraping in tests).
9. Write `aptos_sp/cli/scrape.py` entry point. Register in
   `pyproject.toml` as `[project.scripts] scrape = "aptos_sp.cli.scrape:main"`.
10. Insert a row into `runs` at start; update with counts on finish.

## Definition of done

- `uv run scrape` populates `aptos.db` with at least one listing per
  target neighborhood from a real ZAP run.
- Re-running does not duplicate rows (`(source, source_id)` UNIQUE
  works as expected).
- Unit tests pass against the saved HTML fixtures.
- `runs` table reflects the run's status, counts, and timing.

## Open questions

- Does ZAP's URL pattern stay consistent across all 6 neighborhoods, or
  do any need a different shape? (Resolve during step 6 by spot-check.)
- How many listings per neighborhood does a single page return? Affects
  pagination strategy.

## Decision log

_Empty until execution begins._
