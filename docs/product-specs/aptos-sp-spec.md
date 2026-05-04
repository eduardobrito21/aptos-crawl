# Aptos SP — Product Spec

**Owner:** Eduardo
**Status:** Draft v1
**Last updated:** 2026-05-04

## 1. Problem

Eduardo is moving from Rio to São Paulo and needs to rent a furnished
apartment in a narrow set of target neighborhoods (Pinheiros, Itaim, Vila Olímpia, Vila Nova Conceição, north Moema).
Searching manually across QuintoAndar, ZAP, and Loft is impractical for
three reasons:

1. **Native filters are weak.** You can't filter by gas-heated shower,
   acoustic glass, suite + half-bath, kitchen layout — the criteria
   that actually drive the decision.
2. **Listings duplicate across platforms.** The same apartment appears
   on 3–4 sites with different prices and photos; comparing them
   side-by-side is a time sink.
3. **Price changes and new listings aren't monitorable.** "Price
   dropped" and "new listing" are weak platform signals; we want real
   history.

## 2. Goals

- **G1.** Reproducible pipeline that scrapes listings from the 6
  target neighborhoods on the target platforms, with structured
  filters (price range, area, bedrooms, parking spots, furnished).
- **G2.** For each eligible listing, extract qualitative details from
  the detail page (gas shower, AC, acoustic glass, kitchen layout,
  etc.). Canonical criteria list: see `config/keywords.yaml`.
- **G3.** Persist data locally in SQLite with price history (detect
  real "price dropped" events).
- **G4.** Export the shortlist to the existing Notion database for
  review and decision-making.
- **G5.** Idempotent: run daily without duplicating entries; dedupe by
  `(source, source_id)`.
- **G6.** Compute bike-commute distance to BTG Pactual (Faria Lima)
  for each listing. Soft filter (does not exclude, but ranks/flags).
  See [commute-feature.md](commute-feature.md) and ADR-010.

## 3. Non-goals

- **NG1.** Do not automate visit scheduling (stays manual via the
  platform).
- **NG2.** Do not automate contact with owners or brokers.
- **NG3.** Do not do heavyweight NLP/scoring on description text now —
  regex/keyword extraction is enough (ADR-007); LLM as an optional
  complementary layer (ADR-009).
- **NG4.** Do not build a web UI. Notion is the UI.
- **NG5.** Do not run in the cloud. Local-first.

## 4. User and flow

Single user: Eduardo. Flow:

1. Edit `config/filters.yaml` with neighborhoods, price range, minimum
   area, etc. (See `config/filters.example.yaml` for the shape.)
2. Run `uv run scrape` → populates `aptos.db`.
3. Run `uv run enrich` → visits detail pages of new listings (with
   rate limiting), fills qualitative fields.
4. Run `uv run commute` → geocoding + bike commute distance to BTG.
5. Run `uv run export-notion` → upserts to the Notion database.
6. Review in Notion (Kanban view), set status, schedule in-person
   visits.
7. Repeat daily. Price history and new listings show up as deltas.

## 5. Data sources

| Source       | Status                  | Risk                      |
| ------------ | ----------------------- | ------------------------- |
| ZAP Imóveis  | **Primary** (phase 1)   | Medium (Cloudflare)       |
| QuintoAndar  | **Secondary** (phase 2) | High (aggressive anti-bot)|
| Loft         | Future                  | Medium                    |
| ImovelWeb    | Future                  | Medium                    |

See ADR-001 (prioritization) and ADR-005 (QA risk).

## 6. Filters (shape)

Filters have the following shape; concrete values live in
`config/filters.example.yaml` (and the gitignored `config/filters.yaml`):

- **Neighborhoods** — canonical list of target neighborhoods.
  Per-platform URL slugs are owned by the scrapers, not by user
  config.
- **Bedroom range** — minimum and maximum.
- **Minimum parking spots.**
- **Minimum area** — with conditional flex (e.g. 1 bedroom +
  office).
- **Furnished** — boolean, required.
- **Maximum monthly total** (rent + condo fee + IPTU).
- **Type** — apartment (exclude flat / kitnet / studio / loft).
- **Rate limit** — delays and backoff (see ADR-002).
- **Sources toggle** — disable a source individually (ADR-005).

Qualitative criteria (extracted from the detail page, **not** search
filters) are defined in `config/keywords.yaml`. See ADR-007.

## 7. Output schema (categories)

Each apartment in Notion has, by category:

- **Identification** — name, neighborhood, address, URL, photos.
- **Structured** — area, R$/m², bedrooms, suites, half-bath,
  bathrooms, parking spots, floor, furnished.
- **Pricing** — rent, condo fee, IPTU, monthly total, history.
- **Qualitative** — gas shower, bidet shower, AC, acoustic glass,
  kitchen layout, internet/fiber.
- **Commute** — km, min, quality (see `commute-feature.md`).
- **Manual** — status (Triage → Visit → Rented), score, notes. These
  fields are never overwritten by export (ADR-008).

The canonical field list lives in the Notion database's properties +
the `MANAGED_FIELDS` constant in `exporters/notion.py`. Notion IDs in
`config/notion.example.yaml`.

## 8. Success criteria

- **SC1.** Collect ≥ 50 eligible listings across the 6 neighborhoods
  in a complete run.
- **SC2.** Detect cross-platform duplicates (same address + area +
  price band) with precision ≥ 80% (ADR-006).
- **SC3.** Detect day-over-day price changes in ≥ 90% of cases where
  the platform signals a change.
- **SC4.** Full pipeline (scrape + enrich + commute + export) runs in
  < 30 minutes for a normal load.
- **SC5.** Eduardo runs it daily without touching code for ≥ 2 weeks.

## 9. Out of scope (parking lot)

- Multi-POI commute scoring (gym, restaurants, market). v1 uses BTG
  Faria Lima only — see ADR-010 OQ1.
- Sentiment analysis on building reviews.
- Email / Telegram alerts for new listings matching criteria.
- Automatic weighted scoring (keep manual via Notion for now).
- Geocoding heatmaps per neighborhood beyond commute use.
