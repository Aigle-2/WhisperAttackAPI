"""Unit tests for the speech-to-text keyterm vocabulary model."""

from __future__ import annotations

from vaivox.domain.vocabulary.keyterms import (
    DEFAULT_DCS_KEYTERMS,
    PHONETIC_ALPHABET,
    BudgetedKeyterms,
    KeytermBudget,
    apply_keyterm_budget,
)


def test_phonetic_alphabet_is_complete() -> None:
    assert len(PHONETIC_ALPHABET) == 26
    assert PHONETIC_ALPHABET[0] == "Alpha"
    assert PHONETIC_ALPHABET[-1] == "Zulu"


def test_default_dcs_keyterms_present() -> None:
    assert "Texaco" in DEFAULT_DCS_KEYTERMS
    assert "request startup" in DEFAULT_DCS_KEYTERMS


def test_unlimited_budget_keeps_all_nonblank_terms() -> None:
    result = apply_keyterm_budget(["Alpha", "   ", "Bravo"], KeytermBudget())
    assert result.keyterms == ["Alpha", "Bravo"]


def test_budget_reports_per_reason_omissions() -> None:
    result = apply_keyterm_budget(
        ["Alpha", "Very Long Phrase", "Bravo", "Golf"],
        KeytermBudget(max_terms=2, max_term_chars=7),
    )
    assert isinstance(result, BudgetedKeyterms)
    assert result.keyterms == ["Alpha", "Bravo"]
    assert result.skipped_too_long == 1
    assert result.omitted_by_term_limit == 1


def test_space_budget_skips_overlong_phrase_before_term_limit() -> None:
    result = apply_keyterm_budget(
        [
            "Alpha Bravo Charlie Delta Echo",
            "Alpha Bravo Charlie Delta Echo Foxtrot",
            "Texaco",
        ],
        KeytermBudget(max_terms=2, max_term_spaces=4),
    )

    assert result.keyterms == ["Alpha Bravo Charlie Delta Echo", "Texaco"]
    assert result.skipped_too_many_spaces == 1
    assert result.omitted_by_term_limit == 0


def test_total_char_budget_includes_separators() -> None:
    # "Alpha"(5) + ", "(2) + "Bravo"(5) = 12; "Charlie" would push past the limit.
    result = apply_keyterm_budget(["Alpha", "Bravo", "Charlie"], KeytermBudget(max_total_chars=12))
    assert result.keyterms == ["Alpha", "Bravo"]
    assert result.omitted_by_char_limit == 1
