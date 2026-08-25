# Aggregation And Personalization Rules

**Status:** Accepted

**Date:** 2026-08-25

## Purpose

This record fixes the initial aggregation and Investment Thesis personalization
rules before held-out evaluation. The version is `aggregation-personalization-v1`.
The rules are deterministic, investor-independent before personalization, and
must not be tuned against the held-out period.

## Aggregation

For a document published `age_days` before the snapshot date, the recency weight
is:

```text
recency = exp(-ln(2) * age_days / 90)
```

The 90-day half-life is applied within each 30-, 90-, and 365-day window. A
chunk's aggregation weight is:

```text
weight = importance_score * confidence * recency
```

Scores are the weighted mean of chunk polarity scores. Confidence is a
reliability weight, not a replacement for polarity. Soft-excluded chunks are
omitted from new snapshots but remain available as historical evidence. If a
window has no eligible positive-weight chunks, its score is neutral (`0.5`) and
its confidence is `0.0`.

Document scores use the same formula over their chunks. Company snapshots are
calculated for the 30-, 90-, and 365-day windows and retain the contributing
chunk IDs, the rule version, and the experiment run ID.

## Horizon And Style Rules

The thesis horizon selects two adjacent company windows. The investment style
selects the weights between them:

| Investment horizon | Short window | Long window |
|---|---:|---:|
| `short_term` | 30 days | 90 days |
| `long_term` | 90 days | 365 days |

| Investment style | Short-window weight | Long-window weight |
|---|---:|---:|
| `active` | 0.70 | 0.30 |
| `passive` | 0.30 | 0.70 |

The personalized score is the weighted mean of the selected two snapshot
scores. No free-text thesis description is used by the algorithm.

## Risk Thresholds

Risk tolerance changes only the decision thresholds, not the underlying score:

| Risk tolerance | Negative at or below | Positive at or above |
|---|---:|---:|
| `low` | 0.30 | 0.70 |
| `medium` | 0.40 | 0.60 |
| `high` | 0.45 | 0.55 |

Scores between the two thresholds are labeled `NEUTRAL`. The base sentiment
label continues to use the global `<0.4` and `>0.6` thresholds from the thesis
contract.

## Sensitivity Plan

Before held-out evaluation, the development period may compare the following
pre-registered variants:

- recency half-life: 30, 90, and 180 days;
- importance exponent: 0.5, 1.0, and 2.0;
- active/passive short-window weight: 0.6/0.4, 0.7/0.3, and 0.8/0.2;
- each risk threshold pair shifted symmetrically by 0.05 where it remains in
  the `[0, 1]` range.

All variant results and parameters are reported. The held-out period cannot be
used to select a variant or alter the v1 rules.
