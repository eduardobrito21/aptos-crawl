"""ZAP `glue-api` listings client + parser.

The frontend calls `https://glue-api.zapimoveis.com.br/v4/listings`
with a long query string defining city/zone/neighborhood + page +
`includeFields` (an XPath-shaped projection of which response fields
to return). We emit the same shape with a pruned `includeFields` that
keeps only what we persist.

When ZAP changes the JSON shape, this is the one file to update.
"""

import hashlib
import json
from typing import Any
from urllib.parse import urlencode

from aptos_sp.config.filters import Filters
from aptos_sp.scrapers.base import ListingStub
from aptos_sp.scrapers.zap.locations import Location

API_BASE = "https://glue-api.zapimoveis.com.br/v4/listings"
PAGE_SIZE = 30

# Pruned field projection — request only what we persist. The wire
# format mirrors the frontend's request: `field(sub1,sub2)` with
# parens. Adding a field here is harmless; removing one not used by
# the parser is a no-op.
INCLUDE_FIELDS = (
    "search("
    "result(listings(listing("
    "id,address,usableAreas,bedrooms,suites,bathrooms,parkingSpaces,"
    "pricingInfos),link)),"
    "totalCount)"
)

# Headers the ZAP frontend sends — captured from the browser's network
# tab. `X-Domain` (cookie-form, with leading dot) discriminates ZAP from
# VivaReal in the shared backend. Origin/Referer mirror what the
# frontend's CORS-preflighted request looks like; with curl_cffi we
# control them directly (no browser stripping).
API_HEADERS = {
    "x-domain": ".zapimoveis.com.br",
    "origin": "https://www.zapimoveis.com.br",
    "referer": "https://www.zapimoveis.com.br/",
}

# Stable client UUID. ZAP's frontend generates one per first-visit and
# reuses it forever; we hard-code one for our install. Used by their
# analytics + dedup feature flag.
CLIENT_USER_ID = "aptos-sp-eduardo-2026-05"


def build_url(
    location: Location,
    filters: Filters,
    *,
    page: int = 1,
) -> str:
    """Build the listings query URL for one (location, page) applying
    `filters.yaml` server-side.

    Param mapping (captured from the ZAP frontend's network tab):

    | filters.yaml          | API param                                |
    | --------------------- | ---------------------------------------- |
    | quartos_min/max       | bedrooms=1,2,3                           |
    | vagas_min             | parkingSpaces=N,N+1,…,4                  |
    | area_min_m2           | usableAreasMin                           |
    | total_max             | rentalTotalPriceMax + rentTotalPrice=true|
    | mobiliado=true        | amenities=FURNISHED                      |

    `rentTotalPrice=true` makes `rentalTotalPriceMin/Max` apply to the
    *total* (rent + condo), not just the base rent — without it the
    price filter is wrong for our criterion (`total_max=11000`).

    `bedrooms` and `parkingSpaces` take a comma-separated list of exact
    counts. The API caps at 4 (5+ bedrooms is bucketed into 4). To
    express "≥1 vaga" we send "1,2,3,4".
    """
    bedrooms = ",".join(str(n) for n in range(filters.quartos_min, min(filters.quartos_max, 4) + 1))
    parking = ",".join(str(n) for n in range(filters.vagas_min, 5)) if filters.vagas_min > 0 else ""

    params: dict[str, str | int | float] = {
        "business": "RENTAL",
        "listingType": "USED",
        "categoryPage": "RESULT",
        "parentId": "null",
        "user": CLIENT_USER_ID,
        "__zt": "mtc:deduplication2023",
        "addressCity": "São Paulo",
        "addressState": "São Paulo",
        "addressZone": location["zone"],
        "addressNeighborhood": location["neighborhood"],
        "addressStreet": "",
        "addressLocationId": location["location_id"],
        "addressPointLat": location["lat"],
        "addressPointLon": location["lng"],
        "addressType": "neighborhood",
        "unitTypes": "APARTMENT",
        "unitTypesV3": "APARTMENT",
        "unitSubTypes": "UnitSubType_NONE,DUPLEX,TRIPLEX",
        "usageTypes": "RESIDENTIAL",
        "bedrooms": bedrooms,
        "usableAreasMin": int(filters.area_min_m2),
        "rentalTotalPriceMax": int(filters.total_max),
        "rentTotalPrice": "true",
        "page": page,
        "size": PAGE_SIZE,
        "from": (page - 1) * PAGE_SIZE,
        "includeFields": INCLUDE_FIELDS,
        "images": "webp",
    }
    if parking:
        params["parkingSpaces"] = parking
    if filters.mobiliado:
        params["amenities"] = "FURNISHED"
    return f"{API_BASE}?{urlencode(params)}"


def parse_response(payload: dict[str, Any], *, bairro: str) -> list[ListingStub]:
    """Convert glue-api JSON → typed `ListingStub`s."""
    items = payload.get("search", {}).get("result", {}).get("listings", [])
    out: list[ListingStub] = []
    for item in items:
        listing = item.get("listing") or {}
        if not listing.get("id"):
            continue
        out.append(_to_stub(item, bairro))
    return out


def total_count(payload: dict[str, Any]) -> int | None:
    """Extract `search.totalCount` if our `includeFields` projection
    requested it. Returns None when missing (caller paginates blindly)."""
    raw = payload.get("search", {}).get("totalCount")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _to_stub(wrapper: dict[str, Any], bairro: str) -> ListingStub:
    listing = wrapper.get("listing") or {}
    addr = listing.get("address") or {}
    pricing = _first(listing.get("pricingInfos") or [])
    aluguel = _to_float(pricing.get("price")) if pricing else None
    condo = _to_float(pricing.get("monthlyCondoFee")) if pricing else None
    iptu_yearly = _to_float(pricing.get("yearlyIptu")) if pricing else None
    iptu_monthly = (iptu_yearly / 12) if iptu_yearly is not None else None
    total = _sum(aluguel, condo, iptu_monthly)
    # The API's `includeFields` projection doesn't actually return
    # `link` (the frontend builds URLs client-side from listing data we
    # don't have). Synthesize a canonical URL from the id; ZAP's site
    # redirects this form to the slugged URL.
    listing_id = listing.get("id")
    href = (wrapper.get("link") or {}).get("href")
    if href and href.startswith("http"):
        url = href
    elif href:
        url = f"https://www.zapimoveis.com.br{href}"
    elif listing_id:
        url = f"https://www.zapimoveis.com.br/imovel/id-{listing_id}/"
    else:
        url = ""
    raw = json.dumps(wrapper, sort_keys=True, ensure_ascii=False)

    return ListingStub(
        source="zap",
        source_id=str(listing.get("id")),
        url=url,
        bairro=bairro,
        endereco=_address_str(addr),
        area_m2=_first_float(listing.get("usableAreas")),
        quartos=_first_int(listing.get("bedrooms")),
        suites=_first_int(listing.get("suites")),
        banheiros=_first_int(listing.get("bathrooms")),
        vagas=_first_int(listing.get("parkingSpaces")),
        aluguel=aluguel,
        condominio=condo,
        iptu=iptu_monthly,
        total=total,
        raw_html_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def _first(seq: list[Any]) -> Any:
    return seq[0] if seq else None


def _address_str(addr: dict[str, Any]) -> str | None:
    parts = [
        addr.get("street"),
        addr.get("streetNumber"),
        addr.get("neighborhood"),
        addr.get("city"),
    ]
    pieces = [p for p in parts if p]
    return ", ".join(pieces) or None


def _first_int(seq: Any) -> int | None:
    val = _first(seq) if isinstance(seq, list) else seq
    try:
        return int(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _first_float(seq: Any) -> float | None:
    val = _first(seq) if isinstance(seq, list) else seq
    return _to_float(val)


def _to_float(val: Any) -> float | None:
    try:
        return float(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _sum(*vals: float | None) -> float | None:
    nums = [v for v in vals if v is not None]
    return sum(nums) if nums else None
