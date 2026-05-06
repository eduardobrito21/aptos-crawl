"""QA detail-page fetcher + parser.

QA's listing detail pages are Next.js-rendered (`__NEXT_DATA__`
script tag) — same SSR pattern as their search pages. The parser
extracts the JSON payload and reads
`props.pageProps.initialState.house.houseInfo`, which exposes:

- `generatedDescription.longDescription` — rich broker text (the
  `shortRentDescription` we already had in the search-list response
  is a 1-line summary; this is the multi-paragraph version).
- `displayId` — public-facing listing id (the QA equivalent of
  ZAP's "Código do anunciante").
- `lastPublishedDate` — ISO-8601 timestamp; we store the date.
- `address.street` / `.neighborhood` / `.city` / `.lat` / `.lng` —
  rooftop-precise coords (QA hides the street number publicly, so
  no `street_number` field on the public surface).

When QA changes the JSON shape, this file is the one to update.

Network strategy mirrors `scrapers/zap/detail.py`: `curl_cffi` with
Chrome TLS impersonation. Cloudflare passes the same way.
"""

import json
import re
from datetime import date, datetime

from curl_cffi import requests as curl_requests

from aptos_sp.scrapers.base import DetailFields

DETAIL_TIMEOUT_S = 30
DETAIL_IMPERSONATE = "chrome124"

DETAIL_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" [^>]*>(.*?)</script>',
    re.DOTALL,
)


class QaDetailFetchError(RuntimeError):
    """Raised when the detail page returns non-200 or its
    `__NEXT_DATA__` is missing/malformed."""


def fetch_detail_html(url: str) -> str:
    resp = curl_requests.get(
        url,
        headers=DETAIL_HEADERS,
        impersonate=DETAIL_IMPERSONATE,
        timeout=DETAIL_TIMEOUT_S,
    )
    if resp.status_code != 200:
        snippet = resp.text[:200] if resp.text else ""
        raise QaDetailFetchError(f"{url} → HTTP {resp.status_code} (body: {snippet!r})")
    return resp.text


def parse_detail(html: str) -> DetailFields:
    house_info = _extract_house_info(html)
    if not house_info:
        return DetailFields()
    return DetailFields(
        description=_extract_description(house_info),
        anunciante_code=_extract_display_id(house_info),
        criado_em=_extract_criado_em(house_info),
        endereco=_extract_endereco(house_info),
        address_lat=_extract_lat(house_info),
        address_lng=_extract_lng(house_info),
        condominio=_to_float(house_info.get("condoPrice")),
        iptu=_to_float(house_info.get("iptu")),
        andar=_extract_andar(house_info),
        accepts_pets=_to_bool(house_info.get("acceptsPets")),
        near_subway=_to_bool(house_info.get("isNearSubway")),
        tenant_service_fee=_to_float(house_info.get("tenantServiceFee")),
        home_protection_fee=_to_float(house_info.get("homeProtection")),
        construction_year=_to_int(house_info.get("constructionYear")),
    )


def _extract_house_info(html: str) -> dict[str, object] | None:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    house = payload.get("props", {}).get("pageProps", {}).get("initialState", {}).get("house", {})
    info = house.get("houseInfo") if isinstance(house, dict) else None
    return info if isinstance(info, dict) else None


def _extract_description(info: dict[str, object]) -> str | None:
    """Prefer the rich `generatedDescription.longDescription`; fall
    back to the search-list-style `shortRentDescription`."""
    gd = info.get("generatedDescription")
    if isinstance(gd, dict):
        long_desc = gd.get("longDescription")
        if isinstance(long_desc, str) and long_desc.strip():
            return long_desc.strip()
        short = gd.get("shortRentDescription")
        if isinstance(short, str) and short.strip():
            return short.strip()
    return None


def _extract_display_id(info: dict[str, object]) -> str | None:
    """`displayId` is QA's public listing code; treat it as the
    `anunciante_code` analogue. Fall back to the internal `id` if
    `displayId` isn't exposed."""
    raw = info.get("displayId")
    if raw is not None:
        text = str(raw).strip()
        if text:
            return text
    inner = info.get("id")
    return str(inner) if inner is not None else None


def _extract_criado_em(info: dict[str, object]) -> date | None:
    raw = info.get("lastPublishedDate")
    if not isinstance(raw, str):
        return None
    # Format: "2025-11-21T17:36:46.000Z"
    cleaned = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        return None


def _extract_endereco(info: dict[str, object]) -> str | None:
    addr = info.get("address")
    if not isinstance(addr, dict):
        return None
    parts = [
        addr.get("street"),
        addr.get("neighborhood"),
        addr.get("city"),
    ]
    pieces = [str(p).strip() for p in parts if p]
    if not pieces:
        return None
    base = ", ".join(pieces)
    state = addr.get("stateAcronym")
    if state:
        base = f"{base} - {state}"
    return base


def _extract_lat(info: dict[str, object]) -> float | None:
    addr = info.get("address")
    if not isinstance(addr, dict):
        return None
    return _to_float(addr.get("lat"))


def _extract_lng(info: dict[str, object]) -> float | None:
    addr = info.get("address")
    if not isinstance(addr, dict):
        return None
    return _to_float(addr.get("lng"))


def _to_float(val: object) -> float | None:
    try:
        return float(val) if val not in (None, "") else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_int(val: object) -> int | None:
    try:
        return int(val) if val not in (None, "") else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_bool(val: object) -> bool | None:
    """QA encodes flags as actual bools; pass-through with `None`
    when the field is missing entirely."""
    if isinstance(val, bool):
        return val
    return None


def _extract_andar(info: dict[str, object]) -> str | None:
    """Render `rangeFloor: {min, max}` as the Portuguese string the
    QA UI shows (e.g. "4° a 7° andar"). Mirrors `aptos.andar TEXT`
    so it round-trips through the DB unchanged."""
    rf = info.get("rangeFloor")
    if not isinstance(rf, dict):
        return None
    lo = _to_int(rf.get("min"))
    hi = _to_int(rf.get("max"))
    if lo is None and hi is None:
        return None
    if lo is None or hi is None:
        single = lo if lo is not None else hi
        return f"{single}° andar"
    if lo == hi:
        return f"{lo}° andar"
    return f"{lo}° a {hi}° andar"
