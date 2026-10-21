"""Chronological boundaries are derived from included publications, never wall time."""

from datetime import date

import pytest

from sentiment_system.domain.research import CorpusSplit


def test_split_uses_latest_publication_and_first_actual_held_out_publication() -> None:
    split = CorpusSplit.from_publications((date(2021, 9, 1), date(2024, 9, 4), date(2026, 8, 27)))

    assert split.start == date(2021, 8, 27)
    assert split.cutoff == date(2026, 8, 27)
    assert split.development_ends == date(2024, 8, 27)
    assert split.held_out_starts == date(2024, 9, 4)


def test_calendar_year_subtraction_clamps_leap_day() -> None:
    split = CorpusSplit.from_publications((date(2022, 2, 28), date(2022, 3, 2), date(2024, 2, 29)))

    assert split.start == date(2019, 2, 28)
    assert split.development_ends == date(2022, 2, 28)
    assert split.held_out_starts == date(2022, 3, 2)


def test_empty_corpus_has_no_research_split() -> None:
    with pytest.raises(ValueError, match="publication"):
        CorpusSplit.from_publications(())
