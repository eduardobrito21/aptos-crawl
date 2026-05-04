"""Pydantic schema + loader for `config/filters.yaml`.

Falls back to `config/filters.example.yaml` if the operator hasn't created
their own copy yet — that way a fresh clone runs without manual setup. In
practice the operator copies the example and tweaks values.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, PositiveInt

from aptos_sp.config import CONFIG_DIR


class Filters(BaseModel):
    quartos_min: PositiveInt
    quartos_max: PositiveInt
    vagas_min: int = Field(ge=0)
    area_min_m2: float = Field(gt=0)
    area_min_m2_flex: float = Field(
        gt=0,
        description=(
            "Relaxed area floor used when the listing is `1 quarto + escritório`. "
            "Logic in pipeline/normalize.py."
        ),
    )
    mobiliado: bool
    total_max: float = Field(gt=0, description="Rent + condo fee + IPTU ceiling.")
    tipo: Literal["apartamento"]


class RateLimit(BaseModel):
    delay_min_s: float = Field(ge=0)
    delay_max_s: float = Field(ge=0)
    max_concurrent_origins: PositiveInt = 1
    backoff_multiplier: float = Field(gt=1)
    backoff_max_s: float = Field(gt=0)


class Sources(BaseModel):
    zap: bool = True
    quintoandar: bool = True


class Enrichment(BaseModel):
    llm: bool = False
    commute_elevation: bool = False


class FiltersConfig(BaseModel):
    bairros: list[str] = Field(min_length=1)
    filters: Filters
    rate_limit: RateLimit
    sources: Sources
    enrichment: Enrichment


def load(path: Path | None = None) -> FiltersConfig:
    """Load and validate filters config. Defaults to `filters.yaml`,
    falling back to `filters.example.yaml`."""
    target = path or _resolve()
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return FiltersConfig.model_validate(raw)


def _resolve() -> Path:
    real = CONFIG_DIR / "filters.yaml"
    if real.exists():
        return real
    return CONFIG_DIR / "filters.example.yaml"
