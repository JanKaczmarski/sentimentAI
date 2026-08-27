"""Tests for the canonical ingestion company registry."""

from dataclasses import FrozenInstanceError

import pytest

from sentiment_system.domain.companies import APPROVED_COMPANY_REGISTRY, Company

APPROVED_TICKERS = (
    "AAPL",
    "ADBE",
    "ALGM",
    "ALK",
    "AMAT",
    "AMD",
    "AMZN",
    "ANET",
    "ANF",
    "APH",
    "ARE",
    "AVGO",
    "BLBD",
    "BWXT",
    "CAKE",
    "CMCSA",
    "COST",
    "CRM",
    "CRWD",
    "DDOG",
    "DIS",
    "DUOL",
    "ELF",
    "EPR",
    "EVO",
    "FOUR",
    "FCN",
    "FUBO",
    "GIS",
    "GS",
    "HD",
    "ISRG",
    "JNJ",
    "JPM",
    "KSPI",
    "LULU",
    "MAA",
    "META",
    "MRP",
    "MSFT",
    "NLCP",
    "NOVO B",
    "NVDA",
    "NU",
    "PINS",
    "PLTR",
    "POOL",
    "PYPL",
    "RBLX",
    "RHM",
    "SILA",
    "SIRI",
    "SOFI",
    "SOUN",
    "SPY",
    "STZ",
    "SYNA",
    "T",
    "TDW",
    "TSN",
    "TTD",
    "UNH",
    "UUUU",
    "V",
    "VICI",
    "WHR",
    "XOM",
    "ZM",
)


def test_registry_contains_exact_approved_universe() -> None:
    assert APPROVED_COMPANY_REGISTRY.tickers == APPROVED_TICKERS


def test_registry_preserves_metadata_for_non_us_and_etf_entries() -> None:
    assert APPROVED_COMPANY_REGISTRY.lookup("NOVO B") == Company(
        ticker="NOVO B",
        display_name="Novo Nordisk A/S",
        market_routing="NOVO-B.CO",
        currency="DKK",
    )
    assert APPROVED_COMPANY_REGISTRY.lookup("RHM").market_routing == "RHM.DE"
    assert APPROVED_COMPANY_REGISTRY.lookup("RHM").currency == "EUR"
    assert APPROVED_COMPANY_REGISTRY.lookup("SPY").display_name == "SPDR S&P 500 ETF TRUST"


def test_registry_lookup_normalizes_tickers_and_rejects_unsupported_values() -> None:
    assert APPROVED_COMPANY_REGISTRY.lookup(" aapl ").ticker == "AAPL"

    with pytest.raises(ValueError, match="unsupported company ticker: UNKNOWN"):
        APPROVED_COMPANY_REGISTRY.lookup("UNKNOWN")


def test_company_metadata_is_immutable_and_validated() -> None:
    company = APPROVED_COMPANY_REGISTRY.lookup("AAPL")

    with pytest.raises(FrozenInstanceError):
        company.currency = "EUR"  # type: ignore[misc]

    with pytest.raises(ValueError, match="currency must be a three-letter uppercase code"):
        Company(
            ticker="TEST",
            display_name="Test Company",
            market_routing="TEST",
            currency="usd",
        )
