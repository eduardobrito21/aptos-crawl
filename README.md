# aptos-crawl

Pipeline local para encontrar apartamento de aluguel em São Paulo. Raspa
ZAP Imóveis e QuintoAndar nos bairros-alvo, persiste em SQLite, exporta
para Notion como UI de decisão.

## Status

Shipped:

- Milestone 1 — ZAP scraper via `curl_cffi` + `glue-api`
  ([Plan 0001](docs/exec-plans/completed/0001-milestone-1-zap.md)).
- Milestone 2 — enrichment, dedup, ZAP detail-page fetch
  ([Plan 0002](docs/exec-plans/completed/0002-milestone-2-enrich-dedup.md)).
- Milestone 4 — QuintoAndar scraper via apigw filtered API
  ([Plan 0004](docs/exec-plans/completed/0004-milestone-4-quintoandar.md)).
- Plan 0008 — server-side filter audit harness + ZAP parser fixes
  ([Plan 0008](docs/exec-plans/completed/0008-validate-server-side-filters.md)).
- Plan 0009 — QuintoAndar detail-page enrichment
  ([Plan 0009](docs/exec-plans/completed/0009-milestone-2-part-2-qa-details.md)).

Roadmap (see [docs/exec-plans/active/](docs/exec-plans/active/)):
Milestone 3 Notion export (Plan 0003), Milestone 5 commute (Plan 0005),
Milestone 6 daily orchestration (Plan 0006). Plan 0007 LLM enrichment
is `Inactive` until [ADR-009](docs/adrs/009-llm-enrichment.md) flips to
Accepted.

## Stack

- Python 3.12 + [`uv`](https://docs.astral.sh/uv/)
- [`curl_cffi`](https://github.com/lexiforest/curl_cffi) Chrome TLS
  impersonation — primary transport for ZAP + QA scraping
  ([ADR-011](docs/adrs/011-zap-glue-api.md),
  [ADR-012](docs/adrs/012-curl-cffi-tls-impersonation.md))
- [Playwright](https://playwright.dev/python/) (sync, Chromium) —
  retained as auth/session fallback ([ADR-002](docs/adrs/002-playwright-sync.md))
- SQLite (stdlib)
- Planned: [Notion SDK](https://github.com/ramnes/notion-sdk-py) (Plan 0003),
  Google Maps Platform ([ADR-010](docs/adrs/010-google-maps-platform.md), Plan 0005),
  Anthropic API ([ADR-009](docs/adrs/009-llm-enrichment.md), Plan 0007).

## Read first

**[AGENTS.md](AGENTS.md)** — table of contents, points to ARCHITECTURE,
the product spec, the active exec plan, and the ADR index.

## How to run

```sh
uv sync
uv run playwright install chromium
cp .env.example .env                          # fill in tokens
cp config/filters.example.yaml config/filters.yaml
cp config/places.example.yaml config/places.yaml

uv run scrape             # populate aptos.db (ZAP + QA search)
uv run details            # fetch detail pages for new listings
uv run enrich             # extract qualitative fields (ADR-007)
uv run validate-filters   # audit server-side vs. local filter agreement
```

Roadmap commands (not yet implemented):

```sh
uv run commute            # geocode + bike commute (Plan 0005)
uv run export-notion      # upsert shortlist to Notion (Plan 0003)
./daily.sh                # full daily pipeline (Plan 0006)
```
