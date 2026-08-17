# Market Data And Evaluation Scope Decisions

**Status:** Partially decided

**Date:** 2026-08-17

## Local Market Price Snapshot

- The author-supplied Kaggle archive at `/Users/jwdev/Downloads/archive` is a
  local development input.
- Only exact CSV files for the approved company universe were copied to
  `data/market_prices/`; no other archive files were copied, moved, or
  deleted.
- `SPY` is present in the approved universe and was copied from the archive's
  ETF collection. All other selected files came from its stock collection.
- The copied files are unmodified and are Git-ignored local data artifacts.
- Missing approved symbols are listed in `data/market_prices/README.md` and
  will be fetched manually later. No renamed or related ticker substitutes are
  permitted.

## Evaluation Decisions

### 252-trading-day horizon

- Include the 252-trading-day, approximately one-year, forward evaluation
  horizon alongside the 1, 5, 20, and 60 trading-day horizons.
- This does not affect the current data extraction. It affects later market
  outcome evaluation only.

### Chronological split

- The exact development and held-out evaluation date ranges are deferred until
  the author has fetched and reviewed the final data.
- The local Kaggle snapshot must not be presented as the final research corpus
  or used to tune against a final evaluation period.
- This deferred decision does not block current company-registry, persistence,
  or account/thesis CRUD work.

### Sector benchmark mapping

- Sector benchmark mapping and the S&P 500 fallback are deferred to the future
  evaluation implementation.
- No benchmark-adjusted return calculation is part of the current local price
  extraction.
- This deferred decision does not block current company-registry, persistence,
  or account/thesis CRUD work.

## Remaining Work

The final corpus manifest, exact chronological split, and sector benchmark map
remain necessary only to complete `FEAT-006` and later evaluation work. They
are not prerequisites for `FEAT-008` persistence or `FEAT-009` account/thesis
CRUD. This record captures the approved deferrals and the accepted 252-day
horizon decision.
