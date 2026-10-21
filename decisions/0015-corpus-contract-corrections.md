# Corpus Contract Corrections

**Status:** Accepted (author instruction, 2026-10-18)

Cleaning-materialization update: [decision 0016](0016-reviewed-cleaned-corpus-publication.md)
retains this selection and the original materialization, and activates the new
`thesis-v2-current-cache-sec-form-aware-v2` cleaned corpus with the same records
and dates.

## Frozen current-cache selection

- Freeze the current six-company cache rather than the old September 24, 2025
  window. Preserve decision 0006's derivation: cutoff = latest included
  publication; start = five calendar years earlier; development ends = two
  calendar years earlier; held-out starts = first included publication strictly
  after that development boundary. February 29 clamps to February 28 when needed.
- Retain the existing research eligibility of original SEC 10-K/10-Q and 8-K
  **Item 2.02**, plus the curated full IR call transcripts approved in decision
  0014. Downloaded non-earnings 8-Ks remain in the historical cache; acquiring all
  8-Ks did not approve all of them as evaluation evidence.
- The verified current selection has **363 records**, with cutoff **2026-08-27**,
  window start **2021-08-27**, development end **2024-08-27**, and first held-out
  publication **2024-08-28**. The newer cached AT&T filing on 2026-10-16 is not an
  eligible Item 2.02 record. Each company contributes 20 full call transcripts
  and five annual filings within the common window.
- `data/research_selection/thesis-v2-current-cache.json` in `sentimentAI-data`
  freezes record references, raw checksums, input-manifest checksums, coverage,
  sample membership, and the derived split. Rebuilding with changed inputs is
  refused. Future additions require an explicit new version/decision.
- Replace the prospective `thesis-v2-2025-09-24` identity from decision 0014 with
  **`thesis-v2-current-cache`**, schema 2. Its dates live in the manifest and must
  be validated against its included records. Existing frozen versions are never
  rewritten. Offline materialization preserves full transcripts as their own
  source type and never groups their Q&A with SEC earnings-release text.

## Truthful sector provenance

- Use actual downloaded Stock Analysis company-profile HTML, with original
  URLs, UTC retrieval timestamps and SHA-256, plus a separately hash-recorded
  readable-text representation. No provider credentials are required.
- The assistant reviews each saved profile's explicit Sector field and records
  the source label, exact quote, normalized label, reviewer and normalization
  note in a separate `reviewed.json`. That file pins the downloads manifest.
- These are **provider-reported current sectors mapped to the thesis's
  GICS-aligned benchmark vocabulary**, not a licensed GICS classification feed
  or historical point-in-time sector evidence. This refines decision 0006's
  source-reported-GICS requirement; no unsupported GICS-provider claim is made.
- Salesforce reports **Technology**: explicitly normalize it to **Information
  Technology → XLK**. Other reported labels are retained: META/DIS/T →
  Communication Services/XLC, V → Financials/XLF, WHR → Consumer
  Discretionary/XLY. SPY remains the fallback for unavailable/unsupported sectors.
- The immutable corpus embeds the reviewed file, pinned download manifest,
  original HTML and text. Writer and offline reader verify checksums, quotes,
  issuer identity and agreement with the corpus company metadata. No runtime
  network request or LLM interpretation is needed.

## Operational ingestion and evaluation

The author's answers are **yes** to both:

1. AMAT and other supported companies remain available from the broad cache
   after creating the six-company research corpus.
2. Normal ingestion retains broad-cache documents outside the frozen research
   window, including documents for the six research companies.

`CachedCorpusDocumentSource.fetch_documents()` therefore combines the existing
SEC snapshot, curated IR cache and final corpus. Exact revisions deduplicate by
company, source, source identifier and **original-byte** SHA-256, preferring the
final corpus's provenance; changed revisions remain distinct. In particular,
PDF text extraction must not be used as the original-byte checksum.

`fetch_evaluation_documents()` reads only explicit final-manifest records;
without a final manifest it returns no evaluation records. Broad records never
implicitly become evaluation members. A corrupt final manifest fails loudly
rather than silently falling back to broader data.

## Feature status

This is a bounded FEAT-015 increment. The source corpus is now materialized from
the frozen selection, but the final market-data manifest, price coverage,
forward-horizon completeness and remaining feature gates are separate work.
FEAT-015 remains `in_progress`.

Implementation follow-up: [decision 0017](0017-operational-history-and-source-derivations.md)
adds operational history-manifest loading, validates requested inputs on corpus
reruns, and separates stable original-byte revisions from cleaned/chunk
derivations, including a populated-database migration.
