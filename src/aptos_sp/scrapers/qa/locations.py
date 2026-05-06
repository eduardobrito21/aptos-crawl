"""Bairro → QuintoAndar URL slug mapping.

QA's search-results URL is `/alugar/imovel/{slug}` (page 1) or
`/alugar/imovel/{slug}/{page}` (subsequent pages). The slug is
`{neighborhood-slug}-{city}-{state}-{country}`, all lowercased and
hyphenated, accents stripped — matches what QA's autocomplete returns.

Stays inside the scraper for the same reason as `zap/locations.py`:
QA-side details shouldn't leak into `filters.yaml`.
"""


class UnknownNeighborhood(KeyError):
    """Raised when filters.yaml contains a bairro we have no QA slug
    for. Fix: add an entry to LOCATIONS below."""


# Slug = `{neighborhood}-{city}-{state}-{country}` lowercased, hyphenated,
# no accents. Verified against QA's live URLs.
LOCATIONS: dict[str, str] = {
    "Pinheiros": "pinheiros-sao-paulo-sp-brasil",
    "Itaim Bibi": "itaim-bibi-sao-paulo-sp-brasil",
    "Vila Olímpia": "vila-olimpia-sao-paulo-sp-brasil",
    "Vila Nova Conceição": "vila-nova-conceicao-sao-paulo-sp-brasil",
    "Moema": "moema-sao-paulo-sp-brasil",
}


def slug_for(bairro: str) -> str:
    try:
        return LOCATIONS[bairro]
    except KeyError as e:
        raise UnknownNeighborhood(
            f"No QA slug for {bairro!r}. Add it to aptos_sp/scrapers/qa/locations.py::LOCATIONS."
        ) from e
