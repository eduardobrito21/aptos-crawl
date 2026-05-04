# ADR-008: Idempotent Notion export with manual fields preserved

**Status:** Accepted
**Date:** 2026-05-04
**Related:** 003

## Context

Notion is the decision UI. Eduardo edits Status, Score, and Notes
manually. The SQLite export must not overwrite those fields. It also
needs to be idempotent (run multiple times per day without creating
duplicates).

## Decision

**Pipeline `exporters/notion.py`:**

1. **Read-before-write.** Before exporting, read all existing pages
   from the Notion database via API. Build a map
   `{external_id → (notion_page_id, manual_fields)}`. `external_id` =
   `<source>:<source_id>` (e.g. `zap:2520502009`).
2. **External ID.** Use a database property (rich_text "External ID",
   to be added to the current schema) as the dedup key. Page exists?
   Update. Doesn't exist? Create.
3. **Manual fields preserved.** Status, Score, Notes — if they're
   filled in Notion, **do not** overwrite. Implemented as an
   allowlist in the exporter:
   `MANAGED_FIELDS = {Apartment, Neighborhood, Address, URL, Rent, Condo, IPTU, ...}`
   — only those are updated.
4. **Conflict rule.** Managed fields **always** overwrite on export.
   To protect a field from overwrite, move it out of `MANAGED_FIELDS`
   into the manual-only allowlist. E.g. if Eduardo decides to edit
   "Rent" manually on some apartments, removing `Rent` from
   `MANAGED_FIELDS` is the way to do it — not trying to detect a
   diff.
5. **Notion SDK via `notion-client`.** Use the official Python SDK.
   ADR-008 doesn't cover auth (assume `NOTION_TOKEN` env var).
6. **Export filter.** By default export only `eligible = TRUE`
   apartments (passed `filters.yaml`). Flag `--all` forces a full
   export.

Notion IDs (page, database, data source) live in
`config/notion.example.yaml` (committed) +
`config/notion.yaml` (gitignored).

## Consequences

- **Positive:** Eduardo can trust Notion as a workspace — the script
  doesn't destroy annotations.
- **Negative:** "External ID" must be added to the existing Notion
  database (one-time manual schema migration).
- **Neutral:** if we ever replace Notion with a different UI, only
  the exporter changes.
