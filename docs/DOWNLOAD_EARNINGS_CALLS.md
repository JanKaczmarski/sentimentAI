# Official earnings-call transcript PDFs

The acquisition script lives in the application repository; its outputs belong
to the separate research-data repository, as described in that repository's
`README.md` and `data/company_communications/README.md`.

```bash
SENTIMENT_DATA_ROOT=/Users/jwdev/sidePrjs/sentimentAI-data \
  uv run python -m scripts.download_earnings_calls
```

To refresh selected companies:

```bash
uv run python -m scripts.download_earnings_calls \
  --data-root /Users/jwdev/sidePrjs/sentimentAI-data --tickers META V
```

## Scope

- Default research companies: `META`, `CRM`, `V`, `DIS`, `WHR`, `T`.
  Each has at least five consecutive complete fiscal years of full earnings-call
  transcript PDFs. Adobe, AMD and Amazon remain available through explicit
  `--tickers` arguments for inspecting their shorter/empty transcript archives;
  they are not part of the qualified six-company selection.
- No date cutoff: scan every fiscal period exposed by the official source.
- Adobe and AMD: parse the complete quarterly archive HTML.
- Amazon, Meta, Salesforce, Visa, Disney and Whirlpool: request all financial reports and all
  events from the public feeds used by their IR sites (`year=-1`, `pageSize=-1`).
  Event attachments extend coverage beyond the quarterly financial tables.
- AT&T: follow every year linked from its quarterly-earnings index. Read fiscal
  quarters from the earnings-package headings, not PDF directory years. Newer
  table rows link transcript PDFs and prepared-remarks HTML side by side; only
  the transcript PDF is selected.
- Select PDF links explicitly identified as transcripts in quarterly earnings
  context. Exclude follow-up calls, prepared remarks, scripts, slides, releases,
  investor days and other conferences. Do not manufacture PDFs from HTML/audio.
- Validate the actual PDF structure and earnings/Q&A text before saving it.
  A rejected candidate remains a failed manifest record for inspection.

An issuer's general IR archive can be much longer than its transcript archive.
In particular, Amazon's checked financial and event feeds contain no transcript
PDF links. A successful empty discovery is recorded explicitly; an HTTP or
parser failure is reported separately and results in a nonzero exit code.

## Outputs

```text
data/company_communications/raw/<TICKER>/
  <FYperiod>__<URL hash>__<source filename>.pdf
  earnings_calls_manifest.json
```

PDF bytes are retained unchanged. The prefix avoids collisions between common
filenames from different fiscal periods or URLs. The original filename is also
recorded in the manifest. Distinct source URLs may expose alternate versions of
one call; they remain separate source snapshots and can be grouped by checksum
and fiscal period before corpus selection.

Each manifest contains source IDs/URLs, fiscal periods, retrieval timestamps,
SHA-256 checksums, byte/page counts, local paths, statuses, discovery evidence,
and periods that have no transcript PDF link. The summary records all complete
fiscal years, the longest consecutive complete-year run, and an explicit
`meets_five_full_years` flag. Missing downloads cannot qualify a year as complete.
Explicit fiscal periods in filenames are checked against the archive's labels;
misfiled links are reported under `source_anomalies`. Disney's event archive
provides correct transcripts for two mislinked financial-table entries.
`published_at` uses the official
call date where available, otherwise a date in the PDF's first-page header. Its
basis is recorded explicitly; unknown dates stay null. Fiscal report dates are
never substituted for call dates.

Rerunning verifies existing files against their recorded checksums and skips
their downloads. Manifest progress is saved after each file, including on
partially failed runs. Previous provenance is preserved during interrupted
refreshes and when an issuer delists a previously downloaded document. Network
timeouts and transient HTTP errors are retried. Redirects are checked against
the official HTTPS host list; downloads have size limits and TLS certificate
verification remains enabled. The script requires no credentials or API keys.

`curated/` remains the review stage defined by the data contract; acquisition
does not label these raw files as reviewed or as a final evaluation corpus.

## Verification

```bash
uv run pytest tests/unit/scripts/test_download_earnings_calls.py
```
