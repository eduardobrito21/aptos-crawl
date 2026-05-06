"""`uv run validate-filters` — audit server-side filters against the
canonical local predicate (Plan 0008).

Per source, per axis combination, the harness compares:

- **A (raw + local-filter)** — one raw fetch per source per run
  (apartment + RENT + bairro only), then `passes_filters` applied
  in-memory with the *tested filter* (operator value on the chosen
  axes, permissive baseline everywhere else).
- **B (server-filtered)** — a fresh server fetch with that same
  tested filter sent over the wire.

We compare the resulting `(source, source_id)` sets:

- `|A ∩ B|` — both layers agreed.
- `|A \\ B|` — server rejected, local accepted ⇒ server filter is
  over-restrictive on those axes.
- `|B \\ A|` — server accepted, local rejected ⇒ server filter is
  under-restrictive *or* the local predicate is wrong. Inspect.

Holding the trusted axes (apartment, RENT, bairro) constant and
toggling one or two suspect axes per run isolates which dimension
disagrees. Default: a single all-axes-on run (back-compat). Pass
`--axes a,b` for one combination, `--combinatorial` for every single
axis plus every 2-axis pair.

Suspect axes: `bedrooms`, `parking`, `area`, `mobiliado`, `total`.

Defaults to **one bairro** so the unfiltered raw fetch stays under
each API's offset cap (ZAP < 1500, QA ≤ 1000). Override via
`--bairro NAME` (repeatable).
"""

import argparse
import itertools
import sys
from collections.abc import Iterable

from aptos_sp.config import filters as filters_config
from aptos_sp.config.filters import Filters, FiltersConfig
from aptos_sp.pipeline.local_filter import passes_filters, why_rejected
from aptos_sp.scrapers.base import ListingStub
from aptos_sp.scrapers.qa import QaScraper
from aptos_sp.scrapers.zap import ZapScraper

SOURCES = {
    "zap": ZapScraper,
    "quintoandar": QaScraper,
}

# Axes the operator can mix into a tested filter. Order is the
# preferred display order in reports.
AXES: tuple[str, ...] = ("bedrooms", "parking", "area", "mobiliado", "total")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    base_config = filters_config.load()

    audited = list(args.source) if args.source else list(SOURCES)
    bairros = list(args.bairro) if args.bairro else [base_config.bairros[0]]
    config = base_config.model_copy(update={"bairros": bairros})

    combos = _combos_to_run(args)

    overall = 0
    for source in audited:
        if source not in SOURCES:
            print(f"unknown source: {source}", file=sys.stderr)
            return 2
        print(f"\n=== validating {source} (bairros={bairros}) ===")
        try:
            ran_any_discrepancy = _audit_source(source, config, combos)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            overall = 1
            continue
        overall = overall or (1 if ran_any_discrepancy else 0)
    return overall


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="validate-filters", description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCES),
        help="source to audit (repeatable; defaults to all)",
    )
    parser.add_argument(
        "--bairro",
        action="append",
        help="bairro to audit (repeatable; defaults to first in filters.yaml)",
    )
    parser.add_argument(
        "--axes",
        type=_parse_axes,
        action="append",
        metavar="a,b,...",
        help=(
            "axes to vary in this combo (comma-separated). "
            f"Choices: {', '.join(AXES)}. Repeatable for multiple combos."
        ),
    )
    parser.add_argument(
        "--combinatorial",
        action="store_true",
        help=(
            "run every single-axis combo AND every 2-axis pair, "
            "plus the all-on combo. Multiplies the server-fetch count; "
            "default audits one bairro."
        ),
    )
    return parser.parse_args(argv if argv is not None else sys.argv[1:])


def _parse_axes(value: str) -> tuple[str, ...]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    bad = [p for p in parts if p not in AXES]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown axis/axes: {bad}. Choices: {', '.join(AXES)}")
    # Preserve canonical order so display + caching is stable.
    return tuple(a for a in AXES if a in parts)


def _combos_to_run(args: argparse.Namespace) -> list[tuple[str, ...]]:
    """Decide which axis combinations to test. Order: singletons,
    pairs, then anything explicit the operator passed."""
    if args.combinatorial:
        singles = [(a,) for a in AXES]
        pairs = [tuple(p) for p in itertools.combinations(AXES, 2)]
        return [*singles, *pairs, AXES]
    if args.axes:
        return list(args.axes)
    # Backwards-compatible default: the all-on combo.
    return [AXES]


def _audit_source(source: str, config: FiltersConfig, combos: list[tuple[str, ...]]) -> bool:
    """Run every combo against one source. Reuses one raw fetch."""
    scraper_cls = SOURCES[source]

    print("  pass A: one raw fetch (apartment + RENT + bairro) ...", flush=True)
    raw_stubs = scraper_cls(raw=True).list_listings(config)
    print(f"    raw_returned={len(raw_stubs)}", flush=True)
    cap_hint = _cap_hint(source, raw_stubs, n_bairros=len(config.bairros))
    if cap_hint:
        print(f"    ⚠ {cap_hint}", flush=True)

    any_disc = False
    for axes in combos:
        any_disc = _run_combo(source, scraper_cls, config, raw_stubs, axes) or any_disc
    return any_disc


def _run_combo(
    source: str,
    scraper_cls: type,
    config: FiltersConfig,
    raw_stubs: list[ListingStub],
    axes: tuple[str, ...],
) -> bool:
    label = "+".join(axes) if axes else "(none)"
    print(f"\n  --- combo: {label} ---", flush=True)
    tested = filters_for_axes(config.filters, axes)
    a_listings = [s for s in raw_stubs if passes_filters(s, tested)]

    tested_config = config.model_copy(update={"filters": tested})
    server_listings = scraper_cls(raw=False).list_listings(tested_config)

    report = _Report(source, a_listings, server_listings, tested_config, axes)
    report.print()
    return report.has_discrepancy()


# Permissive baseline (all axes effectively off).
_PERMISSIVE_BASELINE: dict[str, object] = {
    "quartos_min": 1,
    # ZAP buckets 5+ bedrooms into 4, so 1..4 covers the full range.
    "quartos_max": 4,
    "vagas_min": 0,
    "area_min_m2": 1.0,
    "area_min_m2_flex": 1.0,
    "mobiliado": False,
    "total_max": 9_999_999.0,
}

_AXIS_TO_FIELDS: dict[str, tuple[str, ...]] = {
    "bedrooms": ("quartos_min", "quartos_max"),
    "parking": ("vagas_min",),
    "area": ("area_min_m2", "area_min_m2_flex"),
    "mobiliado": ("mobiliado",),
    "total": ("total_max",),
}


def filters_for_axes(operator: Filters, axes: Iterable[str]) -> Filters:
    """Build a `Filters` that constrains only the named axes to the
    operator's `filters.yaml` values; everything else stays
    permissive. Used so each axis combination tests *only* that axis
    (or pair) and isn't conflated with constraints from other
    dimensions."""
    update = dict(_PERMISSIVE_BASELINE)
    for axis in axes:
        for field in _AXIS_TO_FIELDS[axis]:
            update[field] = getattr(operator, field)
    return operator.model_copy(update=update)


class _Report:
    def __init__(
        self,
        source: str,
        a_listings: list[ListingStub],
        b_listings: list[ListingStub],
        config: FiltersConfig,
        axes: tuple[str, ...],
    ) -> None:
        self.source = source
        self.config = config
        self.axes = axes
        self.a = {(s.source, s.source_id): s for s in a_listings}
        self.b = {(s.source, s.source_id): s for s in b_listings}
        self.intersection = self.a.keys() & self.b.keys()
        self.a_only = self.a.keys() - self.b.keys()
        self.b_only = self.b.keys() - self.a.keys()

    def has_discrepancy(self) -> bool:
        return bool(self.a_only) or bool(self.b_only)

    def print(self) -> None:
        a, b, both = len(self.a), len(self.b), len(self.intersection)
        print(f"    A (raw + local) = {a:>4}    B (server) = {b:>4}    A∩B = {both:>4}")
        print(
            f"    A \\ B = {len(self.a_only):>4}  (server over-restrictive)    "
            f"B \\ A = {len(self.b_only):>4}  (server under-restrictive or local wrong)"
        )
        if not self.has_discrepancy():
            print("    ✓ filters agree")
            return

        if self.a_only:
            print("    A \\ B sample (server rejected; local accepted):")
            for key in list(self.a_only)[:3]:
                _print_stub(self.a[key])

        if self.b_only:
            print("    B \\ A sample (server accepted; local rejected):")
            for key in list(self.b_only)[:3]:
                stub = self.b[key]
                reason = why_rejected(stub, self.config.filters)
                _print_stub(
                    stub, why=str(reason) if reason else "(passes_filters True; raw-fetch miss?)"
                )


def _cap_hint(source: str, raw_stubs: list[ListingStub], *, n_bairros: int) -> str | None:
    """ZAP's glue-api caps offset at 1500 (50 pages × 30); QA's
    apigw caps at 1000. When raw fetch nears the cap, `B \\ A` is
    contaminated with listings A could never enumerate."""
    cap_per_bairro = 1500 if source == "zap" else 1000
    threshold = int(cap_per_bairro * 0.9 * max(n_bairros, 1))
    if len(raw_stubs) >= threshold:
        return (
            f"raw fetch likely hit the API offset cap "
            f"({cap_per_bairro}/bairro × {n_bairros}). "
            "B \\ A may include listings A could not enumerate."
        )
    return None


def _print_stub(stub: ListingStub, *, why: str | None = None) -> None:
    parts = [
        f"{stub.source_id}",
        f"q={stub.quartos}",
        f"v={stub.vagas}",
        f"area={stub.area_m2}",
        f"total={stub.total}",
        f"furnished={stub.is_furnished}",
    ]
    print("      " + "  ".join(parts))
    if why:
        print(f"        why_rejected: {why}")
    if stub.endereco:
        print(f"        endereco: {stub.endereco}")


if __name__ == "__main__":
    raise SystemExit(main())
