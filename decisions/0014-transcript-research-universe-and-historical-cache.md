# Transcript Research Universe And Historical Cache

**Status:** Accepted (author instruction, 2026-10-17)

## Decision

- Replace the core research/evaluation sample with `META`, `CRM`, `V`, `DIS`,
  `WHR`, and `T`. Their official IR archives provide long histories of complete
  earnings-call transcripts. The previous AAPL/MSFT/NVDA/JPM/XOM/JNJ functional
  snapshot remains historical evidence; its completed feature records are not
  rewritten to claim they tested the new sample.
- `domain/research.py` owns current sample membership and sector benchmark
  assignments. The broader FEAT-018 operational registry remains the source of
  supported company identities. Every new sample member is already in it.
- Full earnings-call transcripts are a distinct IR document type,
  `earnings_call_transcript`; do not relabel them earnings releases or treat
  their additional Q&A as duplicate text of an SEC earnings release.
- Curated files are verified, canonically named, byte-identical source copies,
  as required by the data repository's company-communications README. Retain
  raw files, original metadata, source URLs, retrieval timestamps, SHA-256,
  publication-date evidence, fiscal periods, alternate versions and gaps.
- Acquire original SEC `10-K`, `10-Q`, and **all** `8-K` forms, retaining Item
  metadata so Item 2.02 can be selected later. Amendments are outside this
  acquisition selection. Download the primary HTML for 10-K/10-Q and the complete
  8-K submission including exhibits. Record that representation explicitly.
- Each company's acquisition begins January 1 of its earliest available IR
  **publication** year and ends on the acquisition date. Downloading the full
  starting year also captures annual/quarterly filings preceding its first call.
  Disney requires both CIK 1001039 (predecessor) and CIK 1744489 (current).
- Fetch overlapping SEC submission-history indexes as well as recent filings;
  retain index snapshots and reconcile every selected accession against saved
  content. Document download failures and discovery errors separately. Per-year
  counts describe publication coverage, not assumed fiscal-year counts.

## Research boundary

**Subsequent correction:** decision 0015 replaces the prospective dated v2
identity below with `thesis-v2-current-cache`, freezes the current selection,
and replaces hardcoded company-sector assignments with downloaded, reviewed
sector evidence. The acquisition policy and sample membership here still apply.

The expanded historical cache is an acquisition superset, not an automatically
expanded evaluation period. Preserve the five-year/two-year-held-out research
methodology until final corpus selection. The changed membership uses the new
manifest identity `thesis-v2-2025-09-24`; never overwrite a v1 manifest or mix
sample memberships. The current frozen-window writer is groundwork; selecting
and materializing the final transcript-inclusive research manifest remains part
of FEAT-015. Sector mapping uses current GICS assignments (Visa: Financials);
the existing SPY fallback applies where a sector ETF did not yet exist.

## Audit artifacts

All source bytes and acquisition inventories live in `sentimentAI-data`:

- `data/company_communications/curated/<TICKER>/{manifest.csv,manifest.json}`
- `data/company_communications/reviewed_dates.json` for source-backed date repairs
- `data/sec/history/<TICKER>/manifest.json` and content-addressed index snapshots
- `data/research_history/{inventory.json,README.md}` for cross-source coverage

Scripts live in the application repository; provider credentials stay in the
environment. FEAT-015 remains `in_progress` after this acquisition increment.
