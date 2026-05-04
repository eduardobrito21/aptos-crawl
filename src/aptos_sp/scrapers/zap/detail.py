"""ZAP detail-page fetcher + parser.

The listings API (`api.py`) returns description + amenities, but several
fields are only on the rendered listing page:

- `anunciante_code` — the broker's internal listing id, e.g. "AP000701"
- `criado_em` — "Anúncio criado em 18 de abril de 2026"
- `endereco` — full address with street number, from
  `data-testid="location-address"` (the API gives address pieces
  separately and sometimes drops the number; the page text is what
  matches the building's mailing address)
- `address_lat` / `address_lng` — extracted from the embedded Google
  Maps iframe `q={lat},{lng}` parameter. ZAP renders rooftop-precise
  coords for listings whose broker exposed the number, neighborhood
  centroid otherwise. These feed Plan 0005 (commute distance) directly
  — no separate geocoding step needed.

Plus the detail page is the canonical source for the broker's free-text
description; we use that to overwrite whatever the listings API
returned (in practice they match, but the page is what a user sees).

Network strategy mirrors `api.py`: `curl_cffi` with Chrome TLS
impersonation. CF blocks plain HTTPS GET on the operator's IP for HTML
pages too, so the same fingerprint trick from ADR-012 applies here.
"""

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qs, urlparse

from curl_cffi import requests as curl_requests

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

# Anchored on the section that wraps the rendered description block. The
# `data-testid` selectors are stable in ZAP's frontend; if they ever
# change, this single file needs to update (mirrors api.py's "one place
# to update" promise).
_DESCRIPTION_RE = re.compile(
    r'<p[^>]*data-testid="description-content"[^>]*>(.*?)</p>',
    re.DOTALL | re.IGNORECASE,
)
# "Código do anunciante: <!-- -->AP000701<!-- -->" — Next.js inserts
# server-component comment placeholders, hence the loose pattern.
_ANUNCIANTE_RE = re.compile(
    r"C[óo]digo do anunciante:\s*(?:<!--[^>]*-->\s*)?([A-Za-z0-9_-]{2,32})",
    re.IGNORECASE,
)
# "Anúncio criado em 18 de abril de 2026, atualizado há 12 horas." —
# the date sits in a span with `data-testid="listing-created-date"`.
_CRIADO_EM_RE = re.compile(
    r'data-testid="listing-created-date"[^>]*>[^<]*?An[úu]ncio criado em\s*'
    r"(?:<!--[^>]*-->\s*)?(\d{1,2})\s+de\s+([a-zçãéíóúâêô]+)\s+de\s+(\d{4})",
    re.IGNORECASE,
)
# Full address with street number — the page format is:
# `<p data-testid="location-address">Rua Marcos Lopes, 272 - Vila Nova
# Conceição, São Paulo - SP</p>`. Tags inside (the location svg icon
# is a sibling, not a child) so we just need the inner text.
_LOCATION_ADDRESS_RE = re.compile(
    r'data-testid="location-address"[^>]*>([^<]+)</p>',
    re.IGNORECASE,
)
# Embedded Google Maps iframe carries the rooftop-precise coords as a
# `q=lat,lng` query param. Two-step match: find the iframe tag whose
# data-testid is `map-iframe` (attribute order in the rendered HTML
# isn't stable — `src` can appear before or after `data-testid`), then
# pull `src` from inside the matched tag. The `&` between params is
# HTML-escaped as `&amp;` in the source.
_MAP_IFRAME_TAG_RE = re.compile(
    r'<iframe[^>]*\bdata-testid="map-iframe"[^>]*>',
    re.IGNORECASE,
)
_IFRAME_SRC_RE = re.compile(r'\bsrc="([^"]+)"', re.IGNORECASE)

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")

_MONTHS_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


@dataclass
class DetailFields:
    description: str | None
    anunciante_code: str | None
    criado_em: date | None
    endereco: str | None
    address_lat: float | None
    address_lng: float | None


class DetailFetchError(RuntimeError):
    """Raised when a detail page returns non-200 or unparseable HTML."""


def fetch_detail_html(url: str) -> str:
    """GET an HTML detail page and return its body. Raises
    `DetailFetchError` on non-200; ZAP intermittently 404s expired
    listings, which the caller treats as "skip"."""
    resp = curl_requests.get(
        url,
        headers=DETAIL_HEADERS,
        impersonate=DETAIL_IMPERSONATE,
        timeout=DETAIL_TIMEOUT_S,
    )
    if resp.status_code != 200:
        snippet = resp.text[:200] if resp.text else ""
        raise DetailFetchError(f"{url} → HTTP {resp.status_code} (body: {snippet!r})")
    return resp.text


def parse_detail(html: str) -> DetailFields:
    """Extract every detail-page field we care about. Each field is
    independent: a missing one returns None rather than failing the
    whole parse, so a layout change to one block doesn't nuke the rest.
    """
    lat, lng = _extract_lat_lng(html)
    return DetailFields(
        description=_extract_description(html),
        anunciante_code=_extract_anunciante_code(html),
        criado_em=_extract_criado_em(html),
        endereco=_extract_endereco(html),
        address_lat=lat,
        address_lng=lng,
    )


def _extract_description(html: str) -> str | None:
    match = _DESCRIPTION_RE.search(html)
    if not match:
        return None
    return _html_to_text(match.group(1))


def _extract_anunciante_code(html: str) -> str | None:
    match = _ANUNCIANTE_RE.search(html)
    if not match:
        return None
    code = match.group(1).strip()
    return code or None


def _extract_criado_em(html: str) -> date | None:
    match = _CRIADO_EM_RE.search(html)
    if not match:
        return None
    day, month_pt, year = match.groups()
    month = _MONTHS_PT.get(month_pt.lower())
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _extract_endereco(html: str) -> str | None:
    match = _LOCATION_ADDRESS_RE.search(html)
    if not match:
        return None
    text = match.group(1).replace("&nbsp;", " ").strip()
    return text or None


def _extract_lat_lng(html: str) -> tuple[float | None, float | None]:
    """Pull `q=lat,lng` from the embedded Maps iframe `src`. ZAP's
    rendered HTML escapes `&` as `&amp;`, which `urlparse` doesn't
    decode — handle both forms before parsing."""
    tag_match = _MAP_IFRAME_TAG_RE.search(html)
    if not tag_match:
        return None, None
    src_match = _IFRAME_SRC_RE.search(tag_match.group(0))
    if not src_match:
        return None, None
    src = src_match.group(1).replace("&amp;", "&")
    qs = parse_qs(urlparse(src).query)
    raw = (qs.get("q") or [""])[0]
    if not raw or "," not in raw:
        return None, None
    try:
        lat_str, lng_str = raw.split(",", 1)
        return float(lat_str), float(lng_str)
    except ValueError:
        return None, None


def _html_to_text(fragment: str) -> str | None:
    """Convert the description HTML fragment to plain text:
    `<br>` → newline, drop other tags, collapse runs of whitespace per
    line, strip surrounding whitespace. Matches what a human would copy
    out of the page and what `pipeline/extract.py` keyword-matches
    against."""
    fragment = _BR_RE.sub("\n", fragment)
    fragment = _TAG_RE.sub("", fragment)
    fragment = fragment.replace("&nbsp;", " ")
    lines = [_WS_RE.sub(" ", line).strip() for line in fragment.split("\n")]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned or None
