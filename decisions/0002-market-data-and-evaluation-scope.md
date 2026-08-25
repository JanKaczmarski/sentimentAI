# Market Data And Evaluation Scope Decisions

**Status:** Accepted

**Date:** 2026-08-17

## Local Market Price Snapshot

- The author-supplied Kaggle archive at `/Users/jwdev/Downloads/archive` is a
  local development input.
- Only exact CSV files for the development snapshot were copied to the
  separate data repository below `$SENTIMENT_DATA_ROOT/data/market_prices/`;
  no other archive files were copied, moved, or deleted.
- `SPY` is present in the development snapshot and was copied from the
  archive's ETF collection. All other selected files came from its stock
  collection.
- The copied files are unmodified local data artifacts and are not the final
  thesis corpus or evaluation dataset.
- Missing snapshot symbols are listed in the data repository README and will be
  fetched manually later. No renamed or related ticker substitutes are
  permitted.

## Evaluation Decisions

### 252-trading-day horizon

- Include the 252-trading-day, approximately one-year, forward evaluation
  horizon alongside the 1, 5, 20, and 60 trading-day horizons.
- This does not affect the current data extraction. It affects later market
  outcome evaluation only.

### Chronological split

- The reproducible derivation of the development and held-out evaluation date
  ranges is fixed in `decisions/0006-reproducible-research-and-runtime-contract.md`.
- The local Kaggle snapshot must not be presented as the final research corpus
  or used to tune against a final evaluation period.
- This deferred decision does not block current company-registry, persistence,
  or account/thesis CRUD work.

### Sector benchmark mapping

- Sector benchmark mapping and the S&P 500 fallback are fixed in
  `decisions/0006-reproducible-research-and-runtime-contract.md`.
- No benchmark-adjusted return calculation is part of the current local price
  extraction.
- This deferred decision does not block current company-registry, persistence,
  or account/thesis CRUD work.

## Remaining Work

The concrete source records remain an implementation responsibility, but the
manifest, split, benchmark, and accepted 252-day protocol are no longer open
research decisions.
