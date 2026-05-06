"""Scraper interface shared by every source.

Each source (`zap`, `quintoandar`, …) implements `Scraper` so the CLI can
iterate sources without knowing platform details. Detail-page enrichment
(Plan 0002) will use `fetch_detail`; M1 only uses `list_listings`.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from aptos_sp.config.filters import FiltersConfig


class ListingStub(BaseModel):
    """Minimal listing data extractable from a search-results page.

    Detail fields (qualitative criteria, full address, photos) are
    populated later by `fetch_detail` + the pipeline.
    """

    source: str
    source_id: str
    url: str
    bairro: str
    endereco: str | None = None
    area_m2: float | None = None
    quartos: int | None = None
    suites: int | None = None
    banheiros: int | None = None
    vagas: int | None = None
    aluguel: float | None = None
    condominio: float | None = None
    iptu: float | None = None
    total: float | None = None
    descricao: str | None = None
    amenities: list[str] = Field(default_factory=list)
    # Source's explicit furnished flag. ZAP encodes it as
    # `"FURNISHED"` in the amenities array; QA exposes a structured
    # `isFurnished` boolean. Parsers normalize both to this field so
    # the local filter has one place to look.
    is_furnished: bool | None = None
    raw_html_hash: str | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ListingDetail(BaseModel):
    """Detail-page payload. Filled by `fetch_detail` once Plan 0002
    activates. Defined here so the M1 scraper can stub it."""

    description: str | None = None
    photos: list[str] = Field(default_factory=list)
    raw_html_hash: str | None = None


@dataclass
class DetailFields:
    """Source-specific detail-page fields, normalized so `cli/details`
    can persist any source's output through the same code path. Each
    source's `parse_detail` returns one of these.

    None means "the page didn't expose this for this listing"; the
    persist step uses `COALESCE(detail, db)` to keep prior values.
    Some fields (the QA-only block below) are still None for ZAP
    today — when ZAP's detail page exposes the equivalent we'll
    populate them too.
    """

    description: str | None = None
    anunciante_code: str | None = None
    criado_em: date | None = None
    endereco: str | None = None
    address_lat: float | None = None
    address_lng: float | None = None
    photos: list[str] = field(default_factory=list)
    # QA detail also exposes the price split (the search-list bundles
    # condo + iptu) and several qualitative flags. ZAP's detail page
    # has equivalents but they're already on the listings API so the
    # detail parser doesn't bother re-emitting them.
    condominio: float | None = None
    iptu: float | None = None
    andar: str | None = None
    accepts_pets: bool | None = None
    near_subway: bool | None = None
    tenant_service_fee: float | None = None
    home_protection_fee: float | None = None
    construction_year: int | None = None


class Scraper(Protocol):
    """Sources implement this protocol. Not an ABC — Protocol keeps the
    contract structural and avoids inheritance ceremony."""

    source: str

    def list_listings(self, config: FiltersConfig) -> list[ListingStub]:
        """Walk search-results pages for every neighborhood in
        `config.bairros`, return every listing found. Filtering against
        `config.filters` happens downstream in pipeline/normalize.py —
        scrapers return everything they see."""
        ...

    def fetch_detail(self, url: str) -> ListingDetail:
        """Visit a detail page; return its parsed payload. M1 stub may
        raise NotImplementedError until Plan 0002."""
        ...
