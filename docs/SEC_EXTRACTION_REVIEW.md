# Offline SEC extraction review

Generate diagnostic evidence from **already downloaded** SEC history. This
workflow supports manual source/output review and parser iteration. It does not
download filings, invoke models, or mark extractions semantically correct.

## Export a development batch

```bash
export SENTIMENT_DATA_ROOT=/absolute/path/to/sentimentAI-data
uv run python -m scripts.review_sec_extraction --limit 36
```

Alternatively pass `--data-root /absolute/path/to/sentimentAI-data`. The default
output is a fresh UTC timestamp directory under
`$SENTIMENT_DATA_ROOT/data/extraction_reviews/`. Use `--output /path/to/new-review`
to choose an explicit fresh directory. Within the research repository's `data/`
tree, outputs must live under `data/extraction_reviews/`. Existing directories,
symlinked output paths, and descendants of previous reviews or manifest-bearing
corpora are refused. There is no overwrite/force option.

Defaults and selection:

- Six allowed tickers: META, CRM, V, DIS, WHR, T; narrow with `--tickers META CRM`.
- Read `data/sec/history/<ticker>/manifest.json` using contained-file checks.
- Include only downloaded/existing original 10-K, 10-Q, and 8-K with Item 2.02.
  Amendments and non-earnings 8-K are excluded.
- `--before 2024-08-27` is an **exclusive filing-date cutoff**, preserving the
  development boundary by default. There is no lower date bound; earlier years
  remain available for diagnosis. Changing the cutoff explicitly changes scope.
- `--limit 36` allocates round-robin quotas across available ticker/form strata,
  then selects evenly spaced filing-date ranks within each stratum. A quota of
  one uses the median. Ties use accession number; manifest ordering has no effect.
  If fewer records are available, all available records are exported.
- `--all` or `--limit 0` means **all eligible records before the cutoff**, not all
  historical/held-out records regardless of date.
- `--accessions ID ID ...` restricts candidates before sampling, useful for a
  targeted retry or a different batch from earlier years. Missing, undownloaded,
  or ineligible requested accessions are reported as errors. Use `--all` alongside
  a target list to export the entire list even when it exceeds 36 records.

For example, repeat a reviewed accession after changing the parser:

```bash
uv run python -m scripts.review_sec_extraction \
  --tickers META \
  --accessions 0001326801-20-000001 \
  --output "$SENTIMENT_DATA_ROOT/data/extraction_reviews/meta-target-v2"
```

The accession above is illustrative; choose actual IDs from the local manifests.

## Evidence and integrity

Every raw filing is checked against its manifest SHA-256 **before extraction**.
The exporter calls `select_sec_content(raw, form=form)` for document decisions
and `_clean_content(raw, source='sec', form=form)` for selected output. Every
supported embedded document, including excluded exhibits, is rendered with a
simple **independent BeautifulSoup text flattener**, not the production cleaner.
It removes script/style/head elements and retains repeated values, XBRL-wrapped
text and hidden metadata. This evidence is not a visible-only browser rendering;
it intentionally preserves source text that production cleaning might lose.
Binary/unsupported bodies retain their decision, reason, and body hash but have
no readable text. Excluded binary bodies are normal metadata, without individual
warnings; a selected binary body produces a warning. Output filenames use
generated document indices, never attachment filenames.

Each bundle contains:

```text
README.md                         reviewer instructions
review.json                       exact inputs, pending status, errors/warnings
inputs/<ticker>.manifest.json      byte-for-byte source manifest snapshots
records/<ticker>__<accession>/
  metadata.json                   raw/manifest/output lineage and all decisions
  cleaned.txt                     SEC/form-aware selected text
  documents/001.txt               independently flattened source evidence per part
```

Metadata includes raw path, expected and observed raw hashes, source URL,
accession/ticker/form/date, manifest snapshot/hash, parser version, selected and
excluded document reasons, issues, evidence paths/hashes, and cleaned hash.
`review.json.implementation_sha256` fingerprints the exporter, selector and
cleaner so development iterations sharing a parser-version label remain distinct.
Body hashes refer to decoded original TEXT content encoded as UTF-8; the raw
filing hash always refers to the original bytes. Legacy cp1252 fallback decoding
is recorded as a warning. The external raw filing remains the authoritative
source; readable text may itself omit structure.

Per-record exceptions are retained while other records continue. Hash mismatch,
unsafe/missing inputs, parser exceptions and missing manifests are errors;
the command exits nonzero. Parser issues, selected binary evidence, empty
readable text and empty selected output are warnings requiring investigation.
Empty supporting evidence (for example an empty EX-101.INS) is written as an
empty text file with its hash and an `empty_readable` status; it does not prevent
successful selected output for the record. Check both `review.json` and the
clearly labeled stderr messages.

## Manual or agent review and iteration

All generated bundles have `reviewed=false` and
`review_status=manual_review_pending`. Extraction completion is not semantic
approval. Follow each bundle's README:

1. Compare original raw HTML/SGML, every readable embedded document, and selected
   output. Include excluded exhibits in the comparison.
2. Check narrative, guidance, financial tables, units, signs and footnotes for
   loss; check that presentations and unrelated exhibits are excluded.
3. Distinguish **selection omission** (relevant embedded content was excluded),
   **cleaning loss**, **unrelated inclusion**, and **external incorporated source
   missing** (the filing references material not present in the download).
4. Keep agent findings as **external manual annotations** with reviewer identity,
   accession, parser version, raw/cleaned hashes, concrete quotations/locations,
   severity and finding category. The script does not orchestrate review agents.
5. Fix the parser separately, regenerate the same targeted records into a new
   directory, compare findings, then review another batch. Leave generated
   evidence intact and retain previous runs for comparison.

These artifacts are diagnostic development results and do not modify the final
corpus, its frozen selection, or original downloaded sources.

## Selection contract

The author-approved extraction scope is the complete main 10-K/10-Q report,
excluding separately attached exhibits, and the earnings release plus its
accompanying financial tables/supplements for an Item 2.02 8-K. Financial
supplements can extend beyond EX-99.2. Exhibit numbers alone do not establish
their role. The selector uses titles, descriptions, filenames and scoped filing
references, including unlinked exhibit-index rows, to exclude presentations and
unrelated communications. Combined earnings/other-news releases remain complete.

When a submission has no separately identified release, retain its main 8-K
disclosure and identified financial supplements in the diagnostic output, with
an explicit issue for review. A missing or nonunique expected 10-K/10-Q main
document raises an error rather than substituting an exhibit. Unresolved EX-99
roles are recorded as issues. The diagnostic exporter does not decide final
corpus inclusion or automatically resolve source-coverage problems.

SEC HTML cleaning preserves XBRL-wrapped report bodies, visible inline facts,
image-page text transcriptions and repeated financial values. It removes
explicitly hidden metadata/resources and keeps leaf-table row text together.
`scripts.acquire_corpus` passes the known form and records `sec-form-aware-v2`
for newly derived SEC content; immutable existing cleaned artifacts retain their
original parser provenance.

## Completed development review — 2026-10-18

The interactive agent-assisted loop started with 36 stratified filings and eight
targeted edge cases, then expanded to **78 unique filings**: 48 main periodic
reports and 30 earnings 8-Ks. All are before the default development cutoff;
review did not use sentiment scores or market outcomes. Independent reviewers
compared original raw content, excluded attachments and output, checked complete
ordered text and financial rows, and verified raw/cleaned hashes.

The iterations corrected:

- A legitimate META earnings/stock-proposal release incorrectly rejected as
  governance-only content.
- WHR reconciliation supplements mislabelled as releases, and a nonstandard
  earnings headline triggering an unnecessary main-filing fallback.
- A Visa conference-call presentation incorrectly included as earnings material;
  its unlinked exhibit-index description now determines the exclusion.
- Review evidence dropping XBRL-wrapped source bodies; source evidence now uses
  an independent flattener rather than the production cleaner.

Latest external evidence:

```text
data/extraction_reviews/sec-v2-round5/                 72 sampled outputs
data/extraction_reviews/sec-v2-edge-round4/            8 targeted outputs
data/extraction_reviews/sec-v2-round5/findings-final.md
```

The bundles overlap by two accessions. Both exports completed without errors.
The final independent review found no remaining material text-selection or
text-omission issue within these 78 filings. Prior rounds and findings remain
available for comparison. Generated bundles deliberately retain their pending
status; the separate findings record the actual review and its bounded scope.

Outstanding coverage limits are explicit: AT&T accession
`0001193125-19-045608` incorporates annual-report content through an external
Exhibit 13 absent from its saved main file; image-only chart contents were not
OCR-verified; plain-text rows do not reconstruct empty cells/colspan/rowspan
geometry. These are not a claim of complete corpus or visual fidelity.

## Published cleaning revision

The reviewed implementation is now materialized in the separate immutable
`data/corpora/thesis-v2-current-cache-sec-form-aware-v2/` corpus. All 243 selected
SEC records were re-cleaned (242 changed hashes), all 120 transcript artifacts
were copied unchanged, and the 24 reviewed unique filings overlapping the frozen
selection matched their reviewed output bytes. All 741 predecessor files remain
unchanged. Selection membership and split dates are unchanged.

See [decision 0016](../decisions/0016-reviewed-cleaned-corpus-publication.md) and
[publication commands](FINAL_CORPUS_ACQUISITION.md). Publication retains the
original review flags and bounded findings; it does not extend the semantic
review to all selected or held-out filings.
