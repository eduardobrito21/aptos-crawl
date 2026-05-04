# ADR-004: Price history via daily snapshot with dedup

**Status:** Accepted
**Date:** 2026-05-04

## Context

Platforms signal "price dropped" but hide the date and the previous
value. We want to detect real changes and have a price history for
decision-making (an apartment that drops 10% in a week is a different
signal than a stable one).

Options:

- **Append-only (insert on every run):** simple, but grows fast
  (thousands of identical rows).
- **On-change (compare to last value before insert):** fewer rows,
  but needs comparison logic.
- **Daily snapshot (dedupe per day):** balance — at most one row per
  (apt, day), losing intra-day granularity (which we don't care
  about).

## Decision

**Daily snapshot with dedup.** `precos_historico` table with PK
`(apto_id, snapshot_date)`. Behavior:

- On every run, `INSERT OR REPLACE` for `(apto_id, today)` — the last
  reading of the day wins.
- Before inserting, compare to the most recent reading. If it
  changed, set `is_change = TRUE`.
- View `v_precos_changes` filters to only changes → easy to review.

## Consequences

- **Positive:** low volume, trivial query for price charting; "new
  price" logic is clear via flag.
- **Negative:** if you run 10 times in one day, only the last reading
  is kept. Acceptable — we have no intraday signal.
- **Neutral:** if we ever need to detect listing reactivation
  (disappeared for X days then came back), `last_seen` on `aptos`
  handles it.
