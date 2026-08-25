# Company Universe Approval

**Status:** Accepted

**Date:** 2026-08-25

## Scope

The author approved the following active company universe for ingestion:

`AAPL, ADBE, ALGM, ALK, AMAT, AMD, AMZN, ANET, ANF, APH, ARE, AVGO, BLBD,
BWXT, CAKE, CMCSA, COST, CRM, CRWD, DDOG, DIS, DUOL, ELF, EPR, EVO, FOUR,
FCN, FUBO, GIS, GS, HD, ISRG, KSPI, LULU, MAA, META, MRP, MSFT, NLCP, NOVO B,
NU, PINS, PLTR, POOL, PYPL, RBLX, RHM, SILA, SIRI, SOFI, SOUN, SPY, STZ, SYNA,
T, TDW, TSN, TTD, UNH, UUUU, V, VICI, WHR, ZM`.

## Boundary

- This registry is the canonical active ingestion universe.
- It does not expand or replace the six-company thesis and evaluation sample:
  `AAPL`, `MSFT`, `NVDA`, `JPM`, `XOM`, and `JNJ`.
- It does not approve database seeding, data downloading, benchmark mapping,
  source-specific identifiers, or Yahoo Finance exchange suffixes.
- The registry stores the approved display name, market-routing value, and
  trading currency for each company; those values must be implemented from the
  approved source list without adapter-local symbol lists.

## Metadata Policy

- SEC-listed US symbols use their approved ticker as the market-routing value
  and `USD` as currency; display names use the SEC company-title snapshot in
  the local acquisition mapping.
- `EVO` is `Evotec SE`, routes as `EVO`, and uses `USD`.
- `MRP` is `Millrose Properties, Inc.`, routes as `MRP`, and uses `USD`.
- `NOVO B` is `Novo Nordisk A/S`, routes as `NOVO-B.CO`, and uses `DKK`.
- `RHM` is `Rheinmetall AG`, routes as `RHM.DE`, and uses `EUR`.
- `SPY` is retained as the approved `SPDR S&P 500 ETF TRUST` USD ETF entry.
- This metadata is a versioned static registry snapshot. Runtime adapters must
  consume the registry and must not maintain separate ticker lists.
