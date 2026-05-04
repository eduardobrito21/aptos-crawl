# AGENTS.md

You (an AI agent, or a human acting like one) are working in `aptos-crawl`,
a Python pipeline that scrapes apartment listings from ZAP Imóveis and
QuintoAndar, persists them to SQLite, enriches them, and exports a shortlist
to a Notion database for decision-making.

This file is a **table of contents**, not an encyclopedia. It tells you where
to look. The deeper sources of truth live in `docs/`.

## Read first, before doing anything

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — layer map and where to put new
   code.
2. **[docs/product-specs/aptos-sp-spec.md](docs/product-specs/aptos-sp-spec.md)**
   — the product spec: problem, goals, non-goals, success criteria.
3. **[docs/exec-plans/active/](docs/exec-plans/active/)** — the working
   plans, one file per milestone. Find the lowest-numbered plan whose
   **Status** is not `Complete`; that is the current focus.
4. **[docs/adrs/index.md](docs/adrs/index.md)** — the ADR index. Skim the
   titles; read in full any ADR that touches the layer you're modifying.

## How knowledge is organized

| Directory                        | What lives there                                                                                                            |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `docs/product-specs/`            | The product spec and feature specs (e.g. `commute-feature.md`). The "what we're building and why."                          |
| `docs/adrs/`                     | Architecture decision records. Each captures one durable decision and the reasons behind it. Numbered, append-only.         |
| `docs/exec-plans/active/`        | Plans for in-flight work, one per milestone. Updated as work progresses; moved to `completed/` when done.                   |
| `docs/exec-plans/completed/`     | Historical record of finished work. Read-only reference.                                                                    |
| `docs/references/`               | External reference material indexed for agents (e.g. operational tips, library notes).                                      |
| `config/`                        | YAML configuration with `*.example.yaml` committed and `*.yaml` gitignored. Holds filter values, keywords, Notion IDs, etc. |
| `db/`                            | Canonical SQLite schema (`schema.sql`) and migrations.                                                                      |
| [SECURITY.md](SECURITY.md)       | Trust boundaries, secret handling, scraping ethics.                                                                         |
| [RELIABILITY.md](RELIABILITY.md) | Failure model, retry behavior, scraper auto-disable, cost guardrails.                                                       |

## How to work

- **Layered architecture is documented but not mechanically enforced.** Read
  `ARCHITECTURE.md` before adding code; ask "which layer does this belong
  to?" If you're tempted to import upward, that's a smell.
- **Boundary parsing.** Anything crossing a process boundary (filesystem,
  HTTP, scraped HTML, env var, YAML) must be parsed with `pydantic`. Trust
  internal types; never trust external shapes.
- **Decisions go in `docs/adrs/`.** If you make a non-obvious choice (which
  library, what shape, what behavior on edge case X), write a short ADR.
  Numbered (`NNN-slug.md`, three-digit), dated, with **Status / Context /
  Decision / Consequences** sections. Add a `**Related:** NNN[, NNN]` line
  if the decision touches another ADR.
- **Plans are first-class artifacts.** When you start a meaningful piece of
  work, either pick up an existing plan in `docs/exec-plans/active/` or
  write a new one. Update it as you learn.
- **Errors should teach.** When you write a validation error, lint message,
  or thrown exception, phrase it so the next reader knows how to fix it.
- **Boring tools beat clever tools.** `uv`, `playwright` (sync), `sqlite3`
  (stdlib), `pydantic`, `pytest`. Picking technology with stable APIs
  makes the codebase legible to agents (and to you in three months).

## How to run

```sh
uv sync                            # one-time
uv run playwright install chromium # one-time, downloads browser
uv run scrape                      # populate aptos.db
uv run enrich                      # extract qualitative fields from detail pages
uv run commute                     # geocode + bike commute (M5+)
uv run export-notion               # upsert shortlist to Notion
```

Daily: `./daily.sh` runs scrape → enrich → commute → export.

## What this project is — and is not

- **Is:** a local-first pipeline for finding a furnished rental in São Paulo.
  Single user, single workstation, run-it-yourself.
- **Is not:** a multi-user product, a SaaS, or a redistribution of scraped
  data. Personal-use only; the scrapers are deliberately conservative
  (rate-limited, persistent context, respect anti-bot signals).

## When in doubt

Read the relevant exec plan. If still unclear, write the question into the
plan as an open question and surface it. Never silently guess on a
load-bearing decision; capture the decision in an ADR or escalate.
