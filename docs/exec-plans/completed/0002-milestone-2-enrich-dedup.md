# Plan 0002 — Milestone 2: enrichment + cross-platform dedup

**Status:** Complete (2026-05-04)
**Depends on:** Plan 0001 (ZAP data flowing into `aptos.db`)

## Goal

For each listing, populate qualitative criteria via keyword matching
(ADR-007). Add a heuristic dedup pass (ADR-006) that flags suspected
duplicates without auto-merging.

## Out of scope

- LLM extraction (Inactive plan 0007)
- Photo perceptual-hash dedup (only if SC2 < 80%, per ADR-006)
- Notion export (M3)

## Steps

1. Implement `aptos_sp/pipeline/extract.py`:
   - Load `keywords.yaml`, normalize text (lowercase + strip accents).
   - Tri-state matcher per criterion: positive list → True, negative
     list → False, neither → None.
   - Special handler for `cozinha_layout` (sub-keyed shape).
   - Promote unambiguous source amenity codes (e.g. ZAP's `LAVABO`,
     `AIR_CONDITIONING`) to `True` when keywords were silent. Amenities
     never overturn an explicit negative.
2. Implement `aptos_sp/pipeline/normalize.py`:
   - `normalize_text(s)` — lowercase, strip accents.
   - `normalize_endereco(s)` — strip prefixes (rua/av/al/...) and
     numbers; collapses whitespace and punctuation.
   - `area_min_with_flex(filters, …)` — applies the `area_min_m2_flex`
     rule (1 quarto + escritório → relax floor).
3. Implement `aptos_sp/pipeline/dedup.py`:
   - Fingerprint per ADR-006 (rua_normalizada + area + quartos +
     vagas).
   - Street-number guard: when both raw `endereco`s expose a number,
     require it to match (covers same-source same-street collapse).
   - 3-tier classifier: strong → set `possible_dup_of`; weak → flag
     with same column; none → leave alone. Idempotent on rerun.
4. Add `aptos_sp/cli/enrich.py`:
   - Re-extract every row whose `raw_html_hash != extracted_at_hash`.
   - Re-normalize `endereco_normalized` whenever stale.
   - Recompute `eligible` per `filters.yaml` (server-side filters
     leaked a few outliers in M1; this catches them).
   - Run dedup classifier.
5. Update `runs` log per source category (`enrich`, `details`).
6. Add `aptos_sp/scrapers/zap/detail.py` + `aptos_sp/cli/details.py`:
   - `curl_cffi` HTML fetch per listing URL (Cloudflare passes the
     same way it does for the listings API).
   - Parse description / anunciante_code / criado_em / endereco /
     lat-lng from stable `data-testid` selectors and the embedded
     Google Maps iframe.
   - Overwrite the API-provided `descricao` + `endereco` with the
     detail-page values (more complete; what the operator sees).
   - Pacing 1.5–4s between fetches; resumable via
     `detail_fetched_at < last_seen`; `--limit N` for incremental
     runs; 404/410 stamp `detail_fetched_at` to skip expired
     listings on rerun.

## Definition of done

- After `uv run enrich`, every newly-scraped row has its qualitative
  columns populated (or NULL — ADR-007 prefers false negatives).
- `v_possible_dups` surfaces the flagged candidates.
- After `uv run details`, every fetched row has `descricao`,
  `endereco`, `anunciante_code`, `criado_em`, and (when the broker
  exposed the street number) `address_lat`/`address_lng` populated.
- Unit tests cover normalization edge cases (acentos, prefixos, ruas
  com número escondido), keyword tri-state, dedup tiers +
  idempotency, and the detail-page parser (description, code, date,
  endereco, lat/lng, partial-HTML fallback).

## Open questions

- _Resolved (see decision log below): no per-criterion confidence
  score in v1; tri-state is enough._

## Decision log

- **2026-05-04 — Fetch `description` + `amenities` via the listings
  API, not via per-listing detail pages.** Plan literally said "fetch
  detail page" but ZAP's `glue-api` returns `description` and
  `amenities` as part of the listings projection — adding two tokens
  to `includeFields` costs nothing and avoids 989 extra HTTP requests
  through Cloudflare. Detail-page scraping stays available for future
  fields not exposed by the listings endpoint.
- **2026-05-04 — Schema migration via `PRAGMA table_info` inspection
  in `db/conn.py`.** SQLite has no `ALTER TABLE ADD COLUMN IF NOT
  EXISTS`, so `_migrate(conn)` reads existing column names and adds
  what's missing. Append-only — never rename or drop here. Six
  columns added across the milestone: `descricao`, `amenities`
  (JSON-encoded list), `extracted_at_hash`, `anunciante_code`,
  `criado_em`, `detail_fetched_at`.
- **2026-05-04 — Idempotency keyed on `extracted_at_hash` vs
  `raw_html_hash`.** Re-extraction skips rows whose hash already
  matches the last extract. Re-running enrich after no scrape changes
  is a no-op (`extracted=0 normalized=0`). When ZAP republishes a
  listing with a new description, hash changes and that row picks up
  on the next enrich.
- **2026-05-04 — Source amenity codes are a stronger signal than
  description prose.** ZAP exposes `LAVABO`, `AIR_CONDITIONING`,
  `FURNISHED` as structured flags — far more reliable than fishing the
  word out of free-text Portuguese. Amenities only fill `None`
  (keyword silence) — they don't overturn an explicit negative like
  "sem ar condicionado". Conservative mapping: only codes whose
  meaning is unambiguous (`HEATING` could be central heating, kept
  out).
- **2026-05-04 — `cozinha_layout` priority order
  integrada > americana > isolada.** Picks the most specific signal
  first. "Cozinha americana" alone → `americana`; "ambientes
  integrados" present → `integrada`. The ambiguous case "cozinha
  americana integrada" lands on `americana` (no integrada-bucket
  phrase fires) — operator confirms during virtual tour per ADR-007.
- **2026-05-04 — `normalize_endereco` collapses "500-A"-style suffixes
  before the number-strip pass.** Without this, the trailing letter
  survived as a stray token (`"500 A"` → `"a"`). Pre-pass joins
  `(\d+)\s*[\-/]\s*([a-z])\b` into `\1\2`, then the standard
  `\b\d+[a-z]?\b` regex strips it as one token.
- **2026-05-04 — Dedup street-number guard.** ADR-006 strips the
  street number from the fingerprint to handle cross-platform
  formatting differences. First live run flagged 597 of 1034 listings
  as possible dups — driven by same-street, same-spec collapse on
  streets with many buildings (Cristiano Viana, Tavares Cabral).
  Added a guard: when both raw `endereco`s expose a number, require
  it to match before flagging. The cross-platform case ADR-006
  designed for (one side hides the number) still falls through to the
  address fingerprint. Dropped the false-positive rate from ~58% →
  ~10%.
- **2026-05-04 — Eligibility recomputed in `enrich.py`, not at scrape
  time.** Server-side filters in Plan 0001 leak a few outliers
  (R$2M/mo and 0-bedroom rows). The eligibility pass also handles the
  `area_min_m2_flex` rule (1 quarto + escritório → relax floor),
  which is conditional on description text and didn't fit cleanly in
  YAML alone. Result: 952 of 1034 rows eligible (the 82 ineligible
  are old outliers + scrape leakage).
- **2026-05-04 — Detail-page fetch reinstated as `cli/details.py`.**
  Initial M2 ship skipped per-listing detail pages because the
  listings API already exposed `description` + `amenities`. Eduardo
  asked to fetch each detail page anyway: ZAP exposes several fields
  only on the rendered page. Verified the curl_cffi transport passes
  Cloudflare for HTML pages too (200 OK, 346 KB), so no Playwright.
  Parser anchors on stable `data-testid` selectors. Pacing 1.5–4s
  between fetches; resumable via `detail_fetched_at < last_seen`
  predicate. Detail-page values overwrite API values where both
  exist (the page is what the operator sees) with `COALESCE(detail,
  db)` falling back when the parser couldn't find a field.
- **2026-05-04 — Detail page yields lat/lng for free (Plan 0005
  preview).** Eduardo flagged the `<iframe data-testid="map-iframe">`
  whose Google Maps `src` carries `q={lat},{lng}` as a query param.
  ZAP renders rooftop-precise coords for listings whose broker
  exposed the street number; neighborhood-centroid otherwise. Added
  to the parser; populates the existing `address_lat`/`address_lng`/
  `address_source='structured'` columns from `db/schema.sql`. This
  preempts the geocoding step Plan 0005 (commute) would otherwise
  need — for the M5 commute calculation we just feed the stored
  coords into the Maps Distance Matrix API directly.
- **2026-05-04 — `endereco` overwritten from
  `data-testid="location-address"`.** The detail page renders the
  full address text ("Rua Marcos Lopes, 272 - Vila Nova Conceição,
  São Paulo - SP") in one piece, including the street number. The
  listings API returns the same parts but joined with commas and
  occasionally drops the streetNumber. Detail-page text takes
  precedence; dedup's street-number guard now sees the more complete
  string when the API hid it.

## Outcome

After `uv run enrich`:

- **1034 rows extracted, 952 eligible.** Per criterion:
  ar_condicionado 670 True / 364 None; lavabo 242 True / 792 None;
  cozinha_layout detected on 129 (108 americana + 21 integrada);
  chuveiro_gas 26 True (under-detected — most listings don't mention
  water heating); vidro_anti_ruido 1 True (correctly rare).
- **84 strong + 17 weak dups flagged** in `v_possible_dups` (down
  from 597 before the street-number guard). Remaining flags are
  plausible republishes — same listing posted twice by different
  brokers with inconsistent address formatting.
- Idempotent on rerun: `extracted=0 normalized=0` when nothing
  changed.

After `uv run details --limit 107` (10% sample to validate before the
full backfill):

- **107/107 (100%)** rows have `descricao`, `anunciante_code`,
  `criado_em`, `endereco`.
- **82/107 (76.6%)** rows have `address_lat` + `address_lng` — the
  remaining 23% are listings whose broker hid the street number on
  the page, so ZAP renders the neighborhood centroid instead of
  rooftop-precise coords (the missing-number share matches the
  missing-coords share exactly, confirming this isn't a parser gap).
- All 107 `anunciante_code` values unique; `criado_em` ranges
  2023-03 → 2026-05 (some long-listed properties); description
  length 100 of 107 in the 300–3000 char range.
- 0 errors, 0 expired listings (404/410), ~3 minutes wall clock at
  1.5–4s pacing.
- Full 1034-row backfill deferred to operator on demand — same CLI,
  same pacing, no code change required.

Quality:

- 88/88 unit tests pass (19 ZAP-API + 6 persist + 24 normalize +
  18 extract + 10 dedup + 11 detail-parser).
- `basedpyright .` 0 errors; `ruff check + format` clean.
