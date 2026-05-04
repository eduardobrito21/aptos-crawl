# Plan 0003 — Milestone 3: Notion export

**Status:** Not started
**Depends on:** Plan 0001 (need data); Plan 0002 helpful but not strict

## Goal

Push the eligible shortlist to the existing Notion database `Aptos SP`
via idempotent upsert, preserving manual fields (Status / Score /
Notas). Per ADR-008.

## Out of scope

- Building a new database in Notion (use the existing one).
- Two-way sync (Notion never writes to SQLite, except for reading
  manual fields back).

## Steps

1. **One-time manual setup:** add an `External ID` rich_text property
   to the existing Notion database. Document this in the plan's
   decision log when done.
2. Create `config/notion.example.yaml` and the gitignored
   `config/notion.yaml` with the operator's real IDs.
3. Implement `aptos_sp/exporters/notion.py`:
   - Define `MANAGED_FIELDS` allowlist constant.
   - Read all existing pages (paginated). Build
     `{external_id → (page_id, manual_fields)}` map.
   - For each row in `v_notion_export`: upsert. Page exists → update
     only `MANAGED_FIELDS`. Page missing → create with all fields.
   - Read manual fields back into `manual_overrides` table.
4. Implement `aptos_sp/cli/export_notion.py`:
   - Default: filter `eligible = TRUE`.
   - Flag `--all` exports everything.
5. Update `runs` log per source category (`export`).

## Definition of done

- After `uv run export-notion`, every eligible row from `aptos.db` has
  a corresponding Notion page.
- Re-running does not duplicate pages.
- Editing Status / Score / Notas in Notion and re-running preserves
  those edits.
- `manual_overrides` table reflects the manual fields after export.

## Open questions

- Notion's rate limits — if we hit them on a 100-row export, do we need
  explicit batching? (Defer until measured.)

## Decision log

_Empty._
