# ADR-003: SQLite as source of truth, Notion as the UI

**Status:** Accepted
**Date:** 2026-05-04
**Related:** 008

## Context

We need to persist scraped data, keep price history, and have an
interface to review and decide. Notion is great as a decision UI
(Kanban, visual filters, mobile), but:

- The API has rate limits and a rigid schema
- Bad for joins, analytical queries, or granular history
- High latency for batch upserts

SQLite is the opposite: fast, queryable, no schema lock-in, but
terrible as a UI.

## Decision

**Local SQLite (`aptos.db`) is the source of truth.** Every scrape
writes there first. **Notion is a projection** —
`exporters/notion.py` does a one-way upsert (SQLite → Notion) of a
pre-filtered view.

Notion **does not write back** to SQLite — exception: manual fields
(Status, Score, Notes) are read from Notion at the start of each
export and merged back into SQLite, so we don't overwrite human
input. "Manual fields are sacred" — see
[ADR-008](008-notion-export.md).

Structure:

- SQLite tables: `aptos`, `precos_historico`, `fotos`,
  `manual_overrides`, `runs`. Canonical schema in
  [`db/schema.sql`](../../db/schema.sql).
- Notion: 1 page per apartment, with properties mirroring a SQLite
  view (`v_notion_export`).

## Consequences

- **Positive:** fast analytical queries; price history is trivial;
  Notion isn't a bottleneck; pipeline is reproducible offline.
- **Negative:** two places to think about (SQLite and Notion); requires
  care to avoid overwriting manual fields. Mitigation:
  `manual_overrides` table is read on every export and takes
  precedence.
- **Neutral:** if we want a remote backup later, `litestream` or rsync
  on the `.db` file is enough.
