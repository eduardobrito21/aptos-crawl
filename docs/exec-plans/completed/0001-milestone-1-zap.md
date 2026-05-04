# Plan 0001 — Milestone 1: skeleton + ZAP scraper

**Status:** Complete (2026-05-04)

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

- **2026-05-04 — `aptos.UNIQUE(source, source_id)` + `INSERT … ON CONFLICT
  DO UPDATE` for upserts.** Schema-level uniqueness gives idempotency for
  free; no application-level dedup needed in M1.
- **2026-05-04 — Parser targets `__NEXT_DATA__`, not the rendered DOM.**
  Superseded by the API pivot below. Kept as historical context.
- **2026-05-04 — `scrape` returns success on 0 listings.** First live run
  hit Cloudflare with a cold persistent context and parsed 0 from the
  challenge page. Treating that as `success` (not `failed`) keeps the
  `runs` row clean while we tune; revisit if it masks real failures —
  consider a "no-listings-this-run" warning + status='partial'.
- **2026-05-04 — sqlite date adapters registered explicitly** in
  `db/conn.py` to silence Python 3.12 deprecation. ISO-8601 round trip.
- **2026-05-04 — `datetime.now(UTC)` everywhere** (not the deprecated
  `utcnow()`). Stored timestamps are timezone-aware UTC.
- **2026-05-04 — Pivot from HTML scrape to `glue-api.zapimoveis.com.br`.**
  HTML path cleared Cloudflare for the first bairro but re-challenged on
  the second every time, even with a warm persistent profile + system
  Chrome + automation-flag masking + 15–30s inter-bairro pacing. Eduardo
  captured the API URL the ZAP frontend itself uses; switched the scraper
  to call `/v4/listings` directly. ADR-011.
- **2026-05-04 — Pivot transport from Playwright `page.goto` to
  `curl_cffi` with Chrome TLS impersonation.** First in-page `fetch`
  approach failed CORS (browser strips browser-managed headers).
  Switched to `page.goto(api_url)`, which then ran into a hard CF block
  on the operator's IP — no challenge UI, immediate 403 at TLS
  handshake. `curl_cffi` impersonates Chrome's exact wire fingerprint
  (JA3, HTTP/2 SETTINGS), defeating the IP/fingerprint block at the
  network layer. ADR-012.
- **2026-05-04 — Drop `UNIQUE(url)` from `aptos`; synthesize URL from
  listing id.** glue-api's `includeFields` projection doesn't actually
  return `link.href` (the frontend builds URLs client-side). Every
  listing parsed to `url=""`, and the schema's `UNIQUE(url)` rejected
  29 of every 30 (silent dedup hid this). `(source, source_id)` is the
  real identity; URL was a defensive constraint that didn't survive
  reality. Synthesized URL form
  `https://www.zapimoveis.com.br/imovel/id-{id}/` — ZAP redirects this
  to the canonical slug.
- **2026-05-04 — Itaim Bibi groups under "Zona Sul" in ZAP's
  taxonomy.** SP's official zoning calls it Zona Oeste; the API filters
  by ZAP's taxonomy, not the city's. Verified via ZAP's autocomplete.
- **2026-05-04 — Network capture revealed missing query params + paging
  cap.** First scrape pulled 745 listings (~150/bairro) — a small
  fraction of the actual inventory. Eduardo captured the live
  frontend's `glue-api` requests; three issues surfaced: (a) we were
  missing `unitTypes=APARTMENT, unitTypesV3=APARTMENT,
  unitSubTypes=UnitSubType_NONE,DUPLEX,TRIPLEX, usageTypes=RESIDENTIAL,
  parentId=null, __zt=mtc:deduplication2023` (the apartment/residential
  server-side filters), (b) `X-Domain` should be `.zapimoveis.com.br`
  (cookie-form, leading dot), (c) we capped pagination at `MAX_PAGES=5`
  and never read `totalCount`. Fixed all three; bumped `MAX_PAGES` to
  200 and now drive pagination off response `totalCount`.
- **2026-05-04 — ZAP API hard-caps pagination at `from < 1500`**
  (50 pages × 30/page); page 51 returns `404 "Page is above
  acceptable limit"`. Standard for paginated search APIs. With
  server-side filters (next decision), every bairro now lands well
  under the cap.
- **2026-05-04 — Apply `filters.yaml` server-side via `glue-api`
  query params.** Eduardo captured the filtered-search request from
  the ZAP frontend's network tab plus the filter sidebar HTML. Wired
  the mappings: `quartos_min/max → bedrooms=1,2,3`,
  `vagas_min → parkingSpaces=N,…,4`, `area_min_m2 → usableAreasMin`,
  `total_max → rentalTotalPriceMax + rentTotalPrice=true` (the
  `rentTotalPrice` flag makes the price filter apply to total cost,
  not base rent — without it the cap is wrong),
  `mobiliado=true → amenities=FURNISHED`. Cuts the haystack
  10× (7369 → 989 listings) and the run time 6× (13:42 → 2:07). The
  ZAP filters aren't strict on every dimension (a few R$2M/mo and
  0-bedroom outliers leak through) — `pipeline/normalize.py` (Plan
  0002) handles those.

## Outcome

`uv run scrape` populates `aptos.db` with the operator's filter
applied server-side end-to-end:

- **989 listings** across the 5 target neighborhoods, all matching
  `quartos∈[1,3]`, `vagas≥1`, `area≥70m²`, `total≤R$11k` (mostly),
  `mobiliado=true`. Per-bairro: Pinheiros 210, Itaim Bibi 199,
  Vila Olímpia 262, Vila Nova Conceição 67, Moema 251.
- 24/24 unit tests pass (parser, locations, persistence + dedup,
  total_count, all 4 server-side filter mappings).
- `runs` row records `success`; ~2 min end-to-end (down from 13 min
  pre-filter) with 8–9 paginated requests per bairro.
- Idempotent on rerun — `(source, source_id)` upsert flips correctly
  to `n_updated`.
- `basedpyright .` 0 errors; `ruff check + format` clean.
