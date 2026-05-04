# ADR-010: Google Maps Platform for commute enrichment

**Status:** Proposed
**Date:** 2026-05-04
**Related:** 007, 009

## Context

The commute feature (see
[commute-feature.md](../product-specs/commute-feature.md)) needs three
capabilities: geocoding (address → lat/lng), routing (bike distance
and time), and optionally elevation (total climb on the route).
Alternatives:

- **Google Maps Platform (GMP):** Geocoding API + Routes API (with
  `BICYCLE` mode in beta) + Elevation API. Monthly free tier $200.
  Mature documentation, official SDK.
- **OpenStreetMap (Overpass + OSRM):** zero cost, but bike routing is
  immature, geocoding (Nominatim) is less precise for Brazilian
  addresses, and the operational complexity is high (rate limits,
  self-maintained).
- **Mapbox / HERE:** comparable in capability, but they add another
  vendor without a clear advantage over GMP.

What quick research revealed:

- **Routes API `BICYCLE` mode is in beta.** Documentation warns that
  cycle-path coverage may be incomplete. In São Paulo proper it
  probably works reasonably, but it's not guaranteed.
- **Route quality** (cycle-path presence) doesn't come through REST
  directly. The JS API's `BicyclingLayer` is visualization-only.
- **Elevation API is a separate endpoint** (not bundled with Routes).

## Decision

Adopt **Google Maps Platform** as the single provider for commute,
with the following stances:

1. **Geocoding API** for address → `(lat, lng)`. Cache by normalized
   address.
2. **Routes API (Compute Routes), `BICYCLE` mode,** for distance and
   time. Field mask: `routes.distanceMeters`, `routes.duration`,
   `routes.polyline.encodedPolyline`. "Basic" tier covers it.
3. **Accept BICYCLE-mode beta with fallback.** If the API returns an
   "incomplete cycling paths" warning, log and continue. If it fails
   outright, fall back to `WALK` mode dividing `duration` by ~3
   (bike is ~3x faster than walking) and set
   `commute_route_source = 'walk_estimate'`.
4. **Elevation API is opt-in** (toggle `commute_elevation: true` in
   `filters.yaml`). When on, populates `commute_climb_m`.
5. **Cycle-path quality deferred to v2.** Option C in the design
   doc: leave `cycleway_pct` null. Eduardo knows SP and has
   intuition. Implement Overpass + spatial join only if v1 isn't
   enough.
6. **Soft filter only.** Distance never disqualifies an apartment. It
   only ranks / flags via the `commute_quality` enum.
7. **Street-level address precision (±200 m) is acceptable.** Marked
   via the `address_precision` flag. If commute ever becomes a hard
   filter, revisit.

## Cost guardrails

Estimate per full run (~50–100 listings): ~$2/run. Monthly free tier
$200 — personal use is nowhere close.

`MAPS_DAILY_BUDGET_USD` env var (default $5) caps spend. When hit,
the pipeline stops calling GMP for the rest of the run (see
[RELIABILITY.md](../../RELIABILITY.md#5-cost-guardrails)).

## Consequences

- **Positive:**
  - One vendor covers all three capabilities.
  - Cost manageable, well within free tier.
  - Mature SDK and docs — low learning cost.
- **Negative:**
  - One more API key to manage.
  - BICYCLE in beta = may produce odd results. Mitigate with
    `commute_route_source` flag and a validation sample before
    trusting.
  - Imprecise addresses (street level, no number) introduce ±200 m
    of error — fine for soft filter, bad if it ever becomes a hard
    filter.
  - Moderate GMP lock-in. Switching would mean rewriting 3 calls;
    not the end of the world.

## Acceptance criteria (Proposed → Accepted)

Validate against 5–10 real listings before marking Accepted:

- Geocoding lands correctly on ≥ 90% of addresses with source
  `structured` or `llm`.
- Bike distance differs by < 15% from what the Google Maps app
  returns manually.
- No unexpected cost overruns above the guardrail.
