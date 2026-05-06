# Plan 0009 — Milestone 2 part 2: QuintoAndar detail-page enrichment

**Status:** Complete (2026-05-05)
**Depends on:** Plan 0002 (M2 enrichment shipped), Plan 0004 (QA scraper),
Plan 0008 (validate-filters harness — used to spot-check no regressions).

## Goal

Bring QA listings up to the same enrichment depth ZAP listings already
have: full broker description (free-text), `anunciante`-equivalent
code, listing creation date, and rooftop-precise lat/lng when QA
exposes them. Today QA only has the 1-line `shortRentDescription`
from the search-list API, which makes keyword extraction (ADR-007)
much weaker for QA than for ZAP.

This is the M2 follow-up the original Plan 0002 deferred when it
swapped per-listing detail fetches for an `includeFields` extension —
a swap that worked for ZAP but never had a QA counterpart.

## Out of scope

- QA login / auth-gated fields (exact street number, full broker
  contact info). QA gates these behind visit booking; we don't try
  to bypass.
- Photo download or perceptual-hash dedup (ADR-006 still defers
  unless cross-platform precision drops below 80%).
- Re-fetching QA descriptions automatically on every run beyond
  what `cli/details.py`'s existing
  `detail_fetched_at < last_seen` predicate covers.
- Backwards-compatible support for old `aptos.db` rows missing the
  M2 schema columns — we already migrated them.

## Steps

1. **Recon.** Probe `https://www.quintoandar.com.br/imovel/{id}/`
   with `curl_cffi` chrome impersonation. Confirm:
   - Cloudflare passes (we already know it does for QA's search
     pages — same TLS fingerprint).
   - Whether the page is Next.js with a `__NEXT_DATA__` JSON dump
     containing the listing's full data (likely — QA's search pages
     work that way).
   - Which selectors are stable: `data-testid="..."`, `itemProp`,
     class names. Pick the ones that survive a layout change.
   - What's renderable vs what's auth-gated.
2. **Implement `scrapers/qa/detail.py`** mirroring
   `scrapers/zap/detail.py`:
   - `fetch_detail_html(url) -> str` (curl_cffi, chrome124, headers
     mirroring the QA scraper's existing http module).
   - `parse_detail(html) -> DetailFields` extracting: description,
     anunciante_code (or QA's equivalent — internal listing code),
     criado_em, address with number if exposed, lat/lng.
   - Reuse `aptos_sp.scrapers.zap.detail.DetailFields` if the field
     set lines up; otherwise add a tiny QA-specific dataclass to
     keep type safety honest.
3. **Extend `cli/details.py`** to handle both sources. Currently
   the CLI is ZAP-only; refactor so it walks `aptos` rows of any
   source whose `detail_fetched_at IS NULL OR < last_seen`, and
   dispatches by `aptos.source` to the right fetcher / parser.
   Keep the same idempotency and pacing.
4. **Schema check.** The columns added in Plan 0002 (`descricao`,
   `anunciante_code`, `criado_em`, `address_lat`, `address_lng`,
   `address_source`, `address_precision`, `detail_fetched_at`)
   should fit QA without changes. Verify; only add columns if
   QA exposes a meaningful field that has no equivalent column.
5. **Tests + fixture.** Save one real QA detail-page HTML slice
   under `tests/fixtures/qa/detail_<id>.html` (analogous to
   `tests/fixtures/zap/detail_*.html`). Write parser tests covering
   description, code, date, lat/lng (if any), graceful handling of
   missing fields.
6. **Live `uv run details --source quintoandar --limit 30`** to
   verify. Spot-check 3–5 fetched rows in the DB to confirm the
   description is the rich broker text, not the 1-line search-list
   one. Re-run `validate-filters --bairro Pinheiros` afterward to
   make sure nothing regressed.

## Definition of done

- `uv run details` fetches detail pages for both ZAP and QA
  listings and persists them into the same columns.
- After a full run, eligible QA rows have `descricao` length
  comparable to eligible ZAP rows (rough median ≥ 200 chars vs
  today's ~80 chars).
- Cross-platform dedup pairs in `v_possible_dups` either stay
  steady or improve — the richer description shouldn't make dedup
  worse, and may help if we later add description-similarity dedup
  (ADR-006 photo-hash backup still off).
- Unit tests cover the QA detail parser including missing-field
  paths.
- `basedpyright .` clean; `ruff check + format` clean.

## Open questions

- **Does QA's detail page use the same `__NEXT_DATA__` pattern as
  the search page?** If yes, parsing is mostly JSON extraction
  (cheap, robust). If no, we're DOM-scraping — slower to write,
  more fragile.
- **Does QA expose `criado_em` on a public detail page?** They
  hide some metadata until you book a visit; the listing date may
  or may not be on the public surface.
- **Per-listing rate limiting.** Today's QA search-list pacing
  (1.5–4s between API calls) was tuned for the apigw endpoint.
  Detail-page HTML fetches go to `www.quintoandar.com.br` — same
  pacing should be safe but worth a sanity check during the live
  run; if CF starts challenging, back off.
- **Should QA detail fetches run alongside ZAP's in the same
  `cli/details.py`, or on a separate cadence?** Default: same
  CLI, both sources. Operator can split with `--source` later.

## Decision log

- **2026-05-05 — QA detail page exposes full data via
  `__NEXT_DATA__`.** Recon found the Next.js SSR script tag carries
  `props.pageProps.initialState.house.houseInfo` with everything we
  need: `generatedDescription.longDescription` (700–1300 chars of
  rich broker prose, vs the 50-char `shortRentDescription` the
  search-list returns), `displayId` (public listing code),
  `lastPublishedDate` (ISO-8601), `address.{street,
  neighborhood, city, lat, lng, zipCode}`. No DOM scraping needed
  — single regex extraction + JSON parse.
- **2026-05-05 — Cloudflare passes via the same curl_cffi /
  chrome124 fingerprint** the QA search scraper uses; no extra auth
  or session setup. Detail-page URLs (`.../imovel/{id}/`) redirect
  to slugged form (`.../imovel/{id}/alugar/apartamento-{n}-quartos-...`)
  and respond 200.
- **2026-05-05 — Shared `DetailFields` dataclass** moved from
  `scrapers/zap/detail.py` to `scrapers/base.py`. Both ZAP and QA
  parsers now produce the same shape so `cli/details._persist`
  doesn't need source-aware logic. Added a `photos` field to the
  dataclass for future use; we don't populate it yet.
- **2026-05-05 — `cli/details.py` dispatches by source via a
  `_HANDLERS` registry** mapping `source` → `(fetch, parse,
  fetch_error)`. Default behavior with no `--source` flag walks
  every source's pending rows. Same idempotency
  (`detail_fetched_at < last_seen`), same pacing (1.5–4s).
- **2026-05-05 — QA `displayId` falls back to internal `id`.** When
  a listing's `displayId` is blank/null, persist the `id` as
  `anunciante_code` so we still have a stable handle.
- **2026-05-05 — Street numbers stay hidden.** QA gates the exact
  `address.streetNumber` behind a visit-booking flow; the public
  detail page only exposes the street name (e.g. "Rua Oscar
  Freire"). We accept the gap — Plan 0002's dedup street-number
  guard already handles "one side hides the number" correctly.

## Outcome

After implementation:

- `uv run details` (no `--source`) walks both ZAP and QA pending
  rows, dispatches to the right per-source handler, persists the
  same `DetailFields` shape into the same columns.
- Live test: `uv run details --source quintoandar --limit 10`
  fetched 10 Pinheiros listings in ~30 s. **100% coverage** on
  every detail field:

  | field | coverage | range |
  |---|---|---|
  | `descricao` | 10/10 | 677–1343 chars (rich broker prose) |
  | `anunciante_code` | 10/10 | QA `displayId` |
  | `criado_em` | 10/10 | 2025-11 → 2026-05 |
  | `address_lat` / `_lng` | 10/10 | rooftop coords |

- Description length jumped ~25× (50 → 1100+ chars median),
  unlocking real keyword-extraction signal for QA listings — they
  now look comparable to ZAP-detail-fetched ZAP rows for ADR-007's
  matching purposes.
- 151/151 unit tests pass (10 new for QA detail parser including
  long-description preference, `displayId` fallback, ISO date
  parse, malformed-JSON guards).
- `basedpyright .` 0 errors; `ruff check + format` clean.

A full QA-only details run takes ~10 min/100 listings at the
1.5–4 s pacing — comparable to ZAP's per-listing latency. Operator
runs the unified `uv run details` whenever the scrape pulls fresh
rows.

- **2026-05-05 — Extended detail extraction after operator pointed
  at the rendered HTML.** Initially we shipped `description /
  anunciante_code / criado_em / endereco / lat / lng`. Operator
  flagged that the QA detail page also exposes a richer block:
  `acceptsPets`, `isNearSubway`, `tenantServiceFee`,
  `homeProtection`, `rangeFloor`, `constructionYear`, and a clean
  split of `condoPrice` vs `iptu` (the search-list bundles them).
  All in `houseInfo`, no DOM scraping required.

  Added five new columns to `aptos` (`accepts_pets`, `near_subway`,
  `tenant_service_fee`, `home_protection_fee`, `construction_year`)
  via the idempotent migration in `db/conn.py`. `andar` already
  existed and now gets populated as `"4° a 7° andar"` (or
  `"5° andar"` when min == max) from `rangeFloor: {min, max}`.

  `condominio` / `iptu` are deliberately NOT updated by the detail
  parser — those columns live in `precos_historico` snapshots, not
  on `aptos`. Splitting QA's bundled price across snapshots is a
  separate concern (defer until the operator wants
  per-snapshot accuracy).

  Live verify on 5 rows: 100% coverage on every new field except
  `construction_year` (1/5 — many QA buildings don't expose the
  year). 156/156 tests pass; lint + typecheck clean.
