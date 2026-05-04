# Commute feature — bike distance to BTG Faria Lima

**Status:** Design (v1 in-scope)
**Owner:** Eduardo
**Related:** ADR-010 (Google Maps Platform decisions),
[exec-plans/active/0005-commute.md](../exec-plans/active/0005-commute.md)

## What this feature does

For each scraped apartment, compute:

- **Distance** by bike to BTG Pactual Faria Lima (km)
- **Time** estimated by bike (minutes)
- **Climb** (total uphill in meters) — optional, via Elevation API
- **Quality enum** — `excellent | good | acceptable | bad`

Display in Notion as `f"{km}km · {min}min"` plus a quality emoji
(🟢 / 🟡 / 🟠 / 🔴). Does not exclude any apartment — soft filter,
ranking only.

## Why

Eduardo will work at BTG Pactual on Faria Lima and use an e-bike as
his primary mode of transport. The 6 target neighborhoods are all
within bike range, but with meaningful variation: northern Vila
Madalena can exceed 5 km, southern Moema likewise. The difference
between 2 km flat and 4 km uphill is life-changing.

Platform decisions (which API, fallback, scope) live in ADR-010. This
document describes the *feature*: how it composes, what lands in the
schema, how it appears in Notion.

## 4 layers

### Layer 1 — address (input)

Each scraper extracts the address however it can:

- ZAP: dedicated field when available (street + neighborhood),
  `endereco` in JSON-LD
- QuintoAndar: "Localização" block on the detail page
- Fallback: regex on the description
  (`r"\b(rua|avenida|av|alameda|al)\.?\s+([^,\n]+)"`)
- LLM as a heavier fallback (ADR-009) when structured extraction fails

Geocoding via Google Geocoding API: address string → `(lat, lng)` +
`formatted_address`. Cache by normalized address.

**Confidence flags** (ADR-010):
- `address_source`: `'structured' | 'regex' | 'llm' | 'geocoded_only'`
- `address_precision`: `'rooftop' | 'street' | 'neighborhood'`

If the geocoder returns `partial_match: true` or `type = 'route'` (a
street without a number), set `address_precision = 'street'`. Distance
has ±200 m of error, acceptable for a soft filter.

### Layer 2 — distance and time (core)

Routes API (Compute Routes endpoint), `BICYCLE` mode:

- **Endpoint:** `https://routes.googleapis.com/directions/v2:computeRoutes`
- **Field mask:** `routes.distanceMeters`, `routes.duration`,
  `routes.polyline.encodedPolyline`. The "Basic" tier covers it.
- **Fixed destination:** lat/lng of BTG Pactual Faria Lima, defined in
  `config/places.yaml`.
- **BICYCLE-mode beta** (ADR-010): if the API returns an "incomplete
  cycling paths" warning, log and continue. If it fails outright, fall
  back to `WALK` mode dividing `duration` by ~3 (bike is ~3x faster
  than walking), and set `commute_route_source = 'walk_estimate'`.
- **Cache** by `(origin_lat, origin_lng, destination, mode)` hash;
  ignore traffic (irrelevant for bike).

### Layer 3 — quality (optional, behind toggle)

Two sub-features, served by different APIs:

**3a — Elevation:**
1. Google Elevation API with the route polyline → array of altitudes.
2. Compute `commute_climb_m` (sum of climbs) and `max_grade_pct`
   (steepest gradient).
3. For 3–4 km of bike near Faria Lima, expect: `total_climb < 50 m` is
   easy, `> 100 m` is tough.

**3b — Cycle paths:**
ADR-010 picks Option C: leave `cycleway_pct` null in v1. Eduardo knows
SP and has intuition for it. Implementing OpenStreetMap (Overpass API)
overlap is a v2 task only if distance + time + elevation aren't
enough.

### Layer 4 — soft filter and ranking

1. **Do not exclude any listing** based on distance.
2. **`commute_quality`** is a simple rule:
   - `excellent`: ≤ 3 km and climb ≤ 30 m
   - `good`: ≤ 4 km and climb ≤ 50 m
   - `acceptable`: ≤ 6 km
   - `bad`: > 6 km
3. **Notion:** "Commute" column shows `f"{km}km · {min}min"` plus a
   quality emoji.

## Schema

The 9 relevant fields live on the `aptos` table. Source of truth:
[`db/schema.sql`](../../db/schema.sql).

Summary (do not duplicate — just for navigation): `address_lat`,
`address_lng`, `address_source`, `address_precision`, `commute_km`,
`commute_min`, `commute_climb_m`, `commute_quality`,
`commute_route_source`, `commute_computed_at`.

## Configuration

`config/places.example.yaml` defines destinations:

```yaml
work:
  name: BTG Pactual - Faria Lima
  address: Av. Brigadeiro Faria Lima, 3477 - Itaim Bibi, São Paulo
  lat: -23.586778
  lng: -46.681972
```

(v1 uses only `work`. Multi-POI is OQ1 of ADR-010 — defer until clear
evidence justifies it.)

## Cost guardrails

Estimate per full run (~50–100 listings):
- Geocoding: ~$0.005/req × 100 = **$0.50**
- Routes API (Basic): ~$0.005/req × 100 = **$0.50**
- Elevation API: ~$0.005/req × 100 = **$0.50**

Total per run: **< $2**. Google Maps Platform monthly free tier is
$200.

`MAPS_DAILY_BUDGET_USD=5.00` env var caps spend; see
[RELIABILITY.md](../../RELIABILITY.md#5-cost-guardrails).

## Pipeline placement

```
scrape → normalize → extract (keyword) → [llm_enrich] → commute → dedup → export
                                                         ^
                                                         └─ layer 1 (geocode) + 2 (routes) + 3a (elevation, opt-in)
```

Idempotent: only runs on listings with `commute_computed_at IS NULL`
or where the address has changed.

## Acceptance criteria

Before considering the feature stable (move ADR-010 to Accepted):

- Geocoding lands correctly on ≥ 90% of addresses with source
  `structured` or `llm`.
- Bike distance differs by < 15% from what the Google Maps app
  returns manually, on a sample of 5–10 listings.
- No unexpected cost overruns above the daily guardrail.
