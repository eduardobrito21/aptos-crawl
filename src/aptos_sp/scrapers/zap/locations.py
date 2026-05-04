"""Neighborhood metadata for ZAP's `glue-api`.

The API takes a `addressLocationId` of the form
`BR>Sao Paulo>NULL>Sao Paulo>{Zone}>{Neighborhood}` plus city/state/zone
breakdowns and a centroid lat/lng. This table mirrors what ZAP's
autocomplete returns — values were copy-pasted from the dropdown URLs
on the live site, not generated.

Stays inside the scraper (not in user config) for the same reason as
the old slug table: ZAP-side details shouldn't leak into `filters.yaml`.
"""

from typing import TypedDict


class Location(TypedDict):
    zone: str
    neighborhood: str
    location_id: str
    lat: float
    lng: float


class UnknownNeighborhood(KeyError):
    """Raised when filters.yaml contains a bairro we have no metadata for.
    Fix: add an entry to LOCATIONS below."""


LOCATIONS: dict[str, Location] = {
    "Pinheiros": {
        "zone": "Zona Oeste",
        "neighborhood": "Pinheiros",
        "location_id": "BR>Sao Paulo>NULL>Sao Paulo>Zona Oeste>Pinheiros",
        "lat": -23.564224,
        "lng": -46.681894,
    },
    "Itaim Bibi": {
        # ZAP groups Itaim Bibi under Zona Sul (verified via their
        # autocomplete), even though SP's official zoning calls it
        # Zona Oeste. Use ZAP's grouping — the API filters by their
        # taxonomy, not the city's.
        "zone": "Zona Sul",
        "neighborhood": "Itaim Bibi",
        "location_id": "BR>Sao Paulo>NULL>Sao Paulo>Zona Sul>Itaim Bibi",
        "lat": -23.585779,
        "lng": -46.677920,
    },
    "Vila Olímpia": {
        "zone": "Zona Sul",
        "neighborhood": "Vila Olímpia",
        "location_id": "BR>Sao Paulo>NULL>Sao Paulo>Zona Sul>Vila Olimpia",
        "lat": -23.594779,
        "lng": -46.685242,
    },
    "Vila Nova Conceição": {
        "zone": "Zona Sul",
        "neighborhood": "Vila Nova Conceição",
        "location_id": "BR>Sao Paulo>NULL>Sao Paulo>Zona Sul>Vila Nova Conceicao",
        "lat": -23.591583,
        "lng": -46.673222,
    },
    "Moema": {
        "zone": "Zona Sul",
        "neighborhood": "Moema",
        "location_id": "BR>Sao Paulo>NULL>Sao Paulo>Zona Sul>Moema",
        "lat": -23.612476,
        "lng": -46.661547,
    },
}


def location_for(bairro: str) -> Location:
    try:
        return LOCATIONS[bairro]
    except KeyError as e:
        raise UnknownNeighborhood(
            f"No ZAP metadata for {bairro!r}. "
            f"Add it to aptos_sp/scrapers/zap/locations.py::LOCATIONS."
        ) from e
