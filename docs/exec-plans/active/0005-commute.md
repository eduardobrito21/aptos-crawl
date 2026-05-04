# Plan 0005 — Milestone 5: commute enrichment

**Status:** Not started
**Depends on:** Plan 0001 (data); Plan 0003 (Notion column)
**Spec:** [docs/product-specs/commute-feature.md](../../product-specs/commute-feature.md)
**Decision:** [docs/adrs/010-google-maps-platform.md](../../adrs/010-google-maps-platform.md)

## Goal

Implement the commute feature end-to-end so each apto in `aptos.db`
has populated `commute_*` columns and a "Commute" column shows up in
the Notion view.

## Out of scope

- Cycleway-quality detection (Opção C in ADR-010 — deferred to v2).
- Multi-POI commute scoring (ADR-010 OQ1 — v1 is BTG only).
- Bike-electric vs regular bike modeling (accept ~20% time error per
  ADR-010 OQ2).

## Steps

1. **Setup:**
   - Enable Geocoding, Routes, Elevation APIs in Google Cloud Console.
   - Add `GOOGLE_MAPS_API_KEY` to `.env`.
   - Create `config/places.example.yaml` and the gitignored
     `config/places.yaml` with BTG Faria Lima coords.
   - Confirm BTG lat/lng (the example file has a placeholder marked
     "confirmar quando montar o repo").
2. **Geocoding** (`aptos_sp/pipeline/geocode.py`):
   - Function `geocode(endereco) -> GeocodeResult` with pydantic-typed
     response.
   - Set `address_source` based on which extraction path produced the
     input: `structured` / `regex` / `llm` / `geocoded_only`.
   - Set `address_precision` based on Google's `partial_match` and
     `types[]` fields.
   - Cache by normalized endereco hash.
3. **Routes** (`aptos_sp/pipeline/commute.py`):
   - Function `compute_route(origin, destination, mode)` with field
     mask `routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline`.
   - BICYCLE first; on failure or warning, fall back to WALK / 3 and
     set `commute_route_source = 'walk_estimate'`.
   - Cache by `(origin, destination, mode)` hash.
4. **Elevation (opt-in):**
   - If `commute_elevation: true` in `filters.yaml`, call Elevation API
     with the polyline; compute `commute_climb_m`.
5. **Quality enum** (`aptos_sp/pipeline/commute.py`):
   - Apply the rule from `commute-feature.md` §"Camada 4":
     `excellent` ≤ 3km/30m climb, `good` ≤ 4km/50m, `acceptable` ≤ 6km,
     `bad` > 6km.
6. **CLI** (`aptos_sp/cli/commute.py`):
   - For each row with `commute_computed_at IS NULL` or where address
     changed, run geocode → routes → (elevation) → quality.
   - Update `runs` log with `maps_cost_usd`.
   - Respect `MAPS_DAILY_BUDGET_USD` cap; short-circuit with warning.
7. **Notion column:**
   - Add a "Commute" property to the Notion database (manual one-time
     step; document in decision log).
   - Update `MANAGED_FIELDS` in `exporters/notion.py` to include it.
   - Format: `f"{km:.1f}km · {min}min"` + emoji
     (🟢 excellent / 🟡 good / 🟠 acceptable / 🔴 bad).

## Definition of done

- After `uv run commute` on a fresh batch of aptos, all rows have
  `commute_km`, `commute_min`, `commute_quality` set (or `NULL` with
  reason in log if address could not be geocoded).
- Notion view shows the "Commute" column with formatted values + emoji.
- Cost stays under `MAPS_DAILY_BUDGET_USD` for normal runs.

## Open questions

- See ADR-010 OQs.

## Decision log

_Empty._
