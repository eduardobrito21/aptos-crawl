"""QuintoAndar `house-listing-search` API — body builder + parser.

The QA frontend POSTs to `apigw.prod.quintoandar.com.br/v2/search/list`
with a structured filter body and gets back ElasticSearch-shaped hits.
The body's `filters.houseSpecs` maps cleanly to our `filters.yaml`,
which means we can apply the same operator constraints server-side
that ZAP's `glue-api` lets us apply — no client-side post-filter walk.

When QA changes the request shape or response structure, this is the
one file to update.
"""

import hashlib
import json
from typing import Any

from aptos_sp.config.filters import Filters
from aptos_sp.scrapers.base import ListingStub

API_URL = "https://apigw.prod.quintoandar.com.br/house-listing-search/v2/search/list"
PAGE_SIZE = 50

# Fields requested per listing. Matches what the QA frontend asks for,
# minus presentational extras we don't store. Adding a field here is
# harmless; removing one is a no-op for the parser.
DEFAULT_FIELDS: list[str] = [
    "id",
    "rent",
    "totalCost",
    "iptuPlusCondominium",
    "area",
    "address",
    "regionName",
    "neighbourhood",
    "type",
    "forRent",
    "forSale",
    "bedrooms",
    "parkingSpaces",
    "suites",
    "bathrooms",
    "isFurnished",
    "installations",
    "amenities",
    "shortRentDescription",
]

_DETAIL_URL_BASE = "https://www.quintoandar.com.br/imovel/"


def build_body(
    slug: str,
    filters: Filters,
    *,
    offset: int = 0,
    page_size: int = PAGE_SIZE,
    raw: bool = False,
) -> dict[str, Any]:
    """Map `filters.yaml` → QA's POST body. With `raw=True`, drops
    every `filters.yaml`-mirroring constraint from `houseSpecs` and
    `priceRange`, keeping only `houseTypes=["APARTMENT"]` and the
    business context. Used by the Plan 0008 audit.

    Mapping notes:

    | filters.yaml          | API path                                 |
    | --------------------- | ---------------------------------------- |
    | quartos_min/max       | houseSpecs.bedrooms.range.{min,max}      |
    | vagas_min             | houseSpecs.parkingSpace.range.min        |
    | area_min_m2           | houseSpecs.area.range.min                |
    | total_max             | priceRange[0].range.max  (TOTAL_COST)    |
    | mobiliado=true        | houseSpecs.isFurnished=true              |
    | tipo=apartamento      | houseSpecs.houseTypes=["APARTMENT"]      |

    `costType: TOTAL_COST` makes the price filter apply to rent + condo
    + IPTU together — exactly what `total_max` means in our config.
    """
    house_specs: dict[str, Any] = {
        "area": {"range": {}},
        "houseTypes": ["APARTMENT"],
        "bedrooms": {"range": {}},
        "parkingSpace": {"range": {}},
        "bathrooms": {"range": {}},
        "suites": {"range": {}},
        "amenities": [],
        "installations": [],
    }
    price_range: list[dict[str, Any]] = []
    if not raw:
        house_specs["area"]["range"] = {"min": int(filters.area_min_m2_flex)}
        house_specs["bedrooms"]["range"] = {
            "min": filters.quartos_min,
            "max": filters.quartos_max,
        }
        if filters.vagas_min > 0:
            house_specs["parkingSpace"]["range"]["min"] = filters.vagas_min
        if filters.mobiliado:
            house_specs["isFurnished"] = True
        price_range = [
            {
                "costType": "TOTAL_COST",
                "range": {"min": 500, "max": int(filters.total_max)},
            }
        ]

    return {
        "slug": slug,
        "topics": [],
        "fields": DEFAULT_FIELDS,
        "sorting": {"criteria": "RELEVANCE", "order": "DESC"},
        "pagination": {"pageSize": page_size, "offset": offset},
        "context": {"isSSR": False},
        "filters": {
            "businessContext": "RENT",
            "location": {
                "coordinate": {},
                "viewport": {},
                "neighborhoods": [],
                "countryCode": "BR",
            },
            "priceRange": price_range,
            "houseSpecs": house_specs,
        },
        "locationDescriptions": [{"description": slug}],
    }


def parse_response(payload: dict[str, Any]) -> tuple[list[ListingStub], int | None]:
    """Convert apigw response → typed ListingStubs + total count.

    `stub.bairro` is set to the API's `neighbourhood` (raw value, e.g.
    `"Vila Olímpia"`, `"Brooklin"`). The QA slug query is fuzzy-radius
    — a `vila-olimpia` query returns adjacent neighborhoods too — so
    the scraper canonicalizes against `config.bairros` and drops
    listings that don't match a target bairro.

    Response shape (ElasticSearch-style):
        { "hits": { "total": {"value": N, "relation": "Eq"}, "hits": [
            {"_id": "...", "_source": { ...fields... }}, ...
        ]}}
    """
    hits = (payload.get("hits") or {}).get("hits") or []
    stubs: list[ListingStub] = []
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict) or not source.get("id"):
            continue
        stub = _to_stub(source)
        if stub is not None:
            stubs.append(stub)
    return stubs, _extract_total(payload)


def _extract_total(payload: dict[str, Any]) -> int | None:
    total = (payload.get("hits") or {}).get("total")
    if isinstance(total, dict):
        try:
            return int(total.get("value", 0))
        except (TypeError, ValueError):
            return None
    if isinstance(total, int):
        return total
    return None


def _to_stub(source: dict[str, Any]) -> ListingStub | None:
    listing_id = str(source["id"])
    raw = json.dumps(source, sort_keys=True, ensure_ascii=False)
    description = source.get("shortRentDescription")
    amenities = (source.get("amenities") or []) + (source.get("installations") or [])
    amenities_list = [str(a) for a in amenities if a]

    rent = _to_float(source.get("rent"))
    total = _to_float(source.get("totalCost"))
    condo_iptu = _to_float(source.get("iptuPlusCondominium"))

    address = _address_str(source)
    api_bairro = source.get("neighbourhood") or source.get("regionName") or ""
    if not api_bairro:
        # The API occasionally returns hits without a neighbourhood;
        # without one we can't canonicalize against `config.bairros`,
        # so skip rather than guess.
        return None
    is_furnished_raw = source.get("isFurnished")
    is_furnished: bool | None = (
        bool(is_furnished_raw) if isinstance(is_furnished_raw, bool) else None
    )

    return ListingStub(
        source="quintoandar",
        source_id=listing_id,
        url=f"{_DETAIL_URL_BASE}{listing_id}/",
        bairro=str(api_bairro),
        endereco=address,
        area_m2=_to_float(source.get("area")),
        quartos=_to_int(source.get("bedrooms")),
        suites=_to_int(source.get("suites")),
        banheiros=_to_int(source.get("bathrooms")),
        vagas=_to_int(source.get("parkingSpaces")),
        aluguel=rent,
        # QA returns iptu+condo as one bundled number. Store under
        # `condominio` so the schema stays clean; leave `iptu` null. M2
        # eligibility uses `total` directly so this doesn't matter for
        # filtering.
        condominio=condo_iptu,
        iptu=None,
        total=total,
        descricao=description if isinstance(description, str) else None,
        amenities=amenities_list,
        is_furnished=is_furnished,
        raw_html_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def _address_str(source: dict[str, Any]) -> str | None:
    """The API's `address` is just the street name (no number — QA
    hides it). Append the neighborhood + city so dedup has more to
    work with."""
    parts = [
        source.get("address"),
        source.get("neighbourhood") or source.get("regionName"),
        "São Paulo",
    ]
    pieces = [p for p in parts if p]
    return ", ".join(str(p) for p in pieces) or None


def _to_int(val: Any) -> int | None:
    try:
        return int(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_float(val: Any) -> float | None:
    try:
        return float(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None
