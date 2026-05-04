# aptos-crawl

Pipeline local para encontrar apartamento de aluguel em São Paulo. Raspa
ZAP Imóveis e QuintoAndar nos bairros-alvo, persiste em SQLite, exporta
para Notion como UI de decisão.

## Status

Specs prontos. Implementação ainda não começou — siga o roadmap em
[docs/exec-plans/active/](docs/exec-plans/active/).

## Stack

- Python 3.12 + [`uv`](https://docs.astral.sh/uv/)
- [Playwright](https://playwright.dev/python/) (sync, Chromium)
- SQLite (stdlib)
- [Notion SDK](https://github.com/ramnes/notion-sdk-py)
- (Opcional) Anthropic API para enrichment via LLM (ADR-009)
- (Opcional) Google Maps Platform para commute (ADR-010)

## Read first

**[AGENTS.md](AGENTS.md)** — table of contents, points to ARCHITECTURE,
the product spec, the active exec plan, and the ADR index.

## How to run

```sh
uv sync
uv run playwright install chromium
cp .env.example .env                          # fill in tokens
cp config/filters.example.yaml config/filters.yaml
cp config/notion.example.yaml config/notion.yaml
cp config/places.example.yaml config/places.yaml

uv run scrape          # populate aptos.db
uv run enrich          # extract qualitative fields
uv run commute         # geocode + bike commute (M5+)
uv run export-notion   # upsert shortlist to Notion
```

Daily: `./daily.sh` (Plan 0006).
