# Plan 0006 — Milestone 6: daily orchestration

**Status:** Not started
**Depends on:** Plans 0001–0005 (all of the steps it orchestrates)

## Goal

Wire the four CLI commands (`scrape`, `enrich`, `commute`,
`export-notion`) into a single daily entrypoint that Eduardo can run
manually or schedule.

## Out of scope

- Email / Telegram alerts for new listings (parking lot in spec §9).
- Cloud orchestration (NG5 in spec).

## Steps

1. Write `daily.sh` (or a `Justfile` recipe `daily`):
   ```sh
   set -euo pipefail
   uv run scrape
   uv run enrich
   uv run commute
   uv run export-notion
   ```
2. Confirm each step writes a row to `runs` so a daily summary is
   inspectable: `sqlite3 aptos.db 'SELECT source, status, n_new, n_errors FROM runs WHERE started_at > date("now", "-1 day");'`.
3. (Optional) `launchd` plist for macOS. Keep it as a one-time setup
   doc in `docs/references/launchd-setup.md` rather than committing the
   plist itself (operator-specific paths).

## Definition of done

- `./daily.sh` (or `just daily`) runs the full pipeline successfully.
- Failing one step does not silently block subsequent steps if the
  failure is recoverable; otherwise fail-fast with `set -euo pipefail`.
- Eduardo runs it daily for ≥ 2 weeks without code changes (SC5).

## Open questions

- Should `daily.sh` skip steps whose previous run today already
  succeeded? (Defer until we have data on whether re-runs are cheap
  enough that we don't care.)

## Decision log

_Empty._
