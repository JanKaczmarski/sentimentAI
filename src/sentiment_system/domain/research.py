"""Author-approved research sample; separate from the operational registry.

See decisions/0014-transcript-research-universe-and-historical-cache.md.
"""

from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

RESEARCH_TICKERS = ("META", "CRM", "V", "DIS", "WHR", "T")
RESEARCH_SELECTION_VERSION = "thesis-v2-current-cache"
FINAL_CORPUS_VERSION = "thesis-v2-current-cache-sec-form-aware-v2"
EVALUATION_MANIFEST_VERSION = "thesis-v2-current-cache-sec-form-aware-v2-market-v1"

SECTOR_BENCHMARKS = MappingProxyType(
    {
        "Communication Services": "XLC",
        "Consumer Discretionary": "XLY",
        "Consumer Staples": "XLP",
        "Energy": "XLE",
        "Financials": "XLF",
        "Health Care": "XLV",
        "Industrials": "XLI",
        "Information Technology": "XLK",
        "Materials": "XLB",
        "Real Estate": "XLRE",
        "Utilities": "XLU",
    }
)


@dataclass(frozen=True, slots=True)
class CorpusSplit:
    """Decision 0006's five-year window and two-year held-out derivation."""

    start: date
    cutoff: date
    development_ends: date
    held_out_starts: date

    @classmethod
    def from_publications(cls, publications: Iterable[date]) -> "CorpusSplit":
        dates = tuple(publications)
        if not dates:
            raise ValueError("at least one included publication is required")
        cutoff = max(dates)
        boundary = calendar_years_before(cutoff, 2)
        return cls(
            start=calendar_years_before(cutoff, 5),
            cutoff=cutoff,
            development_ends=boundary,
            held_out_starts=min(value for value in dates if value > boundary),
        )


def calendar_years_before(value: date, years: int) -> date:
    """Clamp February 29 to February 28 when the target year is not a leap year."""
    year = value.year - years
    return date(year, value.month, min(value.day, monthrange(year, value.month)[1]))
