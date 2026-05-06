"""Scraper interface shared by every source.

Each source (`zap`, `quintoandar`, …) implements `Scraper` so the CLI can
iterate sources without knowing platform details. Detail-page enrichment
(Plan 0002) will use `fetch_detail`; M1 only uses `list_listings`.
"""

from datetime import UTC, datetime
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
