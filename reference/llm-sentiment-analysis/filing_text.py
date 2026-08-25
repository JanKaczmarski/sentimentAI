"""Strip inline-XBRL noise from filing text extracted out of HTML.

SEC filings embed inline XBRL: hidden elements carrying taxonomy URIs, context
identifiers and element qnames. An HTML-to-text pass keeps all of it, so the
extracted document opens with a wall of machine tokens before any prose. In
Apple's 2025 10-K that wall runs to the first 20,100 characters -- ahead of Item
1A -- and it is roughly 4,000 tokens of an input budget that has to hold a
transcript too.

It is also actively harmful as prompt input. A model asked for a verbatim quote
will happily return `aapl:A0.000Notesdue2025Member`: perfectly verbatim, and
evidence of nothing.

Deliberately conservative. Each pattern targets a shape that does not occur in
English prose, so a false positive would have to be a sentence containing a
taxonomy URI or a 60-character unbroken word.
"""

import re

# http://fasb.org/us-gaap/2025#LongTermDebtNoncurrent and friends.
_TAXONOMY_URI = re.compile(
    r"https?://(?:fasb\.org|xbrl\.(?:sec\.gov|org)|www\.w3\.org|xbrl\.ifrs\.org)\S*"
)

# aapl:A0.000Notesdue2025Member, us-gaap:CommonStockMember
# No space around the colon, so prose like "Note: US sales" is untouched.
_QNAME = re.compile(r"\b[A-Za-z][A-Za-z0-9-]{0,12}:[A-Za-z0-9._]{2,}\b")

# The concatenated runs left behind once the tags are gone: no spaces, far
# longer than any English word.
_LONG_RUN = re.compile(r"\S{60,}")

# Shorter mixed alphanumeric runs from the same source -- `false2025FY0000320193P1YP1Y`,
# context ids, scaling factors. Requires 25+ characters with no space and both a
# digit and a letter, which English prose does not produce.
_ALNUM_RUN = re.compile(r"(?=\S*\d)(?=\S*[A-Za-z])\S{25,}")

# A bare CIK repeated down the cover page, and lone ISO dates on their own line.
_LONE_TOKEN_LINE = re.compile(r"^\s*(?:\d{10}|\d{4}-\d{2}-\d{2}|false|true)\s*$")

_BLANK_RUN = re.compile(r"\n{3,}")


def strip_xbrl_noise(text: str) -> str:
    text = _TAXONOMY_URI.sub(" ", text)
    text = _QNAME.sub(" ", text)
    text = _LONG_RUN.sub(" ", text)
    text = _ALNUM_RUN.sub(" ", text)
    # Removing tokens leaves lines holding nothing but the spaces that separated
    # them, which _BLANK_RUN cannot see until they are actually empty.
    text = "\n".join(
        line.strip() for line in text.splitlines() if not _LONE_TOKEN_LINE.match(line)
    )
    text = re.sub(r"[ \t]{2,}", " ", text)
    return _BLANK_RUN.sub("\n\n", text).strip()
