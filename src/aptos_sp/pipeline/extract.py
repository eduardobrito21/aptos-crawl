"""Qualitative-criteria extraction from listing descriptions (ADR-007).

Inputs: a free-text Portuguese description (`descricao`) plus a list of
structured amenity codes from the source (e.g. ZAP's `LAVABO`,
`AIR_CONDITIONING`). Output: a `QualitativeFields` record with one
tri-state per criterion (True / False / None) and a string for
`cozinha_layout`.

Two signals, in order:

1. `keywords.yaml` matched against `normalize_text(descricao)`.
   Positive list → True, negative list → False, neither → None. Per
   ADR-007, we prefer false negatives over false positives.
2. Source amenity codes that map unambiguously to a criterion (e.g.
   ZAP's `LAVABO` flag is more reliable than fishing "lavabo" out of
   prose). When the keyword pass returned None, an amenity hit promotes
   to True. Amenities never overturn an explicit negative — keywords
   are higher-signal for those (e.g. "sem ar condicionado").

`cozinha_layout` is a special case: keywords.yaml stores a sub-keyed
shape (isolada / americana / integrada) instead of positive/negative.
Returns the first sub-key whose phrases match, else None.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from aptos_sp.config import CONFIG_DIR
from aptos_sp.pipeline.normalize import normalize_text

KEYWORDS_PATH = CONFIG_DIR / "keywords.yaml"

CozinhaLayout = Literal["isolada", "americana", "integrada"]

# Amenities that map 1:1 to a criterion. Conservative — only codes
# whose meaning is unambiguous. Anything fuzzy ("HEATING" → could be
# central heating, not a gas shower) stays out.
_AMENITY_MAP: dict[str, str] = {
    "AIR_CONDITIONING": "ar_condicionado",
    "LAVABO": "lavabo",
}


@dataclass
class QualitativeFields:
    chuveiro_gas: bool | None = None
    chuveirinho: bool | None = None
    ar_condicionado: bool | None = None
    vidro_anti_ruido: bool | None = None
    cozinha_layout: CozinhaLayout | None = None
    lavabo: bool | None = None


@lru_cache(maxsize=1)
def _load_keywords(path: Path | None = None) -> dict[str, dict[str, list[str]]]:
    """Parse `keywords.yaml`. Cached: same data on every call until the
    process restarts. Tests pass an explicit path to bypass the cache
    via a fresh function call."""
    target = path or KEYWORDS_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    # Normalize keyword strings up-front so matching is a substring
    # check, not a re-normalize per listing.
    return {
        criterion: {
            bucket: [normalize_text(k) for k in keywords] for bucket, keywords in buckets.items()
        }
        for criterion, buckets in raw.items()
    }


def extract_qualitative(
    descricao: str | None, amenities: list[str] | None = None
) -> QualitativeFields:
    """Run the keyword + amenity pass, return a typed record."""
    keywords = _load_keywords()
    text = normalize_text(descricao)
    amenity_set = {a.upper() for a in (amenities or [])}

    fields = QualitativeFields()
    fields.chuveiro_gas = _tristate(text, keywords.get("chuveiro_gas"))
    fields.chuveirinho = _tristate(text, keywords.get("chuveirinho"))
    fields.ar_condicionado = _tristate(text, keywords.get("ar_condicionado"))
    fields.vidro_anti_ruido = _tristate(text, keywords.get("vidro_anti_ruido"))
    fields.lavabo = _tristate(text, keywords.get("lavabo"))
    fields.cozinha_layout = _cozinha_layout(text, keywords.get("cozinha_layout"))

    # Amenities only fill nulls — they don't overturn explicit negatives.
    for code, criterion in _AMENITY_MAP.items():
        if code in amenity_set and getattr(fields, criterion) is None:
            setattr(fields, criterion, True)

    return fields


def _tristate(text: str, buckets: dict[str, list[str]] | None) -> bool | None:
    if not buckets:
        return None
    if any(kw and kw in text for kw in buckets.get("negative", [])):
        return False
    if any(kw and kw in text for kw in buckets.get("positive", [])):
        return True
    return None


def _cozinha_layout(text: str, buckets: dict[str, list[str]] | None) -> CozinhaLayout | None:
    """Sub-keyed match. The first layout whose phrases hit wins. Order
    follows specificity: 'integrada' > 'americana' > 'isolada' so that
    "cozinha americana integrada" lands on 'integrada' (the more
    specific signal)."""
    if not buckets or not text:
        return None
    for layout in ("integrada", "americana", "isolada"):
        for phrase in buckets.get(layout, []):
            if phrase and phrase in text:
                return layout
    return None
