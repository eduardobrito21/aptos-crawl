# Security

This document describes the trust model, the secrets the pipeline handles,
and the operational safety invariants the codebase enforces.

## Trust posture

`aptos-crawl` is a **single-operator, local-only** pipeline. That means:

- Eduardo owns the host machine, the Notion workspace, and any API tokens.
- All credentials (`NOTION_TOKEN`, `GOOGLE_MAPS_API_KEY`,
  `ANTHROPIC_API_KEY`) authorize full access scoped to those tokens.
- The pipeline does not run on shared infrastructure, does not accept
  network input, and does not redistribute scraped data.

This is **not** suitable for multi-user deployment, public hosting, or
sharing scraped output beyond the operator.

## Trust boundaries

| Boundary                            | Direction | Trust assumption                                                                                |
| ----------------------------------- | --------- | ----------------------------------------------------------------------------------------------- |
| Operator → `config/*.yaml`          | Inbound   | Trusted: local, operator-authored. Validated by pydantic at load time.                          |
| Scraped HTML / JSON-LD              | Inbound   | **Untrusted shape.** Parse defensively; never `eval`, never trust class names, validate types.  |
| Notion API responses                | Inbound   | Untrusted shape, trusted operator. Pydantic-parse before merging into SQLite.                   |
| Google Maps API responses           | Inbound   | Untrusted shape, trusted operator. Pydantic-parse.                                              |
| Operator → SQLite (`aptos.db`)      | Inbound   | Trusted (file is local). No remote write path exists.                                           |
| Pipeline → Notion / Google / LLM    | Outbound  | Trusted credentials; never log secrets.                                                         |

## Secrets

The pipeline reads up to four credentials, all from environment variables:

- `NOTION_TOKEN` — Notion integration token. Used by `exporters/notion.py`.
- `GOOGLE_MAPS_API_KEY` — Geocoding + Routes + Elevation APIs (ADR-010).
  Required only when `commute` enrichment is enabled.
- `ANTHROPIC_API_KEY` — used by `pipeline/llm_enrich.py` (ADR-009).
  Required only when `enrichment.llm: true` in `filters.yaml`.
- `HEADED` — not a secret; opt-in flag for headed Playwright debugging
  (ADR-002).

Rules:

- Secrets are read from environment variables only. Never check secrets
  into the repo or into `config/*.yaml`. `.env` is gitignored;
  `.env.example` documents the keys without values.
- Validate presence of required secrets at startup. The CLI should fail
  fast with a clear "GOOGLE_MAPS_API_KEY missing — required for commute
  enrichment" rather than crashing partway through a run.
- Never echo a secret value in logs, error messages, or commit
  diagnostics. Logging "key prefix: AIza..." is **not** acceptable.

## Filesystem and data invariants

- **`aptos.db`** — gitignored. Contains scraped data; treat as private.
  Backups go to a local path the operator controls, never to a public
  destination.
- **`~/.cache/aptos-sp/playwright-profile/`** — Playwright persistent
  context (cookies, localStorage). Treat as a session token equivalent.
  Don't commit, don't share, purge if a site flags the profile as
  suspicious (see ADR-002).
- **`config/*.yaml` (non-`.example`)** — gitignored. May contain Notion
  IDs and tuning parameters specific to the operator's workspace.

## Scraping ethics

This project's scrapers visit sites that have anti-bot protections and
terms of service. The codebase respects those signals:

- **Rate limit.** 2–5s randomized delays between requests on the same
  origin. Configurable in `filters.yaml` under `rate_limit:`.
- **Backoff.** Exponential backoff on 403/429 (ADR-002).
- **Auto-disable.** If a source fails 3 runs in a row, it disables itself
  in the `runs` log and stops attempting (ADR-005).
- **No anti-detection arms race.** No fingerprint rotation, no proxy
  pools, no captcha solvers. Persistent context + realistic UA + delays.
  If that's not enough, the source gets dropped, not escalated.
- **Personal use only.** Scraped data lives in the operator's local
  SQLite and Notion. Not redistributed.

## Reporting

This is a personal project; there is no formal disclosure process. If you
find an issue worth raising (e.g. a credential leak path or an unsafe
parsing pattern), open a GitHub issue or contact the maintainer directly.
