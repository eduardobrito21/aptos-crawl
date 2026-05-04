"""Pure-text normalization helpers used by extract + dedup.

Two distinct normalizers:

- `normalize_text` — lowercase + strip accents. Used by keyword
  matching so "ar-condicionado" matches "Ar Condicionado".
- `normalize_endereco` — same, plus drop street prefixes and street
  numbers, so the same apartment listed as "R. dos Pinheiros, 500" and
  "Rua dos Pinheiros 500" collapses to one fingerprint (ADR-006).

`area_min_with_flex` lives here too: the rule is "1 bedroom + office =
allow `area_min_m2_flex`", which is conditional on the listing's prose
and didn't fit cleanly in YAML alone (filters.example.yaml comment).
"""

import re
import unicodedata

from aptos_sp.config.filters import Filters

# Brazilian street prefixes seen in real data. Order doesn't matter
# because we anchor the regex to the start of the string.
_STREET_PREFIXES = (
    r"rua",
    r"r\.?",
    r"avenida",
    r"av\.?",
    r"alameda",
    r"al\.?",
    r"travessa",
    r"trav\.?",
    r"praca",
    r"pca\.?",
    r"estrada",
    r"est\.?",
    r"largo",
    r"rodovia",
    r"rod\.?",
    r"viela",
)
_PREFIX_RE = re.compile(rf"^(?:{'|'.join(_STREET_PREFIXES)})\s+", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+[a-z]?\b", re.IGNORECASE)
# "500-A" / "500/A" appear in a few addresses; collapse to "500a" so the
# later number regex strips them as one token instead of leaving a stray
# "a" behind.
_NUMBER_SUFFIX_RE = re.compile(r"(\d+)\s*[\-/]\s*([a-z])\b", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")

# Substrings that signal "1 bedroom + home office", which justifies the
# `area_min_m2_flex` relaxation. Keep the list small and unambiguous —
# these match against `normalize_text(description)`, so accents/case are
# already stripped.
_OFFICE_HINTS = (
    "escritorio",
    "home office",
    "homeoffice",
    "1 quarto + escritorio",
    "1 dormitorio + escritorio",
    "1 quarto mais escritorio",
)


def normalize_text(s: str | None) -> str:
    """Lowercase + strip accents. Returns "" for None/empty."""
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return no_accents.lower()


def normalize_endereco(s: str | None) -> str | None:
    """Address fingerprint for cross-platform dedup (ADR-006).

    Drops accents, prefixes, numbers, punctuation; collapses whitespace.
    Returns None when the input has no text content left after stripping
    (a bare number like "500" alone yields nothing useful for matching).
    """
    if not s:
        return None
    text = normalize_text(s).strip()
    text = _NUMBER_SUFFIX_RE.sub(r"\1\2", text)
    text = _PREFIX_RE.sub("", text)
    text = _NUMBER_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text or None


def area_min_with_flex(filters: Filters, *, quartos: int | None, descricao: str | None) -> float:
    """Return the area floor that should apply to one listing.

    Default = `filters.area_min_m2`. Drop to `area_min_m2_flex` when the
    listing is a 1-bedroom whose description mentions an office /
    `escritório` (the conditional that filters.yaml's comment defers to
    code).
    """
    if quartos == 1 and descricao:
        norm = normalize_text(descricao)
        if any(hint in norm for hint in _OFFICE_HINTS):
            return filters.area_min_m2_flex
    return filters.area_min_m2
