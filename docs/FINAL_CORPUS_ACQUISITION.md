# Final Corpus Acquisition

The active six-company cleaned corpus is
**`thesis-v2-current-cache-sec-form-aware-v2`**, schema 2, under decision
[0016](../decisions/0016-reviewed-cleaned-corpus-publication.md). The approved
source selection remains `thesis-v2-current-cache` under decision
[0015](../decisions/0015-corpus-contract-corrections.md).
All downloaded and derived research artifacts live in the separate
`sentimentAI-data` repository. Scripts live in this application repository.

## Frozen source selection

The selected records are original SEC 10-K/10-Q, 8-K **Item 2.02**, and curated
full IR call transcripts for **META, CRM, V, DIS, WHR, T**. The larger historical
cache remains an acquisition superset, including non-earnings 8-Ks.

The current selection contains **363 records**:

| Boundary | Date |
|---|---|
| Five-year window starts | 2021-08-27 |
| Development ends (inclusive) | 2024-08-27 |
| First included held-out publication | 2024-08-28 |
| Cutoff / latest included publication | 2026-08-27 |

These dates are derived from the selected publications, not hardcoded in the
writer or reader. Each company has 20 full transcripts and five annual filings
in the selected window. The newer cached AT&T 2026-10-16 filing is not an
eligible Item 2.02 record.

```bash
export SENTIMENT_DATA_ROOT=/absolute/path/to/sentimentAI-data
uv run python -m scripts.freeze_corpus_selection
```

This creates `data/research_selection/thesis-v2-current-cache.json`, recording
the exact source references, raw/input-manifest hashes, dates and per-company
coverage. Identical reruns succeed; changed inputs refuse to overwrite it.

## Download and review sectors

```bash
uv run python -m scripts.download_company_sectors --snapshot stockanalysis_2026_10_18
```

The script downloads six real HTTPS company profiles from Stock Analysis,
preserving HTML, readable text, source URLs, actual retrieval timestamps and
SHA-256 in `data/company_sectors/<snapshot>/downloads.json`. It does not invent
a classification or create a review automatically. Snapshots cannot be overwritten.

Review the saved Sector and Ticker Symbol fields, then create `reviewed.json`
alongside them. Record `schema_version: 1`, `downloads_path`,
`downloads_sha256`, `reviewer`, `note`, and a `companies` list containing each
`ticker`, `source_sector`, `sector`, `evidence_quote`, and `normalization_note`.
Quotes use the exact saved text, e.g. `Sector\nCommunication Services`.

The completed 2026-10-18 assistant review is in the data repository. Salesforce's
literal source label **Technology** is explicitly normalized to **Information
Technology**. These are provider-reported current sectors, not a licensed GICS
dataset or historical classifications. Benchmark ETFs follow decision 0006.

## Offline reviewed-cleaner publication

The original `data/corpora/thesis-v2-current-cache/` materialization is retained
intact. Its cleaned artifacts use `source-cleaning-v1`; they are not repaired by
updating application code. The default writer publishes a distinct cleaning
revision using that predecessor and the existing frozen selection:

```bash
uv run python -m scripts.acquire_corpus
```

This reads the frozen selection by default (`--selection` can specify its path),
verifies its input manifests/source bytes and the entire predecessor, re-cleans
SEC text and writes:

```text
data/corpora/thesis-v2-current-cache-sec-form-aware-v2/
  manifest.json
  publication.json
  raw/{sec,investor_relations}/{ticker}/...
  cleaned/{sec,investor_relations}/{ticker}/...
  data/company_sectors/<snapshot>/{downloads.json,reviewed.json,*.html,*.txt}
  provenance/{selection.json,predecessor-manifest.json,predecessor-inventory.json,findings-final.md}
  provenance/inputs/*.json
  provenance/reviews/*.json
```

No SEC, IR or sector network request and no credential is needed for this step.
Full transcripts retain `investor_relations_transcript` source type and distinct
call content groups. Manifest schema 2 records raw/cleaned hashes, parser and
source lineage, derived dates and a hash-pinned sector evidence bundle. All 243
SEC records use `sec-form-aware-v2`; all 120 transcript cleaned bytes and their
existing parser labels are copied unchanged. Selection/raw metadata, content
groups, canonical flags and dates are preserved exactly.

Default review inputs are `data/extraction_reviews/sec-v2-round5/review.json`,
`sec-v2-edge-round4/review.json`, and round5's separate `findings-final.md`.
`--sec-reviews PATH PATH ...` and `--sec-findings PATH` can specify equivalent
saved evidence. Selector/cleaner implementation hashes must match every review
index; overlapping outputs must match both reviewed hashes and actual bytes.
The embedded indexes retain their original pending flags; the separate findings
describe the actual bounded review, not full-corpus semantic certification.

The completed publication re-cleaned 243 SEC records (242 changed hashes), copied
120 transcripts unchanged, matched 24 unique reviewed overlaps, and verified all
741 predecessor files unchanged. `publication.json` and the embedded inventory
record the evidence. AT&T `0000732717-22-000038` now has cleaned SHA-256
`8fe4ec4d504f58ee9cc509debb5a00996ff22935b018e1b8efc66bc2da3dd605`.

The directory is published atomically. Identical writer input is idempotent and
reruns verify all expected artifact bytes; changed input refuses to overwrite
the corpus. Referenced files are confined to their declared data trees, checked
with SHA-256, and copied into a fresh staging directory. Existing materializations are
left intact. The older optional `--ir-plan` mode downloads official IR earnings
releases and SEC recent filings; it is legacy groundwork, not the current
historical-cache selection workflow. It requires `SEC_USER_AGENT` in the
environment and `--sector-review` with a source-backed sector review. Never put
credentials in plans.

Existing-publication reruns verify pinned inputs and the complete artifact set
without re-cleaning or comparing today's runtime-module fingerprint to the
creation fingerprint. `--selection` and `--sector-review` are validated even
when the destination exists. Changed input bytes, missing/corrupt evidence and
unexpected files fail. `--sector-review` defaults to the original pinned sector
review and validates its original downloaded bundle as well as the embedded copy.

## Runtime scopes

- `CachedCorpusDocumentSource.fetch_documents()` combines the final corpus and
  SEC history manifests, legacy quarterly snapshot and curated IR cache,
  preserving AMAT, out-of-window records and non-earnings 8-Ks.
  Identical original-byte revisions deduplicate, with final provenance preferred.
- `fetch_evaluation_documents()` returns only final-manifest records. Do not
  treat the operational union as the evaluation dataset.
- All final artifacts, derived dates and sector evidence are verified offline.
- Stable source revisions use company/source/source ID/original-byte SHA-256.
  Normalized document derivations add cleaning version and cleaned hash; chunk
  derivations add the processing configuration. Migration 0011 reuses equivalent
  legacy IDs and records manifest memberships separately. Existing v1 results
  remain historical; run a new batch to produce results from the active corpus.

See [decision 0017](../decisions/0017-operational-history-and-source-derivations.md)
for the populated-database upgrade and explicit handling of unknown legacy PDF
hashes. Broad-cache PDFs now carry verified original-byte hashes through normal
ingestion and persistence independently of their extracted-text hashes.

The source corpus is linked to the completed market/evaluation artifact bundle
under [decision 0018](../decisions/0018-frozen-market-snapshot-and-evaluation-coverage.md).
The workflow and exact coverage are documented below.

For form-aware SEC extraction and source/output review on downloaded filings,
see [Offline SEC extraction review](SEC_EXTRACTION_REVIEW.md). It documents the
78-filing development review and its remaining source/visual coverage limits.

## Verification

Run real-data checks separately from the fast suite to avoid repeatedly loading
the full cache in unrelated application-container tests:

```bash
SENTIMENT_DATA_ROOT=/absolute/path/to/sentimentAI-data \
  uv run pytest tests/integration/test_cached_sources.py tests/integration/test_research_history.py
```

The cleaning-revision integration check independently compares the entire
predecessor inventory, frozen selection, record metadata, transcript bytes and
the AT&T regression hash through normal ingestion. Unit tests additionally
exercise implementation/review mismatches, changed selection, corrupt lineage,
immutable reruns and distinct old/new chunk identities. PostgreSQL integration
tests verify migration and persistence of both cleaning versions.

Explicit populated-database checks:

```bash
POSTGRES_TEST_DSN="$POSTGRES_TEST_DSN" \
  uv run pytest tests/integration/test_populated_corpus_upgrade.py tests/integration/test_postgres_persistence.py
```

Use a test database for this check; the populated-upgrade cases use isolated
temporary schemas. Do not delete an application database to apply migrations.

## Reproducible market snapshot

The research snapshot is **`nasdaq_2026_10_18_research_v2`**. All eleven series
have 1,290 trading-day rows from 2021-08-27 through 2026-10-16. The return field
is provider-reported `Close`, without a dividend-adjusted total-return claim.

```bash
uv run python -m scripts.download_nasdaq_historical \
  --series META:stocks --series CRM:stocks --series V:stocks \
  --series DIS:stocks --series WHR:stocks --series T:stocks \
  --series XLC:etf --series XLK:etf --series XLF:etf --series XLY:etf --series SPY:etf \
  --start 2021-08-27 --end 2026-10-16 \
  --output-dir "$SENTIMENT_DATA_ROOT/data/market_prices/nasdaq_2026_10_18_research_v2"
```

New acquisitions save actual JSON responses under `raw/` alongside the existing
CSV v1 format. The manifest pins original responses and CSVs, request URLs and
dates, retrieval timestamps and actual coverage. Existing-snapshot reruns verify
all artifacts and reconstruct every CSV offline before succeeding. Different
requests or changed artifacts fail; prior snapshots are retained.

## Freeze and verify evaluation artifacts

```bash
uv run python -m scripts.freeze_evaluation_manifest \
  --market-snapshot nasdaq_2026_10_18_research_v2
uv run python -m scripts.freeze_evaluation_manifest --verify

SENTIMENT_DATA_ROOT="$SENTIMENT_DATA_ROOT" uv run pytest \
  tests/integration/test_evaluation_artifacts.py tests/integration/test_cached_market_data.py
```

Both freeze and verify commands use `SENTIMENT_DATA_ROOT` (or `--data-root`).
They verify the corrected publication, selection, original sources/input
manifests, predecessor inventory, reviewed sectors, and raw-response/CSV replay.
Publication is atomic and immutable; reruns recompute reconciliation and coverage
without acquiring or changing research inputs.

The versioned bundle is:

```text
data/evaluation/thesis-v2-current-cache-sec-form-aware-v2-market-v1/
  manifest.json
  reconciliation.json
  coverage.json
  implementation/*.py
```

The manifest links exact source and market versions, paths and SHA-256 hashes,
1,917 input files, eight output artifacts, benchmark routing and the fixed
alignment/exclusion protocol. `load_evaluation_scope()` is the offline adapter
integrity gate for future evaluation execution. Source, price and implementation
evidence stay in `sentimentAI-data`.

### Recorded availability

| Trading-day horizon | Complete / 363 sources | Unavailable | Complete held-out / 147 |
|---|---:|---:|---:|
| 1 | 363 | 0 | 147 |
| 5 | 363 | 0 | 147 |
| 20 | 363 | 0 | 147 |
| 60 | 348 | 15 | 132 |
| 252 | 291 | 72 | 75 |

Every source appears at every horizon: 1,815 entries, including 735 held-out
entries. All 87 unavailable cases retain `subject_horizon_unavailable`, known
entry dates and absent future exits/returns. No source is removed. The source
cutoff stays **2026-08-27**, development ends **2024-08-27**, and held-out
publications start **2024-08-28**.

The latest complete **as-of** dates supported by the price snapshot are
2026-10-14 / 2026-10-08 / 2026-09-17 / 2026-07-22 / 2025-10-14 for the five
horizons respectively. The latest **entry** is later: 2026-10-15 / 2026-10-09 /
2026-09-18 / 2026-07-23 / 2025-10-15. All exit on 2026-10-16. Per-company
daily intervals and last complete included-publication dates are in
`coverage.json`; interior gaps would be retained explicitly.

META/DIS/T use XLC, CRM uses XLK, V uses XLF, and WHR uses XLY. Sector endpoints
use the exact subject dates; SPY is fallback and required sensitivity. This
snapshot has no observed fallback or benchmark exclusion. Coverage entries are
source-publication availability, not generated predictions or thesis metrics.
Actual evaluation execution remains FEAT-016 work.
