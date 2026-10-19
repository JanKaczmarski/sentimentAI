# Research History Acquisition

Current core companies: **META, CRM, V, DIS, WHR, T** (decision 0014).
All outputs belong to the separate `sentimentAI-data` repository.

```bash
uv run python -m scripts.curate_earnings_calls --data-root ../sentimentAI-data
uv run python -m scripts.download_sec_history --data-root ../sentimentAI-data
uv run python -m scripts.research_inventory --data-root ../sentimentAI-data
```

The SEC script loads `SEC_USER_AGENT` from the environment or the ignored local
`.env`. It never writes that value into a manifest or log. HTTPS verification,
official-host restrictions, bounded responses, rate limiting and retries apply.
Use `--indexes-only` to inspect expected filings without downloading content.
Use `--tickers META CRM` to resume selected companies; completed file hashes are
verified and their original retrieval provenance retained. `--end YYYY-MM-DD`
reproduces a historical acquisition boundary.

## IR curation

Read `data/company_communications/raw/<TICKER>/earnings_calls_manifest.json`.
Verify the original PDF hash, fiscal-period and publication metadata, PDF
structure, readable earnings context, and Q&A content. Copy unchanged bytes to
`curated/<TICKER>/` using the data repository's canonical naming contract.
Keep the document type `earnings_call_transcript`. Record raw and curated paths,
source URLs, publication-date basis, retrieval provenance, and hashes in JSON;
the compatible `manifest.csv` lets the offline cache reader consume the PDFs.

Exact duplicate snapshots share a canonical file and retain all raw origins.
Distinct revisions with a filename collision get an additional SHA-256 suffix.
Unknown dates remain unresolved unless the PDF header or an explicitly recorded
official-event review establishes them. `reviewed_dates.json` retains the latter
evidence; original raw manifests are not rewritten.

Coverage distinguishes missing quarters **inside** the saved transcript span
from older or future archive periods without a saved transcript. Rejected raw
candidates remain documented issues, even if a valid alternate covers the same
quarter. This avoids mistaking an unrelated presentation for a missing call.

## SEC acquisition

Start at January 1 of the earliest curated IR publication year, through the
acquisition date. This is publication-year coverage, not inferred fiscal-year
coverage. Fetch `filings.recent` and each overlapping `filings.files` historical
index. Historical files contain column arrays directly, not another `recent`
wrapper. Deduplicate by accession; reject conflicting metadata and unsafe names.
For Disney, merge CIK **1001039** and **1744489**.

- `10-K`/`10-Q`: unchanged primary HTML filing.
- `8-K`: unchanged complete SEC submission, retaining exhibits and all Item
  metadata. Item 2.02 is counted separately. Other 8-K Items are also downloaded.
- Exact original forms only; amendments (`10-K/A`, etc.) are excluded.
- Older privacy-enhanced SEC submission wrappers are preserved unchanged.

Each company's `data/sec/history/<TICKER>/manifest.json` lists all expected
filings, raw paths and SHA-256, URLs, report/publication dates, representation,
retrieval timestamps, status/errors, and complete index provenance. Filings and
index snapshots are content-addressed. Progress is saved after every filing.

## Inventory

`scripts.research_inventory` independently verifies the referenced files and
hashes and writes `data/research_history/inventory.json` and `README.md`.
It records IR fiscal/publication spans and gaps; SEC form counts, publication
ranges, yearly coverage, missing accessions/URLs, and index failures. A successful
index reconciliation does not assert that the SEC publishes every fiscal
quarter under every form. The expanded cache is not a finalized research split.

## Frozen research selection

Decision 0015 now freezes an explicit subset of this cache as
`thesis-v2-current-cache`: 363 source records, 2021-08-27–2026-08-27, with the
first held-out publication on 2024-08-28. See
[`FINAL_CORPUS_ACQUISITION.md`](FINAL_CORPUS_ACQUISITION.md) for selection,
downloaded/reviewed sector metadata, and offline corpus materialization.
The larger history and operational ingestion scope remain separate.
The active cleaned materialization is now
`thesis-v2-current-cache-sec-form-aware-v2` under decision 0016; the frozen
selection and the original materialization are retained unchanged.

Normal operational ingestion now reads the history manifests directly, using
filing/publication dates and verified original-byte hashes. It includes original
10-K/10-Q and all available 8-K items, deduplicating exact source revisions with
the frozen corpus preferred. Unsupported amendments and pending/failed downloads
are skipped; missing/corrupt downloaded artifacts are errors. Non-earnings 8-Ks
retain their main disclosure and remain outside evaluation. See decision 0017
for source/derivation identities and populated-database upgrade behavior.
