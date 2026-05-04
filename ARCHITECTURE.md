# Architecture

This document is the map. It defines the layers, the allowed dependencies
between them, and where to put new code.

The rules described here are **prose-only** for now. Layer violations are not
mechanically enforced (no `import-linter` config). The package is small;
discipline + code review is the enforcement mechanism. Revisit if violations
start slipping in.

## One process, one package

`aptos-crawl` is a single Python package run from the CLI. There is no
daemon, no HTTP server, no UI. Notion serves as the decision UI; SQLite is
the source of truth.

```
src/aptos_sp/
├── cli/            # entry points: scrape, enrich, commute, export-notion
├── pipeline/       # extract, dedup, normalize, geocode, commute, llm_enrich
├── scrapers/       # base.py + zap.py + qa.py
├── exporters/      # notion.py
└── db/             # conn.py, schema loader, migrations
```

## Layers

Imports may only travel **from a higher layer to a lower layer** (or to
`config/` and `db/`, which are widely shared).

```
        cli/
          ↓
   ┌──────┼──────┐
   ↓      ↓      ↓
pipeline scrapers exporters
   └──────┼──────┘
          ↓
         db/
          ↓
        config/
```

### Layer responsibilities

| Layer        | Purpose                                                                                                                      | May depend on                  |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| `config/`    | Pydantic schemas for `filters.yaml`, `keywords.yaml`, `notion.yaml`, `places.yaml`. Loads + validates YAML at startup.       | nothing                        |
| `db/`        | SQLite connection helpers, schema loader, migrations. Reads `db/schema.sql`.                                                 | `config`                       |
| `scrapers/`  | `Scraper` base class, ZAP and QA implementations. Visits pages with Playwright, parses HTML, returns typed records.          | `config`, `db` (writes only)   |
| `pipeline/`  | Pure transformation logic: keyword extraction, normalization, dedup heuristics, geocoding, commute enrichment, LLM fallback. | `config`, `db`                 |
| `exporters/` | Notion export with read-before-write idempotency (ADR-008).                                                                  | `config`, `db`                 |
| `cli/`       | Entry points exposed via `[project.scripts]` in `pyproject.toml`. Wires concrete components, no business logic.              | all of the above               |

### Why this direction

Lower layers are **policy-free**. `scrapers/` knows how to fetch a ZAP
listing; it does not know whether to dedupe or how to score commute.
`pipeline/` knows how to normalize an address; it does not know whether
that's part of dedup or commute. `cli/` is the only place where decisions
about ordering, retry policy, and what runs when live.

This means:

- Tests for `pipeline/extract.py` don't need a scraper or a Notion mock.
- Swapping ZAP for ImovelWeb requires touching only `scrapers/`.
- Replacing Notion with another decision UI requires touching only
  `exporters/`.

## Boundary parsing

Every value crossing a process boundary must be parsed with `pydantic`
before it enters the typed core:

| Boundary                                   | Parser                              |
| ------------------------------------------ | ----------------------------------- |
| `config/filters.yaml`                      | `aptos_sp/config/filters.py`        |
| `config/keywords.yaml`                     | `aptos_sp/config/keywords.py`       |
| `config/notion.yaml` + env vars            | `aptos_sp/config/notion.py`         |
| `config/places.yaml`                       | `aptos_sp/config/places.py`         |
| Scraped JSON-LD / DOM extraction           | `aptos_sp/scrapers/<source>/parse.py` |
| Notion API responses (read-before-write)   | `aptos_sp/exporters/notion_schema.py` |
| Google Maps API responses                  | `aptos_sp/pipeline/maps_schema.py`  |
| LLM extraction output (when ADR-009 active)| `aptos_sp/pipeline/llm_schema.py`   |

Inside the typed core, values are trusted. Outside it, nothing is.

## Where new code goes

- **A new scraper** → `scrapers/<source>/`. Same `Scraper` interface as
  `zap` and `qa`. URL-slug mapping (e.g. neighborhood name →
  source-specific slug) lives inside the scraper, not in user-facing
  config.
- **A new pipeline step** (geocoding, dedup, scoring) → `pipeline/<name>.py`.
  Pure function preferred; takes a record, returns an enriched record.
- **A new exporter** → `exporters/<target>.py`. Read-before-write to
  preserve manual fields if the target supports manual edits.
- **A new entry point** → `cli/<name>.py` + register in
  `pyproject.toml`'s `[project.scripts]`.
- **A new SQLite column or table** → edit `db/schema.sql` and add a
  migration in `db/migrations/`.
- **A new config field** → add to the relevant pydantic schema in
  `config/`, update the `*.example.yaml`, document the field's meaning.

## Where new code does NOT go

- A `utils/` or `helpers/` directory. Utilities accumulate entropy. Put
  helpers in the lowest layer that needs them; if two layers genuinely
  need the same helper, that's a signal to push it into `config/` (if
  pure data) or factor a small focused module.
- The CLI layer. CLI wires; it does not implement. Don't put extraction
  logic in `cli/scrape.py` — put it in `pipeline/` and call from `cli/`.
- The schema dump in prose docs. `db/schema.sql` is canonical. ADRs and
  feature specs *describe* the schema; they don't redefine it.
