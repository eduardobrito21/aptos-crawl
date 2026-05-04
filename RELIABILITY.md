# Reliability

This document describes the failure model: what kinds of failures the
pipeline anticipates, how it responds to each, and what guarantees it
provides under degraded conditions.

The behavior described here is binding. If implementation drifts, fix the
implementation — or update this document with an ADR explaining why the
behavior changed.

## Failure classes

### 1. Config / startup failures

Examples: missing `config/filters.yaml`, malformed YAML, missing required
env var (`NOTION_TOKEN` with `export-notion`; `GOOGLE_MAPS_API_KEY` with
`commute`), pydantic validation error on a config file.

- **Fail fast** with a typed, operator-readable error. Do not start a
  scrape run with a broken filters file.
- Validation messages must say *which field* and *why* (e.g. `"filters.yaml: total_max must be positive"`),
  not a raw stack trace.

### 2. Scraper failures

Examples: 403/429 responses, Cloudflare challenge, page timeout, missing
selector, JSON-LD shape change, persistent-context profile burned.

| Failure                            | Response                                                                                 |
| ---------------------------------- | ---------------------------------------------------------------------------------------- |
| 403 / 429 (single request)         | Exponential backoff (2× per retry, cap from `rate_limit.backoff_max_s`).                 |
| Page navigation timeout            | Mark the listing as errored in the run log, continue with next listing.                  |
| Missing required selector          | Log the URL, mark errored, continue. Do not write a half-parsed record.                  |
| 3 consecutive failed runs          | Auto-disable that source in `runs` log (ADR-005). Operator decides whether to debug.     |
| Persistent-context profile burned  | Operator deletes `~/.cache/aptos-sp/playwright-profile/` and re-runs. Documented in ADR-002. |

Per ADR-005, QuintoAndar is treated as best-effort: ZAP failures are more
serious because ZAP is the primary source.

### 3. Enrichment failures

Examples: keyword extraction returns null for everything (regex bug),
Pydantic schema mismatch from LLM output, Google Maps API quota exceeded,
geocoder returns `partial_match` for too many addresses.

- **Keyword extraction** (ADR-007): null is a valid result. Tri-state
  (`True`/`False`/`None`) means "I didn't find evidence." No failure to
  retry; Eduardo confirms during tour virtual.
- **LLM extraction** (ADR-009): off by default. When enabled, schema
  validation failure on the LLM response → log + skip that field; do not
  block the run. Cap daily spend with `LLM_DAILY_BUDGET_USD`.
- **Geocoding / Routes / Elevation** (ADR-010): cache by stable input
  hash. Failure → mark `commute_quality = NULL` for that record;
  continue. Cap daily spend with `MAPS_DAILY_BUDGET_USD` (default $5).

### 4. Notion export failures

Examples: rate limit (429), token expired, database property missing
(`External ID` not added), conflict on a manual field.

- **429** → exponential backoff, retry with jitter. Notion's official
  client handles this; we trust its retry policy.
- **Token expired / 401** → fail fast, surface to operator. No silent
  retries that mask credential rot.
- **Missing `External ID` property** → fail with explicit message
  pointing at ADR-008's manual-setup note.
- **Manual-field conflict** (ADR-008): managed-fields always overwrite.
  To protect a field from overwrite, add it to the manual-only allowlist.

### 5. Cost guardrails

Two budgets, both env-configurable:

- `MAPS_DAILY_BUDGET_USD` (default 5.00) — Google Maps Platform spend.
- `LLM_DAILY_BUDGET_USD` (default 1.00) — Anthropic API spend.

Both are tracked per run and across runs in the `runs` table. When the
daily budget is hit, the relevant pipeline step short-circuits with a
warning; subsequent records get `commute_quality = NULL` or `extracted_by = 'keyword'`
without LLM augmentation.

## Idempotency guarantees

The pipeline is designed to run multiple times per day without duplicating
work or corrupting state.

- **Scrape**: `(source, source_id)` UNIQUE constraint prevents duplicates.
  `last_seen` is updated; `scraped_at` is preserved on first sight.
- **Price history** (ADR-004): `INSERT OR REPLACE` keyed by `(apto_id, snapshot_date)`.
  Last reading of the day wins.
- **Enrich**: only re-runs on records where `raw_html_hash` changed since
  last extraction. Idempotent.
- **Commute** (ADR-010): only runs on records with
  `commute_computed_at IS NULL` or where address changed.
- **Export** (ADR-008): read-before-write. Existing Notion pages are
  updated, not duplicated. Manual fields preserved.

## What survives an interrupted run

The pipeline writes to SQLite as it goes, so a Ctrl+C or crash mid-run
loses only in-flight requests. Specifically:

- Listings already inserted persist; re-running re-fetches only what
  changed.
- The persistent Playwright context survives — cookies/localStorage are
  on disk after each navigation.
- The `runs` row gets `status = 'partial'` if the CLI exits via
  exception. Operator can read the latest run row to see where things
  stopped.

## Liveness invariants

- **No silent infinite loop.** Every retry has a max-attempts cap.
- **No unbounded memory.** HTML payloads are processed and discarded;
  only the parsed record + `raw_html_hash` is kept.
- **No mutable global state.** Configuration is loaded once at startup;
  the rest of the pipeline reads typed config objects.

## Operator levers

When something is wrong, the operator has these tools:

1. **Disable a source.** Edit `filters.yaml` `sources.zap: false` or
   `sources.quintoandar: false`. Pipeline skips that source on the next
   run.
2. **Purge persistent context.** `rm -rf ~/.cache/aptos-sp/playwright-profile/`.
   Restarts the cookie/localStorage state.
3. **Re-export everything.** `uv run export-notion --all` exports all
   records, not just `eligible = TRUE`.
4. **Toggle enrichment layers.** `enrichment.llm: true|false` in
   `filters.yaml`; `commute_enabled: true|false` likewise.
5. **Inspect run history.** `sqlite3 aptos.db 'SELECT * FROM runs ORDER BY started_at DESC LIMIT 10;'`.
