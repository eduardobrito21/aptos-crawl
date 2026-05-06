"""Single source of truth for "does this listing match `filters.yaml`?"

Used in two places:

1. `cli/enrich._is_eligible` — the per-row eligibility decision that
   sets `aptos.eligible`.
2. `cli/validate_filters` — the audit harness that compares
   server-side-filtered fetches against unfiltered fetches that we
   then run through *this* predicate locally (Plan 0008).

If the predicate accepts a listing here that the server-side filter
rejected, we know the server filter is over-restrictive. If the
server returns a listing that this predicate rejects, the server
filter is under-restrictive. Either way, the source of truth is
this file.

The predicate is field-by-field, with each rule documented inline so
the audit can cite it. Anything that needs the listing's prose
(currently `area_min_with_flex`) goes through `pipeline.normalize`.
"""

from dataclasses import dataclass

from aptos_sp.config.filters import Filters
from aptos_sp.pipeline.normalize import area_min_with_flex
from aptos_sp.scrapers.base import ListingStub

# Plan 0008 audit found that QA's furniture-amenity codes are too
# noisy to use as fallback signal: built-in wardrobes
# (`ARMARIOS_NA_COZINHA`) and similar fixtures show up in
# *unfurnished* listings too. Only the explicit furnished flag is
# trustworthy.
#
# - ZAP: parser sets `stub.is_furnished = "FURNISHED" in amenities`.
# - QA:  parser sets `stub.is_furnished = source["isFurnished"]`.
#
# So `is_mobiliado` reduces to `stub.is_furnished is True`. None
# (unknown) is treated as a reject when `filters.mobiliado=true`,
# per ADR-007's false-negative-preferred stance.


@dataclass(frozen=True)
class FilterReason:
    """Why a listing was rejected. Useful for the audit harness."""

    field: str
    detail: str

    def __str__(self) -> str:
        return f"{self.field}: {self.detail}"


def passes_filters(stub: ListingStub, filters: Filters) -> bool:
    """Returns True iff the listing matches every dimension of
    `filters.yaml`. Cheap; pure; no I/O."""
    return why_rejected(stub, filters) is None


def why_rejected(stub: ListingStub, filters: Filters) -> FilterReason | None:
    """Returns the first reason this listing fails the filter, or None
    if it passes. The audit harness uses this to bucket discrepancies
    by which dimension the server filter and local filter disagree on.
    Order of checks is from cheapest to most opinionated."""
    if stub.quartos is None:
        return FilterReason("quartos", "missing")
    if not (filters.quartos_min <= stub.quartos <= filters.quartos_max):
        return FilterReason(
            "quartos",
            f"{stub.quartos} not in [{filters.quartos_min}, {filters.quartos_max}]",
        )

    if filters.vagas_min > 0:
        if stub.vagas is None:
            return FilterReason("vagas", "missing")
        if stub.vagas < filters.vagas_min:
            return FilterReason("vagas", f"{stub.vagas} < min {filters.vagas_min}")

    if stub.area_m2 is None:
        return FilterReason("area_m2", "missing")
    floor = area_min_with_flex(filters, quartos=stub.quartos, descricao=stub.descricao)
    if stub.area_m2 < floor:
        return FilterReason("area_m2", f"{stub.area_m2} < {floor}")

    if stub.total is None:
        return FilterReason("total", "missing")
    if stub.total > filters.total_max:
        return FilterReason("total", f"{stub.total} > max {filters.total_max}")

    if filters.mobiliado and not is_mobiliado(stub):
        return FilterReason("mobiliado", "no furnished signal")

    return None


def is_mobiliado(stub: ListingStub) -> bool:
    """True iff the source explicitly flagged this listing as
    furnished. None / False both fail."""
    return stub.is_furnished is True
