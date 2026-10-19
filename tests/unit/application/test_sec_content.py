"""Content-selection regressions grounded in downloaded SEC filing layouts."""

import pytest

from sentiment_system.application.use_cases.ingest_documents import _clean_content


def _part(kind: str, text: str, description: str = "", filename: str = "report.htm") -> str:
    return (
        f"<DOCUMENT>\n<TYPE>{kind}\n<FILENAME>{filename}\n<DESCRIPTION>{description}\n"
        f"<TEXT>{text}</TEXT>\n</DOCUMENT>"
    )


@pytest.mark.parametrize("form", ["10-K", "10-Q"])
def test_complete_submission_retains_main_report_not_exhibit(form: str) -> None:
    raw = _part(form, "<p>Management discussion and financial statements.</p>") + _part(
        "EX-99.1", "<p>Separate supplementary attachment.</p>"
    )
    cleaned = _clean_content(raw, source="sec", form=form)
    assert "Management discussion and financial statements." in cleaned
    assert "Separate supplementary" not in cleaned


def test_release_selection_includes_all_financial_supplements_and_excludes_unrelated() -> None:
    raw = _part("8-K", "Results are attached.")
    raw += _part("EX-99.1", "<h1>Company Reports First Quarter Results</h1><p>Revenue increased.</p>")
    raw += _part("EX-99.2", "<h1>Investor Presentation</h1><p>Earnings call slides.</p>")
    raw += _part("EX-99.3", "<h1>Non-GAAP Reconciliation</h1><p>Net income to adjusted EBIT.</p>")
    raw += _part("EX-99.4", "<h1>Historical Segment Financial Data</h1><p>Segment revenue 123.</p>")
    raw += _part("EX-99.5", "<h1>Director Departs Board</h1><p>Governance announcement.</p>")
    cleaned = _clean_content(raw, source="sec", form="8-K")
    assert "Revenue increased" in cleaned
    assert "Net income to adjusted EBIT" in cleaned
    assert "Segment revenue 123" in cleaned
    assert "Investor Presentation" not in cleaned
    assert "Governance announcement" not in cleaned


def test_sec_preserves_xbrl_wrapped_report_and_visible_facts_but_not_hidden_metadata() -> None:
    raw = _part(
        "10-Q",
        "<XBRL><html><body><ix:header><ix:hidden>Hidden taxonomy fact</ix:hidden></ix:header>"
        "<h1>Quarterly Report</h1><p>Revenue <ix:nonFraction>123</ix:nonFraction></p>"
        '<div style="display:none">Hidden context</div><p>Financial notes remain.</p></body></html></XBRL>',
    )
    cleaned = _clean_content(raw, source="sec", form="10-Q")
    assert "Quarterly Report" in cleaned and "123" in cleaned and "Financial notes remain" in cleaned
    assert "Hidden taxonomy" not in cleaned and "Hidden context" not in cleaned


def test_sec_does_not_delete_repeated_financial_values() -> None:
    raw = "<html><body><table><tr><td>Segment</td><td>Profit</td></tr>"
    raw += "".join(f"<tr><td>Segment {index}</td><td>100</td></tr>" for index in range(4))
    raw += "</table><p>Notes and signatures.</p></body></html>"
    cleaned = _clean_content(raw, source="sec", form="10-Q")
    assert cleaned.count("100") == 4


def test_selector_exposes_unknown_exhibit_and_missing_release_for_review() -> None:
    from sentiment_system.application.use_cases.sec_content import select_sec_content

    raw = _part("8-K", "Item 2.02. Financial disclosure is contained here.")
    raw += _part("EX-99.1", "Unclassifiable attachment text.")
    result = select_sec_content(raw, form="8-K")
    assert result.issues
    assert any(not item.selected and "unresolved" in item.reason for item in result.documents)
    assert "Financial disclosure" in result.content


def test_missing_expected_main_report_is_an_error_not_exhibit_substitution() -> None:
    with pytest.raises(ValueError, match="10-K"):
        _clean_content(_part("EX-99.1", "Reports quarterly results."), source="sec", form="10-K")


def test_release_transcription_white_text_is_preserved() -> None:
    raw = _part("8-K", "Results are attached.") + _part(
        "EX-99.1",
        '<img src="release.jpg"><div style="font-size:xx-small;color:white">'
        "Company Reports Second Quarter Results. Revenue 123.</div>",
        filename="pressrelease.htm",
    )
    assert "Revenue 123" in _clean_content(raw, source="sec", form="8-K")


def test_combined_earnings_and_governance_release_is_not_discarded() -> None:
    from sentiment_system.application.use_cases.sec_content import select_sec_content

    raw = _part("8-K", "Governance and proxy voting cover material.")
    raw += _part(
        "EX-99.1",
        "<h1>Facebook Reports First Quarter 2016 Results and Announces Proposal for New Class of Stock</h1>"
        "<p>Revenue increased. Financial statements and proposal details.</p>",
    )
    raw += _part("EX-99.2", "<h1>Preserving Founder-Led Structure to Focus on the Long Term</h1>")
    result = select_sec_content(raw, form="8-K")
    assert result.documents[1].selected
    assert not result.documents[0].selected and not result.documents[2].selected
    assert "proposal details" in result.content
    assert not result.issues


def test_financial_supplement_is_not_mislabelled_release_or_suppressing_main_disclosure() -> None:
    from sentiment_system.application.use_cases.sec_content import select_sec_content

    raw = _part("8-K", "Main financial disclosure.")
    raw += _part(
        "EX-99.4",
        "<h1>WHIRLPOOL CORPORATION NET EARNINGS TO EBIT RECONCILIATION (UNAUDITED)</h1>"
        "<p>Fourth Quarter 2017 Results. 123.</p>",
    )
    result = select_sec_content(raw, form="8-K")
    assert result.documents[0].selected
    assert result.documents[1].selected and "reconciliation" in result.documents[1].reason
    assert result.issues


def test_unrelated_press_release_does_not_become_earnings_release() -> None:
    from sentiment_system.application.use_cases.sec_content import select_sec_content

    raw = _part("8-K", "Main disclosure.")
    raw += _part("EX-99.1", "<h1>Visa Reports Second Quarter Results</h1><p>Revenue 123.</p>")
    raw += _part(
        "EX-99.2",
        "<h1>Visa Inc. Announces Intent to File a Shelf Registration Statement</h1>",
        description="PRESS RELEASE OF VISA INC.",
    )
    result = select_sec_content(raw, form="8-K")
    assert result.documents[1].selected and not result.documents[2].selected


@pytest.mark.parametrize("linked", [True, False])
def test_explicit_main_report_presentation_reference_beats_financial_slide_text(linked: bool) -> None:
    from sentiment_system.application.use_cases.sec_content import select_sec_content

    reference = '<a href="deck.htm">99.2</a>' if linked else "99.2"
    raw = _part(
        "8-K",
        "<p>A copy of the presentation is attached as Exhibit 99.2.</p><table><tr>"
        f"<td>{reference}</td><td>Presentation of the Company.</td></tr></table>",
    )
    raw += _part("EX-99.1", "<h1>Company Reports Third Quarter Results</h1><p>Revenue 123.</p>")
    raw += _part(
        "EX-99.2",
        "<h1>Fiscal Third Quarter Financial Results</h1><p>2 Forward-Looking Statements</p>"
        + "<p>Risk factors.</p>" * 40
        + "<p>This presentation contains forward-looking statements.</p>",
        filename="deck.htm",
    )
    result = select_sec_content(raw, form="8-K")
    assert not result.documents[2].selected
    assert "presentation" in result.documents[2].reason


def test_release_filename_and_reference_outweigh_incidental_non_gaap_bullet() -> None:
    from sentiment_system.application.use_cases.sec_content import select_sec_content

    raw = _part(
        "8-K",
        '<table><tr><td><a href="pressrelease.htm">99.1</a></td>'
        "<td>Press release announcing quarterly financial results.</td></tr></table>",
    )
    raw += _part(
        "EX-99.1",
        "<h1>Company Delivers Solid Q1; Initiating Strategic Review</h1>"
        "<p>Ongoing (non-GAAP) earnings margin of 9.4%.</p>",
        filename="pressrelease.htm",
    )
    result = select_sec_content(raw, form="8-K")
    assert result.documents[1].selected and "release" in result.documents[1].reason
    assert not result.documents[0].selected
    assert not result.issues
