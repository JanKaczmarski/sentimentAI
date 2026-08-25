# Companion Repository Reference Bundle

This directory preserves selected source material from
`/Users/jwdev/Downloads/llm-sentiment-analysis` for implementation ideas. It is
not application code, is not imported by `src/`, and is not covered by this
project's test suite.

The companion repository author approved copying this material on 2026-08-25.

## `filing_text.py`

Verbatim copy of `lib/filing_text.py` from the companion repository.

Potential use: adapt its conservative `strip_xbrl_noise` function during
`FEAT-007` or `FEAT-015` to create `SourceDocument.cleaned_content` for SEC
filings. Keep the original raw source intact, add focused tests against real
filing samples, and record the cleaner/configuration version in provenance.

The function intentionally removes inline-XBRL tokens that otherwise consume
LLM context and can produce meaningless but verbatim evidence excerpts.

## Other reviewed material

- `lib/sec_api_client.py`: SEC retrieval, exhibit discovery, and retry patterns
  for a future `DocumentSource` adapter.
- `scripts/verify_quotes.py`: evidence-excerpt validation pattern for future
  prediction provenance.
- `running_sentiment_analysis_on_remote/src/predict_sentiment_with_llama.py`:
  malformed-output handling, token-budget fitting, and run-manifest patterns.
- `running_sentiment_analysis_on_remote/src/label_rules.py`: model-evidence then
  deterministic-rule derivation pattern.

These remain in the companion repository for now because they need substantial
adaptation to the target ports and thesis methodology.
