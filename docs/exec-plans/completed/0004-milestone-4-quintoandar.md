# Plan 0004 — Milestone 4: QuintoAndar scraper

**Status:** Complete (2026-05-04)
**Depends on:** Plan 0001 (Scraper interface), Plan 0002 (dedup)

## Goal

Add QuintoAndar as a secondary source per ADR-005, reusing the
`Scraper` interface where possible and tolerating failure gracefully.

## Out of scope

- Anti-detection arms race (per ADR-005 §3): no fingerprint rotation,
  no proxy pool, no captcha solver.
- Loft and ImovelWeb (future).

## Steps

1. Validate first: does ZAP coverage of the 6 neighborhoods make QA
   worth the effort? If ZAP covers ≥ 90%, consider abandoning. (Decide
   *before* writing code.)
2. Implement `aptos_sp/scrapers/qa/`:
   - Reuse `Scraper` base class.
   - Internal slug mapping (canonical neighborhood → QA slug like
     `pinheiros-sao-paulo-sp-brasil`).
   - Page-of-detail strategy: prefer direct
     `quintoandar.com.br/imovel/<id>/...` URLs over scraping the
     listing flow.
3. Implement auto-disable (ADR-005 §2):
   - Query last 3 `runs` rows where `source = 'quintoandar'`.
   - If all 3 have `status = 'failed'`, write a `status = 'disabled'`
     row at start of next run and exit early.
   - Operator clears by editing `runs` (or a CLI flag like
     `--reset-source-disable`).
4. Refactor `Scraper` interface only if QA exposes a structural
   mismatch that hacking around would be worse than refactoring
   (ADR-005 §1).

## Definition of done

- `uv run scrape` runs both ZAP and QA sources by default
  (`sources.quintoandar: true`).
- Disabling QA via `sources.quintoandar: false` skips it cleanly.
- After 3 forced failures, the next run is auto-disabled with a
  visible warning.
- At least 5 cross-platform duplicates are detected by Plan 0002's
  dedup pass.

## Decision log

- **2026-05-04 — Validation step skipped: QA shipped on operator
  request.** Step 1 of the plan asked to decide before coding whether
  QA was worth the effort. The operator chose to ship it for the
  cross-platform dedup signal alone (`v_possible_dups` is more
  trustworthy with a second source) — coverage threshold not
  evaluated.
- **2026-05-04 — `curl_cffi` chrome impersonation passes Cloudflare
  on both QA HTML and the apigw JSON endpoint.** No Playwright
  required; same ADR-012 transport that won M1. Anonymous calls
  (no JWT, no session cookies) are accepted as long as the TLS
  fingerprint matches Chrome's.
- **2026-05-04 — Pivot from SSR walk to filtered POST API.** The
  initial implementation walked QA's `__NEXT_DATA__` payload across
  paginated HTML pages (~600 KB each) because QA filters client-side.
  The operator captured live network traffic showing
  `apigw.prod.quintoandar.com.br/house-listing-search/v2/search/list`
  — a POST endpoint that accepts the same filter spec as the UI's
  filter sidebar. Rewired the scraper around it: server-side filters,
  ElasticSearch-style pagination by offset, ~10× smaller responses,
  ~30× fewer requests for the same coverage.
- **2026-05-04 — Filter mapping is direct.** `filters.yaml` →
  `filters.houseSpecs`: `quartos_min/max → bedrooms.range.{min,max}`,
  `vagas_min → parkingSpace.range.min`, `area_min_m2_flex →
  area.range.min` (loose floor — eligibility step applies the strict
  `area_min_m2` rule), `total_max →
  priceRange[0].range.max + costType=TOTAL_COST` (mirrors ZAP's
  `rentTotalPrice=true` flag), `mobiliado=true →
  isFurnished=true`, `tipo=apartamento → houseTypes=["APARTMENT"]`.
- **2026-05-04 — `total` field over-counts.** API returns
  `hits.total.value` covering a broader region than the slug filter
  actually returns (Pinheiros "total"=131 but only 135 real hits;
  Moema "total"=127 but only 6 real hits). Pagination correctly
  stops on the natural tail (`len(stubs) < PAGE_SIZE`) — `total` is
  printed in logs as a hint but isn't trusted as the stop condition.
- **2026-05-04 — `iptuPlusCondominium` bundles two values.** QA
  returns one combined number for condo + IPTU instead of separate
  fields. Stored under `condominio` with `iptu=NULL`. Plan 0002's
  eligibility step uses `total` directly, so the bundling doesn't
  affect filtering — but if the operator wants to break out IPTU
  separately later, that requires the QA detail page (deferred).
- **2026-05-04 — QA `address` is street-name-only.** API returns
  just the street name (no number — QA hides it pre-visit). Parser
  appends neighbourhood + city to give dedup more signal:
  `"Rua X, Pinheiros, São Paulo"`. Plan 0002's dedup
  street-number guard correctly handles this — when one side hides
  the number (QA) and the other exposes it (ZAP), the address
  fingerprint match still triggers the cross-platform pair.
- **2026-05-04 — Auto-disable lives in `db/runs.py`.** Added
  `is_disabled(conn, source)` reading the last 3 finished runs for
  that source — disables on three consecutive failures or whenever
  the most recent finished row is already `disabled`. In-progress
  rows (`status IS NULL`) are ignored so a crashed run doesn't get
  miscounted. `cli/scrape.py` consults this before each source and
  writes a `disabled` row instead of running.
- **2026-05-04 — `Scraper` interface didn't need refactoring.** QA
  fits the existing `list_listings(config) → list[ListingStub]` /
  `fetch_detail(url) → ListingDetail` shape unchanged. Detail-page
  enrichment for QA is deferred — search-list response already
  provides what cross-platform dedup needs.

## Outcome

After `uv run scrape` (both sources enabled):

- **337 QA listings** persisted across the 5 bairros — Pinheiros 135,
  Itaim Bibi 103, Vila Olímpia 78, Vila Nova Conceição 15, Moema 6.
  ~76 seconds wall clock (~17 paginated POST requests at 1.5–4s
  pacing).
- ZAP unchanged: 1034 rows. Combined: **1371 rows** before dedup.
- After `uv run enrich`: **1194 eligible** across both sources.

After dedup classifier:

- **40 strong + 31 weak duplicates** flagged in `v_possible_dups`,
  including **25 cross-platform (ZAP ↔ QA)** pairs — well past the
  Definition of Done threshold of 5.
- Sample cross-platform matches: Oscar Freire / Pinheiros (3q,
  106m²), Cônego Eugênio Leite / Pinheiros (2q, 86m²), Eusébio
  Matoso / Pinheiros (1q, 75m²) — same listing on both platforms,
  with QA hiding the number and ZAP exposing it. Plan 0002's
  street-number guard handled the asymmetric case correctly.

Quality:

- 112/112 unit tests pass (15 new for QA `api.py` + 9 for
  `db/runs.py` auto-disable, plus M1–M2 carryovers).
- `basedpyright .` 0 errors; `ruff check + format` clean.
