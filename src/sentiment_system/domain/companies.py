"""Canonical company metadata for ingestion and market-data routing."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class Company:
    """Immutable company identity shared by source and market adapters."""

    ticker: str
    display_name: str
    market_routing: str
    currency: str

    def __post_init__(self) -> None:
        for name, value in (
            ("ticker", self.ticker),
            ("display_name", self.display_name),
            ("market_routing", self.market_routing),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if self.ticker != self.ticker.strip().upper():
            raise ValueError("ticker must be normalized uppercase text")
        if len(self.currency) != 3 or not self.currency.isascii() or self.currency != self.currency.upper():
            raise ValueError("currency must be a three-letter uppercase code")


@dataclass(frozen=True, slots=True)
class CompanyRegistry:
    """Immutable lookup over one approved company universe."""

    companies: tuple[Company, ...]
    _lookup: MappingProxyType[str, Company] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not self.companies:
            raise ValueError("companies are required")
        if len({company.ticker for company in self.companies}) != len(self.companies):
            raise ValueError("company tickers must be unique")
        object.__setattr__(self, "_lookup", MappingProxyType({company.ticker: company for company in self.companies}))

    @property
    def tickers(self) -> tuple[str, ...]:
        """Return the approved tickers in registry order."""
        return tuple(company.ticker for company in self.companies)

    def lookup(self, ticker: str) -> Company:
        """Return one approved company or reject an unsupported ticker."""
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("ticker is required")
        normalized = ticker.strip().upper()
        company = self._lookup.get(normalized)
        if company is None:
            raise ValueError(f"unsupported company ticker: {normalized}")
        return company


def _company(ticker: str, display_name: str, market_routing: str = "") -> Company:
    return Company(ticker, display_name, market_routing or ticker, "USD")


APPROVED_COMPANIES: tuple[Company, ...] = (
    _company("AAPL", "Apple Inc."),
    _company("ADBE", "ADOBE INC."),
    _company("ALGM", "ALLEGRO MICROSYSTEMS, INC."),
    _company("ALK", "ALASKA AIR GROUP, INC."),
    _company("AMAT", "APPLIED MATERIALS INC /DE"),
    _company("AMD", "ADVANCED MICRO DEVICES INC"),
    _company("AMZN", "AMAZON COM INC"),
    _company("ANET", "Arista Networks, Inc."),
    _company("ANF", "ABERCROMBIE & FITCH CO /DE/"),
    _company("APH", "AMPHENOL CORP /DE/"),
    _company("ARE", "ALEXANDRIA REAL ESTATE EQUITIES, INC."),
    _company("AVGO", "Broadcom Inc."),
    _company("BLBD", "Blue Bird Corp"),
    _company("BWXT", "BWX Technologies, Inc."),
    _company("CAKE", "CHEESECAKE FACTORY INC"),
    _company("CMCSA", "COMCAST CORP"),
    _company("COST", "COSTCO WHOLESALE CORP /NEW"),
    _company("CRM", "Salesforce, Inc."),
    _company("CRWD", "CrowdStrike Holdings, Inc."),
    _company("DDOG", "Datadog, Inc."),
    _company("DIS", "Walt Disney Co"),
    _company("DUOL", "Duolingo, Inc."),
    _company("ELF", "e.l.f. Beauty, Inc."),
    _company("EPR", "EPR PROPERTIES"),
    _company("EVO", "Evotec SE"),
    _company("FOUR", "Shift4 Payments, Inc."),
    _company("FCN", "FTI CONSULTING, INC"),
    _company("FUBO", "FuboTV Inc."),
    _company("GIS", "GENERAL MILLS INC"),
    _company("GS", "GOLDMAN SACHS GROUP INC"),
    _company("HD", "HOME DEPOT, INC."),
    _company("ISRG", "INTUITIVE SURGICAL INC"),
    _company("KSPI", "Joint Stock Co Kaspi.kz"),
    _company("LULU", "lululemon athletica inc."),
    _company("MAA", "MID AMERICA APARTMENT COMMUNITIES INC."),
    _company("META", "Meta Platforms, Inc."),
    _company("MRP", "Millrose Properties, Inc."),
    _company("MSFT", "MICROSOFT CORP"),
    _company("NLCP", "NewLake Capital Partners, Inc."),
    Company("NOVO B", "Novo Nordisk A/S", "NOVO-B.CO", "DKK"),
    _company("NU", "Nu Holdings Ltd."),
    _company("PINS", "PINTEREST, INC."),
    _company("PLTR", "Palantir Technologies Inc."),
    _company("POOL", "POOL CORP"),
    _company("PYPL", "PayPal Holdings, Inc."),
    _company("RBLX", "Roblox Corp"),
    Company("RHM", "Rheinmetall AG", "RHM.DE", "EUR"),
    _company("SILA", "Sila Realty Trust, Inc."),
    _company("SIRI", "SIRIUS XM HOLDINGS INC."),
    _company("SOFI", "SoFi Technologies, Inc."),
    _company("SOUN", "SOUNDHOUND AI, INC."),
    _company("SPY", "SPDR S&P 500 ETF TRUST"),
    _company("STZ", "CONSTELLATION BRANDS, INC."),
    _company("SYNA", "SYNAPTICS Inc"),
    _company("T", "AT&T INC."),
    _company("TDW", "TIDEWATER INC"),
    _company("TSN", "TYSON FOODS, INC."),
    _company("TTD", "Trade Desk, Inc."),
    _company("UNH", "UNITEDHEALTH GROUP INC"),
    _company("UUUU", "ENERGY FUELS INC"),
    _company("V", "VISA INC."),
    _company("VICI", "VICI PROPERTIES INC."),
    _company("WHR", "WHIRLPOOL CORP /DE/"),
    _company("ZM", "Zoom Communications, Inc."),
)

APPROVED_COMPANY_REGISTRY = CompanyRegistry(APPROVED_COMPANIES)
